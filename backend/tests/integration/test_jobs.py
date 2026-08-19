import pytest

from app.jobs import claim_next_job, complete_job, enqueue_text_moderation


pytestmark = pytest.mark.integration


def test_jobs_rotate_between_users_instead_of_following_global_fifo() -> None:
    first_user_jobs = [
        enqueue_text_moderation(f"Message {number} from user one", user_id=10)
        for number in range(3)
    ]
    second_user_job = enqueue_text_moderation(
        "Message from user two",
        user_id=20,
    )

    claimed_ids: list[int] = []
    claimed_users: list[int] = []
    for _ in range(4):
        claimed = claim_next_job()
        assert claimed is not None
        claimed_ids.append(claimed.id)
        claimed_users.append(claimed.payload["user_id"])
        complete_job(claimed.id, {"approved": True})

    assert claimed_users == [10, 20, 10, 10]
    assert claimed_ids == [
        first_user_jobs[0],
        second_user_job,
        first_user_jobs[1],
        first_user_jobs[2],
    ]


def test_legacy_jobs_without_an_owner_are_still_processed() -> None:
    job_id = enqueue_text_moderation("A system-owned moderation job")

    claimed = claim_next_job()

    assert claimed is not None
    assert claimed.id == job_id
    assert "user_id" not in claimed.payload
