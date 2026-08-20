from datetime import datetime, timezone
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
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.ai import (
    AIAdapter,
    get_ai_adapter,
    moderate_before_publication,
    moderate_media_before_publication,
)
from app.attachments import (
    attachment_for_comment,
    attachment_for_post,
    attachment_response,
)
from app.auth import AuthContext, require_auth
from app.database import SessionLocal
from app.models import (
    ForumComment,
    ForumPost,
    ForumVote,
    MediaAttachment,
    Place,
    Presence,
    User,
)
from app.media import (
    read_limited_upload,
    store_media,
    validate_filename,
    validate_media,
)
from app.place_labels import place_display_name
from app.place_scope import (
    active_place_ids,
    current_content_places,
    resolve_content_place_scope,
)
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
    clean_required_text,
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


async def read_and_moderate_forum_media(
    adapter: AIAdapter, upload: UploadFile
) -> tuple[bytes, str, str, str]:
    media_type, content_type = validate_filename(upload.filename, upload.content_type)
    try:
        data = await read_limited_upload(upload)
    finally:
        await upload.close()
    samples = validate_media(data, media_type, content_type)
    decision = await moderate_media_before_publication(adapter, samples)
    if "ai_failure" in decision.categories:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forum media moderation is temporarily unavailable",
        )
    if not decision.approved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This forum media cannot be published",
        )
    return data, media_type, content_type, upload.filename or "upload"


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
    origin_place = db.get(Place, post.origin_place_id)
    author = db.get(User, post.user_id)
    comment_rows = db.execute(
        select(ForumComment, User.nickname)
        .join(User, User.id == ForumComment.user_id)
        .where(
            ForumComment.post_id == post.id,
            or_(
                ForumComment.moderation_status == "approved",
                and_(
                    ForumComment.moderation_status == "pending",
                    ForumComment.user_id == viewer_user_id,
                ),
            ),
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
        origin_place_id=post.origin_place_id,
        origin_place_name=(
            origin_place.name if origin_place is not None else "Unknown place"
        ),
        origin_place_display_name=place_display_name(db, origin_place),
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
        moderation_status=post.moderation_status,
        upvotes=votes.upvotes,
        downvotes=votes.downvotes,
        score=votes.score,
        my_vote=votes.my_vote,
        created_at=post.created_at,
        media=attachment_response(attachment_for_post(db, post.id)),
        comments=[
            ForumCommentResponse(
                id=comment.id,
                user_id=comment.user_id,
                nickname=nickname,
                text=comment.text,
                moderation_status=comment.moderation_status,
                created_at=comment.created_at,
                media=attachment_response(attachment_for_comment(db, comment.id)),
            )
            for comment, nickname in comment_rows
        ],
    )


@forum_router.get("", response_model=ForumFeedResponse)
def forum_feed(
    place_id: int | None = None,
    auth: AuthContext = Depends(require_auth),
) -> ForumFeedResponse:
    with SessionLocal() as db:
        current_place_ids = active_place_ids(db, auth.user.id)
        if not current_place_ids:
            return ForumFeedResponse(posts=[])
        selected_place_id = place_id
        if selected_place_id is None:
            selected_place_id = current_content_places(db, auth.user.id).origin.id
        require_place_access(db, auth.user.id, selected_place_id)
        posts = list(
            db.scalars(
                select(ForumPost)
                .where(
                    ForumPost.place_id == selected_place_id,
                    or_(
                        ForumPost.moderation_status == "approved",
                        and_(
                            ForumPost.moderation_status == "pending",
                            ForumPost.user_id == auth.user.id,
                        ),
                    ),
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
        selected_place_id = payload.place_id
        if selected_place_id is None:
            selected_place_id = current_content_places(db, auth.user.id).origin.id
        resolve_content_place_scope(db, auth.user.id, selected_place_id)

    with SessionLocal.begin() as db:
        content_scope = resolve_content_place_scope(
            db,
            auth.user.id,
            selected_place_id,
        )
        post = ForumPost(
            place_id=content_scope.scope.id,
            origin_place_id=content_scope.origin.id,
            user_id=auth.user.id,
            title=payload.title,
            body=payload.body,
            is_anonymous=payload.is_anonymous,
            moderation_status="pending",
            created_at=utc_now(),
        )
        db.add(post)
        db.flush()
        post_id = post.id

    try:
        post_text = f"Title: {payload.title}\n\nPost: {payload.body}"
        await require_safe_forum_text(adapter, post_text)
    except Exception:
        with SessionLocal.begin() as db:
            pending_post = db.get(ForumPost, post_id)
            if pending_post is not None and pending_post.moderation_status == "pending":
                db.delete(pending_post)
        raise

    with SessionLocal.begin() as db:
        post = db.get(ForumPost, post_id)
        if post is None:
            raise HTTPException(status_code=404, detail="Forum post not found")
        post.moderation_status = "approved"
        db.flush()
        return post_response(db, post, auth.user.id)


@forum_router.post(
    "/posts/with-media",
    response_model=ForumPostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_post_with_media(
    request: Request,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=120)],
    body: Annotated[str, Form(min_length=1, max_length=1800)],
    place_id: Annotated[int | None, Form(gt=0)] = None,
    is_anonymous: Annotated[bool, Form()] = False,
    auth: AuthContext = Depends(require_auth),
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> ForumPostResponse:
    forum_rate_limiter.check(request, f"forum-post-{auth.user.id}")
    try:
        title = clean_required_text(title, "Post title cannot be empty")
        body = clean_required_text(body, "Post text cannot be empty")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with SessionLocal() as db:
        selected_place_id = place_id
        if selected_place_id is None:
            selected_place_id = current_content_places(db, auth.user.id).origin.id
        resolve_content_place_scope(db, auth.user.id, selected_place_id)

    with SessionLocal.begin() as db:
        content_scope = resolve_content_place_scope(
            db, auth.user.id, selected_place_id
        )
        post = ForumPost(
            place_id=content_scope.scope.id,
            origin_place_id=content_scope.origin.id,
            user_id=auth.user.id,
            title=title,
            body=body,
            is_anonymous=is_anonymous,
            moderation_status="pending",
            created_at=utc_now(),
        )
        db.add(post)
        db.flush()
        post_id = post.id

    try:
        await require_safe_forum_text(adapter, f"Title: {title}\n\nPost: {body}")
        data, media_type, content_type, original_filename = (
            await read_and_moderate_forum_media(adapter, file)
        )
        storage_name, media_path = store_media(data, original_filename, "attachments")
        with SessionLocal.begin() as db:
            post = db.get(ForumPost, post_id)
            if post is None:
                raise HTTPException(status_code=404, detail="Forum post not found")
            post.moderation_status = "approved"
            db.add(
                MediaAttachment(
                    user_id=auth.user.id,
                    forum_post_id=post.id,
                    media_type=media_type,
                    content_type=content_type,
                    storage_name=storage_name,
                    original_filename=original_filename,
                    file_size=len(data),
                    moderation_status="approved",
                    created_at=utc_now(),
                )
            )
            db.flush()
            return post_response(db, post, auth.user.id)
    except Exception:
        if "media_path" in locals():
            media_path.unlink(missing_ok=True)
        with SessionLocal.begin() as db:
            pending_post = db.get(ForumPost, post_id)
            if pending_post is not None and pending_post.moderation_status == "pending":
                db.delete(pending_post)
        raise


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

    with SessionLocal.begin() as db:
        require_post_access(db, auth.user.id, post_id)
        comment = ForumComment(
            post_id=post_id,
            user_id=auth.user.id,
            text=payload.text,
            moderation_status="pending",
            created_at=utc_now(),
        )
        db.add(comment)
        db.flush()
        comment_id = comment.id

    try:
        await require_safe_forum_text(adapter, payload.text)
    except Exception:
        with SessionLocal.begin() as db:
            pending_comment = db.get(ForumComment, comment_id)
            if pending_comment is not None and pending_comment.moderation_status == "pending":
                db.delete(pending_comment)
        raise

    with SessionLocal.begin() as db:
        comment = db.get(ForumComment, comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Forum comment not found")
        comment.moderation_status = "approved"
        db.flush()
        return ForumCommentResponse(
            id=comment.id,
            user_id=comment.user_id,
            nickname=auth.user.nickname,
            text=comment.text,
            moderation_status=comment.moderation_status,
            created_at=comment.created_at,
        )


@forum_router.post(
    "/posts/{post_id}/comments/with-media",
    response_model=ForumCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment_with_media(
    post_id: int,
    request: Request,
    file: Annotated[UploadFile, File()],
    text: Annotated[str, Form(min_length=1, max_length=1000)],
    auth: AuthContext = Depends(require_auth),
    adapter: AIAdapter = Depends(get_ai_adapter),
) -> ForumCommentResponse:
    forum_rate_limiter.check(request, f"forum-comment-{auth.user.id}")
    try:
        text = clean_required_text(text, "Comment cannot be empty")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with SessionLocal() as db:
        require_post_access(db, auth.user.id, post_id)
    with SessionLocal.begin() as db:
        require_post_access(db, auth.user.id, post_id)
        comment = ForumComment(
            post_id=post_id,
            user_id=auth.user.id,
            text=text,
            moderation_status="pending",
            created_at=utc_now(),
        )
        db.add(comment)
        db.flush()
        comment_id = comment.id

    try:
        await require_safe_forum_text(adapter, text)
        data, media_type, content_type, original_filename = (
            await read_and_moderate_forum_media(adapter, file)
        )
        storage_name, media_path = store_media(data, original_filename, "attachments")
        with SessionLocal.begin() as db:
            comment = db.get(ForumComment, comment_id)
            if comment is None:
                raise HTTPException(status_code=404, detail="Forum comment not found")
            comment.moderation_status = "approved"
            attachment = MediaAttachment(
                user_id=auth.user.id,
                forum_comment_id=comment.id,
                media_type=media_type,
                content_type=content_type,
                storage_name=storage_name,
                original_filename=original_filename,
                file_size=len(data),
                moderation_status="approved",
                created_at=utc_now(),
            )
            db.add(attachment)
            db.flush()
            return ForumCommentResponse(
                id=comment.id,
                user_id=comment.user_id,
                nickname=auth.user.nickname,
                text=comment.text,
                moderation_status=comment.moderation_status,
                created_at=comment.created_at,
                media=attachment_response(attachment),
            )
    except Exception:
        if "media_path" in locals():
            media_path.unlink(missing_ok=True)
        with SessionLocal.begin() as db:
            pending_comment = db.get(ForumComment, comment_id)
            if pending_comment is not None and pending_comment.moderation_status == "pending":
                db.delete(pending_comment)
        raise


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
                    ForumPost.moderation_status.in_(("approved", "pending")),
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
