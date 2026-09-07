"""Atomic PostgreSQL implementation of corporate creation commands."""

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from erp.modules.admin.application import (
    BranchCreationResult,
    BranchUpdateResult,
    BranchView,
    CompanyCreationResult,
    CompanyUpdateResult,
    CompanyView,
    CreateBranchCommand,
    CreateCompanyCommand,
    UpdateBranchCommand,
    UpdateCompanyCommand,
)
from erp.modules.admin.domain import Branch, Company, TenantContext
from erp.modules.admin.infrastructure.branch_repository import BranchRepository
from erp.modules.admin.infrastructure.company_repository import CompanyRepository
from erp.modules.admin.infrastructure.corporate_directory_repository import (
    CorporateDirectoryRepository,
)
from erp.modules.admin.infrastructure.corporate_events import (
    BRANCH_CREATED,
    BRANCH_CREATED_ROUTING_KEY,
    BRANCH_UPDATED,
    BRANCH_UPDATED_ROUTING_KEY,
    COMPANY_CREATED,
    COMPANY_CREATED_ROUTING_KEY,
    COMPANY_UPDATED,
    COMPANY_UPDATED_ROUTING_KEY,
)
from erp.modules.admin.infrastructure.corporate_models import CompanyModel
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class PostgresCorporateCommandStore:
    """Commit idempotency, aggregate, audit and Outbox as one local transaction."""

    def __init__(
        self,
        database: Database,
        *,
        idempotency_ttl_seconds: int,
        directory: CorporateDirectoryRepository | None = None,
        companies: CompanyRepository | None = None,
        branches: BranchRepository | None = None,
        audit: AuditService | None = None,
        outbox: OutboxService | None = None,
    ) -> None:
        self._database = database
        self._directory = directory or CorporateDirectoryRepository()
        self._companies = companies or CompanyRepository()
        self._branches = branches or BranchRepository()
        self._audit = audit or AuditService()
        self._outbox = outbox or OutboxService()
        self._idempotency = IdempotencyService(ttl_seconds=idempotency_ttl_seconds)

    async def create_company(
        self,
        command: CreateCompanyCommand,
        context: TenantContext,
    ) -> CompanyCreationResult:
        try:
            async with self._database.session() as session, session.begin():
                decision = await self._idempotency.begin(
                    session,
                    scope=f"admin:{context.actor_user_id}",
                    operation="create-company",
                    key=command.idempotency_key,
                    payload=command.idempotency_payload(),
                )
                if decision.replayed:
                    if decision.response_body is None:
                        raise RuntimeError("Completed idempotency record has no response body.")
                    return CompanyCreationResult.from_replay(decision.response_body)

                visible_groups = await self._directory.list_groups(session, context)
                if command.group_id not in {group.id for group in visible_groups}:
                    raise _not_found("economic_group")
                company = _new_company(command)
                await self._companies.add(
                    session,
                    company,
                    actor_id=context.actor_user_id,
                )
                envelope = _company_created_envelope(company, command)
                audit_id = await self._audit.record(
                    session,
                    AuditEvent(
                        actor_user_id=context.actor_user_id,
                        company_id=company.id,
                        branch_id=None,
                        module="admin",
                        entity_type="company",
                        entity_id=company.id,
                        operation="CREATE",
                        request_id=command.metadata.request_id,
                        correlation_id=command.metadata.correlation_id,
                        after_snapshot=_company_snapshot(company),
                        source_ip=command.metadata.source_ip,
                    ),
                )
                await self._outbox.enqueue(
                    session,
                    envelope,
                    headers={"routing_key": COMPANY_CREATED_ROUTING_KEY},
                )
                result = CompanyCreationResult(
                    company=CompanyView.from_domain(company),
                    event_id=envelope.message_id,
                    audit_event_id=audit_id,
                    idempotency_replayed=False,
                )
                await self._idempotency.complete(
                    session,
                    decision,
                    response_status=201,
                    response_body=result.to_dict(),
                )
                return result
        except IntegrityError as error:
            raise _corporate_conflict() from error

    async def create_branch(
        self,
        command: CreateBranchCommand,
        context: TenantContext,
    ) -> BranchCreationResult:
        try:
            async with self._database.session() as session, session.begin():
                decision = await self._idempotency.begin(
                    session,
                    scope=f"admin:{context.actor_user_id}",
                    operation="create-branch",
                    key=command.idempotency_key,
                    payload=command.idempotency_payload(),
                )
                if decision.replayed:
                    if decision.response_body is None:
                        raise RuntimeError("Completed idempotency record has no response body.")
                    return BranchCreationResult.from_replay(decision.response_body)

                company_exists = await session.scalar(
                    select(CompanyModel.id).where(
                        CompanyModel.id == command.company_id,
                        or_(
                            CompanyModel.id.in_(context.company_ids),
                            CompanyModel.group_id.in_(context.group_ids),
                        ),
                    )
                )
                if company_exists is None:
                    raise _not_found("company")
                branch = _new_branch(command)
                await self._branches.add(
                    session,
                    branch,
                    actor_id=context.actor_user_id,
                )
                envelope = _branch_created_envelope(branch, command)
                audit_id = await self._audit.record(
                    session,
                    AuditEvent(
                        actor_user_id=context.actor_user_id,
                        company_id=branch.company_id,
                        branch_id=branch.id,
                        module="admin",
                        entity_type="branch",
                        entity_id=branch.id,
                        operation="CREATE",
                        request_id=command.metadata.request_id,
                        correlation_id=command.metadata.correlation_id,
                        after_snapshot=_branch_snapshot(branch),
                        source_ip=command.metadata.source_ip,
                    ),
                )
                await self._outbox.enqueue(
                    session,
                    envelope,
                    headers={"routing_key": BRANCH_CREATED_ROUTING_KEY},
                )
                result = BranchCreationResult(
                    branch=BranchView.from_domain(branch),
                    event_id=envelope.message_id,
                    audit_event_id=audit_id,
                    idempotency_replayed=False,
                )
                await self._idempotency.complete(
                    session,
                    decision,
                    response_status=201,
                    response_body=result.to_dict(),
                )
                return result
        except IntegrityError as error:
            raise _corporate_conflict() from error

    async def update_company(
        self,
        command: UpdateCompanyCommand,
        context: TenantContext,
    ) -> CompanyUpdateResult:
        if not command.has_changes():
            raise _empty_patch()
        try:
            async with self._database.session() as session, session.begin():
                visible = await self._directory.list_companies(session, context)
                current = next(
                    (company for company in visible if company.id == command.company_id),
                    None,
                )
                if current is None:
                    raise _not_found("company")
                if current.version != command.expected_version:
                    raise OptimisticLockError(expected_version=command.expected_version)
                updated = _updated_company(current, command)
                stored = await self._companies.save(
                    session,
                    updated,
                    actor_id=context.actor_user_id,
                )
                changed_fields = _changed_fields(
                    _company_snapshot(current),
                    _company_snapshot(stored),
                )
                envelope = _company_updated_envelope(stored, command, changed_fields)
                audit_id = await self._audit.record(
                    session,
                    AuditEvent(
                        actor_user_id=context.actor_user_id,
                        company_id=stored.id,
                        branch_id=None,
                        module="admin",
                        entity_type="company",
                        entity_id=stored.id,
                        operation="UPDATE",
                        request_id=command.metadata.request_id,
                        correlation_id=command.metadata.correlation_id,
                        before_snapshot=_company_snapshot(current),
                        after_snapshot=_company_snapshot(stored),
                        source_ip=command.metadata.source_ip,
                    ),
                )
                await self._outbox.enqueue(
                    session,
                    envelope,
                    headers={"routing_key": COMPANY_UPDATED_ROUTING_KEY},
                )
                return CompanyUpdateResult(
                    company=CompanyView.from_domain(stored),
                    event_id=envelope.message_id,
                    audit_event_id=audit_id,
                )
        except IntegrityError as error:
            raise _corporate_conflict() from error

    async def update_branch(
        self,
        command: UpdateBranchCommand,
        context: TenantContext,
    ) -> BranchUpdateResult:
        if not command.has_changes():
            raise _empty_patch()
        try:
            async with self._database.session() as session, session.begin():
                visible = await self._directory.list_branches(session, context)
                current = next(
                    (branch for branch in visible if branch.id == command.branch_id),
                    None,
                )
                if current is None:
                    raise _not_found("branch")
                if current.version != command.expected_version:
                    raise OptimisticLockError(expected_version=command.expected_version)
                updated = _updated_branch(current, command)
                stored = await self._branches.save(
                    session,
                    updated,
                    actor_id=context.actor_user_id,
                )
                changed_fields = _changed_fields(
                    _branch_snapshot(current),
                    _branch_snapshot(stored),
                )
                envelope = _branch_updated_envelope(stored, command, changed_fields)
                audit_id = await self._audit.record(
                    session,
                    AuditEvent(
                        actor_user_id=context.actor_user_id,
                        company_id=stored.company_id,
                        branch_id=stored.id,
                        module="admin",
                        entity_type="branch",
                        entity_id=stored.id,
                        operation="UPDATE",
                        request_id=command.metadata.request_id,
                        correlation_id=command.metadata.correlation_id,
                        before_snapshot=_branch_snapshot(current),
                        after_snapshot=_branch_snapshot(stored),
                        source_ip=command.metadata.source_ip,
                    ),
                )
                await self._outbox.enqueue(
                    session,
                    envelope,
                    headers={"routing_key": BRANCH_UPDATED_ROUTING_KEY},
                )
                return BranchUpdateResult(
                    branch=BranchView.from_domain(stored),
                    event_id=envelope.message_id,
                    audit_event_id=audit_id,
                )
        except IntegrityError as error:
            raise _corporate_conflict() from error


