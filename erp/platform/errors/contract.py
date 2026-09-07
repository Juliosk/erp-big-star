"""Technology-neutral error types exposed through the HTTP boundary."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """One structured item explaining an invalid field or business rule."""

    location: list[str | int] = []
    message: str
    type: str | None = None


class ErrorBody(BaseModel):
    """Stable error body nested under the top-level error key."""

    code: str
    message: str
    details: list[ErrorDetail]
    correlation_id: str


class ErrorEnvelope(BaseModel):
    """Public error response envelope."""

    error: ErrorBody


@dataclass(eq=False, slots=True)
class ApplicationError(Exception):
    """Expected application failure with a stable public code."""

    code: str
    message: str
    status_code: int
    details: list[ErrorDetail] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def as_log_context(self) -> dict[str, Any]:
        """Return safe, non-payload metadata for structured diagnostic logs."""
        return {"error_code": self.code, "status_code": self.status_code}


__all__ = ["ApplicationError", "ErrorBody", "ErrorDetail", "ErrorEnvelope"]
