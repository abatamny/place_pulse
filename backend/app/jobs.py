from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import validate_model_input
from app.database import SessionLocal
from app.models import AIJob, JobQueueState, KnockMessage

TEXT_MODERATION_JOB = "text_moderation"
EXPLORE_CLUSTER_JOB = "explore_cluster"
KNOCK_CHECK_JOB = "knock_check"
FORUM_POST_CHECK_JOB = "forum_post_check"
FORUM_COMMENT_CHECK_JOB = "forum_comment_check"
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
QUEUE_STATE_NAME = "background"
DENIAL_VISIBLE_SECONDS = 15 * 60


@dataclass(frozen=True)
class ClaimedAIJob:
    id: int
    job_type: str
    payload: dict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_text_moderation(text: str, user_id: int | None = None) -> int:
    cleaned = validate_model_input(text, check_prompt_injection=False)
    payload: dict[str, object] = {"text": cleaned}
    if user_id is not None:
        payload["user_id"] = user_id
    with SessionLocal() as db:
        job = AIJob(
            job_type=TEXT_MODERATION_JOB,
            status=PENDING,
            payload=payload,
            attempts=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id


def queue_explore_cluster_check(
    db: Session,
    place_id: int,
    user_id: int,
) -> None:
    db.add(
        AIJob(
            job_type=EXPLORE_CLUSTER_JOB,
            status=PENDING,
            payload={"place_id": place_id, "user_id": user_id},
            attempts=0,
        )
    )


def queue_knock_check(
    db: Session,
    *,
    message_id: int,
    user_id: int,
    candidate_places: list[dict],
) -> None:
    db.add(
        AIJob(
            job_type=KNOCK_CHECK_JOB,
            status=PENDING,
            payload={
                "message_id": message_id,
                "user_id": user_id,
                "candidate_places": candidate_places,
            },
            attempts=0,
        )
    )


def queue_forum_post_check(
    db: Session,
    *,
    post_id: int,
    user_id: int,
    text: str,
    media_attachment_id: int | None = None,
) -> None:
    payload: dict[str, object] = {
        "post_id": post_id,
        "user_id": user_id,
        "text": validate_model_input(text, check_prompt_injection=False),
    }
    if media_attachment_id is not None:
        payload["media_attachment_id"] = media_attachment_id
    db.add(
        AIJob(
            job_type=FORUM_POST_CHECK_JOB,
            status=PENDING,
            payload=payload,
            attempts=0,
        )
    )


def queue_forum_comment_check(
    db: Session,
    *,
    comment_id: int,
    user_id: int,
    text: str,
    media_attachment_id: int | None = None,
) -> None:
    payload: dict[str, object] = {
        "comment_id": comment_id,
        "user_id": user_id,
        "text": validate_model_input(text, check_prompt_injection=False),
    }
    if media_attachment_id is not None:
        payload["media_attachment_id"] = media_attachment_id
    db.add(
        AIJob(
            job_type=FORUM_COMMENT_CHECK_JOB,
            status=PENDING,
            payload=payload,
            attempts=0,
        )
    )


def claim_next_job() -> ClaimedAIJob | None:
    with SessionLocal.begin() as db:
        pending_jobs = list(
            db.scalars(
                select(AIJob)
                .where(AIJob.status == PENDING)
                .order_by(AIJob.id)
                .with_for_update(skip_locked=True)
            )
        )
        if not pending_jobs:
            return None

        first_job_by_user: dict[int, AIJob] = {}
        for pending_job in pending_jobs:
            raw_user_id = pending_job.payload.get("user_id")
            user_id = (
                raw_user_id
                if isinstance(raw_user_id, int)
                and not isinstance(raw_user_id, bool)
                and raw_user_id > 0
                else 0
            )
            first_job_by_user.setdefault(user_id, pending_job)

        state = db.get(JobQueueState, QUEUE_STATE_NAME)
        if state is None:
            state = JobQueueState(
                queue_name=QUEUE_STATE_NAME,
                last_served={},
                serve_counter=0,
                updated_at=utc_now(),
            )
            db.add(state)

        last_served = state.last_served or {}
        # Round-robin by wait time: the user who was served longest ago goes
        # next, rather than cycling through user ids in numeric order. Users
        # who have never been served rank first; ties among them are broken
        # by whose oldest pending job was enqueued first.
        next_user_id = min(
            first_job_by_user,
            key=lambda user_id: (
                last_served.get(str(user_id), -1),
                first_job_by_user[user_id].id,
            ),
        )
        job = first_job_by_user[next_user_id]
        state.serve_counter += 1
        state.last_served = {**last_served, str(next_user_id): state.serve_counter}
        state.updated_at = utc_now()

        job.status = RUNNING
        job.attempts += 1
        job.started_at = utc_now()
        return ClaimedAIJob(
            id=job.id,
            job_type=job.job_type,
            payload=dict(job.payload),
        )


def complete_job(job_id: int, result: dict) -> None:
    with SessionLocal.begin() as db:
        job = db.get(AIJob, job_id)
        if job is None:
            return
        job.status = COMPLETED
        job.result = result
        job.error = None
        job.completed_at = utc_now()
        knock_message_id = job.payload.get("knock_message_id")
        if isinstance(knock_message_id, int):
            message = db.get(KnockMessage, knock_message_id)
            if message is not None:
                message.moderation_status = (
                    "approved" if result.get("approved") is True else "flagged"
                )


def fail_job(job_id: int, error: str) -> None:
    with SessionLocal.begin() as db:
        job = db.get(AIJob, job_id)
        if job is None:
            return
        job.status = FAILED
        job.result = None
        job.error = error[:500]
        job.completed_at = utc_now()