def _new_company(command: CreateCompanyCommand) -> Company:
    try:
        return Company.create(
            group_id=command.group_id,
            code=command.code,
            legal_name=command.legal_name,
            trade_name=command.trade_name,
            tax_id=command.tax_id,
            timezone=command.timezone,
        )
    except (TypeError, ValueError) as error:
        raise _validation_error(str(error)) from error


def _new_branch(command: CreateBranchCommand) -> Branch:
    try:
        return Branch.create(
            company_id=command.company_id,
            code=command.code,
            name=command.name,
            tax_id=command.tax_id,
            timezone=command.timezone,
        )
    except (TypeError, ValueError) as error:
        raise _validation_error(str(error)) from error


def _updated_company(current: Company, command: UpdateCompanyCommand) -> Company:
    try:
        return current.update_profile(
            legal_name=command.legal_name or current.legal_name,
            trade_name=(command.trade_name if command.trade_name_supplied else current.trade_name),
            timezone=command.timezone or current.timezone,
            status=command.status or current.status,
        )
    except (TypeError, ValueError) as error:
        raise _validation_error(str(error)) from error


def _updated_branch(current: Branch, command: UpdateBranchCommand) -> Branch:
    try:
        return current.update_profile(
            name=command.name or current.name,
            timezone=command.timezone or current.timezone,
            status=command.status or current.status,
        )
    except (TypeError, ValueError) as error:
        raise _validation_error(str(error)) from error


