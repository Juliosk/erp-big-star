"""Authenticated context for UI affordances; backend authorization remains authoritative."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from erp.modules.admin.api.router import resolve_security_context
from erp.modules.admin.application import SecurityContext

router = APIRouter(prefix="/api/v1/admin", tags=["security-context"])


class SessionContextResponse(BaseModel):
    actor_id: UUID
    permissions: list[str]
    development_auth: bool


@router.get("/session-context", response_model=SessionContextResponse)
async def session_context(
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
) -> SessionContextResponse:
    response.headers["Cache-Control"] = "no-store"
    return SessionContextResponse(
        actor_id=context.principal.user_id,
        permissions=sorted(str(code) for code in context.permissions),
        development_auth=bool(request.app.state.settings.dev_auth_enabled),
    )


__all__ = ["router"]
