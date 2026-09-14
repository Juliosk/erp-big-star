"""Static shell security and opt-in development identity through the real HTTP app."""

from uuid import uuid4

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from tests.unit.modules.admin.test_dev_security import dev_settings


def test_shell_contains_no_tokens_and_has_strict_same_origin_policy() -> None:
    settings = dev_settings()
    with TestClient(create_app(settings)) as client:
        page = client.get("/ui/")
        assert page.status_code == 200
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        assert settings.dev_auth_token.get_secret_value() not in page.text
        assert client.get("/ui/app.js").status_code == 200
        assert client.get("/ui/customers.js").status_code == 200
        assert client.get("/ui/inventory.js").status_code == 200
        assert client.get("/ui/pricing.js").status_code == 200
        assert client.get("/ui/wms.js").status_code == 200
        assert client.get("/ui/styles.css").status_code == 200
        assert client.get("/api/v1/admin/session-context").status_code == 401
        result = client.get(
            "/api/v1/admin/session-context",
            headers={"Authorization": f"Bearer {settings.dev_auth_token.get_secret_value()}"},
        )
        assert result.status_code == 200
        assert result.json()["development_auth"] is True
        assert "product.product.discontinue" in result.json()["permissions"]
        assert "crm.customer.merge" in result.json()["permissions"]
        assert "inventory.adjustment.create" in result.json()["permissions"]
        assert "wms.pick.execute" in result.json()["permissions"]
        assert "wms.label.reprint" in result.json()["permissions"]
        assert result.json()["actor_id"] == str(settings.dev_auth_actor_id)
        assert settings.dev_auth_token.get_secret_value() not in result.text
        assert (
            client.get(
                f"/api/v1/products?company_id={uuid4()}",
                headers={"Authorization": "Bearer invalid"},
            ).status_code
            == 401
        )
