"""Brazilian fiscal-identity value objects used by the corporate foundation."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class Cnpj:
    """Normalized and check-digit validated Brazilian CNPJ."""

    value: str

    def __post_init__(self) -> None:
        if any(
            character not in "0123456789./-" and not character.isspace() for character in self.value
        ):
            raise ValueError("tax_id must be a valid CNPJ.")
        digits = "".join(character for character in self.value if character.isdigit())
        if not _is_valid_cnpj(digits):
            raise ValueError("tax_id must be a valid CNPJ.")
        object.__setattr__(self, "value", digits)

    @property
    def formatted(self) -> str:
        """Return the conventional punctuation format without changing persistence."""
        value = self.value
        return f"{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}"

    def __str__(self) -> str:
        return self.value


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


__all__ = ["Cnpj"]
