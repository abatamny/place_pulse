import asyncio
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import hash_session_token, utc_now
from app.database import SessionLocal
from app.models import AuthSession, DirectMessage, User
from app.protection import ConcurrencyLimitMiddleware


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


def test_excess_inflight_requests_receive_a_retryable_busy_response() -> None:
    limited_app = FastAPI()
    limited_app.add_middleware(
        ConcurrencyLimitMiddleware,
        max_http_requests=1,
        max_websocket_connections=1,
    )
    entered = Event()
    release = Event()

    @limited_app.get("/slow")
    async def slow() -> dict[str, str]:
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "released"}

    @limited_app.get("/probe")
    async def probe() -> dict[str, str]:
        return {"status": "available"}

    with TestClient(limited_app) as limited_client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first_request = pool.submit(limited_client.get, "/slow")
            try:
                assert entered.wait(timeout=2)
                rejected = limited_client.get("/probe")
            finally:
                release.set()
            completed = first_request.result(timeout=2)

        recovered = limited_client.get("/probe")

    assert rejected.status_code == 503
    assert rejected.headers["retry-after"] == "1"
    assert completed.status_code == 200
    assert recovered.status_code == 200
