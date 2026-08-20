import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from app.ai import (
    AIAdapter,
    PlaceRouteOption,
    moderate_before_publication,
    route_before_publication,
)
from app.auth import AuthContext, InvalidSessionError, require_auth, resolve_session
from app.database import SessionLocal
from app.jobs import (
    DENIAL_VISIBLE_SECONDS,
    PENDING,
    TEXT_MODERATION_JOB,
    queue_knock_check,
)
from app.models import AIJob, KnockMessage, Place, PlaceMembership, Presence, User
from app.place_labels import place_display_name
from app.place_scope import resolve_content_place_scope
from app.places import PRESENCE_TTL, expire_stale_presences
from app.rate_limit import AuthRateLimiter
from app.schemas import (
    KnockHistoryResponse,
    KnockMessageResponse,
    KnockModerationStatus,
    KnockModerationStatusResponse,
    KnockSendPayload,
)

HISTORY_LIMIT = 50
MESSAGES_PER_MINUTE = 20
BROADCAST_POLL_SECONDS = 0.3
BROADCAST_BATCH_LIMIT = 50

# A KNOCK message sits in "routing" only while an AI call is choosing among
# more than one of the sender's current scopes; "pending" covers the safety
# check that follows (or starts immediately when there's nothing to route).
IN_PROGRESS_STATUSES = ("routing", "pending")

DENY_MESSAGES = {
    "routing_failed": "The KNOCK could not be routed to a current place. Try again.",
    "moderation_rejected": "The KNOCK did not pass the safety check.",
}

knock_router = APIRouter(prefix="/api/knock", tags=["KNOCK"])
knock_websocket_router = APIRouter()
knock_rate_limiter = AuthRateLimiter(
    max_attempts=MESSAGES_PER_MINUTE,
    window_seconds=60,
)
logger = logging.getLogger("placepulse.knock")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActivePlace:
    id: int
    name: str
    display_name: str
    parent_place_id: int | None
    scope_class: str
    rank: str


def order_active_places(places: list[ActivePlace]) -> list[ActivePlace]:
    by_id = {place.id: place for place in places}

    def depth(place: ActivePlace) -> int:
        current = place
        seen: set[int] = set()
        result = 0
        while (
            current.parent_place_id in by_id
            and current.parent_place_id not in seen
        ):
            seen.add(current.id)
            current = by_id[current.parent_place_id]
            result += 1
        return result

    return sorted(places, key=lambda place: (depth(place), place.name))


def active_places_for_user(user_id: int) -> list[ActivePlace]:
    now = utc_now()
    cutoff = now - PRESENCE_TTL
    with SessionLocal() as db:
        expire_stale_presences(db, now)
        rows = db.execute(
            select(
                Place.id,
                Place.name,
                Place.parent_place_id,
                Place.scope_class,
                PlaceMembership.rank,
            )
            .join(
                Presence,
                and_(
                    Presence.place_id == Place.id,
                    Presence.user_id == user_id,
                    Presence.last_seen_at >= cutoff,
                ),
            )
            .join(
                PlaceMembership,
                and_(
                    PlaceMembership.place_id == Place.id,
                    PlaceMembership.user_id == user_id,
                ),
            )
        ).all()
        active_places = [
            ActivePlace(
                id=row.id,
                name=row.name,
                display_name=place_display_name(db, db.get(Place, row.id)),
                parent_place_id=row.parent_place_id,
                scope_class=row.scope_class,
                rank=row.rank,
            )
            for row in rows
        ]
        db.commit()

    return order_active_places(active_places)


def user_is_present(user_id: int, place_id: int) -> bool:
    cutoff = utc_now() - PRESENCE_TTL
    with SessionLocal() as db:
        return (
            db.scalar(
                select(Presence.user_id).where(
                    Presence.user_id == user_id,
                    Presence.place_id == place_id,
                    Presence.last_seen_at >= cutoff,
                )
            )
            is not None
        )


