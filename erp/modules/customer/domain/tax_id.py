"""Brazilian customer fiscal identity value objects."""

from dataclasses import dataclass
from enum import StrEnum


class TaxIdKind(StrEnum):
    CPF = "CPF"
    CNPJ = "CNPJ"


@dataclass(frozen=True, order=True, slots=True)
class CustomerTaxId:
    """Normalized and check-digit validated CPF/CNPJ."""

    kind: TaxIdKind
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TaxIdKind):
            raise ValueError("identity_type must be CPF or CNPJ.")
        if any(
            character not in "0123456789./-" and not character.isspace() for character in self.value
        ):
            raise ValueError("identity_value must be a valid CPF/CNPJ.")
        digits = "".join(character for character in self.value if character.isdigit())
        valid = _is_valid_cpf(digits) if self.kind is TaxIdKind.CPF else _is_valid_cnpj(digits)
        if not valid:
            raise ValueError("identity_value must be a valid CPF/CNPJ.")
        object.__setattr__(self, "value", digits)

    @property
    def reference(self) -> str:
        """Return a non-sensitive reference for audit and integration events."""
        return f"{self.kind}:***{self.value[-4:]}"

    def __str__(self) -> str:
        return self.value


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


__all__ = ["CustomerTaxId", "TaxIdKind"]
