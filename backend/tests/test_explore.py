import asyncio
import io
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, func, select

from app.ai import ImageModerationInput, ModerationDecision, get_ai_adapter
from app.auth import hash_session_token
from app.config import settings
from app.database import SessionLocal
from app.explore import create_memory_from_activity
from app.main import app
from app.models import (
    AIJob,
    AuthSession,
    Dig,
    ExploreComment,
    ExploreLike,
    ExploreMemory,
    ExploreMemoryDig,
    ExploreParticipant,
    Place,
    PlaceMembership,
    Presence,
    User,
)
from app.worker import process_next_job


@dataclass(frozen=True)
class SessionIdentity:
    user_id: int
    token: str


class FakeMediaAI:
    async def moderate_images(
        self, images: list[ImageModerationInput]
    ) -> ModerationDecision:
        assert images
        return ModerationDecision(
            approved=True,
            reason="Media is suitable for publication",
            categories=[],
        )


@pytest.fixture
def fake_media_ai():
    app.dependency_overrides[get_ai_adapter] = lambda: FakeMediaAI()
    yield
    app.dependency_overrides.pop(get_ai_adapter, None)


def create_place(
    name: str,
    osm_id: int,
    parent_place_id: int | None = None,
) -> int:
    with SessionLocal() as db:
        place = Place(
            osm_type="way",
            osm_id=osm_id,
            name=name,
            center_lat=32.0,
            center_lon=35.0,
            radius_m=75,
            parent_place_id=parent_place_id,
        )
        db.add(place)
        db.commit()
        db.refresh(place)
        return place.id


def create_user(
    phone: str,
    nickname: str,
    place_id: int | None = None,
) -> SessionIdentity:
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user = User(
            phone=phone,
            nickname=nickname,
            password_hash="not-used-in-this-test",
            is_verified=True,
        )
        db.add(user)
        db.flush()
        db.add(
            AuthSession(
                token_hash=hash_session_token(token),
                user_id=user.id,
                expires_at=now + timedelta(hours=1),
            )
        )
        if place_id is not None:
            db.add(
                Presence(
                    user_id=user.id,
                    place_id=place_id,
                    started_at=now,
                    last_seen_at=now,
                )
            )
            db.add(
                PlaceMembership(
                    user_id=user.id,
                    place_id=place_id,
                    rank="VISITOR",
                    completed_visits=0,
                )
            )
        db.commit()
        return SessionIdentity(user_id=user.id, token=token)


def auth_headers(identity: SessionIdentity) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity.token}"}


def jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(output, format="JPEG")
    return output.getvalue()


def upload_image(
    client: TestClient,
    identity: SessionIdentity,
    place_id: int,
    number: int,
):
    return client.post(
        "/api/digs",
        headers=auth_headers(identity),
        data={"place_id": str(place_id)},
        files={
            "file": (
                f"moment-{number}.jpg",
                jpeg_bytes((30 * number, 100, 150)),
                "image/jpeg",
            )
        },
    )


def create_memory_for_user(
    place_id: int,
    identity: SessionIdentity,
    *,
    expired: bool = False,
) -> int:
    now = datetime.now(timezone.utc)
    media_directory = settings.media_root / "digs"
    media_directory.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        for number in range(3):
            storage_name = f"explore-test-{place_id}-{number}.jpg"
            (media_directory / storage_name).write_bytes(
                jpeg_bytes((50 + number, 120, 160))
            )
            db.add(
                Dig(
                    place_id=place_id,
                    user_id=identity.user_id,
                    media_type="image",
                    content_type="image/jpeg",
                    storage_name=storage_name,
                    original_filename=f"memory-{number}.jpg",
                    file_size=(media_directory / storage_name).stat().st_size,
                    moderation_status="approved",
                    created_at=now - timedelta(minutes=3 - number),
                    expires_at=(
                        now - timedelta(minutes=1)
                        if expired
                        else now + timedelta(hours=23)
                    ),
                )
            )
        db.commit()

    memory_id = create_memory_from_activity(place_id, now)
    assert memory_id is not None
    return memory_id


