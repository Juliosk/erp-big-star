"""Deterministic payment-remittance adapters behind the M12 application port."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from erp.modules.finance.application.treasury import RemittanceArtifact
from erp.modules.finance.domain import (
    BankRemittanceFormat,
    InvalidTreasuryRuleError,
    PaymentBatch,
)


class Cnab240RemittanceAdapter:
    """Produce a canonical 240-column treasury exchange file.

    The adapter is intentionally bank-neutral. Bank-specific homologation can
    decorate or replace it without changing the application service.
    """

    def generate(self, batch: PaymentBatch, *, dry_run: bool) -> RemittanceArtifact:
        _require_format(batch, BankRemittanceFormat.CNAB_240)
        _require_brl(batch)
        lines = [_cnab_header(batch, width=240, dry_run=dry_run)]
        lines.extend(
            _cnab_detail(batch, item_index=index, width=240)
            for index, _ in enumerate(batch.items, start=1)
        )
        lines.append(_cnab_trailer(batch, width=240, record_count=len(lines) + 1))
        return _artifact(batch, lines=lines, extension="rem", dry_run=dry_run)


class Cnab400RemittanceAdapter:
    """Produce a canonical 400-column treasury exchange file."""

    def generate(self, batch: PaymentBatch, *, dry_run: bool) -> RemittanceArtifact:
        _require_format(batch, BankRemittanceFormat.CNAB_400)
        _require_brl(batch)
        lines = [_cnab_header(batch, width=400, dry_run=dry_run)]
        lines.extend(
            _cnab_detail(batch, item_index=index, width=400)
            for index, _ in enumerate(batch.items, start=1)
        )
        lines.append(_cnab_trailer(batch, width=400, record_count=len(lines) + 1))
        return _artifact(batch, lines=lines, extension="rem", dry_run=dry_run)


class PixApiRemittanceAdapter:
    """Produce a stable JSON payment instruction for a PIX gateway."""

    def generate(self, batch: PaymentBatch, *, dry_run: bool) -> RemittanceArtifact:
        _require_format(batch, BankRemittanceFormat.PIX_API)
        _require_brl(batch)
        payload = {
            "batch_id": str(batch.id),
            "company_id": str(batch.company_id),
            "code": batch.code,
            "currency": batch.currency,
            "dry_run": dry_run,
            "scheduled_date": batch.scheduled_date.isoformat(),
            "total_amount": str(batch.total_amount),
            "payments": [
                {
                    "installment_id": str(item.installment_id),
                    "payable_id": str(item.payable_id),
                    "amount": str(item.amount),
                    "bank_code": item.beneficiary.bank_code,
                    "branch": item.beneficiary.branch_number,
                    "account": item.beneficiary.account_number,
                    "account_digit": item.beneficiary.account_digit,
                    "account_type": item.beneficiary.account_type.value,
                    "holder_name": item.beneficiary.holder_name,
                    "holder_tax_id": item.beneficiary.holder_tax_id,
                }
                for item in batch.items
            ],
        }
        content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        checksum = hashlib.sha256(content).hexdigest()
        return RemittanceArtifact(
            filename=_filename(batch, "json", dry_run=dry_run),
            media_type="application/json",
            content=content,
            checksum_sha256=checksum,
            record_count=len(batch.items),
            total_amount=batch.total_amount,
            dry_run=dry_run,
        )


@dataclass(frozen=True, slots=True)
class RemittanceAdapterRegistry:
    cnab_240: Cnab240RemittanceAdapter = field(default_factory=Cnab240RemittanceAdapter)
    cnab_400: Cnab400RemittanceAdapter = field(default_factory=Cnab400RemittanceAdapter)
    pix_api: PixApiRemittanceAdapter = field(default_factory=PixApiRemittanceAdapter)

    def generate(self, batch: PaymentBatch, *, dry_run: bool) -> RemittanceArtifact:
        if batch.remittance_format is BankRemittanceFormat.CNAB_240:
            return self.cnab_240.generate(batch, dry_run=dry_run)
        if batch.remittance_format is BankRemittanceFormat.CNAB_400:
            return self.cnab_400.generate(batch, dry_run=dry_run)
        return self.pix_api.generate(batch, dry_run=dry_run)


def _cnab_header(batch: PaymentBatch, *, width: int, dry_run: bool) -> str:
    value = "".join(
        (
            "0",
            _fixed("DRYRUN" if dry_run else "REMESSA", 8),
            _fixed(batch.code, 40),
            _fixed(str(batch.company_id).replace("-", ""), 32),
            batch.scheduled_date.strftime("%Y%m%d"),
            _fixed(batch.currency, 3),
        )
    )
    return _fixed(value, width)


def _cnab_detail(batch: PaymentBatch, *, item_index: int, width: int) -> str:
    item = batch.items[item_index - 1]
    beneficiary = item.beneficiary
    value = "".join(
        (
            "3",
            str(item_index).zfill(6),
            beneficiary.bank_code,
            beneficiary.branch_number.zfill(5),
            beneficiary.account_number.zfill(20),
            _fixed(beneficiary.account_digit, 2),
            beneficiary.holder_tax_id.zfill(14),
            _fixed(beneficiary.holder_name, 40),
            _amount_cents(item.amount, 18),
            item.due_date.strftime("%Y%m%d"),
            str(item.payable_id).replace("-", ""),
            str(item.installment_id).replace("-", ""),
        )
    )
    return _fixed(value, width)


def _cnab_trailer(batch: PaymentBatch, *, width: int, record_count: int) -> str:
    value = "".join(
        (
            "9",
            str(record_count).zfill(8),
            str(len(batch.items)).zfill(8),
            _amount_cents(batch.total_amount, 18),
            _fixed(batch.code, 40),
        )
    )
    return _fixed(value, width)


def _artifact(
    batch: PaymentBatch,
    *,
    lines: list[str],
    extension: str,
    dry_run: bool,
) -> RemittanceArtifact:
    content = ("\r\n".join(lines) + "\r\n").encode("ascii")
    return RemittanceArtifact(
        filename=_filename(batch, extension, dry_run=dry_run),
        media_type="text/plain; charset=ascii",
        content=content,
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        record_count=len(lines),
        total_amount=batch.total_amount,
        dry_run=dry_run,
    )


def _filename(batch: PaymentBatch, extension: str, *, dry_run: bool) -> str:
    prefix = "DRYRUN-" if dry_run else "REMESSA-"
    safe_code = "".join(
        character for character in batch.code if character.isalnum() or character == "-"
    )
    return f"{prefix}{safe_code}.{extension}"


def _fixed(value: str, width: int) -> str:
    normalized = value.encode("ascii", errors="ignore").decode("ascii").upper()
    return normalized[:width].ljust(width)


def _amount_cents(value: Decimal, width: int) -> str:
    return str(int(value * 100)).zfill(width)


def _require_brl(batch: PaymentBatch) -> None:
    if batch.currency != "BRL":
        raise InvalidTreasuryRuleError(
            "The built-in treasury remittance adapters currently require BRL."
        )


def _require_format(batch: PaymentBatch, expected: BankRemittanceFormat) -> None:
    if batch.remittance_format is not expected:
        raise InvalidTreasuryRuleError(f"The remittance adapter requires format {expected.value}.")


__all__ = [
    "Cnab240RemittanceAdapter",
    "Cnab400RemittanceAdapter",
    "PixApiRemittanceAdapter",
    "RemittanceAdapterRegistry",
]
