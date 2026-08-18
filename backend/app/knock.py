import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import and_, select

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
from app.places import PRESENCE_TTL, expire_stale_presences
from app.schemas import KnockHistoryResponse, KnockMessageResponse, KnockSendPayload

HISTORY_LIMIT = 50
MESSAGES_PER_MINUTE = 20

knock_router = APIRouter(prefix="/api/knock", tags=["KNOCK"])
knock_websocket_router = APIRouter()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActivePlace:
    id: int
    name: str
    parent_place_id: int | None
    rank: str

    def route_option(self) -> PlaceRouteOption:
        return PlaceRouteOption(
            place_id=self.id,
            name=self.name,
            parent_place_id=self.parent_place_id,
        )


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
        db.commit()

    return order_active_places(
        [
            ActivePlace(
                id=row.id,
                name=row.name,
                parent_place_id=row.parent_place_id,
                rank=row.rank,
            )
            for row in rows
        ]
    )


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
    message_times: deque[float] = field(default_factory=deque)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def allow_message(self) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        while self.message_times and self.message_times[0] <= cutoff:
            self.message_times.popleft()
        if len(self.message_times) >= MESSAGES_PER_MINUTE:
            return False
        self.message_times.append(now)
        return True


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
    connection: RoomConnection, code: str, detail: str
) -> None:
    await room_manager.send(
        connection,
        {"type": "error", "code": code, "detail": detail},
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
            user_id=user_id,
            text=text,
            author_rank=current_rank,
            moderation_status=(
                "post_pending" if current_rank == "BELONG" else "approved"
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
            user_id=message.user_id,
            nickname=nickname,
            author_rank=message.author_rank,
            text=message.text,
            created_at=message.created_at,
        )


async def publish_message(
    connection: RoomConnection,
    auth: AuthContext,
    adapter: AIAdapter,
    text: str,
) -> None:
    active_places = active_places_for_user(auth.user.id)
    if not active_places:
        await send_error(
            connection,
            "presence_required",
            "Share your location before sending a KNOCK.",
        )
        return

    room_manager.update_places(
        connection, {place.id for place in active_places}
    )

    if len(active_places) == 1:
        target = active_places[0]
    else:
        route = await route_before_publication(
            adapter,
            text,
            [place.route_option() for place in active_places],
        )
        if route is None:
            await send_error(
                connection,
                "routing_failed",
                "The message could not be routed safely. Try again.",
            )
            return
        target = next(
            place for place in active_places if place.id == route.place_id
        )

    if target.rank == "VISITOR":
        moderation = await moderate_before_publication(adapter, text)
        if not moderation.approved:
            await send_error(
                connection,
                "moderation_rejected",
                moderation.reason,
            )
            return

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
        )
        return

    await room_manager.broadcast(
        target.id,
        {"type": "message", "message": saved.model_dump(mode="json")},
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
                {"id": place.id, "name": place.name, "rank": place.rank}
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

            if not connection.allow_message():
                await send_error(
                    connection,
                    "rate_limited",
                    "Too many messages. Wait a moment before trying again.",
                )
                continue

            await publish_message(connection, auth, adapter, payload.text)
    except WebSocketDisconnect:
        pass
    finally:
        room_manager.disconnect(connection)


@knock_router.get("/history", response_model=KnockHistoryResponse)
def knock_history(
    place_id: int,
    auth: AuthContext = Depends(require_auth),
) -> KnockHistoryResponse:
    if place_id not in {place.id for place in active_places_for_user(auth.user.id)}:
        raise HTTPException(
            status_code=403,
            detail="Current presence at this place is required",
        )

    with SessionLocal() as db:
        rows = db.execute(
            select(KnockMessage, Place.name, User.nickname)
            .join(Place, Place.id == KnockMessage.place_id)
            .join(User, User.id == KnockMessage.user_id)
            .where(
                KnockMessage.place_id == place_id,
                KnockMessage.moderation_status != "flagged",
            )
            .order_by(KnockMessage.created_at.desc(), KnockMessage.id.desc())
            .limit(HISTORY_LIMIT)
        ).all()

    messages = [
        KnockMessageResponse(
            id=row.KnockMessage.id,
            place_id=row.KnockMessage.place_id,
            place_name=row.name,
            user_id=row.KnockMessage.user_id,
            nickname=row.nickname,
            author_rank=row.KnockMessage.author_rank,
            text=row.KnockMessage.text,
            created_at=row.KnockMessage.created_at,
        )
        for row in reversed(rows)
    ]
    return KnockHistoryResponse(messages=messages)
