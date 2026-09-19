"""Strict ETag parser for M15 commands."""

import re
from typing import Annotated

from fastapi import Header

from erp.platform.errors import ApplicationError

_ETAG = re.compile(r'^"([1-9][0-9]*)"$')


def require_version(if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    if if_match is None:
        raise ApplicationError(
            code="PRECONDITION_REQUIRED", message="If-Match is required.", status_code=428
        )
    match = _ETAG.fullmatch(if_match)
    if match is None:
        raise ApplicationError(
            code="INVALID_IF_MATCH",
            message='If-Match must be a quoted positive version, such as "1".',
            status_code=400,
        )
    return int(match.group(1))


__all__ = ["require_version"]
