import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.protection import RequestBodyLimitMiddleware
from app.rate_limit import AuthRateLimiter


pytestmark = [pytest.mark.unit, pytest.mark.security]


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