def test_uploaded_activity_worker_creates_memory_that_outlives_digs(
    client: TestClient,
    fake_media_ai,
) -> None:
    place_id = create_place("Festival Courtyard", 4001)
    participant = create_user("0500004001", "Participant", place_id)

    uploads = [
        upload_image(client, participant, place_id, number)
        for number in range(1, 4)
    ]
    assert [response.status_code for response in uploads] == [201, 201, 201]

    assert asyncio.run(process_next_job()) is True

    with SessionLocal() as db:
        memory = db.scalar(select(ExploreMemory))
        assert memory is not None
        memory_id = memory.id
        assert db.scalar(select(func.count()).select_from(ExploreMemoryDig)) == 3
        assert db.get(ExploreParticipant, (memory_id, participant.user_id))
        completed_job = db.scalar(
            select(AIJob).where(AIJob.status == "completed")
        )
        assert completed_job is not None
        assert completed_job.result == {"created": True, "memory_id": memory_id}
        for dig in db.scalars(select(Dig)):
            dig.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.execute(
            delete(Presence).where(Presence.user_id == participant.user_id)
        )
        db.commit()

    feed = client.get("/api/explore", headers=auth_headers(participant))
    assert feed.status_code == 200
    assert [memory["id"] for memory in feed.json()["memories"]] == [memory_id]
    assert feed.json()["memories"][0]["participant"] is True

    media = client.get(
        feed.json()["memories"][0]["digs"][0]["media_url"],
        headers=auth_headers(participant),
    )
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/jpeg"


def test_nonparticipant_needs_current_presence_to_access_memory(
    client: TestClient,
) -> None:
    place_id = create_place("Memory Hall", 4002)
    participant = create_user("0500004002", "Past Participant")
    outsider = create_user("0500004003", "Current Visitor")
    memory_id = create_memory_for_user(place_id, participant, expired=True)
    media_url = f"/api/explore/{memory_id}/media/1"

    denied_feed = client.get("/api/explore", headers=auth_headers(outsider))
    denied_media = client.get(media_url, headers=auth_headers(outsider))
    assert denied_feed.json() == {"memories": []}
    assert denied_media.status_code == 403

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            Presence(
                user_id=outsider.user_id,
                place_id=place_id,
                started_at=now,
                last_seen_at=now,
            )
        )
        db.commit()

    allowed_feed = client.get("/api/explore", headers=auth_headers(outsider))
    assert allowed_feed.status_code == 200
    assert [memory["id"] for memory in allowed_feed.json()["memories"]] == [
        memory_id
    ]
    actual_media_url = allowed_feed.json()["memories"][0]["digs"][0]["media_url"]
    assert client.get(actual_media_url, headers=auth_headers(outsider)).status_code == 200

    with SessionLocal() as db:
        presence = db.get(Presence, (outsider.user_id, place_id))
        assert presence is not None
        presence.last_seen_at = now - timedelta(minutes=5)
        db.commit()

    assert client.get("/api/explore", headers=auth_headers(outsider)).json() == {
        "memories": []
    }
    assert (
        client.get(actual_media_url, headers=auth_headers(outsider)).status_code
        == 403
    )


def test_feed_describes_nested_places_and_distinct_participants(
    client: TestClient,
    fake_media_ai,
) -> None:
    campus_id = create_place("Example Campus", 4010)
    building_id = create_place("Library Building", 4011, campus_id)
    first = create_user("0500004010", "First Witness", building_id)
    second = create_user("0500004011", "Second Witness", building_id)

    uploads = [
        upload_image(client, first, building_id, 1),
        upload_image(client, first, building_id, 2),
        upload_image(client, second, building_id, 3),
    ]
    assert [response.status_code for response in uploads] == [201, 201, 201]
    assert asyncio.run(process_next_job()) is True

    feed = client.get("/api/explore", headers=auth_headers(first))
    assert feed.status_code == 200
    memory = feed.json()["memories"][0]
    assert memory["place_names"] == ["Example Campus", "Library Building"]
    assert memory["participant_count"] == 2


def test_participant_can_comment_like_and_unlike_after_leaving(
    client: TestClient,
) -> None:
    place_id = create_place("Old Library", 4003)
    participant = create_user("0500004004", "Remembering User")
    memory_id = create_memory_for_user(place_id, participant, expired=True)

    comment = client.post(
        f"/api/explore/{memory_id}/comments",
        headers=auth_headers(participant),
        json={"text": "  A great moment after class.  "},
    )
    first_like = client.post(
        f"/api/explore/{memory_id}/likes",
        headers=auth_headers(participant),
    )
    repeated_like = client.post(
        f"/api/explore/{memory_id}/likes",
        headers=auth_headers(participant),
    )

    assert comment.status_code == 201
    assert comment.json()["text"] == "A great moment after class."
    assert first_like.json() == {"liked_by_me": True, "like_count": 1}
    assert repeated_like.json() == {"liked_by_me": True, "like_count": 1}

    feed = client.get("/api/explore", headers=auth_headers(participant)).json()
    assert feed["memories"][0]["comments"] == [comment.json()]
    assert feed["memories"][0]["like_count"] == 1

    unlike = client.delete(
        f"/api/explore/{memory_id}/likes",
        headers=auth_headers(participant),
    )
    assert unlike.json() == {"liked_by_me": False, "like_count": 0}

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExploreComment)) == 1
        assert db.scalar(select(func.count()).select_from(ExploreLike)) == 0
