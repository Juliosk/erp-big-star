"""Tests for privacy-preserving, deterministic request fingerprints."""

from erp.platform.idempotency import payload_fingerprint


def test_payload_fingerprint_is_stable_across_key_order() -> None:
    first = payload_fingerprint({"name": "Big Star", "quantity": 2})
    second = payload_fingerprint({"quantity": 2, "name": "Big Star"})

    assert first == second
    assert len(first) == 64


def test_payload_fingerprint_changes_with_semantic_value() -> None:
    assert payload_fingerprint({"quantity": 1}) != payload_fingerprint({"quantity": 2})
