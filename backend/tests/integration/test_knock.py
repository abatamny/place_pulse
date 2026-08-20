import asyncio
import secrets
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app.ai import (
    ModerationDecision,
    PlaceRouteOption,
    RoutingDecision,
    get_ai_adapter,
)
from app.auth import hash_session_token, utc_now
from app.database import SessionLocal
from app.main import app
from app.models import (
    AIJob,
    AuthSession,
    KnockMessage,
    Place,
    PlaceMembership,
    Presence,
    User,
)
from app.worker import process_next_job


pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class SessionIdentity:
    user_id: int
    token: str


class FakeKnockAI:
    def __init__(self) -> None:
        self.moderation = ModerationDecision(
            approved=True,
            reason="Message is suitable for publication",
            categories=[],
        )
        self.route_place_id: int | None = None
        self.moderation_calls = 0
        self.routing_calls = 0
        self.routing_places: list[PlaceRouteOption] = []

    async def moderate_text(self, text: str) -> object:
        self.moderation_calls += 1
        return self.moderation

    async def route_message(
        self, text: str, places: list[PlaceRouteOption]
    ) -> object:
        self.routing_calls += 1
        self.routing_places = list(places)
        return RoutingDecision(
            place_id=self.route_place_id or places[-1].place_id,
            reason="Selected the matching place layer",
        )


@pytest.fixture
def fake_ai() -> FakeKnockAI:
    adapter = FakeKnockAI()
    app.dependency_overrides[get_ai_adapter] = lambda: adapter
    yield adapter
    app.dependency_overrides.pop(get_ai_adapter, None)


def create_place(
    name: str,
    osm_id: int,
    parent_place_id: int | None = None,
    locality: str | None = None,
    scope_class: str = "OTHER",
) -> int:
    with SessionLocal() as db:
        place = Place(
            osm_type="way",
            osm_id=osm_id,
            name=name,
            scope_class=scope_class,
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
    phone: str,
    nickname: str,
    place_ids: list[int],
    *,
    rank: str = "VISITOR",
) -> SessionIdentity:
    token = secrets.token_urlsafe(24)
    now = utc_now()
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
                    rank=rank,
                    completed_visits=3 if rank == "BELONG" else 0,
                )
            )
        db.commit()
        return SessionIdentity(user_id=user.id, token=token)


def websocket_path(identity: SessionIdentity) -> str:
    return f"/ws/knock?token={identity.token}"


def assert_ready(websocket) -> None:
    ready = websocket.receive_json()
    assert ready["type"] == "ready"


