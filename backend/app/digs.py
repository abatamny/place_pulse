import io
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import av
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
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import (
    AIAdapter,
    ImageModerationInput,
    get_ai_adapter,
    moderate_media_before_publication,
)
from app.auth import AuthContext, require_auth
from app.config import settings
from app.database import SessionLocal
from app.jobs import queue_explore_cluster_check
from app.knock import user_is_present
from app.models import Dig, Place, User
from app.place_labels import place_display_name
from app.rate_limit import AuthRateLimiter
from app.schemas import DigFeedResponse, DigResponse

DIG_LIFETIME = timedelta(hours=24)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_SECONDS = 15
MAX_IMAGE_PIXELS = 20_000_000
UPLOADS_PER_MINUTE = 10
READ_CHUNK_BYTES = 1024 * 1024

ALLOWED_MEDIA = {
    "image/jpeg": ("image", {".jpg", ".jpeg"}),
    "image/png": ("image", {".png"}),
    "image/webp": ("image", {".webp"}),
    "video/mp4": ("video", {".mp4"}),
    "video/webm": ("video", {".webm"}),
}
IMAGE_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

digs_router = APIRouter(prefix="/api/digs", tags=["DIG"])
upload_rate_limiter = AuthRateLimiter(
    max_attempts=UPLOADS_PER_MINUTE, window_seconds=60
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_filename(filename: str | None, content_type: str | None) -> tuple[str, str]:
    if not filename or len(filename) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a file with a valid filename",
        )
    if any(character in filename for character in ("/", "\\", "\x00")) or any(
        ord(character) < 32 for character in filename
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename contains invalid characters",
        )

    normalized_type = (content_type or "").lower()
    media_details = ALLOWED_MEDIA.get(normalized_type)
    if media_details is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG, WebP, MP4, or WebM file",
        )
    media_type, extensions = media_details
    if Path(filename).suffix.lower() not in extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The filename extension does not match the file type",
        )
    return media_type, normalized_type


async def read_limited_upload(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(READ_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="DIG uploads cannot exceed 10 MB",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty",
        )
    return b"".join(chunks)


def moderation_image(image: Image.Image) -> ImageModerationInput:
    converted = image.convert("RGB")
    converted.thumbnail((1024, 1024))
    output = io.BytesIO()
    converted.save(output, format="JPEG", quality=82, optimize=True)
    return ImageModerationInput(content_type="image/jpeg", data=output.getvalue())


def validate_image(data: bytes, content_type: str) -> list[ImageModerationInput]:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != IMAGE_FORMATS[content_type]:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="The file contents do not match the selected image type",
                )
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The image dimensions are too large",
                )
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            return [moderation_image(image)]
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The image file is invalid",
        ) from exc


def validate_video(data: bytes, content_type: str) -> list[ImageModerationInput]:
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            format_names = set(container.format.name.split(","))
            expected_format = "mp4" if content_type == "video/mp4" else "webm"
            if expected_format not in format_names:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="The file contents do not match the selected video type",
                )

            stream = next(
                (candidate for candidate in container.streams if candidate.type == "video"),
                None,
            )
            if stream is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The upload does not contain a video track",
                )
            if stream.width * stream.height > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The video dimensions are too large",
                )

            duration = None
            if container.duration is not None:
                duration = float(container.duration / av.time_base)
            elif stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            if duration is None or duration <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The video duration could not be read",
                )
            if duration > MAX_VIDEO_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="DIG videos cannot be longer than 15 seconds",
                )

            targets = (0.0, duration / 2, max(0.0, duration - 0.1))
            closest: list[tuple[float, Image.Image] | None] = [None, None, None]
            fallback_time = 0.0
            frame_rate = float(stream.average_rate) if stream.average_rate else 30.0
            for frame_number, frame in enumerate(container.decode(stream)):
                frame_time = (
                    float(frame.time)
                    if frame.time is not None
                    else frame_number / frame_rate
                )
                fallback_time = frame_time
                image = frame.to_image()
                for index, target in enumerate(targets):
                    distance = abs(frame_time - target)
                    if closest[index] is None or distance < closest[index][0]:
                        closest[index] = (distance, image.copy())

            if not any(closest) or fallback_time > MAX_VIDEO_SECONDS + 0.5:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The video file is invalid",
                )
            return [
                moderation_image(match[1]) for match in closest if match is not None
            ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The video file is invalid",
        ) from exc


def dig_response(
    db: Session,
    dig: Dig,
    place: Place,
    nickname: str,
) -> DigResponse:
    return DigResponse(
        id=dig.id,
        place_id=dig.place_id,
        place_name=place.name,
        place_display_name=place_display_name(db, place),
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
    place_id: Annotated[int, Form(gt=0)],
    file: Annotated[UploadFile, File()],
    auth: AuthContext = Depends(require_auth),
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> DigResponse:
    upload_rate_limiter.check(request, f"dig-upload-{auth.user.id}")
    require_place_presence(auth.user.id, place_id)
    media_type, content_type = validate_filename(file.filename, file.content_type)
    try:
        data = await read_limited_upload(file)
    finally:
        await file.close()

    samples = (
        validate_image(data, content_type)
        if media_type == "image"
        else validate_video(data, content_type)
    )
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
    extension = Path(original_filename).suffix.lower()
    storage_name = f"{secrets.token_hex(20)}{extension}"
    media_directory = settings.media_root / "digs"
    media_directory.mkdir(parents=True, exist_ok=True)
    media_path = media_directory / storage_name
    now = utc_now()
    media_path.write_bytes(data)

    try:
        with SessionLocal() as db:
            place = db.get(Place, place_id)
            if place is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Place not found",
                )
            dig = Dig(
                place_id=place_id,
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
            queue_explore_cluster_check(db, place_id, auth.user.id)
            db.commit()
            db.refresh(dig)
            return dig_response(db, dig, place, auth.user.nickname)
    except Exception:
        media_path.unlink(missing_ok=True)
        raise


@digs_router.get("", response_model=DigFeedResponse)
def dig_feed(
    place_id: int,
    auth: AuthContext = Depends(require_auth),
) -> DigFeedResponse:
    require_place_presence(auth.user.id, place_id)
    with SessionLocal() as db:
        rows = db.execute(
            select(Dig, Place, User.nickname)
            .join(Place, Place.id == Dig.place_id)
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
                dig_response(db, dig, place, nickname)
                for dig, place, nickname in rows
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
