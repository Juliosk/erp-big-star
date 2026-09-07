"""Versioned messaging contracts shared by infrastructure adapters."""

from erp.platform.messaging.envelope import MessageEnvelope, MessageKind
from erp.platform.messaging.rabbitmq import (
    BrokerPublishError,
    BrokerUnavailableError,
    ConsumerBinding,
    IncomingDelivery,
    RabbitMQBroker,
)
from erp.platform.messaging.routing import build_routing_key

__all__ = [
    "BrokerPublishError",
    "BrokerUnavailableError",
    "ConsumerBinding",
    "IncomingDelivery",
    "MessageEnvelope",
    "MessageKind",
    "RabbitMQBroker",
    "build_routing_key",
]