def test_same_place_users_receive_live_message(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    place_id = create_place("Course Library", 2001, locality="Haifa")
    sender = create_present_user("0500001001", "Sender", [place_id])
    recipient = create_present_user("0500001002", "Recipient", [place_id])

    with client.websocket_connect(websocket_path(sender)) as sender_socket:
        assert_ready(sender_socket)
        with client.websocket_connect(websocket_path(recipient)) as recipient_socket:
            assert_ready(recipient_socket)
            sender_socket.send_json({"type": "message", "text": "Study group?"})

            sent = sender_socket.receive_json()
            received = recipient_socket.receive_json()

    assert sent["type"] == "message"
    assert sent["message"]["id"] == received["message"]["id"]
    assert received["message"]["text"] == "Study group?"
    assert received["message"]["place_id"] == place_id
    assert received["message"]["place_display_name"] == "Course Library, Haifa"
    assert fake_ai.routing_calls == 1
    assert fake_ai.moderation_calls == 1


@pytest.mark.security
def test_cross_place_rooms_are_isolated(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    first_place = create_place("North Campus", 2101)
    second_place = create_place("South Campus", 2102)
    first_user = create_present_user("0500001101", "North User", [first_place])
    second_user = create_present_user("0500001102", "South User", [second_place])

    with client.websocket_connect(websocket_path(first_user)) as first_socket:
        assert_ready(first_socket)
        with client.websocket_connect(websocket_path(second_user)) as second_socket:
            assert_ready(second_socket)
            first_socket.send_json({"type": "message", "text": "North only"})
            assert first_socket.receive_json()["message"]["text"] == "North only"

            second_socket.send_json({"type": "message", "text": "South only"})
            second_received = second_socket.receive_json()

    assert second_received["message"]["text"] == "South only"
    assert second_received["message"]["place_id"] == second_place


@pytest.mark.security
def test_knock_routing_rejects_an_invented_scope(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    current_place = create_place("Current Place", 2110)
    sender = create_present_user(
        "0500001110", "Routed Sender", [current_place]
    )
    fake_ai.route_place_id = 999

    with client.websocket_connect(websocket_path(sender)) as websocket:
        assert_ready(websocket)
        websocket.send_json(
            {
                "type": "message",
                "text": "This must not escape the active scopes",
            }
        )
        rejected = websocket.receive_json()

    assert rejected["type"] == "error"
    assert rejected["code"] == "routing_failed"
    assert [place.place_id for place in fake_ai.routing_places] == [current_place]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(KnockMessage)) == 0


@pytest.mark.security
def test_invalid_websocket_token_is_rejected(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect("/ws/knock?token=not-valid"):
            pass
    assert disconnected.value.code == 4401


@pytest.mark.security
def test_visitor_moderation_rejection_is_not_published(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    place_id = create_place("Student Center", 2201)
    visitor = create_present_user("0500001201", "Visitor", [place_id])
    fake_ai.moderation = ModerationDecision(
        approved=False,
        reason="Harassing content is not allowed",
        categories=["harassment"],
    )

    with client.websocket_connect(websocket_path(visitor)) as websocket:
        assert_ready(websocket)
        websocket.send_json(
            {
                "type": "message",
                "client_id": "visitor-rejected-1",
                "text": "Rejected text",
            }
        )
        rejected = websocket.receive_json()

    assert rejected["type"] == "error"
    assert rejected["code"] == "moderation_rejected"
    assert rejected["client_id"] == "visitor-rejected-1"
    assert fake_ai.routing_calls == 1
    assert fake_ai.moderation_calls == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(KnockMessage)) == 0


def test_reconnecting_user_can_send_and_load_saved_history(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    place_id = create_place("Engineering Hall", 2301)
    user = create_present_user("0500001301", "Reconnect User", [place_id])

    with client.websocket_connect(websocket_path(user)) as websocket:
        assert_ready(websocket)
        websocket.send_json({"type": "message", "text": "Before reconnect"})
        assert websocket.receive_json()["type"] == "message"

    with client.websocket_connect(websocket_path(user)) as websocket:
        assert_ready(websocket)
        websocket.send_json({"type": "message", "text": "After reconnect"})
        assert websocket.receive_json()["message"]["text"] == "After reconnect"

    history = client.get(
        "/api/knock/history",
        headers={"Authorization": f"Bearer {user.token}"},
    )
    assert history.status_code == 200
    assert [message["text"] for message in history.json()["messages"]] == [
        "Before reconnect",
        "After reconnect",
    ]


def test_belong_message_is_immediate_and_queued_for_background_check(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    place_id = create_place("Faculty Lounge", 2401)
    belong_user = create_present_user(
        "0500001401", "Belong User", [place_id], rank="BELONG"
    )

    with client.websocket_connect(websocket_path(belong_user)) as websocket:
        assert_ready(websocket)
        websocket.send_json({"type": "message", "text": "Immediate message"})
        published = websocket.receive_json()

    assert published["type"] == "message"
    assert published["message"]["author_rank"] == "BELONG"
    assert published["message"]["moderation_status"] == "post_pending"
    assert fake_ai.routing_calls == 1
    assert fake_ai.moderation_calls == 0
    with SessionLocal() as db:
        job = db.scalar(select(AIJob))
        assert job is not None
        assert job.status == "pending"
        assert job.payload["knock_message_id"] == published["message"]["id"]

    pending_status = client.get(
        "/api/knock/moderation-status",
        params={"message_ids": published["message"]["id"]},
        headers={"Authorization": f"Bearer {belong_user.token}"},
    )
    assert pending_status.status_code == 200
    assert pending_status.json()["messages"] == [
        {
            "id": published["message"]["id"],
            "moderation_status": "post_pending",
        }
    ]

    fake_ai.moderation = ModerationDecision(
        approved=False,
        reason="Flagged by the background check",
        categories=["harassment"],
    )
    assert asyncio.run(process_next_job(fake_ai)) is True
    assert fake_ai.moderation_calls == 1

    with SessionLocal() as db:
        saved = db.get(KnockMessage, published["message"]["id"])
        assert saved is not None
        assert saved.moderation_status == "flagged"

    flagged_status = client.get(
        "/api/knock/moderation-status",
        params={"message_ids": published["message"]["id"]},
        headers={"Authorization": f"Bearer {belong_user.token}"},
    )
    assert flagged_status.status_code == 200
    assert flagged_status.json()["messages"][0]["moderation_status"] == "flagged"

    history = client.get(
        "/api/knock/history",
        headers={"Authorization": f"Bearer {belong_user.token}"},
    )
    assert history.status_code == 200
    assert history.json()["messages"] == []


def test_belong_message_background_approval_updates_status_and_history(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    place_id = create_place("Approved Lounge", 2402)
    belong_user = create_present_user(
        "0500001402", "Approved User", [place_id], rank="BELONG"
    )

    with client.websocket_connect(websocket_path(belong_user)) as websocket:
        assert_ready(websocket)
        websocket.send_json({"type": "message", "text": "Safe message"})
        published = websocket.receive_json()["message"]

    assert published["moderation_status"] == "post_pending"
    assert asyncio.run(process_next_job(fake_ai)) is True

    status = client.get(
        "/api/knock/moderation-status",
        params={"message_ids": published["id"]},
        headers={"Authorization": f"Bearer {belong_user.token}"},
    )
    assert status.status_code == 200
    assert status.json()["messages"] == [
        {"id": published["id"], "moderation_status": "approved"}
    ]

    history = client.get(
        "/api/knock/history",
        headers={"Authorization": f"Bearer {belong_user.token}"},
    )
    assert history.status_code == 200
    assert history.json()["messages"][0]["text"] == "Safe message"
    assert history.json()["messages"][0]["moderation_status"] == "approved"


@pytest.mark.security
def test_moderation_status_is_isolated_to_current_places(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    sender_place = create_place("Sender Place", 2403)
    viewer_place = create_place("Viewer Place", 2404)
    sender = create_present_user(
        "0500001403", "Background Sender", [sender_place], rank="BELONG"
    )
    viewer = create_present_user(
        "0500001404", "Other Viewer", [viewer_place]
    )

    with client.websocket_connect(websocket_path(sender)) as websocket:
        assert_ready(websocket)
        websocket.send_json({"type": "message", "text": "Other place"})
        message_id = websocket.receive_json()["message"]["id"]

    status = client.get(
        "/api/knock/moderation-status",
        params={"message_ids": message_id},
        headers={"Authorization": f"Bearer {viewer.token}"},
    )
    assert status.status_code == 200
    assert status.json()["messages"] == []


@pytest.mark.security
def test_nested_message_is_sent_only_to_ai_routed_place_scope(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    campus_id = create_place("Course Campus", 2501)
    building_id = create_place(
        "Engineering Building", 2502, parent_place_id=campus_id
    )
    sender = create_present_user(
        "0500001501", "Nested Sender", [campus_id, building_id]
    )
    campus_user = create_present_user(
        "0500001502", "Campus User", [campus_id]
    )
    building_user = create_present_user(
        "0500001503", "Building User", [building_id]
    )
    with client.websocket_connect(websocket_path(sender)) as sender_socket:
        assert_ready(sender_socket)
        with client.websocket_connect(websocket_path(campus_user)) as campus_socket:
            assert_ready(campus_socket)
            with client.websocket_connect(
                websocket_path(building_user)
            ) as building_socket:
                assert_ready(building_socket)
                sender_socket.send_json(
                    {
                        "type": "message",
                        "text": "Meet inside the building",
                    }
                )
                assert sender_socket.receive_json()["message"]["place_id"] == building_id
                building_received = building_socket.receive_json()

                campus_socket.send_json(
                    {
                        "type": "message",
                        "text": "Campus announcement",
                    }
                )
                campus_received = campus_socket.receive_json()

    assert building_received["message"]["text"] == "Meet inside the building"
    assert campus_received["message"]["text"] == "Campus announcement"
    assert fake_ai.routing_calls == 2


def test_nested_message_can_use_parent_scope_while_preserving_origin(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    campus_id = create_place("Shared Campus", 2510, scope_class="SITE")
    building_id = create_place(
        "Science Building",
        2511,
        parent_place_id=campus_id,
        scope_class="BUILDING",
    )
    sender = create_present_user(
        "0500001510", "Building Sender", [campus_id, building_id]
    )
    campus_user = create_present_user(
        "0500001511", "Campus Recipient", [campus_id]
    )
    fake_ai.route_place_id = campus_id
    with client.websocket_connect(websocket_path(sender)) as sender_socket:
        assert_ready(sender_socket)
        with client.websocket_connect(websocket_path(campus_user)) as campus_socket:
            assert_ready(campus_socket)
            sender_socket.send_json(
                {
                    "type": "message",
                    "text": "Campus event starts soon",
                }
            )
            sent = sender_socket.receive_json()["message"]
            received = campus_socket.receive_json()["message"]

    assert sent["id"] == received["id"]
    assert sent["place_id"] == campus_id
    assert sent["origin_place_id"] == building_id
    assert [
        (place.place_id, place.parent_place_id, place.scope_class)
        for place in fake_ai.routing_places
    ] == [
        (campus_id, None, "SITE"),
        (building_id, campus_id, "BUILDING"),
    ]


def test_history_combines_all_current_knock_scopes(
    client: TestClient, fake_ai: FakeKnockAI
) -> None:
    campus_id = create_place("Combined Campus", 2520)
    building_id = create_place(
        "Combined Building", 2521, parent_place_id=campus_id
    )
    sender = create_present_user(
        "0500001520", "Combined Sender", [campus_id, building_id]
    )

    with client.websocket_connect(websocket_path(sender)) as websocket:
        assert_ready(websocket)
        fake_ai.route_place_id = building_id
        websocket.send_json({"type": "message", "text": "Building update"})
        building_message = websocket.receive_json()["message"]

        fake_ai.route_place_id = campus_id
        websocket.send_json({"type": "message", "text": "Campus update"})
        campus_message = websocket.receive_json()["message"]

    history = client.get(
        "/api/knock/history",
        headers={"Authorization": f"Bearer {sender.token}"},
    )

    assert history.status_code == 200
    assert [message["id"] for message in history.json()["messages"]] == [
        building_message["id"],
        campus_message["id"],
    ]
    assert {
        message["place_id"] for message in history.json()["messages"]
    } == {campus_id, building_id}
