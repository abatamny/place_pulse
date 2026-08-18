from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_auth
from app.config import settings
from app.database import SessionLocal
from app.models import (
    Dig,
    ExploreComment,
    ExploreLike,
    ExploreMemory,
    ExploreMemoryDig,
    ExploreParticipant,
    Place,
    Presence,
    User,
)
from app.places import PRESENCE_TTL
from app.rate_limit import AuthRateLimiter
from app.schemas import (
    ExploreCommentRequest,
    ExploreCommentResponse,
    ExploreDigResponse,
    ExploreFeedResponse,
    ExploreLikeResponse,
    ExploreMemoryResponse,
)

EXPLORE_CLUSTER_THRESHOLD = 3
EXPLORE_ACTIVITY_WINDOW = timedelta(hours=1)
EXPLORE_MAX_DIGS = 5
EXPLORE_WRITES_PER_MINUTE = 20

explore_router = APIRouter(prefix="/api/explore", tags=["Explore"])
explore_rate_limiter = AuthRateLimiter(
    max_attempts=EXPLORE_WRITES_PER_MINUTE,
    window_seconds=60,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_memory_from_activity(
    place_id: int,
    now: datetime | None = None,
) -> int | None:
    """Preserve one small, unpreserved DIG cluster for a place."""
    now = now or utc_now()
    with SessionLocal.begin() as db:
        if db.get(Place, place_id) is None:
            return None

        digs = list(
            db.scalars(
                select(Dig)
                .outerjoin(
                    ExploreMemoryDig,
                    ExploreMemoryDig.dig_id == Dig.id,
                )
                .where(
                    Dig.place_id == place_id,
                    Dig.moderation_status == "approved",
                    Dig.created_at >= now - EXPLORE_ACTIVITY_WINDOW,
                    Dig.created_at <= now,
                    ExploreMemoryDig.dig_id.is_(None),
                )
                .order_by(Dig.created_at)
                .limit(EXPLORE_MAX_DIGS)
            )
        )
        if len(digs) < EXPLORE_CLUSTER_THRESHOLD:
            return None

        memory = ExploreMemory(place_id=place_id, created_at=now)
        db.add(memory)
        db.flush()
        for dig in digs:
            db.add(ExploreMemoryDig(memory_id=memory.id, dig_id=dig.id))
        for user_id in {dig.user_id for dig in digs}:
            db.add(ExploreParticipant(memory_id=memory.id, user_id=user_id))
        db.flush()
        return memory.id


def user_can_access_memory(
    db: Session,
    memory: ExploreMemory,
    user_id: int,
    now: datetime | None = None,
) -> bool:
    if db.get(ExploreParticipant, (memory.id, user_id)) is not None:
        return True

    cutoff = (now or utc_now()) - PRESENCE_TTL
    return (
        db.scalar(
            select(Presence.user_id).where(
                Presence.user_id == user_id,
                Presence.place_id == memory.place_id,
                Presence.last_seen_at >= cutoff,
            )
        )
        is not None
    )


def require_memory_access(
    db: Session,
    memory_id: int,
    user_id: int,
) -> ExploreMemory:
    memory = db.get(ExploreMemory, memory_id)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Explore memory not found",
        )
    if not user_can_access_memory(db, memory, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a participant or currently at this place",
        )
    return memory


def comment_response(comment: ExploreComment, nickname: str) -> ExploreCommentResponse:
    return ExploreCommentResponse(
        id=comment.id,
        user_id=comment.user_id,
        nickname=nickname,
        text=comment.text,
        created_at=comment.created_at,
    )


def place_hierarchy_names(db: Session, place: Place | None) -> list[str]:
    names: list[str] = []
    visited: set[int] = set()
    current = place
    while current is not None and current.id not in visited:
        visited.add(current.id)
        names.append(current.name)
        current = (
            db.get(Place, current.parent_place_id)
            if current.parent_place_id is not None
            else None
        )
    return list(reversed(names))


def memory_response(
    db: Session,
    memory: ExploreMemory,
    user_id: int,
) -> ExploreMemoryResponse:
    place = db.get(Place, memory.place_id)
    dig_rows = db.execute(
        select(Dig, User.nickname)
        .join(ExploreMemoryDig, ExploreMemoryDig.dig_id == Dig.id)
        .join(User, User.id == Dig.user_id)
        .where(ExploreMemoryDig.memory_id == memory.id)
        .order_by(Dig.created_at)
    ).all()
    comment_rows = db.execute(
        select(ExploreComment, User.nickname)
        .join(User, User.id == ExploreComment.user_id)
        .where(ExploreComment.memory_id == memory.id)
        .order_by(ExploreComment.created_at, ExploreComment.id)
    ).all()
    like_count = db.scalar(
        select(func.count())
        .select_from(ExploreLike)
        .where(ExploreLike.memory_id == memory.id)
    )
    participant_count = db.scalar(
        select(func.count())
        .select_from(ExploreParticipant)
        .where(ExploreParticipant.memory_id == memory.id)
    )

    return ExploreMemoryResponse(
        id=memory.id,
        place_id=memory.place_id,
        place_name=place.name if place is not None else "Unknown place",
        place_names=place_hierarchy_names(db, place) or ["Unknown place"],
        participant_count=int(participant_count or 0),
        created_at=memory.created_at,
        participant=db.get(ExploreParticipant, (memory.id, user_id)) is not None,
        liked_by_me=db.get(ExploreLike, (memory.id, user_id)) is not None,
        like_count=int(like_count or 0),
        digs=[
            ExploreDigResponse(
                id=dig.id,
                user_id=dig.user_id,
                nickname=nickname,
                media_type=dig.media_type,
                content_type=dig.content_type,
                original_filename=dig.original_filename,
                media_url=f"/api/explore/{memory.id}/media/{dig.id}",
                created_at=dig.created_at,
            )
            for dig, nickname in dig_rows
        ],
        comments=[
            comment_response(comment, nickname)
            for comment, nickname in comment_rows
        ],
    )


