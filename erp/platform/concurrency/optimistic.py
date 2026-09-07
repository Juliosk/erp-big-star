"""SQLAlchemy version convention and stable conflict translation."""

from typing import Any

from sqlalchemy import Integer, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from erp.platform.errors import ApplicationError, ErrorDetail


class OptimisticLockError(ApplicationError):
    """Stable API conflict raised when an expected version is stale."""

    def __init__(self, *, expected_version: int) -> None:
        super().__init__(
            code="VERSION_CONFLICT",
            message="The resource was changed by another transaction.",
            status_code=409,
            details=[ErrorDetail(message=f"Expected version {expected_version}.")],
        )


class OptimisticLockMixin:
    """Declare integer versioning with SQLAlchemy's compare-and-increment mapper support."""

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}


__all__ = ["OptimisticLockError", "OptimisticLockMixin"]
