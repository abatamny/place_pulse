import io
import secrets
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app.auth import hash_session_token, utc_now
from app.database import SessionLocal
from app.models import AuthSession, DirectMessage, MediaAttachment, User


pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class SessionIdentity:
    user_id: int
    token: str


def create_user(phone: str, nickname: str) -> SessionIdentity:
    token = secrets.token_urlsafe(24)
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
                expires_at=utc_now() + timedelta(hours=1),
            )
        )
        db.commit()
        return SessionIdentity(user_id=user.id, token=token)


def auth_headers(identity: SessionIdentity) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity.token}"}


def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 60), (70, 150, 110)).save(output, format="JPEG")
    return output.getvalue()


def send_message(
    client: TestClient,
    sender: SessionIdentity,
    recipient: SessionIdentity,
    text: str,
):
    return client.post(
        "/api/dms/messages",
        headers=auth_headers(sender),
        json={"recipient_id": recipient.user_id, "text": text},
    )


@pytest.mark.security
def test_messages_are_private_saved_and_marked_read(client: TestClient) -> None:
    alice = create_user("0500006001", "Alice")
    bob = create_user("0500006002", "Bob")
    eve = create_user("0500006003", "Eve")

    search = client.get(
        "/api/dms/users?query=Bob",
        headers=auth_headers(alice),
    )
    assert search.status_code == 200
    assert search.json()["users"] == [
        {"id": bob.user_id, "nickname": "Bob", "phone": "0500006002"}
    ]

    sent = send_message(client, alice, bob, "  Are you coming to class?  ")
    assert sent.status_code == 201
    assert sent.json()["text"] == "Are you coming to class?"

    alice_history = client.get(
        f"/api/dms/{bob.user_id}", headers=auth_headers(alice)
    )
    bob_history = client.get(
        f"/api/dms/{alice.user_id}", headers=auth_headers(bob)
    )
    eve_history = client.get(
        f"/api/dms/{alice.user_id}", headers=auth_headers(eve)
    )
    assert [item["id"] for item in alice_history.json()["messages"]] == [
        sent.json()["id"]
    ]
    assert bob_history.json()["messages"] == alice_history.json()["messages"]
    assert eve_history.json()["messages"] == []

    bob_conversations = client.get(
        "/api/dms/conversations", headers=auth_headers(bob)
    ).json()
    assert bob_conversations["conversations"][0]["user"]["id"] == alice.user_id
    assert bob_conversations["conversations"][0]["unread_count"] == 1

    marked = client.post(
        f"/api/dms/{alice.user_id}/read",
        headers=auth_headers(bob),
    )
    assert marked.status_code == 204
    refreshed = client.get(
        "/api/dms/conversations", headers=auth_headers(bob)
    ).json()
    assert refreshed["conversations"][0]["unread_count"] == 0
    with SessionLocal() as db:
        saved = db.scalar(select(DirectMessage))
        assert saved is not None
        assert saved.read_at is not None


def test_recipient_receives_live_notification(client: TestClient) -> None:
    sender = create_user("0500006004", "Live Sender")
    recipient = create_user("0500006005", "Live Recipient")

    with client.websocket_connect(
        f"/ws/dms?token={recipient.token}"
    ) as websocket:
        assert websocket.receive_json() == {"type": "ready"}

        sent = send_message(client, sender, recipient, "This arrived live")
        notification = websocket.receive_json()

    assert sent.status_code == 201
    assert notification["type"] == "message"
    assert notification["message"]["id"] == sent.json()["id"]
    assert notification["message"]["text"] == "This arrived live"


@pytest.mark.security
def test_dm_authentication_recipient_and_input_are_validated(
    client: TestClient,
) -> None:
    user = create_user("0500006006", "Validated User")

    assert client.get("/api/dms/conversations").status_code == 401
    self_message = client.post(
        "/api/dms/messages",
        headers=auth_headers(user),
        json={"recipient_id": user.user_id, "text": "Message to myself"},
    )
    missing_user = client.post(
        "/api/dms/messages",
        headers=auth_headers(user),
        json={"recipient_id": 999999, "text": "Nobody there"},
    )
    invalid_text = client.post(
        "/api/dms/messages",
        headers=auth_headers(user),
        json={"recipient_id": 999999, "text": "bad\u0000text"},
    )
    assert self_message.status_code == 400
    assert missing_user.status_code == 404
    assert invalid_text.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DirectMessage)) == 0

    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect("/ws/dms?token=invalid"):
            pass
    assert disconnect.value.code == 4401


@pytest.mark.security
def test_dm_media_is_unmoderated_but_private_and_validated(client: TestClient) -> None:
    sender = create_user("0500006010", "Media Sender")
    recipient = create_user("0500006011", "Media Recipient")
    outsider = create_user("0500006012", "Media Outsider")

    sent = client.post(
        "/api/dms/messages/with-media",
        headers=auth_headers(sender),
        data={"recipient_id": str(recipient.user_id), "text": "Private photo"},
        files={"file": ("private.jpg", jpeg_bytes(), "image/jpeg")},
    )

    assert sent.status_code == 201
    body = sent.json()
    assert body["media"]["original_filename"] == "private.jpg"
    media_url = body["media"]["media_url"]
    assert client.get(media_url, headers=auth_headers(sender)).status_code == 200
    assert client.get(media_url, headers=auth_headers(recipient)).status_code == 200
    assert client.get(media_url, headers=auth_headers(outsider)).status_code == 404
    with SessionLocal() as db:
        attachment = db.scalar(select(MediaAttachment))
        assert attachment is not None
        assert attachment.moderation_status == "not_required"

    invalid = client.post(
        "/api/dms/messages/with-media",
        headers=auth_headers(sender),
        data={"recipient_id": str(recipient.user_id), "text": "Not really media"},
        files={"file": ("fake.jpg", b"not an image", "image/jpeg")},
    )
    assert invalid.status_code == 400