def _company_created_envelope(
    company: Company,
    command: CreateCompanyCommand,
) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=COMPANY_CREATED,
        event_version=1,
        producer_module="admin",
        producer_domain="admin",
        aggregate_type="company",
        aggregate_id=company.id,
        aggregate_version=company.version,
        company_id=company.id,
        branch_id=None,
        correlation_id=command.metadata.correlation_id,
        causation_id=None,
        request_id=command.metadata.request_id,
        payload={
            "company_id": str(company.id),
            "group_id": str(company.group_id),
            "legal_name": company.legal_name,
            "status": company.status,
        },
    )


def _branch_created_envelope(branch: Branch, command: CreateBranchCommand) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=BRANCH_CREATED,
        event_version=1,
        producer_module="admin",
        producer_domain="admin",
        aggregate_type="branch",
        aggregate_id=branch.id,
        aggregate_version=branch.version,
        company_id=branch.company_id,
        branch_id=branch.id,
        correlation_id=command.metadata.correlation_id,
        causation_id=None,
        request_id=command.metadata.request_id,
        payload={
            "branch_id": str(branch.id),
            "company_id": str(branch.company_id),
            "code": branch.code,
            "timezone": branch.timezone,
        },
    )


def _company_updated_envelope(
    company: Company,
    command: UpdateCompanyCommand,
    changed_fields: list[str],
) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=COMPANY_UPDATED,
        event_version=1,
        producer_module="admin",
        producer_domain="admin",
        aggregate_type="company",
        aggregate_id=company.id,
        aggregate_version=company.version,
        company_id=company.id,
        branch_id=None,
        correlation_id=command.metadata.correlation_id,
        causation_id=None,
        request_id=command.metadata.request_id,
        payload={
            "company_id": str(company.id),
            "changed_fields": changed_fields,
            "version": company.version,
        },
    )


def _branch_updated_envelope(
    branch: Branch,
    command: UpdateBranchCommand,
    changed_fields: list[str],
) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=BRANCH_UPDATED,
        event_version=1,
        producer_module="admin",
        producer_domain="admin",
        aggregate_type="branch",
        aggregate_id=branch.id,
        aggregate_version=branch.version,
        company_id=branch.company_id,
        branch_id=branch.id,
        correlation_id=command.metadata.correlation_id,
        causation_id=None,
        request_id=command.metadata.request_id,
        payload={
            "branch_id": str(branch.id),
            "changed_fields": changed_fields,
            "version": branch.version,
        },
    )


def _company_snapshot(company: Company) -> dict[str, object]:
    return {
        "id": str(company.id),
        "group_id": str(company.group_id),
        "code": company.code,
        "legal_name": company.legal_name,
        "trade_name": company.trade_name,
        "tax_id": str(company.tax_id),
        "timezone": company.timezone,
        "status": company.status,
        "version": company.version,
    }


def _branch_snapshot(branch: Branch) -> dict[str, object]:
    return {
        "id": str(branch.id),
        "company_id": str(branch.company_id),
        "code": branch.code,
        "name": branch.name,
        "tax_id": str(branch.tax_id),
        "timezone": branch.timezone,
        "status": branch.status,
        "version": branch.version,
    }


def _changed_fields(before: dict[str, object], after: dict[str, object]) -> list[str]:
    ignored = {"id", "group_id", "company_id", "version"}
    return sorted(
        key for key, value in before.items() if key not in ignored and after[key] != value
    )


def _validation_error(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Corporate data violates a business rule.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"The requested {resource} was not found.",
        status_code=404,
    )


def _corporate_conflict() -> ApplicationError:
    return ApplicationError(
        code="CORPORATE_IDENTIFIER_CONFLICT",
        message="A corporate code or tax identifier is already in use.",
        status_code=409,
    )


def _empty_patch() -> ApplicationError:
    return ApplicationError(
        code="EMPTY_PATCH",
        message="At least one mutable field must be provided.",
        status_code=422,
    )


__all__ = ["PostgresCorporateCommandStore"]
