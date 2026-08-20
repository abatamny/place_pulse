import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.ai import AIAdapter, get_ai_adapter, moderate_media_before_publication
from app.auth import AuthContext, require_auth
from app.config import settings
from app.database import SessionLocal
from app.jobs import queue_explore_cluster_check
from app.knock import room_manager, user_is_present
from app.media import (
    read_limited_upload,
    store_media,
    validate_filename,
    validate_media,
)
from app.models import Dig, Place, User
from app.place_labels import place_display_name
from app.place_scope import current_content_places, resolve_content_place_scope
from app.rate_limit import AuthRateLimiter
from app.schemas import DigFeedResponse, DigResponse

DIG_LIFETIME = timedelta(hours=24)
UPLOADS_PER_MINUTE = 10

digs_router = APIRouter(prefix="/api/digs", tags=["DIG"])
logger = logging.getLogger(__name__)
upload_rate_limiter = AuthRateLimiter(
    max_attempts=UPLOADS_PER_MINUTE, window_seconds=60
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def dig_response(
    db: Session,
    dig: Dig,
    place: Place,
    origin_place: Place,
    nickname: str,
) -> DigResponse:
    return DigResponse(
        id=dig.id,
        place_id=dig.place_id,
        place_name=place.name,
        place_display_name=place_display_name(db, place),
        origin_place_id=origin_place.id,
        origin_place_name=origin_place.name,
        origin_place_display_name=place_display_name(db, origin_place),
        user_id=dig.user_id,
        nickname=nickname,
        media_type=dig.media_type,
        content_type=dig.content_type,
        original_filename=dig.original_filename,
        file_size=dig.file_size,
        media_url=f"/api/digs/{dig.id}/media",
        created_at=dig.created_at,
        expires_at=dig.expires_at,
    )


def require_place_presence(user_id: int, place_id: int) -> None:
    if not user_is_present(user_id, place_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be present at this place",
        )


@digs_router.post("", response_model=DigResponse, status_code=status.HTTP_201_CREATED)
async def upload_dig(
    request: Request,
    file: Annotated[UploadFile, File()],
    place_id: Annotated[int | None, Form()] = None,
    auth: AuthContext = Depends(require_auth),
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> DigResponse:
    upload_rate_limiter.check(request, f"dig-upload-{auth.user.id}")
    with SessionLocal() as db:
        selected_place_id = place_id
        if selected_place_id is None:
            selected_place_id = current_content_places(db, auth.user.id).origin.id
        resolve_content_place_scope(db, auth.user.id, selected_place_id)
    media_type, content_type = validate_filename(file.filename, file.content_type)
    try:
        data = await read_limited_upload(file)
    finally:
        await file.close()

    samples = validate_media(data, media_type, content_type)
    moderation = await moderate_media_before_publication(adapter, samples)
    if "ai_failure" in moderation.categories:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media moderation is temporarily unavailable",
        )
    if not moderation.approved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This media cannot be published",
        )

    original_filename = file.filename or "upload"
    storage_name, media_path = store_media(data, original_filename, "digs")
    now = utc_now()

    try:
        with SessionLocal() as db:
            content_scope = resolve_content_place_scope(
                db,
                auth.user.id,
                selected_place_id,
            )
            origin_place = content_scope.origin
            place = content_scope.scope
            dig = Dig(
                place_id=place.id,
                origin_place_id=origin_place.id,
                user_id=auth.user.id,
                media_type=media_type,
                content_type=content_type,
                storage_name=storage_name,
                original_filename=original_filename,
                file_size=len(data),
                moderation_status="approved",
                created_at=now,
                expires_at=now + DIG_LIFETIME,
            )
            db.add(dig)
            queue_explore_cluster_check(db, origin_place.id, auth.user.id)
            db.commit()
            db.refresh(dig)
            published = dig_response(
                db,
                dig,
                place,
                origin_place,
                auth.user.nickname,
            )
    except Exception:
        media_path.unlink(missing_ok=True)
        raise

    try:
        await room_manager.broadcast(
            published.place_id,
            {
                "type": "dig_published",
                "dig": published.model_dump(mode="json"),
            },
        )
    except Exception:
        logger.exception("Could not broadcast published DIG %s", published.id)
    return published


@digs_router.get("", response_model=DigFeedResponse)
def dig_feed(
    place_id: int,
    auth: AuthContext = Depends(require_auth),
) -> DigFeedResponse:
    require_place_presence(auth.user.id, place_id)
    with SessionLocal() as db:
        origin_place = aliased(Place)
        rows = db.execute(
            select(Dig, Place, origin_place, User.nickname)
            .join(Place, Place.id == Dig.place_id)
            .join(origin_place, origin_place.id == Dig.origin_place_id)
            .join(User, User.id == Dig.user_id)
            .where(
                Dig.place_id == place_id,
                Dig.moderation_status == "approved",
                Dig.expires_at > utc_now(),
            )
            .order_by(Dig.created_at.desc())
        ).all()
        return DigFeedResponse(
            digs=[
                dig_response(db, dig, place, origin, nickname)
                for dig, place, origin, nickname in rows
            ]
        )


@digs_router.get("/{dig_id}/media")
def dig_media(
    dig_id: int,
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    with SessionLocal() as db:
        dig = db.get(Dig, dig_id)
        if (
            dig is None
            or dig.moderation_status != "approved"
            or dig.expires_at <= utc_now()
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DIG not found",
            )
        require_place_presence(auth.user.id, dig.place_id)
        content_type = dig.content_type
        storage_name = dig.storage_name

    media_path = settings.media_root / "digs" / storage_name
    if not media_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DIG media is unavailable",
        )
    return FileResponse(
        media_path,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=60"},
    )
