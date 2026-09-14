"""Strong integer ETags at the M10 HTTP boundary."""

import re
from typing import Annotated

from fastapi import Header

from erp.platform.errors import ApplicationError


def require_version(if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    if if_match is None:
        raise ApplicationError(
            code="PRECONDITION_REQUIRED", message="If-Match is required.", status_code=428
        )
    matched = re.fullmatch(r'"([1-9][0-9]{0,9})"', if_match)
    if matched is None or int(matched[1]) > 2_147_483_647:
        raise ApplicationError(
            code="INVALID_IF_MATCH",
            message='If-Match must be a quoted positive version, such as "1".',
            status_code=400,
        )
    return int(matched[1])


__all__ = ["require_version"]