@explore_router.get("", response_model=ExploreFeedResponse)
def explore_feed(
    auth: AuthContext = Depends(require_auth),
) -> ExploreFeedResponse:
    now = utc_now()
    cutoff = now - PRESENCE_TTL
    with SessionLocal() as db:
        participant_memory_ids = select(ExploreParticipant.memory_id).where(
            ExploreParticipant.user_id == auth.user.id
        )
        present_place_ids = select(Presence.place_id).where(
            Presence.user_id == auth.user.id,
            Presence.last_seen_at >= cutoff,
        )
        memories = list(
            db.scalars(
                select(ExploreMemory)
                .where(
                    or_(
                        ExploreMemory.id.in_(participant_memory_ids),
                        ExploreMemory.place_id.in_(present_place_ids),
                    )
                )
                .order_by(ExploreMemory.created_at.desc(), ExploreMemory.id.desc())
            )
        )
        return ExploreFeedResponse(
            memories=[
                memory_response(db, memory, auth.user.id) for memory in memories
            ]
        )


@explore_router.get("/{memory_id}/media/{dig_id}")
def explore_media(
    memory_id: int,
    dig_id: int,
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    with SessionLocal() as db:
        require_memory_access(db, memory_id, auth.user.id)
        dig = db.scalar(
            select(Dig)
            .join(ExploreMemoryDig, ExploreMemoryDig.dig_id == Dig.id)
            .where(
                ExploreMemoryDig.memory_id == memory_id,
                Dig.id == dig_id,
                Dig.moderation_status == "approved",
            )
        )
        if dig is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Explore media not found",
            )
        content_type = dig.content_type
        storage_name = dig.storage_name

    media_path = settings.media_root / "digs" / storage_name
    if not media_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Explore media is unavailable",
        )
    return FileResponse(
        media_path,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=60"},
    )


@explore_router.post(
    "/{memory_id}/comments",
    response_model=ExploreCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(
    memory_id: int,
    payload: ExploreCommentRequest,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> ExploreCommentResponse:
    explore_rate_limiter.check(request, f"explore-comment-{auth.user.id}")
    with SessionLocal.begin() as db:
        require_memory_access(db, memory_id, auth.user.id)
        comment = ExploreComment(
            memory_id=memory_id,
            user_id=auth.user.id,
            text=payload.text,
            created_at=utc_now(),
        )
        db.add(comment)
        db.flush()
        return comment_response(comment, auth.user.nickname)


def like_response(db: Session, memory_id: int, user_id: int) -> ExploreLikeResponse:
    like_count = db.scalar(
        select(func.count())
        .select_from(ExploreLike)
        .where(ExploreLike.memory_id == memory_id)
    )
    return ExploreLikeResponse(
        liked_by_me=db.get(ExploreLike, (memory_id, user_id)) is not None,
        like_count=int(like_count or 0),
    )


@explore_router.post("/{memory_id}/likes", response_model=ExploreLikeResponse)
def like_memory(
    memory_id: int,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> ExploreLikeResponse:
    explore_rate_limiter.check(request, f"explore-like-{auth.user.id}")
    with SessionLocal.begin() as db:
        require_memory_access(db, memory_id, auth.user.id)
        if db.get(ExploreLike, (memory_id, auth.user.id)) is None:
            db.add(
                ExploreLike(
                    memory_id=memory_id,
                    user_id=auth.user.id,
                    created_at=utc_now(),
                )
            )
            db.flush()
        return like_response(db, memory_id, auth.user.id)


@explore_router.delete("/{memory_id}/likes", response_model=ExploreLikeResponse)
def unlike_memory(
    memory_id: int,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> ExploreLikeResponse:
    explore_rate_limiter.check(request, f"explore-unlike-{auth.user.id}")
    with SessionLocal.begin() as db:
        require_memory_access(db, memory_id, auth.user.id)
        like = db.get(ExploreLike, (memory_id, auth.user.id))
        if like is not None:
            db.delete(like)
            db.flush()
        return like_response(db, memory_id, auth.user.id)