@dataclass(eq=False)
class RoomConnection:
    websocket: WebSocket
    user_id: int
    place_ids: set[int]
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class KnockRoomManager:
    def __init__(self) -> None:
        self.rooms: dict[int, set[RoomConnection]] = defaultdict(set)
        self.user_connections: dict[int, set[RoomConnection]] = defaultdict(set)

    async def connect(
        self, websocket: WebSocket, user_id: int, place_ids: set[int]
    ) -> RoomConnection:
        await websocket.accept()
        connection = RoomConnection(
            websocket=websocket,
            user_id=user_id,
            place_ids=set(place_ids),
        )
        for place_id in place_ids:
            self.rooms[place_id].add(connection)
        self.user_connections[user_id].add(connection)
        return connection

    def update_places(
        self, connection: RoomConnection, current_place_ids: set[int]
    ) -> None:
        for place_id in connection.place_ids - current_place_ids:
            self.rooms[place_id].discard(connection)
            if not self.rooms[place_id]:
                self.rooms.pop(place_id, None)
        for place_id in current_place_ids - connection.place_ids:
            self.rooms[place_id].add(connection)
        connection.place_ids = set(current_place_ids)

    def disconnect(self, connection: RoomConnection) -> None:
        for place_id in list(connection.place_ids):
            self.rooms[place_id].discard(connection)
            if not self.rooms[place_id]:
                self.rooms.pop(place_id, None)
        connection.place_ids.clear()
        self.user_connections[connection.user_id].discard(connection)
        if not self.user_connections[connection.user_id]:
            self.user_connections.pop(connection.user_id, None)

    async def send(self, connection: RoomConnection, payload: dict) -> None:
        async with connection.send_lock:
            await connection.websocket.send_json(payload)

    async def broadcast(self, place_id: int, payload: dict) -> None:
        for connection in list(self.rooms.get(place_id, set())):
            if not user_is_present(connection.user_id, place_id):
                current = set(connection.place_ids)
                current.discard(place_id)
                self.update_places(connection, current)
                continue
            try:
                await self.send(connection, payload)
            except (RuntimeError, WebSocketDisconnect):
                self.disconnect(connection)

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        for connection in list(self.user_connections.get(user_id, set())):
            try:
                await self.send(connection, payload)
            except (RuntimeError, WebSocketDisconnect):
                self.disconnect(connection)


room_manager = KnockRoomManager()


async def send_error(
    connection: RoomConnection,
    code: str,
    detail: str,
    client_id: str | None = None,
) -> None:
    payload = {"type": "error", "code": code, "detail": detail}
    if client_id is not None:
        payload["client_id"] = client_id
    await room_manager.send(
        connection,
        payload,
    )


def save_pending_message(
    *,
    user_id: int,
    place: ActivePlace,
    text: str,
    client_id: str | None,
    needs_routing: bool,
) -> KnockMessage | None:
    cutoff = utc_now() - PRESENCE_TTL
    with SessionLocal.begin() as db:
        try:
            content_places = resolve_content_place_scope(db, user_id, place.id)
        except HTTPException:
            return None
        current_rank = db.scalar(
            select(PlaceMembership.rank)
            .join(
                Presence,
                and_(
                    Presence.user_id == PlaceMembership.user_id,
                    Presence.place_id == PlaceMembership.place_id,
                ),
            )
            .where(
                PlaceMembership.user_id == user_id,
                PlaceMembership.place_id == place.id,
                Presence.last_seen_at >= cutoff,
            )
        )
        if current_rank is None:
            return None

        message = KnockMessage(
            place_id=place.id,
            origin_place_id=content_places.origin.id,
            user_id=user_id,
            text=text,
            author_rank=current_rank,
            moderation_status="routing" if needs_routing else "pending",
            client_id=client_id,
        )
        db.add(message)
        db.flush()
        db.refresh(message)
        db.expunge(message)
        return message


def _deny_knock_message(message_id: int, code: str) -> None:
    with SessionLocal.begin() as db:
        message = db.get(KnockMessage, message_id)
        if message is not None and message.moderation_status in IN_PROGRESS_STATUSES:
            message.moderation_status = "denied"
            message.deny_code = code
            message.decided_at = utc_now()


