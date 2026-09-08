"""Negative, rollback and concurrent gates for the final M2 commands."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from erp.modules.product.application.permissions import PRODUCT_ACTIVATE
from erp.modules.product.infrastructure.product_repository import ProductRepository
from erp.platform.audit import AuditService
from erp.platform.idempotency.service import IdempotencyDecision, IdempotencyService
from erp.platform.outbox import OutboxService
from tests.integration.product_api_support import product_api
from tests.integration.test_product_creation_api import counts
from tests.integration.test_product_updates_api import create_for_update

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("action", ["submit-for-homologation", "barcodes"])
def test_missing_product_headers_and_replay_authorization(action: str) -> None:
    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context, permissions=api.resolver.context.permissions | {PRODUCT_ACTIVATE}
        )
        body = {"barcode_type": "INTERNAL", "barcode": "BC-1"} if action == "barcodes" else None
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        command_url = f"{path}/{action}?{query}"
        assert api.client.post(command_url, json=body, headers=headers).status_code == 428
        headers["If-Match"] = '"1"'
        missing = f"/api/v1/products/{uuid4()}/{action}?{query}"
        assert api.client.post(missing, json=body, headers=headers).status_code == 404
        if action == "barcodes":
            assert api.client.get(missing, headers=api.headers).status_code == 404
        assert counts(api) == (1, 1, 1, 1)
        response = api.client.post(command_url, json=body, headers=headers)
        assert response.status_code in (200, 201)
        api.resolver.context = replace(api.resolver.context, permissions=frozenset())
        assert api.client.post(command_url, json=body, headers=headers).status_code == 403
        assert counts(api) == (1, 2, 2, 2)


@pytest.mark.parametrize("action", ["submit-for-homologation", "barcodes"])
def test_corrupted_final_command_replay_fails_closed(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def corrupt(*args: Any, **kwargs: Any) -> IdempotencyDecision:
        return IdempotencyDecision(record_id=uuid4(), replayed=True)

    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context, permissions=api.resolver.context.permissions | {PRODUCT_ACTIVATE}
        )
        monkeypatch.setattr(IdempotencyService, "begin", corrupt)
        with pytest.raises(RuntimeError, match="no response body"):
            api.client.post(
                f"{path}/{action}?{query}",
                json={"barcode_type": "INTERNAL", "barcode": "BC-1"}
                if action == "barcodes"
                else None,
                headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())},
            )
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"1"'
        assert counts(api) == (1, 1, 1, 1)


@pytest.mark.parametrize("action", ["submit-for-homologation", "barcodes"])
@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_final_effect_rolls_back_all_state(
    action: str, component: type[Any], method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced failure")

    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context, permissions=api.resolver.context.permissions | {PRODUCT_ACTIVATE}
        )
        headers = {**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())}
        body = {"barcode_type": "INTERNAL", "barcode": "BC-1"} if action == "barcodes" else None
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced failure"):
                api.client.post(f"{path}/{action}?{query}", json=body, headers=headers)
        assert counts(api) == (1, 1, 1, 1)
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"1"'
        assert api.client.get(f"{path}/barcodes?{query}", headers=api.headers).json()["data"] == []
        assert api.client.post(
            f"{path}/{action}?{query}", json=body, headers=headers
        ).status_code in (200, 201)


def test_non_unique_database_failure_is_not_mislabeled_as_barcode_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise IntegrityError("test", None, Exception("foreign key error"))

    with product_api() as api:
        path, query = create_for_update(api).split("?")
        monkeypatch.setattr(ProductRepository, "save", fail)
        with pytest.raises(IntegrityError):
            api.client.post(
                f"{path}/barcodes?{query}",
                json={"barcode_type": "INTERNAL", "barcode": "BC-1"},
                headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())},
            )
        assert counts(api) == (1, 1, 1, 1)


def test_lifecycle_and_barcode_compete_for_one_aggregate_version() -> None:
    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context, permissions=api.resolver.context.permissions | {PRODUCT_ACTIVATE}
        )

        def call(action: str) -> int:
            return api.client.post(
                f"{path}/{action}?{query}",
                json={"barcode_type": "INTERNAL", "barcode": "BC-1"}
                if action == "barcodes"
                else None,
                headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(call, ("barcodes", "submit-for-homologation")))
        assert 409 in results
        assert any(status in (200, 201) for status in results)
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"2"'
        assert counts(api) == (1, 2, 2, 2)
