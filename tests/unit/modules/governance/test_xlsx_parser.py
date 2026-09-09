from io import BytesIO
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from erp.modules.governance.domain import ImportCommitMode, ImportField, ImportTemplateVersion
from erp.modules.governance.infrastructure.xlsx_parser import parse_xlsx
from erp.platform.errors import ApplicationError


def version() -> ImportTemplateVersion:
    return ImportTemplateVersion(
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        tuple(ImportField(name, True) for name in ("code", "sku", "name", "product_type", "uom")),
        (ImportCommitMode.ALL_OR_NOTHING,),
    )


def xlsx(*, sheet_name: str = "Produtos", rows: list[list[Any]] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = sheet_name
    sheet.append([field.name for field in version().fields])
    for row in rows if rows is not None else [["A", "000123", "Name", "PA", "UN"]]:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def rewrite(content: bytes, name: str, data: bytes, *, append: bool = False) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename != name or append:
                target.writestr(item, source.read(item.filename))
        target.writestr(name, data)
    return output.getvalue().replace(name.replace("\\", "/").encode(), name.encode())


def test_parser_preserves_text_blanks_and_reports_invalid_cell_types() -> None:
    content = xlsx(
        rows=[[None, "000123", " Name ", None, "UN"], [], ["A", 123, "x" * 1001, "PA", "UN"]]
    )
    parsed = parse_xlsx(content, version())
    assert parsed[0].values["sku"] == "000123"
    assert parsed[0].values["name"] == "Name"
    assert parsed[0].values["code"] == ""
    assert parsed[1].number == 4
    assert len(parsed[1].errors) == 2


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not-a-zip",
        b"x" * (10 * 1024 * 1024 + 1),
        xlsx(sheet_name="Wrong"),
        xlsx(rows=[]),
        xlsx(rows=[["A", "SKU", "=1+1", "PA", "UN"]]),
        xlsx(rows=[["A", "SKU", "N", "PA", "UN", "extra"]]),
    ],
    ids=lambda value: f"xlsx-{len(value)}",
)
def test_rejects_invalid_workbooks(content: bytes) -> None:
    with pytest.raises(ApplicationError) as error:
        parse_xlsx(content, version())
    assert error.value.code == "IMPORT_INVALID_FILE"


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("xl/vbaProject.bin", b"macro"),
        ("../outside.txt", b"unsafe"),
        ("/outside.txt", b"unsafe"),
        ("xl\\unsafe.bin", b"unsafe"),
        ("xl/embeddings/evil.bin", b"unsafe"),
        ("xl/workbook.xml", b"<broken"),
        ("xl/workbook.xml", b'<!DOCTYPE root [<!ENTITY x "bomb">]><root>&x;</root>'),
        ("xl/links.rels", b'<Relationships><Relationship TargetMode="External"/></Relationships>'),
        ("xl/worksheets/sheet1.xml", b'<worksheet><c r="A9000"/></worksheet>'),
        ("xl/worksheets/sheet1.xml", b'<worksheet><c r="bad"/></worksheet>'),
        ("xl/workbook.xml", b"<root><definedName>x</definedName></root>"),
        ("[Content_Types].xml", b'<Types><Override ContentType="macroEnabled"/></Types>'),
    ],
)
def test_rejects_hostile_zip_xml_and_understated_dimensions(name: str, data: bytes) -> None:
    with pytest.raises(ApplicationError):
        parse_xlsx(rewrite(xlsx(), name, data), version())


def test_rejects_duplicate_members_missing_workbook_expansion_and_member_count() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = rewrite(xlsx(), "xl/workbook.xml", b"<root/>", append=True)
    for content in (duplicate, rewrite(xlsx(), "padding.bin", b"x" * (33 * 1024 * 1024))):
        with pytest.raises(ApplicationError):
            parse_xlsx(content, version())
    for count in (1, 201):
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            for number in range(count):
                archive.writestr(str(number), b"x")
        with pytest.raises(ApplicationError):
            parse_xlsx(output.getvalue(), version())


def test_rejects_wrong_header_and_overstated_dimensions_but_allows_inert_members() -> None:
    content = xlsx()
    with ZipFile(BytesIO(content)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml")
    for altered in (sheet.replace(b">code<", b">wrong<"), sheet.replace(b"A1:E2", b"A1:XFD9000")):
        with pytest.raises(ApplicationError):
            parse_xlsx(rewrite(content, "xl/worksheets/sheet1.xml", altered), version())
    assert (
        parse_xlsx(rewrite(content, "inert.bin", b"inert"), version())[0].values["sku"] == "000123"
    )
