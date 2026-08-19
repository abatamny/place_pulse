import io
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import av
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.ai import (
    ImageModerationInput,
    MediaRoutingDecision,
    ModerationDecision,
    PlaceRouteOption,
    get_ai_adapter,
)
from app.auth import hash_session_token
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, Dig, Place, PlaceMembership, Presence, User


pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class SessionIdentity:
    user_id: int
    token: str


class FakeMediaAI:
    def __init__(self) -> None:
        self.decision = ModerationDecision(
            approved=True,
            reason="Media is suitable for publication",
            categories=[],
        )
        self.sample_counts: list[int] = []
        self.route_place_id: int | None = None
        self.route_confidence = 0.95
        self.route_calls = 0

    async def moderate_images(self, images: list[ImageModerationInput]) -> object:
        self.sample_counts.append(len(images))
        return self.decision

    async def route_media(
        self,
        images: list[ImageModerationInput],
        places: list[PlaceRouteOption],
    ) -> object:
        self.route_calls += 1
        return MediaRoutingDecision(
            place_id=self.route_place_id or places[-1].place_id,
            reason="The media matches this audience",
            confidence=self.route_confidence,
        )


@pytest.fixture
def fake_media_ai() -> FakeMediaAI:
    adapter = FakeMediaAI()
    app.dependency_overrides[get_ai_adapter] = lambda: adapter
    yield adapter
    app.dependency_overrides.pop(get_ai_adapter, None)


def create_place(
    name: str,
    osm_id: int,
    locality: str | None = None,
    parent_place_id: int | None = None,
) -> int:
    with SessionLocal() as db:
        place = Place(
            osm_type="way",
            osm_id=osm_id,
            name=name,
            locality=locality,
            center_lat=32.0,
            center_lon=35.0,
            radius_m=75,
            parent_place_id=parent_place_id,
        )
        db.add(place)
        db.commit()
        db.refresh(place)
        return place.id


