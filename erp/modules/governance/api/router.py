"""Bounded binary upload and explicit, company-scoped import commands."""

import re
from io import BytesIO
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.contracts import SecurityContext, SecurityContextResolver
from erp.modules.governance.application.imports import ImportService
from erp.modules.governance.domain.import_job import MAX_SOURCE_BYTES
from erp.modules.product.contracts import CommandMetadata
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key
from erp.platform.storage.minio import XLSX_CONTENT_TYPE

router = APIRouter(prefix="/api/v1/data", tags=["product-import"])
bearer = HTTPBearer(auto_error=False)


async def security(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SecurityContext:
    if credentials is None:
        raise ApplicationError(
            code="AUTHENTICATION_REQUIRED", message="Bearer required.", status_code=401
        )
    resolver = getattr(request.app.state, "security_context_resolver", None)
    if resolver is None:
        raise ApplicationError(
            code="AUTHENTICATION_UNAVAILABLE", message="Identity unavailable.", status_code=503
        )
    context = await cast(SecurityContextResolver, resolver).resolve(credentials.credentials)
    if context is None:
        raise ApplicationError(
            code="AUTHENTICATION_REQUIRED", message="Invalid Bearer.", status_code=401
        )
    return context


def service(request: Request) -> ImportService:
    result = getattr(request.app.state, "imports", None)
    if not isinstance(result, ImportService):
        raise ApplicationError(
            code="IMPORT_UNAVAILABLE", message="Import service unavailable.", status_code=503
        )
    return result


Identity = Annotated[SecurityContext, Depends(security)]
Imports = Annotated[ImportService, Depends(service)]


def version(if_match: Annotated[str | None, Header()] = None) -> int:
    if if_match is None:
        raise ApplicationError(
            code="PRECONDITION_REQUIRED", message="If-Match required.", status_code=428
        )
    if re.fullmatch(r'"[1-9][0-9]{0,9}"', if_match) is None or int(if_match[1:-1]) > 2147483647:
        raise ApplicationError(
            code="INVALID_IF_MATCH", message="Use a quoted positive version.", status_code=400
        )
    return int(if_match[1:-1])


def metadata(request: Request) -> CommandMetadata:
    return CommandMetadata(
        UUID(request.state.request_id),
        UUID(request.state.correlation_id),
        request.client.host if request.client else None,
    )


def headers(response: Response, result: dict[str, Any]) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = f'"{result["version"]}"'
    response.headers["Idempotency-Replayed"] = str(
        result.get("idempotency_replayed", False)
    ).lower()
    return result


@router.get("/import-templates")
async def templates(company_id: UUID, context: Identity, imports: Imports) -> dict[str, Any]:
    await imports.authorize(context, company_id)
    return {"items": await imports.store.templates(company_id)}


@router.post("/import-templates/product", status_code=201)
async def provision(
    company_id: UUID, context: Identity, imports: Imports, request: Request
) -> dict[str, Any]:
    await imports.authorize(context, company_id, confirm=True, write=True)
    return await imports.store.provision(company_id, context.principal.user_id, metadata(request))


@router.get("/import-templates/{template_id}/download-model")
async def download(
    template_id: UUID,
    company_id: UUID,
    context: Identity,
    imports: Imports,
    template_version: Annotated[int, Query(ge=1)] = 1,
) -> Response:
    await imports.authorize(context, company_id)
    content = await imports.store.download(company_id, template_id, template_version)
    return Response(
        content,
        media_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="produtos-v{template_version}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/imports", status_code=201)
async def upload(
    request: Request,
    response: Response,
    company_id: UUID,
    template_id: UUID,
    context: Identity,
    imports: Imports,
    key: Annotated[str, Depends(require_idempotency_key)],
    filename: Annotated[str, Query(min_length=6, max_length=255)],
    template_version: Annotated[int, Query(ge=1)] = 1,
    commit_mode: Literal["ALL_OR_NOTHING"] = "ALL_OR_NOTHING",
) -> dict[str, Any]:
    await imports.authorize(context, company_id, write=True)
    if request.headers.get("content-type", "").split(";", 1)[0] != XLSX_CONTENT_TYPE:
        raise ApplicationError(
            code="IMPORT_MEDIA_TYPE",
            message="Upload the XLSX bytes with its official media type.",
            status_code=415,
        )
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SOURCE_BYTES:
            raise ApplicationError(
                code="IMPORT_FILE_TOO_LARGE", message="Maximum upload is 10 MiB.", status_code=413
            )
        content.extend(chunk)
    try:
        result = await imports.store.upload(
            context,
            company_id,
            template_id,
            template_version,
            filename,
            bytes(content),
            key,
            metadata(request),
        )
    except ValueError as error:
        raise ApplicationError(
            code="IMPORT_INVALID_FILE", message=str(error), status_code=422
        ) from error
    return headers(response, result)


@router.get("/imports")
async def history(
    company_id: UUID,
    context: Identity,
    imports: Imports,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
) -> dict[str, Any]:
    await imports.authorize(context, company_id)
    return {"items": await imports.store.history(company_id, page), "page": page}


@router.get("/imports/{job_id}")
async def detail(
    job_id: UUID,
    company_id: UUID,
    response: Response,
    context: Identity,
    imports: Imports,
) -> dict[str, Any]:
    await imports.authorize(context, company_id)
    return headers(response, await imports.store.get(company_id, job_id))


class CommandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(default="", max_length=64)


@router.post("/imports/{job_id}/{action}")
async def command(
    job_id: UUID,
    company_id: UUID,
    action: Literal["validate", "preview", "confirm", "commit", "cancel"],
    body: CommandBody,
    request: Request,
    response: Response,
    context: Identity,
    imports: Imports,
    expected: Annotated[int, Depends(version)],
) -> dict[str, Any]:
    await imports.authorize(
        context, company_id, confirm=action in {"confirm", "commit"}, write=True
    )
    key = request.headers.get("Idempotency-Key", "")
    if action == "commit" and not key.strip():
        raise ApplicationError(
            code="INVALID_IDEMPOTENCY_KEY", message="Idempotency-Key required.", status_code=400
        )
    try:
        result = await imports.store.command(
            context, company_id, job_id, action, expected, body.fingerprint, key, metadata(request)
        )
    except ValueError as error:
        raise ApplicationError(
            code="IMPORT_INVALID_STATE", message=str(error), status_code=409
        ) from error
    return headers(response, result)


@router.get("/imports/{job_id}/rejected-file")
async def rejected(job_id: UUID, company_id: UUID, context: Identity, imports: Imports) -> Response:
    await imports.authorize(context, company_id)
    job = await imports.store.get(company_id, job_id)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Inconsistencias"
    sheet.append(["Linha", "SKU", "Erros"])
    for row in job.get("rows", []):
        if row["errors"]:
            sheet.append([row["number"], "", ""])
            for column, text in (
                (2, row["proposed"].get("sku", "")),
                (3, "; ".join(row["errors"])),
            ):
                cell = sheet.cell(sheet.max_row, column)
                cell.value = text
                cell.data_type = "s"
    sheet.column_dimensions["B"].width = 40
    sheet.column_dimensions["C"].width = 90
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return Response(
        output.getvalue(),
        media_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="inconsistencias.xlsx"',
            "Cache-Control": "no-store",
        },
    )


__all__ = ["router"]