def _origin_from_candidates(
    candidates: list[dict], target_place_id: int
) -> int:
    """Replicate resolve_content_place_scope using the places captured at
    submission time, so a slow worker doesn't punish a user who has since
    moved: the AI is still constrained to where they actually were."""
    by_id = {candidate["place_id"]: candidate for candidate in candidates}
    best_id = target_place_id
    best_depth = 0
    for candidate in candidates:
        depth = 0
        current = candidate
        seen: set[int] = set()
        reached = current["place_id"] == target_place_id
        while not reached:
            parent_id = current.get("parent_place_id")
            if (
                parent_id is None
                or parent_id not in by_id
                or current["place_id"] in seen
            ):
                break
            seen.add(current["place_id"])
            current = by_id[parent_id]
            depth += 1
            reached = current["place_id"] == target_place_id
        if reached and depth > best_depth:
            best_depth = depth
            best_id = candidate["place_id"]
    return best_id


async def apply_knock_check(payload: dict, adapter: AIAdapter) -> None:
    """Resolve routing and moderation for one queued KNOCK message."""
    message_id = payload.get("message_id")
    user_id = payload.get("user_id")
    candidate_places_raw = payload.get("candidate_places")
    if (
        not isinstance(message_id, int)
        or not isinstance(user_id, int)
        or not isinstance(candidate_places_raw, list)
    ):
        return

    with SessionLocal() as db:
        message = db.get(KnockMessage, message_id)
        if message is None or message.moderation_status not in IN_PROGRESS_STATUSES:
            return
        text = message.text

    try:
        places = [
            PlaceRouteOption(
                place_id=option["place_id"],
                name=option["name"],
                parent_place_id=option.get("parent_place_id"),
                scope_class=option.get("scope_class", "OTHER"),
            )
            for option in candidate_places_raw
        ]
        rank_by_place_id = {
            option["place_id"]: option["rank"] for option in candidate_places_raw
        }
    except (KeyError, TypeError, ValueError):
        _deny_knock_message(message_id, "routing_failed")
        return

    if not places:
        _deny_knock_message(message_id, "routing_failed")
        return
    if len(places) == 1:
        # Only one current scope: nothing to choose between, so skip the AI
        # routing call and go straight to moderation.
        target_place_id = places[0].place_id
    else:
        routing = await route_before_publication(adapter, text, places)
        if routing is None:
            _deny_knock_message(message_id, "routing_failed")
            return
        target_place_id = routing.place_id

    author_rank = rank_by_place_id.get(target_place_id)
    if author_rank is None:
        _deny_knock_message(message_id, "routing_failed")
        return
    origin_place_id = _origin_from_candidates(candidate_places_raw, target_place_id)

    with SessionLocal.begin() as db:
        message = db.get(KnockMessage, message_id)
        if message is None or message.moderation_status not in IN_PROGRESS_STATUSES:
            return
        message.place_id = target_place_id
        message.origin_place_id = origin_place_id
        message.author_rank = author_rank
        if author_rank == "BELONG":
            message.moderation_status = "post_pending"
            message.decided_at = utc_now()
            db.add(
                AIJob(
                    job_type=TEXT_MODERATION_JOB,
                    status=PENDING,
                    payload={
                        "text": text,
                        "knock_message_id": message.id,
                        "user_id": user_id,
                    },
                    attempts=0,
                )
            )
        else:
            # Routing (if any) is resolved; the safety check is next.
            message.moderation_status = "pending"

    if author_rank == "BELONG":
        return

    moderation = await moderate_before_publication(adapter, text)
    with SessionLocal.begin() as db:
        message = db.get(KnockMessage, message_id)
        if message is None or message.moderation_status != "pending":
            return
        message.decided_at = utc_now()
        if moderation.approved:
            message.moderation_status = "approved"
        else:
            message.moderation_status = "denied"
            message.deny_code = "moderation_rejected"