def create_present_user(
    phone: str, nickname: str, place_ids: list[int]
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
        for place_id in place_ids:
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


def jpeg_bytes(color: tuple[int, int, int] = (70, 150, 110)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(output, format="JPEG")
    return output.getvalue()


def mp4_bytes(frame_count: int = 10) -> bytes:
    output = io.BytesIO()
    with av.open(output, mode="w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=5)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            image = Image.new("RGB", (64, 48), (20 * index, 100, 170))
            frame = av.VideoFrame.from_image(image)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return output.getvalue()


def upload_image(
    client: TestClient,
    identity: SessionIdentity,
    *,
    filename: str = "campus.jpg",
    content_type: str = "image/jpeg",
    data: bytes | None = None,
    place_id: int | None = None,
):
    return client.post(
        "/api/digs",
        headers=auth_headers(identity),
        data={"place_id": str(place_id)} if place_id is not None else None,
        files={"file": (filename, data or jpeg_bytes(), content_type)},
    )


def test_approved_image_is_saved_and_appears_in_feed(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Course Courtyard", 3001, locality="Haifa")
    identity = create_present_user("0500003001", "Photographer", [place_id])
    image_data = jpeg_bytes()

    uploaded = upload_image(client, identity, data=image_data)

    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["place_id"] == place_id
    assert body["media_type"] == "image"
    assert body["nickname"] == "Photographer"
    assert body["place_display_name"] == "Course Courtyard, Haifa"
    assert fake_media_ai.sample_counts == [1]

    feed = client.get(
        f"/api/digs?place_id={place_id}", headers=auth_headers(identity)
    )
    assert feed.status_code == 200
    assert [dig["id"] for dig in feed.json()["digs"]] == [body["id"]]

    media = client.get(body["media_url"], headers=auth_headers(identity))
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/jpeg"
    assert media.content == image_data

    with SessionLocal() as db:
        dig = db.get(Dig, body["id"])
        assert dig is not None
        assert (settings.media_root / "digs" / dig.storage_name).is_file()


def test_approved_image_is_broadcast_to_present_viewers(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Live DIG Courtyard", 3011, locality="Haifa")
    uploader = create_present_user("0500003011", "Uploader", [place_id])
    viewer = create_present_user("0500003012", "Viewer", [place_id])

    with client.websocket_connect(f"/ws/knock?token={viewer.token}") as websocket:
        assert websocket.receive_json()["type"] == "ready"
        uploaded = upload_image(client, uploader, place_id=place_id)
        event = websocket.receive_json()

    assert uploaded.status_code == 201
    assert event["type"] == "dig_published"
    assert event["dig"] == uploaded.json()


def test_short_video_is_validated_and_moderated_as_frames(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Media Lab", 3002)
    identity = create_present_user("0500003002", "Videographer", [place_id])

    uploaded = client.post(
        "/api/digs",
        headers=auth_headers(identity),
        files={"file": ("clip.mp4", mp4_bytes(), "video/mp4")},
    )

    assert uploaded.status_code == 201
    assert uploaded.json()["media_type"] == "video"
    assert fake_media_ai.sample_counts == [3]


@pytest.mark.security
def test_rejected_media_is_neither_saved_nor_listed(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Student Center", 3003)
    identity = create_present_user("0500003003", "Uploader", [place_id])
    fake_media_ai.decision = ModerationDecision(
        approved=False,
        reason="Media violates policy",
        categories=["violence"],
    )

    rejected = upload_image(client, identity)

    assert rejected.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Dig)) == 0
    media_directory = settings.media_root / "digs"
    assert not media_directory.exists() or not any(media_directory.iterdir())
    feed = client.get(
        f"/api/digs?place_id={place_id}", headers=auth_headers(identity)
    )
    assert feed.json() == {"digs": []}


@pytest.mark.security
def test_moderation_failure_fails_closed_without_storing_media(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Workshop", 3008)
    identity = create_present_user("0500003008", "Workshop User", [place_id])
    fake_media_ai.decision = ModerationDecision(
        approved=False,
        reason="Moderation is temporarily unavailable",
        categories=["ai_failure"],
    )

    unavailable = upload_image(client, identity)

    assert unavailable.status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Dig)) == 0


@pytest.mark.security
def test_wrong_type_filename_and_oversized_uploads_are_rejected(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Lecture Hall", 3004)
    identity = create_present_user("0500003004", "Careful User", [place_id])

    wrong_type = upload_image(
        client,
        identity,
        filename="notes.txt",
        content_type="text/plain",
        data=b"not media",
    )
    unsafe_name = upload_image(
        client,
        identity,
        filename="../photo.jpg",
    )
    oversized = upload_image(
        client,
        identity,
        data=b"x" * (10 * 1024 * 1024 + 1),
    )
    long_video = client.post(
        "/api/digs",
        headers=auth_headers(identity),
        files={"file": ("long.mp4", mp4_bytes(frame_count=80), "video/mp4")},
    )

    assert wrong_type.status_code == 415
    assert unsafe_name.status_code == 400
    assert oversized.status_code == 413
    assert long_video.status_code == 413
    assert fake_media_ai.sample_counts == []


@pytest.mark.security
def test_upload_requires_authentication(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    place_id = create_place("Private Studio", 3009)

    response = client.post(
        "/api/digs",
        files={"file": ("photo.jpg", jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 401
    assert fake_media_ai.sample_counts == []


@pytest.mark.security
def test_upload_rejects_a_selected_scope_without_current_presence(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    first_place = create_place("North Building", 3005)
    second_place = create_place("South Building", 3006)
    first_user = create_present_user("0500003005", "North User", [first_place])
    second_user = create_present_user("0500003006", "South User", [second_place])

    uploaded = upload_image(client, first_user)
    assert uploaded.status_code == 201
    media_url = uploaded.json()["media_url"]

    automatic_upload = client.post(
        "/api/digs",
        headers=auth_headers(second_user),
        data={"place_id": str(first_place)},
        files={"file": ("photo.jpg", jpeg_bytes(), "image/jpeg")},
    )
    denied_feed = client.get(
        f"/api/digs?place_id={first_place}", headers=auth_headers(second_user)
    )
    denied_media = client.get(media_url, headers=auth_headers(second_user))

    assert automatic_upload.status_code == 403
    assert denied_feed.status_code == 403
    assert denied_media.status_code == 403


def test_expired_dig_is_hidden_and_media_is_unavailable(
    client: TestClient, fake_media_ai: FakeMediaAI, monkeypatch: pytest.MonkeyPatch
) -> None:
    place_id = create_place("Old Quad", 3007)
    identity = create_present_user("0500003007", "Time Traveler", [place_id])
    created_at = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("app.digs.utc_now", lambda: created_at)

    uploaded = upload_image(client, identity)
    assert uploaded.status_code == 201
    media_url = uploaded.json()["media_url"]
    assert client.get(
        f"/api/digs?place_id={place_id}", headers=auth_headers(identity)
    ).json()["digs"]

    monkeypatch.setattr("app.digs.utc_now", lambda: created_at + timedelta(hours=25))
    feed = client.get(
        f"/api/digs?place_id={place_id}", headers=auth_headers(identity)
    )
    media = client.get(media_url, headers=auth_headers(identity))

    assert feed.status_code == 200
    assert feed.json() == {"digs": []}
    assert media.status_code == 404


def test_parent_scope_uses_deepest_origin_and_reaches_sibling_place_user(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    campus_id = create_place("Shared Campus", 3010, locality="Haifa")
    north_id = create_place(
        "North Building", 3011, parent_place_id=campus_id
    )
    south_id = create_place(
        "South Building", 3012, parent_place_id=campus_id
    )
    author = create_present_user(
        "0500003010", "North Author", [campus_id, north_id]
    )
    viewer = create_present_user(
        "0500003011", "South Viewer", [campus_id, south_id]
    )

    uploaded = upload_image(client, author, place_id=campus_id)

    assert uploaded.status_code == 201
    dig = uploaded.json()
    assert dig["place_id"] == campus_id
    assert dig["origin_place_id"] == north_id

    feed = client.get(
        f"/api/digs?place_id={campus_id}", headers=auth_headers(viewer)
    )
    assert feed.status_code == 200
    assert [item["id"] for item in feed.json()["digs"]] == [dig["id"]]
    assert client.get(dig["media_url"], headers=auth_headers(viewer)).status_code == 200


def test_omitted_media_scope_falls_back_to_deepest_current_place(
    client: TestClient, fake_media_ai: FakeMediaAI
) -> None:
    campus_id = create_place("Fallback Campus", 3013)
    room_id = create_place("Fallback Room", 3014, parent_place_id=campus_id)
    author = create_present_user(
        "0500003012", "Fallback Author", [campus_id, room_id]
    )
    uploaded = upload_image(client, author)

    assert uploaded.status_code == 201
    assert uploaded.json()["place_id"] == room_id
    assert uploaded.json()["origin_place_id"] == room_id
    assert fake_media_ai.route_calls == 0
