import io
import secrets
from pathlib import Path

import av
from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.ai import ImageModerationInput
from app.config import settings

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_SECONDS = 15
MAX_IMAGE_PIXELS = 20_000_000
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
                detail="Media uploads cannot exceed 10 MB",
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
                    detail="Videos cannot be longer than 15 seconds",
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
            return [moderation_image(match[1]) for match in closest if match]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The video file is invalid",
        ) from exc


def validate_media(
    data: bytes, media_type: str, content_type: str
) -> list[ImageModerationInput]:
    return (
        validate_image(data, content_type)
        if media_type == "image"
        else validate_video(data, content_type)
    )


def store_media(
    data: bytes, original_filename: str, directory_name: str
) -> tuple[str, Path]:
    extension = Path(original_filename).suffix.lower()
    storage_name = f"{secrets.token_hex(20)}{extension}"
    media_directory = settings.media_root / directory_name
    media_directory.mkdir(parents=True, exist_ok=True)
    media_path = media_directory / storage_name
    media_path.write_bytes(data)
    return storage_name, media_path
