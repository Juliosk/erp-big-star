"""Barcode values preserve leading zeroes; GS1 checks do not prove number ownership."""

import re
from dataclasses import dataclass
from enum import StrEnum


class BarcodeType(StrEnum):
    EAN = "EAN"
    DUN = "DUN"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True, slots=True)
class Barcode:
    barcode_type: BarcodeType
    barcode: str

    def __post_init__(self) -> None:
        if not isinstance(self.barcode_type, BarcodeType):
            raise ValueError("Unsupported barcode type.")
        if self.barcode_type is BarcodeType.INTERNAL:
            if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", self.barcode) is None:
                raise ValueError(
                    "Internal barcode must be a canonical identifier (1-64 characters)."
                )
            return
        lengths = (8, 13) if self.barcode_type is BarcodeType.EAN else (14,)
        if len(self.barcode) not in lengths or re.fullmatch(r"[0-9]+", self.barcode) is None:
            raise ValueError("EAN requires 8/13 digits; DUN requires 14 digits.")
        total = sum(
            int(digit) * (3 if index % 2 == 0 else 1)
            for index, digit in enumerate(reversed(self.barcode[:-1]))
        )
        if (10 - total % 10) % 10 != int(self.barcode[-1]):
            raise ValueError("Invalid GS1 check digit.")


__all__ = ["Barcode", "BarcodeType"]
