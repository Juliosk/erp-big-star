from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import delete

from erp.modules.governance.infrastructure.import_models import (
    ImportJobModel,
    ImportTemplateModel,
    ImportTemplateVersionModel,
)
from erp.modules.governance.infrastructure.processing_models import (
    ImportCommitBatchModel,
    ImportStagingRowModel,
    ImportValidationResultModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.import_api_support import workbook_bytes
from tests.integration.minio_support import minio_storage
from tests.integration.test_product_browser import browser_server

pytestmark = [pytest.mark.integration, pytest.mark.browser]


def test_import_wizard_chromium_minio_postgres_and_company_switch() -> None:
    with minio_storage() as storage, browser_server(import_storage=storage) as server:
        data = server.fixture.data
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                failures: list[str] = []
                page.on("pageerror", lambda error: failures.append(str(error)))
                page.goto(server.url + "/ui/")
                page.get_by_label("Token de acesso").fill(server.token)
                page.get_by_role("button", name="Conectar", exact=True).click()
                expect(page.locator("#catalog")).to_be_visible()
                page.locator("#company").select_option(str(data.company_id))
                expect(page.locator("#empty")).to_be_visible()
                page.locator("#imports-nav").click()
                page.get_by_role("button", name="Habilitar template de produtos").click()
                expect(page.locator("#import-template option")).to_have_count(1)
                with page.expect_download() as downloaded:
                    page.get_by_role("button", name="Baixar modelo XLSX").click()
                assert downloaded.value.suggested_filename == "produtos-v1.xlsx"
                page.locator("#import-file").set_input_files(
                    {
                        "name": "Importacao.xlsx",
                        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "buffer": workbook_bytes(
                            [["WEB", uuid4().hex, "Produto importado pela Web", "PA", "UN"]]
                        ),
                    }
                )
                page.get_by_role("button", name="Enviar arquivo").click()
                expect(page.locator("#import-job-status")).to_contain_text("Arquivo recebido")
                page.get_by_role("button", name="Validar arquivo").click()
                expect(page.locator("#import-job-status")).to_contain_text("Validação concluída")
                page.get_by_role("button", name="Abrir preview", exact=True).click()
                expect(page.locator("#import-job-status")).to_contain_text("Preview pronto")
                expect(page.locator("#import-preview-rows")).to_contain_text(
                    "Produto importado pela Web"
                )
                outputs = Path("test-results")
                outputs.mkdir(exist_ok=True)
                page.screenshot(path=str(outputs / "import-preview-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(outputs / "import-preview-mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.get_by_role("button", name="Confirmar preview", exact=True).click()
                page.get_by_role("button", name="Gravar todos os produtos", exact=True).click()
                expect(page.locator("#import-job-status")).to_contain_text("Importação concluída")
                page.locator("#products-nav").click()
                expect(page.locator("#product-rows")).to_contain_text("Produto importado pela Web")
                page.locator("#imports-nav").click()
                page.locator("#import-file").set_input_files(
                    {
                        "name": "Rejeitada.xlsx",
                        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "buffer": workbook_bytes([["BAD", uuid4().hex, "", "PA", "UN"]]),
                    }
                )
                page.get_by_role("button", name="Enviar arquivo", exact=True).click()
                expect(page.locator("#import-job-status")).to_contain_text("Arquivo recebido")
                page.get_by_role("button", name="Validar arquivo", exact=True).click()
                expect(page.locator("#import-job-status")).to_contain_text("Carga rejeitada")
                expect(page.get_by_role("button", name="Gravar todos os produtos")).to_have_count(0)
                with page.expect_download() as rejected:
                    page.get_by_role("button", name="Baixar inconsistências").click()
                assert rejected.value.suggested_filename == "inconsistencias.xlsx"
                page.locator("#company").select_option(str(data.other_company_id))
                expect(page.locator("#empty")).to_be_visible()
                page.locator("#imports-nav").click()
                expect(page.locator("#import-history tr")).to_have_count(0)
                expect(page.locator("#import-preview-rows tr")).to_have_count(0)
                page.get_by_role("button", name="Sair", exact=True).click()
                expect(page.locator("#imports")).to_be_hidden()
                assert page.evaluate("localStorage.length + sessionStorage.length") == 0
                assert failures == []
                browser.close()
        finally:

            async def cleanup() -> None:
                companies = (data.company_id, data.other_company_id)
                async with data.database.session() as session, session.begin():
                    for model in (
                        ImportCommitBatchModel,
                        ImportValidationResultModel,
                        ImportStagingRowModel,
                        ImportJobModel,
                        ImportTemplateVersionModel,
                        ImportTemplateModel,
                    ):
                        await session.execute(delete(model).where(model.company_id.in_(companies)))
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.module == "governance",
                            AuditEventModel.company_id.in_(companies),
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.source_module == "governance",
                            OutboxEventModel.payload["company_id"].astext.in_(
                                str(company) for company in companies
                            ),
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.in_(
                                f"governance:{company}:{data.actor_id}" for company in companies
                            )
                        )
                    )

            assert server.fixture.client.portal is not None
            server.fixture.client.portal.call(cleanup)
