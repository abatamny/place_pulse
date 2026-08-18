import asyncio
import logging

from app.ai import (
    AIAdapter,
    AIError,
    AIInputError,
    ModerationDecision,
    PromptInjectionError,
    create_ai_adapter,
    request_moderation,
)
from app.config import settings
from app.database import create_schema
from app.explore import create_memory_from_activity
from app.jobs import (
    EXPLORE_CLUSTER_JOB,
    TEXT_MODERATION_JOB,
    claim_next_job,
    complete_job,
    fail_job,
)

POLL_INTERVAL_SECONDS = 2
logger = logging.getLogger("placepulse.worker")


async def process_next_job(
    adapter: AIAdapter | None = None,
    *,
    timeout_seconds: float | None = None,
) -> bool:
    job = claim_next_job()
    if job is None:
        return False

    try:
        if job.job_type == EXPLORE_CLUSTER_JOB:
            place_id = job.payload.get("place_id")
            if not isinstance(place_id, int) or place_id <= 0:
                raise AIInputError("Explore cluster job is missing a place")
            memory_id = create_memory_from_activity(place_id)
            complete_job(
                job.id,
                {
                    "created": memory_id is not None,
                    "memory_id": memory_id,
                },
            )
            return True

        if job.job_type != TEXT_MODERATION_JOB:
            raise AIInputError(f"Unsupported AI job type: {job.job_type}")

        text = job.payload.get("text")
        if not isinstance(text, str):
            raise AIInputError("Moderation job is missing text")

        active_adapter = adapter or create_ai_adapter()
        try:
            decision = await request_moderation(
                active_adapter,
                text,
                timeout_seconds=timeout_seconds or settings.ai_timeout_seconds,
            )
        except PromptInjectionError:
            decision = ModerationDecision(
                approved=False,
                reason="Possible prompt injection detected",
                categories=["prompt_injection"],
            )

        complete_job(job.id, decision.model_dump())
    except AIError as exc:
        fail_job(job.id, str(exc))
    except Exception:
        logger.exception("Unexpected failure while processing AI job %s", job.id)
        fail_job(job.id, "Unexpected worker failure")
    return True


async def run_worker() -> None:
    create_schema()
    logger.info("AI worker started")
    while True:
        try:
            processed = await process_next_job()
        except Exception:
            logger.exception("Worker loop failed")
            processed = False
        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
