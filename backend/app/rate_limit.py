import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status


class AuthRateLimiter:
    """Small per-process limiter suitable for the single course backend."""

    def __init__(self, max_attempts: int = 20, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, request: Request, action: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        key = (action, client_host)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()

            if len(attempts) >= self.max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many authentication attempts. Try again shortly.",
                )
            attempts.append(now)


auth_rate_limiter = AuthRateLimiter()