async def deliver_ready_messages() -> None:
    """Broadcast resolved KNOCK messages and notify authors of denials."""
    deliveries: list[tuple] = []
    with SessionLocal.begin() as db:
        rows = list(
            db.scalars(
                select(KnockMessage)
                .where(
                    KnockMessage.broadcast_at.is_(None),
                    KnockMessage.moderation_status.in_(
                        ("approved", "post_pending", "denied")
                    ),
                )
                .order_by(KnockMessage.id)
                .limit(BROADCAST_BATCH_LIMIT)
            )
        )
        for message in rows:
            message.broadcast_at = utc_now()
            if message.moderation_status == "denied":
                deliveries.append(
                    (
                        "denied",
                        message.id,
                        message.user_id,
                        message.client_id,
                        message.deny_code,
                    )
                )
                continue
            place = db.get(Place, message.place_id)
            origin = db.get(Place, message.origin_place_id)
            author = db.get(User, message.user_id)
            response = KnockMessageResponse(
                id=message.id,
                place_id=message.place_id,
                place_name=place.name if place is not None else "Unknown place",
                place_display_name=place_display_name(db, place),
                origin_place_id=message.origin_place_id,
                origin_place_name=(
                    origin.name if origin is not None else "Unknown place"
                ),
                origin_place_display_name=place_display_name(db, origin),
                user_id=message.user_id,
                nickname=author.nickname if author is not None else "Unknown user",
                author_rank=message.author_rank,
                moderation_status=message.moderation_status,
                text=message.text,
                created_at=message.created_at,
                decided_at=message.decided_at,
            )
            deliveries.append(("message", message.place_id, response, message.client_id))

    for delivery in deliveries:
        if delivery[0] == "denied":
            _, message_id, user_id, client_id, deny_code = delivery
            await room_manager.send_to_user(
                user_id,
                {
                    "type": "error",
                    "code": deny_code or "moderation_rejected",
                    "detail": DENY_MESSAGES.get(
                        deny_code, "The KNOCK could not be sent."
                    ),
                    "client_id": client_id,
                    "message_id": message_id,
                },
            )
        else:
            _, place_id, response, client_id = delivery
            await room_manager.broadcast(
                place_id,
                {
                    "type": "message",
                    "message": response.model_dump(mode="json"),
                    "client_id": client_id,
                },
            )


async def run_knock_broadcaster() -> None:
    while True:
        try:
            await deliver_ready_messages()
        except Exception:
            logger.exception("KNOCK broadcaster pass failed")
        await asyncio.sleep(BROADCAST_POLL_SECONDS)


async def publish_message(
    connection: RoomConnection,
    auth: AuthContext,
    text: str,
    client_id: str | None,
) -> None:
    active_places = active_places_for_user(auth.user.id)
    if not active_places:
        await send_error(
            connection,
            "presence_required",
            "Share your location before sending a KNOCK.",
            client_id,
        )
        return

    room_manager.update_places(
        connection, {place.id for place in active_places}
    )
    active_place_ids = {place.id for place in active_places}

    pending = save_pending_message(
        user_id=auth.user.id,
        place=active_places[-1],
        text=text,
        client_id=client_id,
        needs_routing=len(active_places) > 1,
    )
    if pending is None:
        await send_error(
            connection,
            "presence_required",
            "Your presence expired. Share your location again.",
            client_id,
        )
        return

    candidate_places = [
        {
            "place_id": place.id,
            "name": place.name,
            "parent_place_id": (
                place.parent_place_id
                if place.parent_place_id in active_place_ids
                else None
            ),
            "scope_class": place.scope_class,
            "rank": place.rank,
        }
        for place in active_places
    ]
    with SessionLocal.begin() as db:
        queue_knock_check(
            db,
            message_id=pending.id,
            user_id=auth.user.id,
            candidate_places=candidate_places,
        )

    await room_manager.send(
        connection,
        {"type": "queued", "client_id": client_id, "message_id": pending.id},
    )


