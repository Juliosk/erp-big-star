"""Minimal structured JSON logging configuration."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from erp.platform.config import Settings
from erp.platform.observability.context import get_correlation_id, get_request_id


class JsonFormatter(logging.Formatter):
    """Serialize the approved log envelope without arbitrary record attributes."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Format one record as a stable JSON object."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "environment": self._environment,
        }

        request_id = get_request_id()
        correlation_id = get_correlation_id()
        if request_id is not None:
            payload["request_id"] = request_id
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    """Route application and server logs through the structured formatter."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            service=settings.app_name,
            environment=settings.environment.value,
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.value)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        server_logger = logging.getLogger(logger_name)
        server_logger.handlers.clear()
        server_logger.propagate = True


__all__ = ["JsonFormatter", "configure_logging"]
