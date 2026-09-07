"""ASGI middleware for request and correlation identifiers."""

from typing import Any
from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from erp.platform.observability import (
    bind_correlation_id,
    bind_request_id,
    reset_correlation_id,
    reset_request_id,
)

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


def normalized_uuid(value: str | None) -> str | None:
    """Return a canonical UUID string or reject an untrusted identifier."""
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


class RequestIdMiddleware:
    """Assign one request-scoped UUID before any inner HTTP middleware."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = normalized_uuid(Headers(scope=scope).get(REQUEST_ID_HEADER)) or str(uuid4())
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = bind_request_id(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            reset_request_id(token)


class CorrelationIdMiddleware:
    """Propagate a valid correlation UUID or fall back to the request UUID."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        state: dict[str, Any] = scope.setdefault("state", {})
        request_id = state.get("request_id")
        fallback_id = request_id if isinstance(request_id, str) else str(uuid4())
        correlation_id = (
            normalized_uuid(Headers(scope=scope).get(CORRELATION_ID_HEADER)) or fallback_id
        )
        state["correlation_id"] = correlation_id
        token = bind_correlation_id(correlation_id)

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_ID_HEADER] = correlation_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_correlation_id)
        finally:
            reset_correlation_id(token)


__all__ = ["CorrelationIdMiddleware", "RequestIdMiddleware"]
