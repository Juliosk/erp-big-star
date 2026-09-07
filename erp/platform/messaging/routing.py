"""RabbitMQ routing-key conventions."""

import re

ROUTING_SEGMENT = re.compile(r"^[a-z][a-z0-9_-]*$")
PASCAL_WORD = re.compile(r"[A-Z][a-z0-9]*|[A-Z]+(?=[A-Z]|$)")


def build_routing_key(*, domain: str, aggregate: str, action: str, version: int) -> str:
    """Build and validate ``<domain>.<aggregate>.<action>.v<major>``."""
    segments = (domain, aggregate, action)
    if any(ROUTING_SEGMENT.fullmatch(segment) is None for segment in segments):
        raise ValueError("Routing-key segments must use lowercase names.")
    if version < 1:
        raise ValueError("Routing-key version must be positive.")
    return f"{domain}.{aggregate}.{action}.v{version}"


def action_from_message_type(message_type: str) -> str:
    """Extract the final PascalCase verb for the default event route."""
    words: list[str] = PASCAL_WORD.findall(message_type)
    if not words:
        raise ValueError("Message type must be PascalCase.")
    return words[-1].lower()


__all__ = ["action_from_message_type", "build_routing_key"]
