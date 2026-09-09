"""M14 public contracts and API providers stay explicit."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from erp.modules.customer.api.creation import get_creation
from erp.modules.customer.api.duplicates import get_duplicates
from erp.modules.customer.api.groups import get_groups
from erp.modules.customer.api.queries import get_queries
from erp.modules.customer.api.updates import get_updates
from erp.modules.customer.application.permissions import CUSTOMER_READ, CustomerAuthorization
from erp.modules.customer.contracts import CustomerReference
from erp.platform.errors import ApplicationError


def test_public_contract_exports_customer_reference_without_infrastructure() -> None:
    reference = CustomerReference(
        customer_id=uuid4(),
        company_id=uuid4(),
        customer_type="INDIVIDUAL",
        status="ACTIVE",
        identity_ref="CPF:***4725",
        legal_name="Maria Souza",
        version=1,
    )

    assert reference.version == 1
    assert str(CUSTOMER_READ) == "crm.customer.read"
    assert CustomerAuthorization.__name__ == "CustomerAuthorization"


@pytest.mark.parametrize(
    ("provider", "code"),
    [
        (get_queries, "CUSTOMER_QUERY_UNAVAILABLE"),
        (get_creation, "CUSTOMER_COMMAND_UNAVAILABLE"),
        (get_updates, "CUSTOMER_COMMAND_UNAVAILABLE"),
        (get_groups, "CUSTOMER_GROUP_UNAVAILABLE"),
        (get_duplicates, "CUSTOMER_DUPLICATE_UNAVAILABLE"),
    ],
)
def test_api_dependency_providers_fail_closed(provider: object, code: str) -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(ApplicationError) as captured:
        cast(Any, provider)(request)

    assert captured.value.code == code
    assert captured.value.status_code == 503
