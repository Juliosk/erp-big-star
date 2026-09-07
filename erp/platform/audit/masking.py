"""Sensitive-value masking applied before durable audit persistence."""

from collections.abc import Mapping, Sequence

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None

MASKED_VALUE = "***MASKED***"
SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "card_number",
        "confirm_password",
        "credential",
        "credentials",
        "current_password",
        "cvv",
        "new_password",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def mask_sensitive_values(value: object) -> JsonValue:
    """Return a JSON-compatible copy with known credential fields redacted."""
    if isinstance(value, Mapping):
        masked: dict[str, JsonValue] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            masked[key] = (
                MASKED_VALUE if key.casefold() in SENSITIVE_KEYS else mask_sensitive_values(item)
            )
        return masked
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [mask_sensitive_values(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


__all__ = ["MASKED_VALUE", "JsonValue", "mask_sensitive_values"]
