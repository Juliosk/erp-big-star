"""NF-e/NFC-e access-key invariants."""

import pytest

from erp.modules.fiscal.domain import InvalidAccessKeyError, NFeAccessKey


def _key(model: str = "55") -> str:
    body = f"35" "2610" "12345678000195" f"{model}" "001" "000000123" "1" "12345678"
    weight = 2
    total = 0
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return body + str(0 if remainder in {0, 1} else 11 - remainder)


def test_access_key_validates_and_exposes_legal_segments() -> None:
    key = NFeAccessKey(_key())

    assert str(key) == _key()
    assert key.state_code == "35"
    assert key.issued_year_month == "2610"
    assert key.issuer_tax_id == "12345678000195"
    assert key.model == "55"
    assert key.series == "001"
    assert key.number == "000000123"


def test_nfce_model_is_accepted() -> None:
    assert NFeAccessKey(_key("65")).model == "65"


@pytest.mark.parametrize(
    "value",
    [
        "1" * 43,
        "A" * 44,
        " " + _key()[1:],
        _key()[:-1] + str((int(_key()[-1]) + 1) % 10),
        _key("55")[:20] + "57" + _key("55")[22:],
    ],
)
def test_invalid_access_keys_are_rejected(value: str) -> None:
    with pytest.raises(InvalidAccessKeyError):
        NFeAccessKey(value)
