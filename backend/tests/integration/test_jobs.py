import pytest

from app.database import SessionLocal
from app.jobs import (
    claim_next_job,
    complete_job,
    enqueue_text_moderation,
    queue_forum_comment_check,
    queue_forum_post_check,
    queue_knock_check,
)


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


def test_fairness_rotates_by_user_across_every_job_type() -> None:
    """A user who floods KNOCK/forum jobs cannot starve another user's job,
    regardless of which job types are mixed in the shared queue."""
    with SessionLocal.begin() as db:
        queue_knock_check(db, message_id=1, user_id=30, candidate_places=[])
        queue_forum_post_check(db, post_id=1, user_id=30, text="Spammy post")
        queue_forum_comment_check(
            db, comment_id=1, user_id=30, text="Spammy comment"
        )
    enqueue_text_moderation("A single message from the quiet user", user_id=40)

    claimed_types: list[str] = []
    claimed_users: list[int] = []
    for _ in range(4):
        claimed = claim_next_job()
        assert claimed is not None
        claimed_types.append(claimed.job_type)
        claimed_users.append(claimed.payload["user_id"])
        complete_job(claimed.id, {"handled": True})

    assert claimed_users == [30, 40, 30, 30]
    assert claimed_types == [
        "knock_check",
        "text_moderation",
        "forum_post_check",
        "forum_comment_check",
    ]


def test_rotation_follows_wait_time_not_user_id_order() -> None:
    """A user with a lower id who has already had a turn must not cut in
    front of a higher-id user who has been waiting longer, and vice versa:
    turn order should track who was served longest ago, not numeric id."""
    user_a_job = enqueue_text_moderation("From user A", user_id=100)
    user_b_job = enqueue_text_moderation("From user B", user_id=5)

    first = claim_next_job()
    assert first is not None
    assert first.id == user_a_job
    complete_job(first.id, {"approved": True})

    # User A (id 100) gets a new job right away, while user B (id 5) is
    # still waiting on its very first turn. Naive numeric-id rotation would
    # wrap straight back to the smallest id (5) here too, which happens to
    # be correct - so add a third, even-lower id user who arrives late and
    # must NOT jump the still-waiting user B.
    user_c_job = enqueue_text_moderation("From user C", user_id=1)

    second = claim_next_job()
    assert second is not None
    assert second.id == user_b_job
    complete_job(second.id, {"approved": True})

    third = claim_next_job()
    assert third is not None
    assert third.id == user_c_job
    complete_job(third.id, {"approved": True})
