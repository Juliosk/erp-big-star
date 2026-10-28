"""OFX and CSV statement adapters normalize bank data without leaking I/O to domain."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from erp.modules.finance.domain import (
    BankMovementDirection,
    BankStatementSource,
    BankTransactionKind,
    InvalidBankStatementError,
)
from erp.modules.finance.infrastructure import (
    BankStatementImportContext,
    BankStatementParserRegistry,
    CsvStatementLayout,
    CsvStatementParser,
    OfxStatementParser,
)


def _context(*, with_bank: bool = True) -> BankStatementImportContext:
    return BankStatementImportContext(
        statement_id=uuid4(),
        company_id=uuid4(),
        bank_account_id=uuid4(),
        imported_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
        bank_code="001" if with_bank else None,
        account_reference="****1234" if with_bank else None,
    )


def _ofx(*, include_account: bool = True) -> bytes:
    account = "<BANKID>341<ACCTID>12345-6" if include_account else ""
    return f"""OFXHEADER:100
DATA:OFXSGML

<OFX>
<STMTRS>{account}
<BANKTRANLIST><DTSTART>20261027000000<DTEND>20261028235959
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261027120000<TRNAMT>-100.00
<FITID>OFX-180-1<CHECKNUM>NF-123<MEMO>Pagamento fornecedor</STMTTRN>
<STMTTRN><TRNTYPE>FEE<DTPOSTED>20261028120000<TRNAMT>-12.50
<FITID>OFX-180-2<MEMO>Tarifa bancaria</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>887.50</LEDGERBAL></STMTRS></OFX>""".encode()


def test_ofx_sgml_parser_normalizes_transactions_and_metadata() -> None:
    statement = OfxStatementParser().parse(_ofx(), context=_context(with_bank=False))

    assert statement.source is BankStatementSource.OFX
    assert statement.bank_code == "341"
    assert statement.account_reference == "12345-6"
    assert statement.period_start.isoformat() == "2026-10-27"
    assert statement.period_end.isoformat() == "2026-10-28"
    assert statement.closing_balance == Decimal("887.50")
    assert len(statement.source_hash) == 64
    assert statement.movements[0].direction is BankMovementDirection.DEBIT
    assert statement.movements[0].kind is BankTransactionKind.PAYMENT
    assert statement.movements[0].document_number == "NF-123"
    assert statement.movements[1].kind is BankTransactionKind.BANK_FEE


def test_ofx_parser_uses_context_fallback_and_transaction_dates() -> None:
    content = b"""<OFX><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20261028</DTPOSTED>
<TRNAMT>25.00</TRNAMT><FITID>CREDIT-1</FITID><NAME>PIX recebido</NAME></STMTTRN>
</BANKTRANLIST></OFX>"""
    statement = OfxStatementParser().parse(content, context=_context())
    assert statement.period_start == statement.period_end
    assert statement.movements[0].direction is BankMovementDirection.CREDIT
    assert statement.movements[0].kind is BankTransactionKind.RECEIPT


@pytest.mark.parametrize(
    "content",
    [
        b"not ofx",
        b"<!DOCTYPE OFX><OFX></OFX>",
        b"<OFX></OFX>",
        b"<OFX><STMTTRN><DTPOSTED>bad<TRNAMT>-1<FITID>x</STMTTRN></OFX>",
        b"<OFX><STMTTRN><DTPOSTED>20261028<TRNAMT>bad<FITID>x</STMTTRN></OFX>",
    ],
)
def test_ofx_parser_fails_closed_for_malformed_content(content: bytes) -> None:
    with pytest.raises(InvalidBankStatementError):
        OfxStatementParser().parse(content, context=_context())


def test_ofx_requires_account_identity_when_file_and_context_omit_it() -> None:
    with pytest.raises(InvalidBankStatementError, match="bank and account"):
        OfxStatementParser().parse(_ofx(include_account=False), context=_context(with_bank=False))


def test_csv_parser_autodetects_brazilian_and_english_bank_layouts() -> None:
    br = (
        b"Data;Valor;Descricao;Documento;Identificador;Natureza\n"
        b"27/10/2026;-1.234,56;Pagamento fornecedor;NF-180;CSV-1;D\n"
        b"28/10/2026;15,50;Rendimento conta;;CSV-2;C\n"
    )
    statement = CsvStatementParser().parse(br, context=_context())
    assert statement.source is BankStatementSource.CSV
    assert statement.movements[0].amount == Decimal("1234.56")
    assert statement.movements[0].direction is BankMovementDirection.DEBIT
    assert statement.movements[1].kind is BankTransactionKind.INTEREST

    english = b"date,amount,description,document\n2026-10-28,100.00,Customer receipt,DOC-1\n"
    parsed = CsvStatementParser().parse(english, context=_context())
    assert parsed.movements[0].direction is BankMovementDirection.CREDIT
    assert len(parsed.movements[0].external_id) == 64


def test_csv_layout_supports_custom_columns_encoding_and_date_format() -> None:
    layout = CsvStatementLayout(
        delimiter="|",
        encoding="cp1252",
        date_format="%d.%m.%Y",
        date_column="Quando",
        amount_column="Montante",
        description_column="Histórico Livre",
        external_id_column="Chave",
        direction_column="DC",
    )
    content = "Quando|Montante|Histórico Livre|Chave|DC\n28.10.2026|10,00|Crédito|X-1|C\n".encode(
        "cp1252"
    )
    statement = CsvStatementParser(layout).parse(content, context=_context())
    assert statement.movements[0].external_id == "X-1"
    assert statement.movements[0].kind is BankTransactionKind.RECEIPT


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"only-one-column\nvalue\n",
        b"date,description\n2026-10-28,Missing amount\n",
        b"date,amount,description\nbad,10.00,Invalid date\n",
        b"date,amount,description\n2026-10-28,zero,Invalid amount\n",
        b"date,amount,description\n2026-10-28,0.00,Zero amount\n",
        b"date,amount,description\n2026-10-28,10.00,\n",
    ],
)
def test_csv_parser_rejects_invalid_or_incomplete_statements(content: bytes) -> None:
    with pytest.raises(InvalidBankStatementError):
        CsvStatementParser().parse(content, context=_context())


def test_csv_requires_account_metadata_and_configured_columns() -> None:
    content = b"date,amount,description\n2026-10-28,10.00,Receipt\n"
    with pytest.raises(InvalidBankStatementError, match="account metadata"):
        CsvStatementParser().parse(content, context=_context(with_bank=False))
    with pytest.raises(InvalidBankStatementError, match="Configured CSV column"):
        CsvStatementParser(CsvStatementLayout(date_column="missing")).parse(
            content,
            context=_context(),
        )


def test_parser_registry_dispatches_supported_formats_and_rejects_unknown_values() -> None:
    registry = BankStatementParserRegistry()
    assert (
        registry.parse(BankStatementSource.OFX, _ofx(), context=_context()).source
        is BankStatementSource.OFX
    )
    csv_content = b"date,amount,description\n2026-10-28,10.00,Receipt\n"
    assert (
        registry.parse(BankStatementSource.CSV, csv_content, context=_context()).source
        is BankStatementSource.CSV
    )
    with pytest.raises(InvalidBankStatementError, match="Unsupported"):
        registry.parse(cast(BankStatementSource, "PDF"), csv_content, context=_context())
