from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.ai import ModerationDecision, get_ai_adapter
from app.main import app
from app.osm import ResolvedPlace, get_place_resolver


pytestmark = pytest.mark.system


@dataclass
class FakePlaceResolver:
    calls: int = 0

    def resolve(self, latitude: float, longitude: float) -> list[ResolvedPlace]:
        self.calls += 1
        return [
            ResolvedPlace(
                osm_type="way",
                osm_id=9001,
                name="Course Library",
                center_lat=latitude,
                center_lon=longitude,
                boundary_geojson={
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [longitude - 0.001, latitude - 0.001],
                            [longitude + 0.001, latitude - 0.001],
                            [longitude + 0.001, latitude + 0.001],
                            [longitude - 0.001, latitude + 0.001],
                            [longitude - 0.001, latitude - 0.001],
                        ]
                    ],
                },
            )
        ]


class FakeAIAdapter:
    def __init__(self) -> None:
        self.moderated_texts: list[str] = []

    async def moderate_text(self, text: str) -> ModerationDecision:
        self.moderated_texts.append(text)
        return ModerationDecision(
            approved=True,
            reason="Safe course test content",
            categories=[],
        )


@pytest.fixture
def system_dependencies():
    resolver = FakePlaceResolver()
    adapter = FakeAIAdapter()
    app.dependency_overrides[get_place_resolver] = lambda: resolver
    app.dependency_overrides[get_ai_adapter] = lambda: adapter
    yield resolver, adapter
    app.dependency_overrides.pop(get_place_resolver, None)
    app.dependency_overrides.pop(get_ai_adapter, None)


def register_login(
    client: TestClient, phone: str, nickname: str
) -> tuple[int, str]:
    registration = client.post(
        "/api/auth/register",
        json={
            "phone": phone,
            "nickname": nickname,
            "password": "course-password",
        },
    )
    assert registration.status_code == 201

    verification = client.post(
        "/api/auth/verify",
        json={
            "phone": phone,
            "code": registration.json()["verification_code"],
        },
    )
    assert verification.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "course-password"},
    )
    assert login.status_code == 200
    body = login.json()
    return body["user"]["id"], body["access_token"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_journey_from_registration_to_place_activity_and_messaging(
    client: TestClient,
    system_dependencies: tuple[FakePlaceResolver, FakeAIAdapter],
) -> None:
    resolver, adapter = system_dependencies
    first_user_id, first_token = register_login(
        client, "0500090001", "Journey User"
    )

    heartbeat = client.post(
        "/api/presence/heartbeat",
        headers=headers(first_token),
        json={"latitude": 32.113, "longitude": 35.109},
    )
    assert heartbeat.status_code == 200
    place = heartbeat.json()["places"][0]
    assert place["name"] == "Course Library"
    assert place["rank"] == "VISITOR"
    assert resolver.calls == 1

    with client.websocket_connect(f"/ws/knock?token={first_token}") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        assert ready["places"][0]["id"] == place["id"]

        websocket.send_json(
            {"type": "message", "text": "Study group starts at four."}
        )
        published = websocket.receive_json()

    assert published["type"] == "message"
    assert published["message"]["text"] == "Study group starts at four."
    history = client.get(
        f"/api/knock/history?place_id={place['id']}",
        headers=headers(first_token),
    )
    assert [item["id"] for item in history.json()["messages"]] == [
        published["message"]["id"]
    ]

    forum_post = client.post(
        "/api/forum/posts",
        headers=headers(first_token),
        json={
            "place_id": place["id"],
            "title": "Library study group",
            "body": "Meet beside the entrance at four.",
            "is_anonymous": True,
        },
    )
    assert forum_post.status_code == 201
    assert forum_post.json()["nickname"] == "Anonymous"
    assert forum_post.json()["user_id"] is None

    second_user_id, second_token = register_login(
        client, "0500090002", "Message Recipient"
    )
    sent = client.post(
        "/api/dms/messages",
        headers=headers(first_token),
        json={"recipient_id": second_user_id, "text": "See you in class."},
    )
    assert sent.status_code == 201
    received = client.get(
        f"/api/dms/{first_user_id}", headers=headers(second_token)
    )
    assert [message["text"] for message in received.json()["messages"]] == [
        "See you in class."
    ]

    assert len(adapter.moderated_texts) == 2
    assert client.post(
        "/api/auth/logout", headers=headers(first_token)
    ).status_code == 204
    assert client.get(
        "/api/auth/me", headers=headers(first_token)
    ).status_code == 401