@knock_websocket_router.websocket("/ws/knock")
async def knock_websocket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=4401)
        return

    try:
        auth = resolve_session(token)
    except InvalidSessionError:
        await websocket.close(code=4401)
        return

    active_places = active_places_for_user(auth.user.id)
    if not active_places:
        await websocket.close(code=4403)
        return

    connection = await room_manager.connect(
        websocket,
        auth.user.id,
        {place.id for place in active_places},
    )
    await room_manager.send(
        connection,
        {
            "type": "ready",
            "places": [
                {
                    "id": place.id,
                    "name": place.name,
                    "display_name": place.display_name,
                    "rank": place.rank,
                }
                for place in active_places
            ],
        },
    )

    try:
        while True:
            try:
                raw_payload = await websocket.receive_json()
                payload = KnockSendPayload.model_validate(raw_payload)
            except (TypeError, ValueError, ValidationError):
                await send_error(
                    connection,
                    "invalid_message",
                    "Send a text message between 1 and 500 characters.",
                )
                continue

            try:
                knock_rate_limiter.check_key(str(auth.user.id), "knock-message")
            except HTTPException:
                await send_error(
                    connection,
                    "rate_limited",
                    "Too many messages. Wait a moment before trying again.",
                    payload.client_id,
                )
                continue

            await publish_message(
                connection,
                auth,
                payload.text,
                payload.client_id,
            )
    except WebSocketDisconnect:
        pass
    finally:
        room_manager.disconnect(connection)


@knock_router.get("/history", response_model=KnockHistoryResponse)
def knock_history(
    auth: AuthContext = Depends(require_auth),
) -> KnockHistoryResponse:
    active_place_ids = {
        place.id for place in active_places_for_user(auth.user.id)
    }
    if not active_place_ids:
        raise HTTPException(
            status_code=403,
            detail="Current presence is required",
        )

    denial_cutoff = utc_now() - timedelta(seconds=DENIAL_VISIBLE_SECONDS)
    with SessionLocal() as db:
        origin_place = aliased(Place)
        rows = db.execute(
            select(KnockMessage, Place, origin_place, User.nickname)
            .join(Place, Place.id == KnockMessage.place_id)
            .join(origin_place, origin_place.id == KnockMessage.origin_place_id)
            .join(User, User.id == KnockMessage.user_id)
            .where(
                KnockMessage.place_id.in_(active_place_ids),
                or_(
                    KnockMessage.moderation_status.in_(
                        ("approved", "post_pending")
                    ),
                    and_(
                        KnockMessage.moderation_status.in_(IN_PROGRESS_STATUSES),
                        KnockMessage.user_id == auth.user.id,
                    ),
                    and_(
                        KnockMessage.moderation_status == "denied",
                        KnockMessage.user_id == auth.user.id,
                        KnockMessage.decided_at >= denial_cutoff,
                    ),
                ),
            )
            .order_by(KnockMessage.created_at.desc(), KnockMessage.id.desc())
            .limit(HISTORY_LIMIT)
        ).all()

        messages = [
            KnockMessageResponse(
                id=message.id,
                place_id=message.place_id,
                place_name=place.name,
                place_display_name=place_display_name(db, place),
                origin_place_id=message.origin_place_id,
                origin_place_name=origin.name,
                origin_place_display_name=place_display_name(db, origin),
                user_id=message.user_id,
                nickname=nickname,
                author_rank=message.author_rank,
                moderation_status=message.moderation_status,
                text=message.text,
                created_at=message.created_at,
                decided_at=message.decided_at,
            )
            for message, place, origin, nickname in reversed(rows)
        ]
        return KnockHistoryResponse(messages=messages)


@knock_router.get(
    "/moderation-status",
    response_model=KnockModerationStatusResponse,
)
def knock_moderation_status(
    message_ids: Annotated[
        list[int],
        Query(min_length=1, max_length=HISTORY_LIMIT),
    ],
    auth: AuthContext = Depends(require_auth),
) -> KnockModerationStatusResponse:
    active_place_ids = {
        place.id for place in active_places_for_user(auth.user.id)
    }
    if not active_place_ids:
        raise HTTPException(
            status_code=403,
            detail="Current presence at this place is required",
        )

    with SessionLocal() as db:
        rows = db.execute(
            select(KnockMessage.id, KnockMessage.moderation_status)
            .where(
                KnockMessage.id.in_(message_ids),
                KnockMessage.place_id.in_(active_place_ids),
                or_(
                    KnockMessage.moderation_status != "pending",
                    KnockMessage.user_id == auth.user.id,
                ),
            )
            .order_by(KnockMessage.id)
        ).all()
        return KnockModerationStatusResponse(
            messages=[
                KnockModerationStatus(
                    id=message_id,
                    moderation_status=moderation_status,
                )
                for message_id, moderation_status in rows
            ]
        )
