from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import AIAdapter, get_ai_adapter, moderate_before_publication
from app.auth import AuthContext, require_auth
from app.database import SessionLocal
from app.models import (
    ForumComment,
    ForumPost,
    ForumVote,
    Place,
    Presence,
    User,
)
from app.place_labels import place_display_name
from app.places import PRESENCE_TTL
from app.rate_limit import AuthRateLimiter
from app.schemas import (
    ForumCommentCreate,
    ForumCommentResponse,
    ForumFeedResponse,
    ForumPostCreate,
    ForumPostResponse,
    ForumVoteRequest,
    ForumVoteResponse,
    PersonalForumResponse,
)

FORUM_POST_LIMIT = 100
FORUM_WRITES_PER_MINUTE = 20

forum_router = APIRouter(prefix="/api/forum", tags=["forum"])
forum_rate_limiter = AuthRateLimiter(
    max_attempts=FORUM_WRITES_PER_MINUTE,
    window_seconds=60,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def user_is_present_in_session(db: Session, user_id: int, place_id: int) -> bool:
    cutoff = utc_now() - PRESENCE_TTL
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


def require_place_access(db: Session, user_id: int, place_id: int) -> Place:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Place not found",
        )
    if not user_is_present_in_session(db, user_id, place_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be present at this place to use its forum",
        )
    return place


def require_post_access(db: Session, user_id: int, post_id: int) -> ForumPost:
    post = db.get(ForumPost, post_id)
    if post is None or post.moderation_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Forum post not found",
        )
    require_place_access(db, user_id, post.place_id)
    return post


async def require_safe_forum_text(adapter: AIAdapter, text: str) -> None:
    decision = await moderate_before_publication(adapter, text)
    if "ai_failure" in decision.categories:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forum moderation is temporarily unavailable",
        )
    if not decision.approved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This forum content cannot be published",
        )


def vote_counts(db: Session, post_id: int, user_id: int) -> ForumVoteResponse:
    values = list(
        db.scalars(select(ForumVote.value).where(ForumVote.post_id == post_id))
    )
    my_vote = db.get(ForumVote, (post_id, user_id))
    upvotes = values.count(1)
    downvotes = values.count(-1)
    return ForumVoteResponse(
        upvotes=upvotes,
        downvotes=downvotes,
        score=upvotes - downvotes,
        my_vote=my_vote.value if my_vote is not None else 0,
    )


def post_response(
    db: Session,
    post: ForumPost,
    viewer_user_id: int,
) -> ForumPostResponse:
    place = db.get(Place, post.place_id)
    author = db.get(User, post.user_id)
    comment_rows = db.execute(
        select(ForumComment, User.nickname)
        .join(User, User.id == ForumComment.user_id)
        .where(
            ForumComment.post_id == post.id,
            ForumComment.moderation_status == "approved",
        )
        .order_by(ForumComment.created_at, ForumComment.id)
    ).all()
    votes = vote_counts(db, post.id, viewer_user_id)
    is_mine = post.user_id == viewer_user_id
    return ForumPostResponse(
        id=post.id,
        place_id=post.place_id,
        place_name=place.name if place is not None else "Unknown place",
        place_display_name=place_display_name(db, place),
        user_id=None if post.is_anonymous else post.user_id,
        nickname=(
            "Anonymous"
            if post.is_anonymous
            else author.nickname if author is not None else "Unknown user"
        ),
        is_anonymous=post.is_anonymous,
        is_mine=is_mine,
        title=post.title,
        body=post.body,
        upvotes=votes.upvotes,
        downvotes=votes.downvotes,
        score=votes.score,
        my_vote=votes.my_vote,
        created_at=post.created_at,
        comments=[
            ForumCommentResponse(
                id=comment.id,
                user_id=comment.user_id,
                nickname=nickname,
                text=comment.text,
                created_at=comment.created_at,
            )
            for comment, nickname in comment_rows
        ],
    )


@forum_router.get("", response_model=ForumFeedResponse)
def forum_feed(
    place_id: int = Query(gt=0),
    auth: AuthContext = Depends(require_auth),
) -> ForumFeedResponse:
    with SessionLocal() as db:
        require_place_access(db, auth.user.id, place_id)
        posts = list(
            db.scalars(
                select(ForumPost)
                .where(
                    ForumPost.place_id == place_id,
                    ForumPost.moderation_status == "approved",
                )
                .order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
                .limit(FORUM_POST_LIMIT)
            )
        )
        return ForumFeedResponse(
            posts=[post_response(db, post, auth.user.id) for post in posts]
        )


