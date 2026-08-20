from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_auth
from app.config import settings
from app.database import SessionLocal
from app.models import (
    DirectMessage,
    ForumComment,
    ForumPost,
    MediaAttachment,
    Presence,
)
from app.places import PRESENCE_TTL
from app.schemas import MediaAttachmentResponse

attachments_router = APIRouter(prefix="/api/media", tags=["media"])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def attachment_response(
    attachment: MediaAttachment | None,
) -> MediaAttachmentResponse | None:
    if attachment is None:
        return None
    return MediaAttachmentResponse(
        id=attachment.id,
        media_type=attachment.media_type,
        content_type=attachment.content_type,
        original_filename=attachment.original_filename,
        file_size=attachment.file_size,
        media_url=f"/api/media/{attachment.id}",
    )


def attachment_for_post(db: Session, post_id: int) -> MediaAttachment | None:
    return db.scalar(
        select(MediaAttachment).where(MediaAttachment.forum_post_id == post_id)
    )


def attachment_for_comment(db: Session, comment_id: int) -> MediaAttachment | None:
    return db.scalar(
        select(MediaAttachment).where(MediaAttachment.forum_comment_id == comment_id)
    )


def attachment_for_message(db: Session, message_id: int) -> MediaAttachment | None:
    return db.scalar(
        select(MediaAttachment).where(MediaAttachment.direct_message_id == message_id)
    )


def user_is_present(db: Session, user_id: int, place_id: int) -> bool:
    cutoff = utc_now() - PRESENCE_TTL
    return db.scalar(
        select(Presence.user_id).where(
            Presence.user_id == user_id,
            Presence.place_id == place_id,
            Presence.last_seen_at >= cutoff,
        )
    ) is not None


def can_access_forum_attachment(
    db: Session, attachment: MediaAttachment, user_id: int
) -> bool:
    if attachment.forum_post_id is not None:
        post = db.get(ForumPost, attachment.forum_post_id)
        content_owner_id = post.user_id if post is not None else None
        content_approved = True
    else:
        comment = db.get(ForumComment, attachment.forum_comment_id)
        post = db.get(ForumPost, comment.post_id) if comment is not None else None
        content_owner_id = comment.user_id if comment is not None else None
        content_approved = bool(
            comment is not None and comment.moderation_status == "approved"
        )
    return bool(
        post is not None
        and content_approved
        and post.moderation_status == "approved"
        and attachment.moderation_status == "approved"
        and (
            user_id in {post.user_id, content_owner_id}
            or user_is_present(db, user_id, post.place_id)
        )
    )


def can_access_dm_attachment(
    db: Session, attachment: MediaAttachment, user_id: int
) -> bool:
    message = db.get(DirectMessage, attachment.direct_message_id)
    return bool(
        message is not None
        and attachment.moderation_status == "not_required"
        and user_id in {message.sender_id, message.recipient_id}
    )


@attachments_router.get("/{attachment_id}")
def get_attachment(
    attachment_id: int,
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    with SessionLocal() as db:
        attachment = db.get(MediaAttachment, attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Media not found")
        allowed = (
            can_access_dm_attachment(db, attachment, auth.user.id)
            if attachment.direct_message_id is not None
            else can_access_forum_attachment(db, attachment, auth.user.id)
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="Media not found")
        storage_name = attachment.storage_name
        content_type = attachment.content_type

    media_path = settings.media_root / "attachments" / storage_name
    if not media_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media is unavailable",
        )
    return FileResponse(
        media_path,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=60"},
    )
