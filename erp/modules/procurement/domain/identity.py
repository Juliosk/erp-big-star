"""Supplier fiscal identity value object."""

import re
from dataclasses import dataclass
from enum import StrEnum

from erp.modules.procurement.domain.exceptions import InvalidSupplierIdentityError


class SupplierIdentityKind(StrEnum):
    CPF = "CPF"
    CNPJ = "CNPJ"
    FOREIGN_REGISTRATION = "FOREIGN_REGISTRATION"


@dataclass(frozen=True, order=True, slots=True)
class SupplierTaxIdentity:
    kind: SupplierIdentityKind
    value: str
    country_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SupplierIdentityKind):
            raise InvalidSupplierIdentityError("identity kind is not supported by M6.")
        country_code = self.country_code.strip().upper()
        if re.fullmatch(r"[A-Z]{2}", country_code) is None:
            raise InvalidSupplierIdentityError("country_code must use ISO alpha-2 format.")
        if self.kind in {SupplierIdentityKind.CPF, SupplierIdentityKind.CNPJ}:
            if country_code != "BR":
                raise InvalidSupplierIdentityError("CPF/CNPJ suppliers must use country BR.")
            if any(
                character not in "0123456789./-" and not character.isspace()
                for character in self.value
            ):
                raise InvalidSupplierIdentityError("identity value must be a valid CPF/CNPJ.")
            normalized = "".join(character for character in self.value if character.isdigit())
            valid = (
                _is_valid_cpf(normalized)
                if self.kind is SupplierIdentityKind.CPF
                else _is_valid_cnpj(normalized)
            )
            if not valid:
                raise InvalidSupplierIdentityError("identity value must be a valid CPF/CNPJ.")
        else:
            if country_code == "BR":
                raise InvalidSupplierIdentityError(
                    "foreign registration requires a country other than BR."
                )
            normalized = self.value.strip().upper()
            if re.fullmatch(r"[A-Z0-9][A-Z0-9 ._/-]{1,59}", normalized) is None:
                raise InvalidSupplierIdentityError(
                    "foreign registration must contain 2 to 60 safe characters."
                )
        object.__setattr__(self, "value", normalized)
        object.__setattr__(self, "country_code", country_code)

    @property
    def reference(self) -> str:
        return f"{self.kind}:{self.country_code}:***{self.value[-4:]}"


def _is_valid_cpf(value: str) -> bool:
    if len(value) != 11 or len(set(value)) == 1:
        return False
    base = [int(character) for character in value[:9]]
    first = _check_digit(base, tuple(range(10, 1, -1)))
    second = _check_digit([*base, first], tuple(range(11, 1, -1)))
    return value[-2:] == f"{first}{second}"


def _is_valid_cnpj(value: str) -> bool:
    if len(value) != 14 or len(set(value)) == 1:
        return False
    base = [int(character) for character in value[:12]]
    first = _check_digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second = _check_digit([*base, first], (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return value[-2:] == f"{first}{second}"


def _check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(digit * weight for digit, weight in zip(digits, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


__all__ = ["SupplierIdentityKind", "SupplierTaxIdentity"]
