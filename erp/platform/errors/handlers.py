"""FastAPI adapters for the standard error contract."""

import logging
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from erp.platform.errors.contract import ApplicationError, ErrorBody, ErrorDetail, ErrorEnvelope
from erp.platform.observability import get_correlation_id

logger = logging.getLogger(__name__)


def _correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, str) else (get_correlation_id() or str(uuid4()))


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
            correlation_id=_correlation_id(request),
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


async def handle_application_error(request: Request, exc: Exception) -> JSONResponse:
    """Render an expected failure without leaking implementation details."""
    error = cast(ApplicationError, exc)
    logger.info("application.request.rejected", extra=error.as_log_context())
    return _response(
        request,
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        details=error.details,
        headers=error.headers,
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Normalize Pydantic/FastAPI validation diagnostics."""
    error = cast(RequestValidationError, exc)
    details = [
        ErrorDetail(
            location=[str(part) if not isinstance(part, int) else part for part in item["loc"]],
            message=item["msg"],
            type=item.get("type"),
        )
        for item in error.errors()
    ]
    return _response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details=details,
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log an unexpected exception and expose only a stable generic response."""
    logger.exception("application.request.failed", exc_info=exc)
    return _response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
    )


async def handle_http_error(request: Request, exc: Exception) -> Response:
    """Preserve framework HTTP behavior for routes outside the application contract."""
    return await http_exception_handler(request, cast(StarletteHTTPException, exc))


def register_error_handlers(application: FastAPI) -> None:
    """Install all error-boundary adapters on one application instance."""
    application.add_exception_handler(ApplicationError, handle_application_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(StarletteHTTPException, handle_http_error)
    application.add_exception_handler(Exception, handle_unexpected_error)


__all__ = ["register_error_handlers"]
