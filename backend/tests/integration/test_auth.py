import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.database import SessionLocal
from app.models import User
from app.sms import SMSDeliveryError


pytestmark = pytest.mark.integration


def register_and_verify(
    client: TestClient,
    phone: str = "0500000001",
    nickname: str = "Course User",
    password: str = "course-password",
) -> None:
    registration = client.post(
        "/api/auth/register",
        json={"phone": phone, "nickname": nickname, "password": password},
    )
    assert registration.status_code == 201
    code = registration.json()["verification_code"]
    assert code is not None

    verification = client.post(
        "/api/auth/verify", json={"phone": phone, "code": code}
    )
    assert verification.status_code == 200
    assert verification.json()["phone"] == phone


def login(
    client: TestClient,
    phone: str = "0500000001",
    password: str = "course-password",
) -> str:
    response = client.post(
        "/api/auth/login", json={"phone": phone, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_successful_registration_login_and_logout(client: TestClient) -> None:
    register_and_verify(client)

    with SessionLocal() as db:
        stored_user = db.scalar(select(User).where(User.phone == "0500000001"))
        assert stored_user is not None
        assert stored_user.password_hash != "course-password"
        assert stored_user.password_hash.startswith("$argon2")

    token = login(client)
    headers = {"Authorization": f"Bearer {token}"}

    protected = client.get("/api/auth/me", headers=headers)
    assert protected.status_code == 200
    assert protected.json()["nickname"] == "Course User"

    with client.websocket_connect(f"/ws/auth-check?token={token}") as websocket:
        message = websocket.receive_json()
    assert message["status"] == "authenticated"
    assert message["user"]["phone"] == "0500000001"

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_configured_sms_provider_sends_and_hides_verification_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, str] = {}

    class RecordingSMSProvider:
        def send_verification_code(self, phone: str, code: str) -> None:
            sent["phone"] = phone
            sent["code"] = code

    monkeypatch.setattr(
        "app.auth.get_sms_provider", lambda: RecordingSMSProvider()
    )

    registration = client.post(
        "/api/auth/register",
        json={
            "phone": "+972500000002",
            "nickname": "SMS User",
            "password": "course-password",
        },
    )

    assert registration.status_code == 201
    assert registration.json()["verification_code"] is None
    assert registration.json()["message"] == "A verification code was sent by SMS"
    assert sent["phone"] == "+972500000002"
    assert len(sent["code"]) == 6
    assert sent["code"].isdigit()

    verification = client.post(
        "/api/auth/verify",
        json={"phone": sent["phone"], "code": sent["code"]},
    )
    assert verification.status_code == 200


def test_sms_delivery_failure_rolls_back_registration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingSMSProvider:
        def send_verification_code(self, phone: str, code: str) -> None:
            raise SMSDeliveryError("provider unavailable")

    monkeypatch.setattr("app.auth.get_sms_provider", lambda: FailingSMSProvider())

    registration = client.post(
        "/api/auth/register",
        json={
            "phone": "+972500000003",
            "nickname": "Failed SMS User",
            "password": "course-password",
        },
    )

    assert registration.status_code == 503
    assert registration.json()["detail"] == (
        "Verification SMS could not be sent. Try again later."
    )
    with SessionLocal() as db:
        assert (
            db.scalar(select(User).where(User.phone == "+972500000003")) is None
        )


def test_duplicate_phone_number_is_rejected(client: TestClient) -> None:
    register_and_verify(client)

    duplicate = client.post(
        "/api/auth/register",
        json={
            "phone": "0500000001",
            "nickname": "Another User",
            "password": "another-password",
        },
    )
    assert duplicate.status_code == 409


@pytest.mark.security
def test_wrong_password_is_rejected(client: TestClient) -> None:
    register_and_verify(client)

    response = client.post(
        "/api/auth/login",
        json={"phone": "0500000001", "password": "definitely-wrong"},
    )
    assert response.status_code == 401


@pytest.mark.security
def test_unauthenticated_user_cannot_access_protected_endpoint(
    client: TestClient,
) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401

    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect("/ws/auth-check"):
            pass
    assert disconnect.value.code == 4401
