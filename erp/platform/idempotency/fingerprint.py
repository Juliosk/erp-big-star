"""Stable request fingerprinting without storing request payloads."""

import hashlib
import json
from typing import Any


def payload_fingerprint(payload: dict[str, Any]) -> str:
    """Hash a canonical UTF-8 JSON representation of one command payload."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["payload_fingerprint"]
