import secrets
from datetime import timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.auth import hash_session_token, utc_now
from app.database import SessionLocal
from app.models import AuthSession, User
from app.protection import RequestBodyLimitMiddleware
from app.rate_limit import AuthRateLimiter
from app.schemas import KnockSendPayload


pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        ("get", "/api/auth/me", {}),
        (
            "post",
            "/api/presence/heartbeat",
            {"json": {"latitude": 32.0, "longitude": 35.0}},
        ),
        ("get", "/api/presence/current", {}),
        ("post", "/api/presence/leave", {}),
        ("get", "/api/knock/history?place_id=1", {}),
        ("get", "/api/digs?place_id=1", {}),
        ("get", "/api/explore", {}),
        ("get", "/api/forum", {}),
        ("get", "/api/forum/me", {}),
        ("get", "/api/dms/conversations", {}),
    ],
)
def test_protected_http_routes_reject_anonymous_requests(
    client: TestClient,
    method: str,
    path: str,
    request_kwargs: dict,
) -> None:
    response = getattr(client, method)(path, **request_kwargs)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_session_tokens_are_hashed_and_expired_sessions_are_removed(
    client: TestClient,
) -> None:
    valid_token = secrets.token_urlsafe(24)
    expired_token = secrets.token_urlsafe(24)
    with SessionLocal() as db:
        user = User(
            phone="0500091001",
            nickname="Security User",
            password_hash="not-used-in-this-test",
            is_verified=True,
        )
        db.add(user)
        db.flush()
        db.add_all(
            [
                AuthSession(
                    token_hash=hash_session_token(valid_token),
                    user_id=user.id,
                    expires_at=utc_now() + timedelta(hours=1),
                ),
                AuthSession(
                    token_hash=hash_session_token(expired_token),
                    user_id=user.id,
                    expires_at=utc_now() - timedelta(seconds=1),
                ),
            ]
        )
        db.commit()

    valid = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {valid_token}"}
    )
    expired = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert valid.status_code == 200
    assert expired.status_code == 401

    with SessionLocal() as db:
        stored_hashes = set(db.scalars(select(AuthSession.token_hash)))
    assert valid_token not in stored_hashes
    assert hash_session_token(valid_token) in stored_hashes
    assert hash_session_token(expired_token) not in stored_hashes


def test_rate_limiter_blocks_a_burst_and_allows_requests_after_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = AuthRateLimiter(max_attempts=2, window_seconds=10)
    request = Request(
        {"type": "http", "method": "POST", "path": "/", "client": ("127.0.0.1", 1)}
    )
    times = iter([0.0, 1.0, 2.0, 12.0])
    monkeypatch.setattr("app.rate_limit.time.monotonic", lambda: next(times))

    limiter.check(request, "login")
    limiter.check(request, "login")
    with pytest.raises(HTTPException) as blocked:
        limiter.check(request, "login")
    assert blocked.value.status_code == 429
    assert blocked.value.headers == {"Retry-After": "8"}

    limiter.check(request, "login")


def test_rate_limiter_key_survives_a_new_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = AuthRateLimiter(max_attempts=2, window_seconds=60)
    times = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr("app.rate_limit.time.monotonic", lambda: next(times))

    limiter.check_key("user-7", "knock-message")
    limiter.check_key("user-7", "knock-message")
    with pytest.raises(HTTPException) as blocked_after_reconnect:
        limiter.check_key("user-7", "knock-message")

    assert blocked_after_reconnect.value.status_code == 429


def test_request_body_limit_rejects_large_payload_before_endpoint() -> None:
    limited_app = FastAPI()
    limited_app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=16)

    @limited_app.post("/echo-size")
    async def echo_size(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    with TestClient(limited_app) as limited_client:
        accepted = limited_client.post("/echo-size", content=b"1234567890123456")
        rejected = limited_client.post("/echo-size", content=b"12345678901234567")

    assert accepted.status_code == 200
    assert accepted.json() == {"size": 16}
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "Request body is too large"}


def test_malformed_json_and_unexpected_fields_fail_safely(
    client: TestClient,
) -> None:
    malformed = client.post(
        "/api/auth/login",
        content=b'{"phone":',
        headers={"Content-Type": "application/json"},
    )
    unexpected = client.post(
        "/api/auth/login",
        json={
            "phone": "0500091999",
            "password": "password",
            "is_admin": True,
        },
    )

    assert malformed.status_code == 422
    assert unexpected.status_code == 422
    assert client.get("/api/health").status_code == 200


def test_user_text_rejects_control_characters_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        KnockSendPayload.model_validate(
            {"type": "message", "text": "hello\u0000world"}
        )
    with pytest.raises(ValidationError):
        KnockSendPayload.model_validate(
            {"type": "message", "text": "hello", "unexpected": True}
        )
