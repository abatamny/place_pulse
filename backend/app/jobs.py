from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import validate_model_input
from app.database import SessionLocal
from app.models import AIJob, JobQueueState, KnockMessage

TEXT_MODERATION_JOB = "text_moderation"
EXPLORE_CLUSTER_JOB = "explore_cluster"
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
QUEUE_STATE_NAME = "background"


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
                last_user_id=None,
                updated_at=utc_now(),
            )
            db.add(state)

        user_ids = sorted(first_job_by_user)
        last_user_id = state.last_user_id
        next_user_id = user_ids[0]
        if last_user_id is not None:
            next_user_id = next(
                (user_id for user_id in user_ids if user_id > last_user_id),
                user_ids[0],
            )
        job = first_job_by_user[next_user_id]
        state.last_user_id = next_user_id
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
