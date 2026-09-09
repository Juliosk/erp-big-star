"""Fail-closed structural parsing with bounded ZIP/XML and cell expansion."""

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from erp.modules.governance.domain import ImportTemplateVersion
from erp.modules.governance.domain.import_job import MAX_SOURCE_BYTES
from erp.platform.errors import ApplicationError

MAX_ROWS = 1000
MAX_EXPANDED_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ParsedRow:
    number: int
    values: dict[str, str]
    errors: tuple[str, ...] = ()


def invalid_file(message: str) -> ApplicationError:
    return ApplicationError(code="IMPORT_INVALID_FILE", message=message, status_code=422)


def _inspect_archive(content: bytes, columns: int) -> None:
    if not 1 <= len(content) <= MAX_SOURCE_BYTES:
        raise invalid_file("XLSX must contain 1 byte to 10 MiB.")
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (
            len(entries) > 200
            or len(set(names)) != len(names)
            or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES
            or "xl/workbook.xml" not in names
        ):
            raise invalid_file("Invalid or oversized XLSX package.")
        for entry in entries:
            name = entry.orig_filename.lower()
            if (
                ".." in PurePosixPath(name).parts
                or name.startswith("/")
                or "\\" in name
                or entry.flag_bits & 1
                or any(part in name for part in ("vbaproject", "externallinks/", "embeddings/"))
                or entry.file_size > max(entry.compress_size, 1) * 1000
            ):
                raise invalid_file("Encrypted, external or unsafe XLSX content is forbidden.")
            if name.endswith((".xml", ".rels")):
                root = fromstring(archive.read(entry), forbid_dtd=True)
                for element in root.iter():
                    tag = str(element.tag).rsplit("}", 1)[-1]
                    if name.startswith("xl/worksheets/") and tag == "c":
                        coordinate = re.fullmatch(
                            r"([A-Z]{1,3})([1-9][0-9]{0,6})", element.attrib.get("r", "")
                        )
                        if (
                            coordinate is None
                            or int(coordinate[2]) > MAX_ROWS + 1
                            or column_index_from_string(coordinate[1]) > columns
                        ):
                            raise invalid_file("Cell coordinates exceed the template bounds.")
                    if (
                        element.attrib.get("TargetMode") == "External"
                        or tag in {"f", "definedName", "oleObject"}
                        or "macroEnabled" in element.attrib.get("ContentType", "")
                    ):
                        raise invalid_file(
                            "Formulas, named expressions and external links are forbidden."
                        )


def parse_xlsx(content: bytes, version: ImportTemplateVersion) -> tuple[ParsedRow, ...]:
    try:
        _inspect_archive(content, len(version.fields))
        return _read_cells(content, version)
    except (BadZipFile, DefusedXmlException, KeyError, ValueError, OSError, ParseError) as error:
        raise invalid_file("The source is not a supported, safe XLSX workbook.") from error


def _read_cells(content: bytes, version: ImportTemplateVersion) -> tuple[ParsedRow, ...]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    try:
        if "Produtos" not in workbook.sheetnames or set(workbook.sheetnames) - {
            "Produtos",
            "Instrucoes",
        }:
            raise invalid_file("Use the Produtos sheet from the official template.")
        sheet = workbook["Produtos"]
        fields = [field.name for field in version.fields]
        if (sheet.max_column or 0) > len(fields) or (sheet.max_row or 0) > MAX_ROWS + 1:
            raise invalid_file("Worksheet exceeds the template columns or 1,000 row limit.")
        # Ignore untrusted dimension hints. Explicit bounds also cover understated dimensions.
        rows = sheet.iter_rows(min_row=1, max_row=MAX_ROWS + 2, max_col=len(fields) + 1)
        header = next(rows)
        if [cell.value for cell in header] != [*fields, None]:
            raise invalid_file("Headers must exactly match the selected template version.")
        result: list[ParsedRow] = []
        for number, cells in enumerate(rows, 2):
            if all(cell.value is None for cell in cells):
                continue
            values: dict[str, str] = {}
            errors = []
            for field, cell in zip(fields, cells[:-1], strict=True):
                value = cell.value
                if value is None:
                    values[field] = ""
                elif not isinstance(value, str) or cell.data_type != "s" or len(value) > 1000:
                    values[field] = ""
                    errors.append(f"{field}: use plain text up to 1000 characters.")
                else:
                    values[field] = value.strip()
            result.append(ParsedRow(number, values, tuple(errors)))
        if not result:
            raise invalid_file("The workbook contains no product rows.")
        return tuple(result)
    finally:
        workbook.close()


__all__ = ["MAX_ROWS", "ParsedRow", "parse_xlsx"]
