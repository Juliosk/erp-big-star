"""GS1 check digits and canonical internal codes without I/O."""

import pytest

from erp.modules.product.domain.barcode import Barcode, BarcodeType


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (BarcodeType.EAN, "4006381333931"),
        (BarcodeType.EAN, "96385074"),
        (BarcodeType.DUN, "04006381333931"),
        (BarcodeType.INTERNAL, "0001-ABC"),
    ],
)
def test_valid_barcodes_preserve_text(kind: BarcodeType, value: str) -> None:
    assert Barcode(kind, value).barcode == value


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (BarcodeType.EAN, "4006381333932"),
        (BarcodeType.EAN, "123"),
        (BarcodeType.EAN, "ABCDEFGHIJKLM"),
        (BarcodeType.DUN, "4006381333931"),
        (BarcodeType.INTERNAL, "lower"),
        (BarcodeType.INTERNAL, ""),
        (BarcodeType.INTERNAL, "A B"),
    ],
)
def test_invalid_barcodes_are_rejected(kind: BarcodeType, value: str) -> None:
    with pytest.raises(ValueError, match=r"barcode|digits|digit"):
        Barcode(kind, value)
