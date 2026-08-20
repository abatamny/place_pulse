from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.attachments import attachment_for_message, attachment_response
from app.auth import (
    AuthContext,
    InvalidSessionError,
    require_auth,
    resolve_session,
)
from app.database import SessionLocal
from app.media import (
    read_limited_upload,
    store_media,
    validate_filename,
    validate_media,
)
from app.models import DirectMessage, MediaAttachment, User
from app.rate_limit import AuthRateLimiter
from app.schemas import (
    DMConversationListResponse,
    DMConversationResponse,
    DMHistoryResponse,
    DMMessageCreate,
    DMMessageResponse,
    DMUserResponse,
    DMUserSearchResponse,
    clean_required_text,
)

DM_HISTORY_LIMIT = 200
DM_SEARCH_LIMIT = 20
DM_SENDS_PER_MINUTE = 30

dm_router = APIRouter(prefix="/api/dms", tags=["direct messages"])
dm_websocket_router = APIRouter()
dm_rate_limiter = AuthRateLimiter(
    max_attempts=DM_SENDS_PER_MINUTE,
    window_seconds=60,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def user_response(user: User) -> DMUserResponse:
    return DMUserResponse(id=user.id, nickname=user.nickname, phone=user.phone)


def message_response(db: Session, message: DirectMessage) -> DMMessageResponse:
    sender = db.get(User, message.sender_id)
    recipient = db.get(User, message.recipient_id)
    return DMMessageResponse(
        id=message.id,
        sender_id=message.sender_id,
        sender_nickname=sender.nickname if sender is not None else "Unknown user",
        recipient_id=message.recipient_id,
        recipient_nickname=(
            recipient.nickname if recipient is not None else "Unknown user"
        ),
        text=message.text,
        created_at=message.created_at,
        read_at=message.read_at,
        media=attachment_response(attachment_for_message(db, message.id)),
    )


def require_other_user(db: Session, current_user_id: int, other_user_id: int) -> User:
    if other_user_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot message yourself",
        )
    other_user = db.get(User, other_user_id)
    if other_user is None or not other_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return other_user


class DMConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        connections = self.connections.get(user_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self.connections.pop(user_id, None)

    async def notify(self, user_id: int, payload: dict) -> None:
        for websocket in list(self.connections.get(user_id, set())):
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                self.disconnect(user_id, websocket)


dm_connections = DMConnectionManager()


@dm_router.get("/users", response_model=DMUserSearchResponse)
def search_users(
    query: str = Query(min_length=2, max_length=30),
    auth: AuthContext = Depends(require_auth),
) -> DMUserSearchResponse:
    cleaned = query.strip()
    if len(cleaned) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter at least two search characters",
        )
    pattern = f"%{cleaned}%"
    with SessionLocal() as db:
        users = list(
            db.scalars(
                select(User)
                .where(
                    User.id != auth.user.id,
                    User.is_verified.is_(True),
                    or_(
                        User.nickname.ilike(pattern),
                        User.phone.ilike(pattern),
                    ),
                )
                .order_by(User.nickname, User.id)
                .limit(DM_SEARCH_LIMIT)
            )
        )
        return DMUserSearchResponse(users=[user_response(user) for user in users])


@dm_router.get("/conversations", response_model=DMConversationListResponse)
def conversations(
    auth: AuthContext = Depends(require_auth),
) -> DMConversationListResponse:
    with SessionLocal() as db:
        messages = list(
            db.scalars(
                select(DirectMessage)
                .where(
                    or_(
                        DirectMessage.sender_id == auth.user.id,
                        DirectMessage.recipient_id == auth.user.id,
                    )
                )
                .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
            )
        )
        latest_by_user: dict[int, DirectMessage] = {}
        unread_by_user: dict[int, int] = defaultdict(int)
        for message in messages:
            other_user_id = (
                message.recipient_id
                if message.sender_id == auth.user.id
                else message.sender_id
            )
            latest_by_user.setdefault(other_user_id, message)
            if (
                message.recipient_id == auth.user.id
                and message.read_at is None
            ):
                unread_by_user[other_user_id] += 1

        result: list[DMConversationResponse] = []
        for other_user_id, last_message in latest_by_user.items():
            other_user = db.get(User, other_user_id)
            if other_user is None:
                continue
            result.append(
                DMConversationResponse(
                    user=user_response(other_user),
                    last_message=message_response(db, last_message),
                    unread_count=unread_by_user[other_user_id],
                )
            )
        return DMConversationListResponse(conversations=result)


