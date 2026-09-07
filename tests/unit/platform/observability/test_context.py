"""Tests for async-safe logging context."""

from erp.platform.observability import (
    bind_correlation_id,
    bind_request_id,
    get_correlation_id,
    get_request_id,
    reset_correlation_id,
    reset_request_id,
)


def test_identifiers_are_bound_and_reset() -> None:
    request_token = bind_request_id("request-123")
    correlation_token = bind_correlation_id("correlation-456")

    assert get_request_id() == "request-123"
    assert get_correlation_id() == "correlation-456"

    reset_correlation_id(correlation_token)
    reset_request_id(request_token)

    assert get_request_id() is None
    assert get_correlation_id() is None
