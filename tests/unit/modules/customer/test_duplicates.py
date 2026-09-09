"""Pure duplicate detection and merge request rules for M14."""

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.customer.application.commands import CommandMetadata
from erp.modules.customer.application.duplicates import (
    CustomerDuplicateService,
    CustomerDuplicateStore,
    CustomerMergeRequestResult,
    RequestCustomerMerge,
)
from erp.modules.customer.application.permissions import (
    CUSTOMER_MERGE,
    CUSTOMER_READ,
    CustomerAuthorization,
)
from erp.modules.customer.domain import (
    Customer,
    CustomerDuplicateCandidate,
    CustomerMergeRequest,
    CustomerType,
    DuplicateReason,
    MergeRequestStatus,
    TaxIdKind,
    detect_duplicate_candidates,
)
from erp.modules.customer.domain.duplicate import _similarity
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, object, bool]] = []

    async def require(
        self, context: SecurityContext, company_id: UUID, permission: object, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeStore:
    def __init__(self) -> None:
        self.detect_actor: UUID | None = None
        self.merge: RequestCustomerMerge | None = None

    async def detect(
        self, company_id: UUID, customer_id: UUID, actor_id: UUID
    ) -> tuple[CustomerDuplicateCandidate, ...]:
        self.detect_actor = actor_id
        return ()

    async def request_merge(
        self, command: RequestCustomerMerge, actor_id: UUID
    ) -> CustomerMergeRequestResult:
        self.merge = command
        merge_request = CustomerMergeRequest.request(
            company_id=command.company_id,
            source_customer_id=command.source_customer_id,
            candidate_customer_id=command.candidate_customer_id,
            surviving_customer_id=command.surviving_customer_id,
            reason=command.reason,
        )
        return CustomerMergeRequestResult(merge_request, uuid4(), uuid4())


def _customer(
    *,
    company_id: UUID,
    customer_id: UUID | None = None,
    identity_value: str = "52998224725",
    legal_name: str = "Maria Souza",
    trade_name: str | None = "Maria",
) -> Customer:
    item = Customer.create(
        company_id=company_id,
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value=identity_value,
        legal_name=legal_name,
        trade_name=trade_name,
    )
    if customer_id is not None:
        object.__setattr__(item, "id", customer_id)
    return item


def _context(user_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(user_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(),
        scopes=frozenset(),
    )


def test_duplicate_detector_finds_exact_identity_and_similar_names_inside_company() -> None:
    company_id, other_company_id = uuid4(), uuid4()
    source = _customer(company_id=company_id)
    exact = _customer(company_id=company_id, identity_value=source.tax_id.value)
    similar = _customer(
        company_id=company_id,
        identity_value="15350946056",
        legal_name="Maria Sousa",
        trade_name="Maria S.",
    )
    foreign = _customer(
        company_id=other_company_id,
        identity_value="98765432100",
        legal_name="Maria Souza",
    )

    detected = detect_duplicate_candidates(source, (exact, similar, foreign))

    assert [candidate.candidate_customer_id for candidate in detected] == [exact.id, similar.id]
    assert detected[0].confidence == 100
    assert detected[0].reason_codes == (DuplicateReason.EXACT_IDENTITY,)
    assert DuplicateReason.LEGAL_NAME_SIMILAR in detected[1].reason_codes


def test_duplicate_detector_covers_trade_name_and_empty_similarity_paths() -> None:
    company_id = uuid4()
    source = _customer(
        company_id=company_id,
        identity_value="52998224725",
        legal_name="Cliente muito diferente",
        trade_name="Forma Kids Loja",
    )
    trade = _customer(
        company_id=company_id,
        identity_value="15350946056",
        legal_name="Outro Cadastro",
        trade_name="Forma Kids Loja",
    )
    weak = _customer(
        company_id=company_id,
        identity_value="98765432100",
        legal_name="Nome sem relacao",
        trade_name=None,
    )

    detected = detect_duplicate_candidates(source, (trade, weak))

    assert [candidate.candidate_customer_id for candidate in detected] == [trade.id]
    assert detected[0].reason_codes == (DuplicateReason.TRADE_NAME_SIMILAR,)
    assert _similarity("", "Forma Kids") == 0


def test_duplicate_detector_validates_threshold_and_candidate_shape() -> None:
    with pytest.raises(ValueError, match="similarity_threshold"):
        detect_duplicate_candidates(_customer(company_id=uuid4()), (), similarity_threshold=0)
    customer_id = uuid4()
    with pytest.raises(ValueError, match="different customers"):
        CustomerDuplicateCandidate(
            uuid4(), uuid4(), customer_id, customer_id, 90, (DuplicateReason.EXACT_IDENTITY,)
        )
    with pytest.raises(ValueError, match="UUID"):
        CustomerDuplicateCandidate(
            uuid4(), uuid4(), uuid4(), cast(UUID, None), 90, (DuplicateReason.EXACT_IDENTITY,)
        )
    with pytest.raises(ValueError, match="confidence"):
        CustomerDuplicateCandidate(
            uuid4(), uuid4(), uuid4(), uuid4(), 101, (DuplicateReason.EXACT_IDENTITY,)
        )
    with pytest.raises(ValueError, match="reason_codes"):
        CustomerDuplicateCandidate(uuid4(), uuid4(), uuid4(), uuid4(), 90, ())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"candidate_customer_id": None}, "UUID"),
        ({"candidate_customer_id": "same"}, "different"),
        ({"surviving_customer_id": uuid4()}, "surviving"),
        ({"reason": " "}, "reason"),
    ],
)
def test_merge_request_validates_fiscal_traceability_shape(
    changes: dict[str, object], message: str
) -> None:
    source, candidate = uuid4(), uuid4()
    values: dict[str, object] = {
        "company_id": uuid4(),
        "source_customer_id": source,
        "candidate_customer_id": candidate,
        "surviving_customer_id": source,
        "reason": "Possivel duplicidade",
    }
    values.update(changes)
    if changes.get("candidate_customer_id") == "same":
        values["candidate_customer_id"] = source
    with pytest.raises(ValueError, match=message):
        CustomerMergeRequest.request(**cast(Any, values))


