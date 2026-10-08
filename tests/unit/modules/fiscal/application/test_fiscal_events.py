"""M11 event contracts prevent effects before fiscal authorization."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from erp.modules.fiscal.application.events import (
    FiscalDocumentAuthorized,
    FiscalDocumentCancelled,
    FiscalDocumentDenied,
    FiscalDocumentRejected,
    FiscalIntegrationEffect,
    integration_effects,
)
from erp.modules.fiscal.domain import FiscalDocumentModel
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key


def test_only_authorization_triggers_stock_and_receivable_creation() -> None:
    event = FiscalDocumentAuthorized(
        uuid4(),
        uuid4(),
        FiscalDocumentModel.NFE,
        access_key(),
        "135260000000001",
        datetime.now(UTC),
        Decimal("19.00"),
        3,
    )
    assert integration_effects(event) == (
        FiscalIntegrationEffect.INVENTORY_EFFECTUATE,
        FiscalIntegrationEffect.RECEIVABLE_CREATE,
    )


def test_rejection_and_denial_never_trigger_cross_module_effects() -> None:
    company_id = uuid4()
    document_id = uuid4()
    assert integration_effects(
        FiscalDocumentRejected(company_id, document_id, "204", "Duplicidade", 3)
    ) == ()
    assert integration_effects(
        FiscalDocumentDenied(company_id, document_id, "301", "Irregularidade", 3)
    ) == ()


def test_cancellation_triggers_only_compensating_effects() -> None:
    event = FiscalDocumentCancelled(
        uuid4(), uuid4(), access_key(), "135260000000002", datetime.now(UTC), 4
    )
    assert integration_effects(event) == (
        FiscalIntegrationEffect.INVENTORY_REVERSE,
        FiscalIntegrationEffect.RECEIVABLE_REVERSE,
    )
