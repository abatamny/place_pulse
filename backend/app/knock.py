import asyncio
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
    get_ai_adapter,
    moderate_before_publication,
    route_before_publication,
)
from app.auth import AuthContext, InvalidSessionError, require_auth, resolve_session
from app.database import SessionLocal
from app.jobs import PENDING, TEXT_MODERATION_JOB
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

knock_router = APIRouter(prefix="/api/knock", tags=["KNOCK"])
knock_websocket_router = APIRouter()
knock_rate_limiter = AuthRateLimiter(
    max_attempts=MESSAGES_PER_MINUTE,
    window_seconds=60,
)


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


def save_message(
    *,
    user_id: int,
    nickname: str,
    place: ActivePlace,
    text: str,
) -> KnockMessageResponse | None:
    cutoff = utc_now() - PRESENCE_TTL
    with SessionLocal() as db:
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
            moderation_status=(
                "post_pending" if current_rank == "BELONG" else "pending"
            ),
        )
        db.add(message)
        db.flush()

        if current_rank == "BELONG":
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

        db.commit()
        db.refresh(message)
        return KnockMessageResponse(
            id=message.id,
            place_id=message.place_id,
            place_name=place.name,
            place_display_name=place.display_name,
            origin_place_id=content_places.origin.id,
            origin_place_name=content_places.origin.name,
            origin_place_display_name=place_display_name(db, content_places.origin),
            user_id=message.user_id,
            nickname=nickname,
            author_rank=message.author_rank,
            moderation_status=message.moderation_status,
            text=message.text,
            created_at=message.created_at,
        )


def approve_pending_message(message_id: int, user_id: int) -> bool:
    with SessionLocal.begin() as db:
        message = db.get(KnockMessage, message_id)
        if (
            message is None
            or message.user_id != user_id
            or message.moderation_status != "pending"
        ):
            return False
        message.moderation_status = "approved"
        return True


def delete_pending_message(message_id: int, user_id: int) -> None:
    with SessionLocal.begin() as db:
        message = db.get(KnockMessage, message_id)
        if (
            message is not None
            and message.user_id == user_id
            and message.moderation_status == "pending"
        ):
            db.delete(message)


async def publish_message(
    connection: RoomConnection,
    auth: AuthContext,
    adapter: AIAdapter,
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

    routing = await route_before_publication(
        adapter,
        text,
        [
            PlaceRouteOption(
                place_id=place.id,
                name=place.name,
                parent_place_id=(
                    place.parent_place_id
                    if place.parent_place_id in active_place_ids
                    else None
                ),
                scope_class=place.scope_class,
            )
            for place in active_places
        ],
    )
    if routing is None:
        await send_error(
            connection,
            "routing_failed",
            "The KNOCK could not be routed to a current place. Try again.",
            client_id,
        )
        return
    target = next(
        place for place in active_places if place.id == routing.place_id
    )

    saved = save_message(
        user_id=auth.user.id,
        nickname=auth.user.nickname,
        place=target,
        text=text,
    )
    if saved is None:
        await send_error(
            connection,
            "presence_required",
            "Your presence expired. Share your location again.",
            client_id,
        )
        return

    if target.rank == "VISITOR":
        try:
            moderation = await moderate_before_publication(adapter, text)
        except Exception:
            delete_pending_message(saved.id, auth.user.id)
            raise
        if not moderation.approved:
            delete_pending_message(saved.id, auth.user.id)
            await send_error(
                connection,
                "moderation_rejected",
                moderation.reason,
                client_id,
            )
            return
        if not approve_pending_message(saved.id, auth.user.id):
            await send_error(
                connection,
                "moderation_failed",
                "The KNOCK could not finish its safety check. Try again.",
                client_id,
            )
            return
        saved = saved.model_copy(update={"moderation_status": "approved"})

    await room_manager.broadcast(
        target.id,
        {
            "type": "message",
            "message": saved.model_dump(mode="json"),
            "client_id": client_id,
        },
    )


@knock_websocket_router.websocket("/ws/knock")
async def knock_websocket(
    websocket: WebSocket,
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> None:
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
                adapter,
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
                        KnockMessage.moderation_status == "pending",
                        KnockMessage.user_id == auth.user.id,
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
