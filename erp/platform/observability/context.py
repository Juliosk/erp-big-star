"""Async-safe diagnostic context shared by logs and HTTP middleware."""

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_request_id() -> str | None:
    """Return the current request identifier, when inside a request."""
    return _request_id.get()


def get_correlation_id() -> str | None:
    """Return the current cross-request correlation identifier."""
    return _correlation_id.get()


def bind_request_id(value: str) -> Token[str | None]:
    """Bind a request identifier and return its reset token."""
    return _request_id.set(value)


def bind_correlation_id(value: str) -> Token[str | None]:
    """Bind a correlation identifier and return its reset token."""
    return _correlation_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request identifier."""
    _request_id.reset(token)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Restore the previous correlation identifier."""
    _correlation_id.reset(token)


__all__ = [
    "bind_correlation_id",
    "bind_request_id",
    "get_correlation_id",
    "get_request_id",
    "reset_correlation_id",
    "reset_request_id",
]