def test_merge_request_rejects_invalid_status_and_version_snapshots() -> None:
    source, candidate = uuid4(), uuid4()
    with pytest.raises(ValueError, match="status"):
        CustomerMergeRequest(
            uuid4(),
            uuid4(),
            source,
            candidate,
            source,
            cast(Any, "PENDING_APPROVAL"),
            "Possivel duplicidade",
            1,
        )
    with pytest.raises(ValueError, match="version"):
        CustomerMergeRequest(
            uuid4(),
            uuid4(),
            source,
            candidate,
            source,
            MergeRequestStatus.PENDING_APPROVAL,
            "Possivel duplicidade",
            0,
        )


def test_duplicate_service_authorizes_read_and_merge_write() -> None:
    async def scenario() -> None:
        company_id, actor_id = uuid4(), uuid4()
        authorization = FakeAuthorization()
        store = FakeStore()
        service = CustomerDuplicateService(
            cast(CustomerDuplicateStore, store), cast(CustomerAuthorization, authorization)
        )
        context = _context(actor_id)
        await service.detect(context, company_id, uuid4())
        source, candidate = uuid4(), uuid4()
        command = RequestCustomerMerge(
            company_id,
            source,
            candidate,
            source,
            "Solicitar aprovacao de merge",
            CommandMetadata(uuid4(), uuid4()),
        )
        with pytest.raises(ApplicationError):
            await service.request_merge(
                context,
                RequestCustomerMerge(
                    company_id,
                    command.source_customer_id,
                    command.source_customer_id,
                    command.source_customer_id,
                    command.reason,
                    command.metadata,
                ),
            )
        await service.request_merge(context, command)

        assert store.detect_actor == actor_id
        assert store.merge == command
        assert authorization.calls == [
            (company_id, CUSTOMER_READ, False),
            (company_id, CUSTOMER_MERGE, True),
        ]

    asyncio.run(scenario())
