import asyncio

import pytest
from sqlalchemy import select

from app.ai import ModerationDecision
from app.database import SessionLocal
from app.jobs import COMPLETED, FAILED, enqueue_text_moderation
from app.models import AIJob
from app.worker import process_next_job


pytestmark = pytest.mark.integration


class FakeWorkerAI:
    def __init__(self, decision: object | None = None) -> None:
        self.decision = decision or ModerationDecision(
            approved=True,
            reason="Message is suitable for the place feed",
            categories=[],
        )

    async def moderate_text(self, text: str) -> object:
        return self.decision


def test_worker_stores_background_moderation_result() -> None:
    job_id = enqueue_text_moderation("A calm post-publication message")

    assert asyncio.run(process_next_job(FakeWorkerAI())) is True

    with SessionLocal() as db:
        job = db.get(AIJob, job_id)
        assert job is not None
        assert job.status == COMPLETED
        assert job.attempts == 1
        assert job.result == {
            "approved": True,
            "reason": "Message is suitable for the place feed",
            "categories": [],
        }
        assert job.error is None
        assert job.completed_at is not None


@pytest.mark.security
def test_worker_records_invalid_model_output_as_failed() -> None:
    job_id = enqueue_text_moderation("This result will be malformed")

    assert asyncio.run(
        process_next_job(FakeWorkerAI({"unexpected": "output"}))
    ) is True

    with SessionLocal() as db:
        job = db.scalar(select(AIJob).where(AIJob.id == job_id))
        assert job is not None
        assert job.status == FAILED
        assert job.result is None
        assert job.error == "AI moderation returned invalid output"
