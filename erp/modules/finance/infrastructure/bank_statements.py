"""Bank-neutral OFX/CSV adapters that normalize external statements into M12."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    BankStatement,
    BankStatementSource,
    BankTransactionKind,
    InvalidBankStatementError,
)

_MAX_STATEMENT_BYTES = 10 * 1024 * 1024
_OFX_TAG = re.compile(r"<(?P<tag>[A-Z0-9_]+)(?:\s[^>]*)?>(?P<value>[^<\r\n]+)", re.I)
_OFX_TRANSACTION = re.compile(
    r"<STMTTRN(?:\s[^>]*)?>(.*?)(?=</STMTTRN\s*>|<STMTTRN(?:\s|>)|</BANKTRANLIST|</OFX>)",
    re.I | re.S,
)


@dataclass(frozen=True, slots=True)
class BankStatementImportContext:
    """Trusted tenant and account metadata supplied by the application boundary."""

    statement_id: UUID
    company_id: UUID
    bank_account_id: UUID
    imported_at: datetime
    bank_code: str | None = None
    account_reference: str | None = None


@dataclass(frozen=True, slots=True)
class CsvStatementLayout:
    delimiter: str | None = None
    encoding: str | None = None
    date_format: str | None = None
    date_column: str | None = None
    amount_column: str | None = None
    description_column: str | None = None
    document_column: str | None = None
    external_id_column: str | None = None
    direction_column: str | None = None


class OfxStatementParser:
    """Parse OFX 1.x SGML and OFX 2.x XML without evaluating external entities."""

    def parse(self, content: bytes, *, context: BankStatementImportContext) -> BankStatement:
        text = _decode(content)
        upper = text.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise InvalidBankStatementError("OFX DTD and entity declarations are forbidden.")
        ofx_start = upper.find("<OFX")
        if ofx_start < 0:
            raise InvalidBankStatementError("OFX root element was not found.")
        body = text[ofx_start:]
        blocks = _OFX_TRANSACTION.findall(body)
        if not blocks:
            raise InvalidBankStatementError("OFX statement does not contain transactions.")
        movements = tuple(
            _ofx_movement(block, context=context, index=index)
            for index, block in enumerate(blocks, start=1)
        )
        start = _optional_ofx_date(_ofx_value(body, "DTSTART")) or min(
            movement.booked_on for movement in movements
        )
        end = _optional_ofx_date(_ofx_value(body, "DTEND")) or max(
            movement.booked_on for movement in movements
        )
        bank_code = _ofx_value(body, "BANKID") or context.bank_code
        account_reference = _ofx_value(body, "ACCTID") or context.account_reference
        if bank_code is None or account_reference is None:
            raise InvalidBankStatementError("OFX requires bank and account identification.")
        closing = _optional_decimal(_ofx_value(body, "BALAMT"))
        return BankStatement(
            id=context.statement_id,
            company_id=context.company_id,
            bank_account_id=context.bank_account_id,
            bank_code=bank_code,
            account_reference=account_reference,
            period_start=start,
            period_end=end,
            imported_at=context.imported_at,
            source=BankStatementSource.OFX,
            source_hash=_source_hash(content),
            movements=movements,
            closing_balance=closing,
        )


class CsvStatementParser:
    """Parse configurable or auto-detected CSV layouts used by multiple banks."""

    def __init__(self, layout: CsvStatementLayout | None = None) -> None:
        self._layout = layout or CsvStatementLayout()

    def parse(self, content: bytes, *, context: BankStatementImportContext) -> BankStatement:
        text = _decode(content, encoding=self._layout.encoding)
        delimiter = self._layout.delimiter or _detect_delimiter(text)
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if reader.fieldnames is None:
            raise InvalidBankStatementError("CSV statement requires a header row.")
        columns = {_header(name): name for name in reader.fieldnames if name is not None}
        date_column = _column(columns, self._layout.date_column, _DATE_COLUMNS, "date")
        amount_column = _column(columns, self._layout.amount_column, _AMOUNT_COLUMNS, "amount")
        description_column = _column(
            columns,
            self._layout.description_column,
            _DESCRIPTION_COLUMNS,
            "description",
        )
        document_column = _optional_column(
            columns,
            self._layout.document_column,
            _DOCUMENT_COLUMNS,
        )
        external_id_column = _optional_column(
            columns,
            self._layout.external_id_column,
            _EXTERNAL_ID_COLUMNS,
        )
        direction_column = _optional_column(
            columns,
            self._layout.direction_column,
            _DIRECTION_COLUMNS,
        )
        movements = tuple(
            _csv_movement(
                row,
                context=context,
                index=index,
                date_column=date_column,
                amount_column=amount_column,
                description_column=description_column,
                document_column=document_column,
                external_id_column=external_id_column,
                direction_column=direction_column,
                date_format=self._layout.date_format,
            )
            for index, row in enumerate(reader, start=1)
            if any(value and value.strip() for value in row.values() if value is not None)
        )
        if not movements:
            raise InvalidBankStatementError("CSV statement does not contain transactions.")
        if context.bank_code is None or context.account_reference is None:
            raise InvalidBankStatementError("CSV imports require bank and account metadata.")
        return BankStatement(
            id=context.statement_id,
            company_id=context.company_id,
            bank_account_id=context.bank_account_id,
            bank_code=context.bank_code,
            account_reference=context.account_reference,
            period_start=min(movement.booked_on for movement in movements),
            period_end=max(movement.booked_on for movement in movements),
            imported_at=context.imported_at,
            source=BankStatementSource.CSV,
            source_hash=_source_hash(content),
            movements=movements,
        )


@dataclass(frozen=True, slots=True)
class BankStatementParserRegistry:
    ofx: OfxStatementParser = field(default_factory=OfxStatementParser)
    csv: CsvStatementParser = field(default_factory=CsvStatementParser)

    def parse(
        self,
        source: BankStatementSource,
        content: bytes,
        *,
        context: BankStatementImportContext,
    ) -> BankStatement:
        if source is BankStatementSource.OFX:
            return self.ofx.parse(content, context=context)
        if source is BankStatementSource.CSV:
            return self.csv.parse(content, context=context)
        raise InvalidBankStatementError("Unsupported bank statement format.")


_DATE_COLUMNS = ("data", "date", "data_lancamento", "data_movimento", "posted_on")
_AMOUNT_COLUMNS = ("valor", "amount", "valor_lancamento", "transaction_amount")
_DESCRIPTION_COLUMNS = ("descricao", "historico", "memo", "description", "narrative")
_DOCUMENT_COLUMNS = ("documento", "numero_documento", "document", "checknum", "refnum")
_EXTERNAL_ID_COLUMNS = ("id", "fitid", "identificador", "transaction_id", "external_id")
_DIRECTION_COLUMNS = ("tipo", "natureza", "direction", "credito_debito", "debito_credito")


def _ofx_movement(
    block: str,
    *,
    context: BankStatementImportContext,
    index: int,
) -> BankMovement:
    amount = _required_decimal(_ofx_value(block, "TRNAMT"), "TRNAMT")
    external_id = _ofx_value(block, "FITID") or f"OFX-{index}"
    transaction_type = (_ofx_value(block, "TRNTYPE") or "OTHER").upper()
    document = _ofx_value(block, "CHECKNUM") or _ofx_value(block, "REFNUM")
    description = _ofx_value(block, "MEMO") or _ofx_value(block, "NAME") or transaction_type
    direction = BankMovementDirection.CREDIT if amount > 0 else BankMovementDirection.DEBIT
    return BankMovement(
        id=uuid5(context.statement_id, external_id),
        company_id=context.company_id,
        bank_account_id=context.bank_account_id,
        external_id=external_id,
        booked_on=_required_ofx_date(_ofx_value(block, "DTPOSTED")),
        amount=abs(amount).quantize(Decimal("0.01")),
        direction=direction,
        kind=_ofx_kind(transaction_type, direction),
        description=description,
        document_number=document,
    )


def _csv_movement(
    row: dict[str, str | None],
    *,
    context: BankStatementImportContext,
    index: int,
    date_column: str,
    amount_column: str,
    description_column: str,
    document_column: str | None,
    external_id_column: str | None,
    direction_column: str | None,
    date_format: str | None,
) -> BankMovement:
    amount = _required_decimal(row.get(amount_column), amount_column)
    direction_value = row.get(direction_column) if direction_column is not None else None
    direction = _csv_direction(amount, direction_value)
    document = _clean(row.get(document_column)) if document_column is not None else None
    external_id = _clean(row.get(external_id_column)) if external_id_column is not None else None
    description = _clean(row.get(description_column))
    if description is None:
        raise InvalidBankStatementError("CSV description cannot be blank.")
    if external_id is None:
        fingerprint = "|".join(
            f"{key}={row.get(key) or ''}" for key in sorted(row) if key is not None
        )
        external_id = hashlib.sha256(f"{index}|{fingerprint}".encode()).hexdigest()
    return BankMovement(
        id=uuid5(context.statement_id, external_id),
        company_id=context.company_id,
        bank_account_id=context.bank_account_id,
        external_id=external_id,
        booked_on=_csv_date(row.get(date_column), date_format=date_format),
        amount=abs(amount).quantize(Decimal("0.01")),
        direction=direction,
        kind=_csv_kind(description, direction),
        description=description,
        document_number=document,
    )


def _decode(content: bytes, *, encoding: str | None = None) -> str:
    if not isinstance(content, bytes) or not content:
        raise InvalidBankStatementError("Bank statement content cannot be empty.")
    if len(content) > _MAX_STATEMENT_BYTES:
        raise InvalidBankStatementError("Bank statement exceeds the 10 MiB safety limit.")
    encodings = (encoding,) if encoding is not None else ("utf-8-sig", "cp1252")
    for candidate in encodings:
        assert candidate is not None
        try:
            return content.decode(candidate)
        except LookupError, UnicodeDecodeError:
            continue
    raise InvalidBankStatementError("Bank statement encoding is unsupported.")


def _ofx_value(text: str, tag: str) -> str | None:
    for match in _OFX_TAG.finditer(text):
        if match.group("tag").upper() == tag:
            return _clean(match.group("value"))
    return None


def _required_ofx_date(value: str | None) -> date:
    parsed = _optional_ofx_date(value)
    if parsed is None:
        raise InvalidBankStatementError("OFX transaction requires DTPOSTED in YYYYMMDD format.")
    return parsed


def _optional_ofx_date(value: str | None) -> date | None:
    if value is None:
        return None
    digits = "".join(character for character in value[:8] if character.isdigit())
    if len(digits) != 8:
        raise InvalidBankStatementError("OFX date must start with YYYYMMDD.")
    try:
        return date.fromisoformat(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}")
    except ValueError as error:
        raise InvalidBankStatementError("OFX date is invalid.") from error


def _csv_date(value: str | None, *, date_format: str | None) -> date:
    normalized = _clean(value)
    if normalized is None:
        raise InvalidBankStatementError("CSV transaction requires a date.")
    formats = (
        (date_format,)
        if date_format is not None
        else (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y%m%d",
        )
    )
    for format_value in formats:
        assert format_value is not None
        try:
            return datetime.strptime(normalized, format_value).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    raise InvalidBankStatementError("CSV date does not match a supported format.")


def _required_decimal(value: str | None, field: str) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None or parsed == 0:
        raise InvalidBankStatementError(f"{field} must contain a non-zero monetary value.")
    return parsed


def _optional_decimal(value: str | None) -> Decimal | None:
    normalized = _clean(value)
    if normalized is None:
        return None
    negative = normalized.startswith("(") and normalized.endswith(")")
    normalized = normalized.strip("()").replace("R$", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as error:
        raise InvalidBankStatementError("Bank amount is invalid.") from error
    if not parsed.is_finite():
        raise InvalidBankStatementError("Bank amount must be finite.")
    return -parsed if negative else parsed


def _ofx_kind(transaction_type: str, direction: BankMovementDirection) -> BankTransactionKind:
    if transaction_type in {"FEE", "SRVCHG"}:
        return BankTransactionKind.BANK_FEE
    if transaction_type in {"INT", "DIV"}:
        return BankTransactionKind.INTEREST
    if transaction_type in {"CHECK", "PAYMENT", "DEBIT"}:
        return BankTransactionKind.PAYMENT
    if transaction_type in {"DEP", "DIRECTDEP", "CREDIT"}:
        return BankTransactionKind.RECEIPT
    if transaction_type in {"XFER", "DIRECTDEBIT", "DIRECTDEPOSIT"}:
        return BankTransactionKind.TRANSFER
    return (
        BankTransactionKind.RECEIPT
        if direction is BankMovementDirection.CREDIT
        else BankTransactionKind.OTHER
    )


def _csv_kind(description: str, direction: BankMovementDirection) -> BankTransactionKind:
    normalized = _header(description)
    if any(term in normalized for term in ("tarifa", "fee", "cesta", "taxa_bancaria")):
        return BankTransactionKind.BANK_FEE
    if any(term in normalized for term in ("juros", "rendimento", "interest")):
        return BankTransactionKind.INTEREST
    if any(term in normalized for term in ("imposto", "tributo", "tax")):
        return BankTransactionKind.TAX
    return (
        BankTransactionKind.RECEIPT
        if direction is BankMovementDirection.CREDIT
        else BankTransactionKind.PAYMENT
    )


def _csv_direction(value: Decimal, raw: str | None) -> BankMovementDirection:
    normalized = _header(raw or "")
    if normalized in {"d", "debito", "debit", "saida"}:
        return BankMovementDirection.DEBIT
    if normalized in {"c", "credito", "credit", "entrada"}:
        return BankMovementDirection.CREDIT
    return BankMovementDirection.CREDIT if value > 0 else BankMovementDirection.DEBIT


def _detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
    except csv.Error as error:
        raise InvalidBankStatementError("CSV delimiter could not be detected.") from error


def _column(
    columns: dict[str, str],
    explicit: str | None,
    aliases: tuple[str, ...],
    field: str,
) -> str:
    result = _optional_column(columns, explicit, aliases)
    if result is None:
        raise InvalidBankStatementError(f"CSV {field} column was not found.")
    return result


def _optional_column(
    columns: dict[str, str],
    explicit: str | None,
    aliases: tuple[str, ...],
) -> str | None:
    if explicit is not None:
        result = columns.get(_header(explicit))
        if result is None:
            raise InvalidBankStatementError(f"Configured CSV column {explicit!r} was not found.")
        return result
    return next((columns[alias] for alias in aliases if alias in columns), None)


def _header(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _source_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = [
    "BankStatementImportContext",
    "BankStatementParserRegistry",
    "CsvStatementLayout",
    "CsvStatementParser",
    "OfxStatementParser",
]
