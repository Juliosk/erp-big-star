"""Stable application error contract and FastAPI handlers."""

from erp.platform.errors.contract import ApplicationError, ErrorDetail, ErrorEnvelope
from erp.platform.errors.handlers import register_error_handlers

__all__ = ["ApplicationError", "ErrorDetail", "ErrorEnvelope", "register_error_handlers"]
