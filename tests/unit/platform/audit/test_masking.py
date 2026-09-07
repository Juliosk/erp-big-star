"""Tests for audit snapshot sanitization."""

from erp.platform.audit.masking import MASKED_VALUE, mask_sensitive_values


def test_mask_sensitive_values_redacts_nested_credentials_without_mutating_source() -> None:
    source = {
        "name": "Big Star",
        "password": "plain-text",
        "nested": {"access_token": "abc", "items": [{"cvv": "123"}]},
    }

    masked = mask_sensitive_values(source)

    assert masked == {
        "name": "Big Star",
        "password": MASKED_VALUE,
        "nested": {"access_token": MASKED_VALUE, "items": [{"cvv": MASKED_VALUE}]},
    }
    assert source["password"] == "plain-text"


def test_mask_sensitive_values_converts_non_json_leaf_to_text() -> None:
    masked = mask_sensitive_values({"value": object()})

    assert isinstance(masked, dict)
    assert isinstance(masked["value"], str)
    assert masked["value"].startswith("<object object")
