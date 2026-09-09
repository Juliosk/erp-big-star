"""Runtime XLSX codec for the versioned import API, not an analysis workbook."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from erp.modules.governance.domain import ImportTemplateVersion


def template_xlsx(version: ImportTemplateVersion) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Produtos"
    sheet.freeze_panes = "A2"
    for index, field in enumerate(version.fields, 1):
        cell = sheet.cell(1, index, field.name)
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="192C4F")
        column = sheet.column_dimensions[get_column_letter(index)]
        column.width = 48 if field.name == "name" else 22
        column.number_format = "@"
        # Excel retains leading zeroes when entering identifiers in this bounded template.
        for row in range(2, 1002):
            sheet.cell(row, index).number_format = "@"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(version.fields))}1001"
    instructions = workbook.create_sheet("Instrucoes")
    for line in (
        "Importação de produtos por SKU — ALL_OR_NOTHING",
        f"Template {version.template_id} / versão {version.number}",
        f"Fingerprint: {version.fingerprint}",
        "Preencha somente Produtos. Limite: 1.000 linhas, 10 MiB. Não use fórmulas.",
        "SKU é texto. Preserve zeros iniciais. Não repita SKU ou código no arquivo.",
        "Criação: code, sku, name, product_type e uom obrigatórios.",
        "Atualização: SKU existente na empresa; apenas name/uom. Code e tipo não mudam.",
        "Uma linha inválida bloqueia todo o catálogo. Confirme os valores no preview.",
    ):
        instructions.append([line])
    instructions.column_dimensions["A"].width = 110
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


__all__ = ["template_xlsx"]
