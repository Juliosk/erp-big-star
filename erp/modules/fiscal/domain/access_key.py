"""NF-e/NFC-e access-key value object."""

from dataclasses import dataclass

from erp.modules.fiscal.domain.exceptions import InvalidAccessKeyError


@dataclass(frozen=True, slots=True)
class NFeAccessKey:
    """Validated 44-digit Brazilian electronic fiscal document key."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value
        if len(normalized) != 44 or not normalized.isascii() or not normalized.isdigit():
            raise InvalidAccessKeyError("Access key must contain exactly 44 ASCII digits.")
        if normalized[20:22] not in {"55", "65"}:
            raise InvalidAccessKeyError("Access key model must be 55 (NF-e) or 65 (NFC-e).")
        if _check_digit(normalized[:43]) != int(normalized[43]):
            raise InvalidAccessKeyError("Access key check digit is invalid.")
        object.__setattr__(self, "value", normalized)

    @property
    def state_code(self) -> str:
        return self.value[:2]

    @property
    def issued_year_month(self) -> str:
        return self.value[2:6]

    @property
    def issuer_tax_id(self) -> str:
        return self.value[6:20]

    @property
    def model(self) -> str:
        return self.value[20:22]

    @property
    def series(self) -> str:
        return self.value[22:25]

    @property
    def number(self) -> str:
        return self.value[25:34]

    def __str__(self) -> str:
        return self.value


def _check_digit(body: str) -> int:
    weight = 2
    total = 0
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return 0 if remainder in {0, 1} else 11 - remainder


__all__ = ["NFeAccessKey"]
