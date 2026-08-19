import math
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status


class AuthRateLimiter:
    """Small per-process sliding-window limiter for the single course backend."""

    def __init__(self, max_attempts: int = 20, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, request: Request, action: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        self.check_key(client_host, action)

    def check_key(self, subject: str, action: str) -> None:
        key = (action, subject)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()

            if len(attempts) >= self.max_attempts:
                retry_after = max(
                    1,
                    math.ceil(attempts[0] + self.window_seconds - now),
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            attempts.append(now)


auth_rate_limiter = AuthRateLimiter()