@dm_router.get("/{other_user_id}", response_model=DMHistoryResponse)
def message_history(
    other_user_id: int,
    auth: AuthContext = Depends(require_auth),
) -> DMHistoryResponse:
    with SessionLocal() as db:
        other_user = require_other_user(db, auth.user.id, other_user_id)
        recent = list(
            db.scalars(
                select(DirectMessage)
                .where(
                    or_(
                        (
                            (DirectMessage.sender_id == auth.user.id)
                            & (DirectMessage.recipient_id == other_user_id)
                        ),
                        (
                            (DirectMessage.sender_id == other_user_id)
                            & (DirectMessage.recipient_id == auth.user.id)
                        ),
                    )
                )
                .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
                .limit(DM_HISTORY_LIMIT)
            )
        )
        return DMHistoryResponse(
            user=user_response(other_user),
            messages=[message_response(db, message) for message in reversed(recent)],
        )


@dm_router.post(
    "/messages",
    response_model=DMMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    payload: DMMessageCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> DMMessageResponse:
    dm_rate_limiter.check(request, f"dm-send-{auth.user.id}")
    with SessionLocal.begin() as db:
        require_other_user(db, auth.user.id, payload.recipient_id)
        message = DirectMessage(
            sender_id=auth.user.id,
            recipient_id=payload.recipient_id,
            text=payload.text,
            created_at=utc_now(),
        )
        db.add(message)
        db.flush()
        response = message_response(db, message)

    notification = {"type": "message", "message": response.model_dump(mode="json")}
    await dm_connections.notify(payload.recipient_id, notification)
    await dm_connections.notify(auth.user.id, notification)
    return response


@dm_router.post(
    "/messages/with-media",
    response_model=DMMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message_with_media(
    request: Request,
    file: Annotated[UploadFile, File()],
    recipient_id: Annotated[int, Form(gt=0)],
    text: Annotated[str, Form(min_length=1, max_length=1000)],
    auth: AuthContext = Depends(require_auth),
) -> DMMessageResponse:
    dm_rate_limiter.check(request, f"dm-send-{auth.user.id}")
    try:
        text = clean_required_text(text, "Message cannot be empty")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with SessionLocal() as db:
        require_other_user(db, auth.user.id, recipient_id)

    media_type, content_type = validate_filename(file.filename, file.content_type)
    try:
        data = await read_limited_upload(file)
    finally:
        await file.close()
    validate_media(data, media_type, content_type)
    original_filename = file.filename or "upload"
    storage_name, media_path = store_media(data, original_filename, "attachments")
    try:
        with SessionLocal.begin() as db:
            require_other_user(db, auth.user.id, recipient_id)
            message = DirectMessage(
                sender_id=auth.user.id,
                recipient_id=recipient_id,
                text=text,
                created_at=utc_now(),
            )
            db.add(message)
            db.flush()
            db.add(
                MediaAttachment(
                    user_id=auth.user.id,
                    direct_message_id=message.id,
                    media_type=media_type,
                    content_type=content_type,
                    storage_name=storage_name,
                    original_filename=original_filename,
                    file_size=len(data),
                    moderation_status="not_required",
                    created_at=utc_now(),
                )
            )
            db.flush()
            response = message_response(db, message)
    except Exception:
        media_path.unlink(missing_ok=True)
        raise

    notification = {"type": "message", "message": response.model_dump(mode="json")}
    await dm_connections.notify(recipient_id, notification)
    await dm_connections.notify(auth.user.id, notification)
    return response


@dm_router.post("/{other_user_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_conversation_read(
    other_user_id: int,
    auth: AuthContext = Depends(require_auth),
) -> Response:
    with SessionLocal.begin() as db:
        require_other_user(db, auth.user.id, other_user_id)
        db.execute(
            update(DirectMessage)
            .where(
                DirectMessage.sender_id == other_user_id,
                DirectMessage.recipient_id == auth.user.id,
                DirectMessage.read_at.is_(None),
            )
            .values(read_at=utc_now())
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@dm_websocket_router.websocket("/ws/dms")
async def dm_notifications(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=4401)
        return
    try:
        auth = resolve_session(token)
    except InvalidSessionError:
        await websocket.close(code=4401)
        return

    await dm_connections.connect(auth.user.id, websocket)
    await websocket.send_json({"type": "ready"})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        dm_connections.disconnect(auth.user.id, websocket)
