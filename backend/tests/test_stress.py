import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import hash_session_token, utc_now
from app.database import SessionLocal
from app.models import AuthSession, DirectMessage, User


pytestmark = pytest.mark.stress


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


def test_public_health_endpoint_handles_a_small_concurrent_burst(
    client: TestClient,
) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.get("/api/health"), range(40)))

    assert [response.status_code for response in responses] == [200] * 40
    assert all(response.json() == {"status": "ok", "database": "ok"} for response in responses)


def test_concurrent_direct_messages_are_all_persisted(
    client: TestClient,
) -> None:
    sender = create_user("0500092001", "Load Sender")
    recipient = create_user("0500092002", "Load Recipient")
    message_count = 24
    auth_headers = {"Authorization": f"Bearer {sender.token}"}

    def send(index: int):
        return client.post(
            "/api/dms/messages",
            headers=auth_headers,
            json={
                "recipient_id": recipient.user_id,
                "text": f"Concurrent message {index:02d}",
            },
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(send, range(message_count)))

    assert [response.status_code for response in responses] == [201] * message_count
    assert len({response.json()["id"] for response in responses}) == message_count
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DirectMessage)) == message_count

    conversations = client.get(
        "/api/dms/conversations",
        headers={"Authorization": f"Bearer {recipient.token}"},
    )
    assert conversations.status_code == 200
    assert conversations.json()["conversations"][0]["unread_count"] == message_count
