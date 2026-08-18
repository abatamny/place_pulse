from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.ai import validate_model_input
from app.database import SessionLocal
from app.models import AIJob

TEXT_MODERATION_JOB = "text_moderation"
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"


@dataclass(frozen=True)
class ClaimedAIJob:
    id: int
    job_type: str
    payload: dict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_text_moderation(text: str) -> int:
    cleaned = validate_model_input(text, check_prompt_injection=False)
    with SessionLocal() as db:
        job = AIJob(
            job_type=TEXT_MODERATION_JOB,
            status=PENDING,
            payload={"text": cleaned},
            attempts=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id


def claim_next_job() -> ClaimedAIJob | None:
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(AIJob)
            .where(AIJob.status == PENDING)
            .order_by(AIJob.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None

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


def fail_job(job_id: int, error: str) -> None:
    with SessionLocal.begin() as db:
        job = db.get(AIJob, job_id)
        if job is None:
            return
        job.status = FAILED
        job.result = None
        job.error = error[:500]
        job.completed_at = utc_now()
