from io import BytesIO
from uuid import uuid4

from openpyxl import load_workbook

from erp.modules.governance.domain import ImportCommitMode, ImportField, ImportTemplateVersion
from erp.modules.governance.infrastructure.xlsx_template import template_xlsx


def test_versioned_template_is_text_formatted_and_has_no_example_product() -> None:
    version = ImportTemplateVersion(
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        tuple(ImportField(name, True) for name in ("code", "sku", "name", "product_type", "uom")),
        (ImportCommitMode.ALL_OR_NOTHING,),
    )
    workbook = load_workbook(BytesIO(template_xlsx(version)))
    try:
        assert workbook.sheetnames == ["Produtos", "Instrucoes"]
        sheet = workbook["Produtos"]
        assert [cell.value for cell in sheet[1]] == [field.name for field in version.fields]
        assert sheet["B2"].value is None
        assert sheet["B1001"].number_format == "@"
        assert sheet.freeze_panes == "A2"
        assert version.fingerprint in str(workbook["Instrucoes"]["A3"].value)
    finally:
        workbook.close()
