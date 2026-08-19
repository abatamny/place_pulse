from threading import Lock

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyTooLargeError(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies before an endpoint processes them."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                await self._reject(scope, receive, send, 400, "Invalid Content-Length")
                return
            if declared_bytes < 0:
                await self._reject(scope, receive, send, 400, "Invalid Content-Length")
                return
            if declared_bytes > self.max_body_bytes:
                await self._reject(scope, receive, send, 413, "Request body is too large")
                return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise RequestBodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLargeError:
            if response_started:
                raise
            await self._reject(scope, receive, send, 413, "Request body is too large")

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(scope, receive, send)


class ConcurrencyLimitMiddleware:
    """Bound in-flight HTTP work and long-lived WebSocket connections."""

    def __init__(
        self,
        app: ASGIApp,
        max_http_requests: int,
        max_websocket_connections: int,
    ) -> None:
        if max_http_requests <= 0 or max_websocket_connections <= 0:
            raise ValueError("concurrency limits must be positive")
        self.app = app
        self.max_http_requests = max_http_requests
        self.max_websocket_connections = max_websocket_connections
        self._active_http_requests = 0
        self._active_websocket_connections = 0
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type == "http":
            if not self._claim_http_slot():
                response = JSONResponse(
                    status_code=503,
                    content={"detail": "Server is busy. Try again shortly."},
                    headers={"Retry-After": "1"},
                )
                await response(scope, receive, send)
                return
            try:
                await self.app(scope, receive, send)
            finally:
                self._release_http_slot()
            return

        if scope_type == "websocket":
            if not self._claim_websocket_slot():
                await send(
                    {
                        "type": "websocket.close",
                        "code": 1013,
                        "reason": "Server is busy. Try again shortly.",
                    }
                )
                return
            try:
                await self.app(scope, receive, send)
            finally:
                self._release_websocket_slot()
            return

        await self.app(scope, receive, send)

    def _claim_http_slot(self) -> bool:
        with self._lock:
            if self._active_http_requests >= self.max_http_requests:
                return False
            self._active_http_requests += 1
            return True

    def _release_http_slot(self) -> None:
        with self._lock:
            self._active_http_requests -= 1

    def _claim_websocket_slot(self) -> bool:
        with self._lock:
            if (
                self._active_websocket_connections
                >= self.max_websocket_connections
            ):
                return False
            self._active_websocket_connections += 1
            return True

    def _release_websocket_slot(self) -> None:
        with self._lock:
            self._active_websocket_connections -= 1