@forum_router.post(
    "/posts",
    response_model=ForumPostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_post(
    payload: ForumPostCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> ForumPostResponse:
    forum_rate_limiter.check(request, f"forum-post-{auth.user.id}")
    with SessionLocal() as db:
        require_place_access(db, auth.user.id, payload.place_id)

    await require_safe_forum_text(
        adapter,
        f"Title: {payload.title}\n\nPost: {payload.body}",
    )

    with SessionLocal.begin() as db:
        require_place_access(db, auth.user.id, payload.place_id)
        post = ForumPost(
            place_id=payload.place_id,
            user_id=auth.user.id,
            title=payload.title,
            body=payload.body,
            is_anonymous=payload.is_anonymous,
            moderation_status="approved",
            created_at=utc_now(),
        )
        db.add(post)
        db.flush()
        return post_response(db, post, auth.user.id)


@forum_router.post(
    "/posts/{post_id}/comments",
    response_model=ForumCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    post_id: int,
    payload: ForumCommentCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> ForumCommentResponse:
    forum_rate_limiter.check(request, f"forum-comment-{auth.user.id}")
    with SessionLocal() as db:
        require_post_access(db, auth.user.id, post_id)

    await require_safe_forum_text(adapter, payload.text)

    with SessionLocal.begin() as db:
        require_post_access(db, auth.user.id, post_id)
        comment = ForumComment(
            post_id=post_id,
            user_id=auth.user.id,
            text=payload.text,
            moderation_status="approved",
            created_at=utc_now(),
        )
        db.add(comment)
        db.flush()
        return ForumCommentResponse(
            id=comment.id,
            user_id=comment.user_id,
            nickname=auth.user.nickname,
            text=comment.text,
            created_at=comment.created_at,
        )


@forum_router.put(
    "/posts/{post_id}/vote",
    response_model=ForumVoteResponse,
)
def set_vote(
    post_id: int,
    payload: ForumVoteRequest,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> ForumVoteResponse:
    forum_rate_limiter.check(request, f"forum-vote-{auth.user.id}")
    with SessionLocal.begin() as db:
        require_post_access(db, auth.user.id, post_id)
        vote = db.get(ForumVote, (post_id, auth.user.id))
        if vote is None:
            vote = ForumVote(
                post_id=post_id,
                user_id=auth.user.id,
                value=payload.value,
                created_at=utc_now(),
            )
            db.add(vote)
        else:
            vote.value = payload.value
        db.flush()
        return vote_counts(db, post_id, auth.user.id)


@forum_router.delete(
    "/posts/{post_id}/vote",
    response_model=ForumVoteResponse,
)
def remove_vote(
    post_id: int,
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> ForumVoteResponse:
    forum_rate_limiter.check(request, f"forum-unvote-{auth.user.id}")
    with SessionLocal.begin() as db:
        require_post_access(db, auth.user.id, post_id)
        vote = db.get(ForumVote, (post_id, auth.user.id))
        if vote is not None:
            db.delete(vote)
            db.flush()
        return vote_counts(db, post_id, auth.user.id)


@forum_router.get("/me", response_model=PersonalForumResponse)
def personal_forum(
    auth: AuthContext = Depends(require_auth),
) -> PersonalForumResponse:
    with SessionLocal() as db:
        posts = list(
            db.scalars(
                select(ForumPost)
                .where(
                    ForumPost.user_id == auth.user.id,
                    ForumPost.moderation_status == "approved",
                )
                .order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
            )
        )
        responses = [post_response(db, post, auth.user.id) for post in posts]
        total_upvotes = db.scalar(
            select(func.count())
            .select_from(ForumVote)
            .join(ForumPost, ForumPost.id == ForumVote.post_id)
            .where(
                ForumPost.user_id == auth.user.id,
                ForumVote.value == 1,
            )
        )
        total_downvotes = db.scalar(
            select(func.count())
            .select_from(ForumVote)
            .join(ForumPost, ForumPost.id == ForumVote.post_id)
            .where(
                ForumPost.user_id == auth.user.id,
                ForumVote.value == -1,
            )
        )
        upvotes = int(total_upvotes or 0)
        downvotes = int(total_downvotes or 0)
        return PersonalForumResponse(
            posts=responses,
            total_upvotes=upvotes,
            total_downvotes=downvotes,
            total_score=upvotes - downvotes,
        )
