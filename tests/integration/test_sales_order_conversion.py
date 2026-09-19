"""Transactional and idempotent Quote-to-Order conversion proofs."""

from uuid import UUID, uuid4

import pytest

from erp.modules.sales.application import CommandMetadata, ConvertQuoteToOrder
from erp.modules.sales.infrastructure import PostgresSalesOrderConversion
from tests.integration.test_sales_quote_api import sales_api

pytestmark = pytest.mark.integration


def test_conversion_freezes_quote_and_replays_same_order() -> None:
    with sales_api() as api:
        created = api.client.post(
            "/api/v1/sales/quotes",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "number": "Q-CONVERT",
                "customer_id": api.customer_id,
            },
        ).json()
        quote_id = created["id"]
        revised = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/revisions",
            headers={**api.headers, "If-Match": '"1"'},
            json={
                "company_id": str(api.data.company_id),
                "lines": [
                    {
                        "product_id": api.product_id,
                        "quantity": "3.250000",
                        "unit_price": "20.00",
                        "discount_amount": "5.00",
                    }
                ],
            },
        )
        assert revised.status_code == 200
        sent = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/send",
            headers={**api.headers, "If-Match": '"2"'},
            json={"company_id": str(api.data.company_id)},
        )
        assert sent.status_code == 200
        accepted = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/accept",
            headers={**api.headers, "If-Match": '"3"'},
            json={"company_id": str(api.data.company_id)},
        )
        assert accepted.status_code == 200

        request_id = uuid4()
        command = ConvertQuoteToOrder(
            company_id=api.data.company_id,
            quote_id=UUID(quote_id),
            order_number="SO-CONVERT-001",
            expected_version=4,
            idempotency_key="convert-key-001",
            metadata=CommandMetadata(request_id, request_id, "127.0.0.1"),
        )

        async def convert() -> object:
            return await PostgresSalesOrderConversion(
                api.data.database, ttl_seconds=86_400
            ).convert(command, api.data.actor_id)

        assert api.client.portal is not None
        first = api.client.portal.call(convert)
        replay = api.client.portal.call(convert)
        assert first.order.id == replay.order.id
        assert first.order.items[0].quantity.as_tuple().exponent == -6
        assert first.order.net_amount.as_tuple().exponent == -2
        assert first.quote_version == 5
        assert first.idempotency_replayed is False
        assert replay.idempotency_replayed is True

        quote = api.client.get(
            f"/api/v1/sales/quotes/{quote_id}?company_id={api.data.company_id}",
            headers=api.headers,
        ).json()["quote"]
        assert quote["status"] == "CONVERTED"
        assert quote["converted_order_id"] == str(first.order.id)


def test_official_conversion_and_order_query_apis() -> None:
    with sales_api() as api:
        created = api.client.post(
            "/api/v1/sales/quotes",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "number": "Q-API-CONVERT",
                "customer_id": api.customer_id,
            },
        ).json()
        quote_id = created["id"]
        assert api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/revisions",
            headers={**api.headers, "If-Match": '"1"'},
            json={
                "company_id": str(api.data.company_id),
                "lines": [
                    {
                        "product_id": api.product_id,
                        "quantity": "1.000000",
                        "unit_price": "50.00",
                        "discount_amount": "0.00",
                    }
                ],
            },
        ).status_code == 200
        assert api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/send",
            headers={**api.headers, "If-Match": '"2"'},
            json={"company_id": str(api.data.company_id)},
        ).status_code == 200
        assert api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/accept",
            headers={**api.headers, "If-Match": '"3"'},
            json={"company_id": str(api.data.company_id)},
        ).status_code == 200

        url = f"/api/v1/sales/quotes/{quote_id}/convert-to-order"
        headers = {
            **api.headers,
            "If-Match": '"4"',
            "Idempotency-Key": "api-convert-key",
        }
        converted = api.client.post(
            url,
            headers=headers,
            json={
                "company_id": str(api.data.company_id),
                "order_number": "SO-API-001",
            },
        )
        assert converted.status_code == 201
        assert converted.headers["etag"] == '"1"'
        assert converted.headers["idempotency-replayed"] == "false"
        order_id = converted.json()["order"]["id"]

        replay = api.client.post(
            url,
            headers=headers,
            json={
                "company_id": str(api.data.company_id),
                "order_number": "SO-API-001",
            },
        )
        assert replay.status_code == 201
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["order"]["id"] == order_id

        listed = api.client.get(
            f"/api/v1/sales/orders?company_id={api.data.company_id}", headers=api.headers
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["data"]] == [order_id]
        detail = api.client.get(
            f"/api/v1/sales/orders/{order_id}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.json()["source_quote_id"] == quote_id

        foreign = api.client.get(
            f"/api/v1/sales/orders?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert foreign.status_code == 404
