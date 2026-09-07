"""Tests for structured JSON logging."""

import json
import logging

from erp.platform.observability import (
    JsonFormatter,
    bind_correlation_id,
    bind_request_id,
    reset_correlation_id,
    reset_request_id,
)


def test_json_formatter_emits_context_and_ignores_arbitrary_extras() -> None:
    formatter = JsonFormatter(service="erp-test", environment="test")
    record = logging.LogRecord(
        name="erp.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request.completed",
        args=(),
        exc_info=None,
    )
    record.postgres_password = "must-not-be-logged"
    request_token = bind_request_id("request-123")
    correlation_token = bind_correlation_id("correlation-456")

    try:
        payload = json.loads(formatter.format(record))
    finally:
        reset_correlation_id(correlation_token)
        reset_request_id(request_token)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "erp.test"
    assert payload["message"] == "request.completed"
    assert payload["service"] == "erp-test"
    assert payload["environment"] == "test"
    assert payload["request_id"] == "request-123"
    assert payload["correlation_id"] == "correlation-456"
    assert "timestamp" in payload
    assert "must-not-be-logged" not in formatter.format(record)


def test_json_formatter_omits_request_context_outside_request() -> None:
    formatter = JsonFormatter(service="erp-test", environment="test")
    record = logging.LogRecord(
        name="erp.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="background.warning",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "WARNING"
    assert "request_id" not in payload
    assert "correlation_id" not in payload
