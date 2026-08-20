import secrets
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_session_token, utc_now
from app.database import SessionLocal
from app.models import AuthSession, User


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
        ("get", "/api/knock/moderation-status?message_ids=1", {}),
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
