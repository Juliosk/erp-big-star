"""Reliable aio-pika adapter with durable retry and dead-letter topology."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractIncomingMessage,
    AbstractRobustConnection,
    HeadersType,
)
from aio_pika.exceptions import AMQPException
from pamqp.commands import Basic

from erp.platform.config import Settings
from erp.platform.messaging.envelope import MessageEnvelope


class BrokerUnavailableError(RuntimeError):
    """Raised when RabbitMQ cannot be reached or initialized."""


class BrokerPublishError(RuntimeError):
    """Raised when RabbitMQ does not confirm a mandatory publication."""


@dataclass(frozen=True, slots=True)
class ConsumerBinding:
    """One durable consumer queue bound to exactly one event routing key."""

    consumer_name: str
    queue_name: str
    routing_key: str


@dataclass(slots=True)
class IncomingDelivery:
    """Validated corporate message plus transport acknowledgement handle."""

    envelope: MessageEnvelope
    headers: dict[str, object]
    exchange: str
    routing_key: str
    _message: AbstractIncomingMessage = field(repr=False)

    async def ack(self) -> None:
        """Acknowledge only after the consumer transaction commits."""
        await self._message.ack()


class RabbitMQBroker:
    """Own robust AMQP resources and the corporate queue topology."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._events: AbstractExchange | None = None
        self._requests: AbstractExchange | None = None
        self._retry: AbstractExchange | None = None
        self._dlx: AbstractExchange | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open a recoverable connection and declare shared durable exchanges."""
        if self._connection is not None and not self._connection.is_closed:
            return
        async with self._connect_lock:
            if self._connection is not None and not self._connection.is_closed:
                return
            try:
                connection = await aio_pika.connect_robust(
                    host=self._settings.rabbitmq_host,
                    port=self._settings.rabbitmq_amqp_port,
                    login=self._settings.rabbitmq_default_user,
                    password=self._settings.rabbitmq_default_pass.get_secret_value(),
                    virtualhost=self._settings.rabbitmq_virtual_host,
                    timeout=self._settings.rabbitmq_connection_timeout_seconds,
                    client_properties={"connection_name": "erp-platform"},
                )
                channel = await connection.channel(
                    publisher_confirms=True,
                    on_return_raises=True,
                )
                await channel.set_qos(prefetch_count=self._settings.rabbitmq_prefetch_count)
                self._events = await channel.declare_exchange(
                    self._settings.rabbitmq_events_exchange,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                self._requests = await channel.declare_exchange(
                    self._settings.rabbitmq_requests_exchange,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                self._retry = await channel.declare_exchange(
                    self._settings.rabbitmq_retry_exchange,
                    ExchangeType.DIRECT,
                    durable=True,
                )
                self._dlx = await channel.declare_exchange(
                    self._settings.rabbitmq_dead_letter_exchange,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                self._connection = connection
                self._channel = channel
            except (AMQPException, OSError, TimeoutError) as error:
                raise BrokerUnavailableError("RabbitMQ connection failed.") from error

    async def close(self) -> None:
        """Release the AMQP connection; safe to call more than once."""
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._events = None
        self._requests = None
        self._retry = None
        self._dlx = None

    async def declare_consumer(self, binding: ConsumerBinding) -> None:
        """Declare the main queue, four TTL retry queues and its isolated DLQ."""
        await self.connect()
        channel = self._required_channel()
        events = self._required_exchange(self._events)
        retry = self._required_exchange(self._retry)
        dlx = self._required_exchange(self._dlx)

        main_queue = await channel.declare_queue(binding.queue_name, durable=True)
        await main_queue.bind(events, routing_key=binding.routing_key)

        for attempt, delay_ms in enumerate(self._settings.rabbitmq_retry_delays_ms, start=1):
            retry_name = self._retry_queue_name(binding, attempt)
            retry_queue = await channel.declare_queue(
                retry_name,
                durable=True,
                arguments={
                    "x-message-ttl": delay_ms,
                    "x-dead-letter-exchange": self._settings.rabbitmq_events_exchange,
                    "x-dead-letter-routing-key": binding.routing_key,
                },
            )
            await retry_queue.bind(retry, routing_key=retry_name)

        dlq_name = self._dead_letter_queue_name(binding)
        dead_letter_queue = await channel.declare_queue(dlq_name, durable=True)
        await dead_letter_queue.bind(dlx, routing_key=dlq_name)

    async def publish(
        self,
        envelope: MessageEnvelope,
        *,
        routing_key: str,
        headers: dict[str, object] | None = None,
    ) -> None:
        """Publish a persistent event and require a positive broker confirmation."""
        await self.connect()
        message = self._message(envelope, headers=headers)
        try:
            confirmed = await self._required_exchange(self._events).publish(
                message,
                routing_key=routing_key,
                mandatory=True,
            )
        except (AMQPException, OSError, TimeoutError) as error:
            raise BrokerPublishError("RabbitMQ publication failed.") from error
        if isinstance(confirmed, Basic.Nack | Basic.Reject):
            raise BrokerPublishError("RabbitMQ did not confirm publication.")

    async def get(
        self,
        binding: ConsumerBinding,
        *,
        timeout_seconds: float = 5.0,
    ) -> IncomingDelivery | None:
        """Get one message for transaction-controlled consumption."""
        await self.declare_consumer(binding)
        return await self._get_from_queue(
            binding.queue_name,
            fallback_routing_key=binding.routing_key,
            timeout_seconds=timeout_seconds,
        )

    async def get_dead_letter(
        self,
        binding: ConsumerBinding,
        *,
        timeout_seconds: float = 5.0,
    ) -> IncomingDelivery | None:
        """Read one dead letter for controlled diagnostics or replay tooling."""
        await self.declare_consumer(binding)
        queue_name = self._dead_letter_queue_name(binding)
        return await self._get_from_queue(
            queue_name,
            fallback_routing_key=queue_name,
            timeout_seconds=timeout_seconds,
        )

    async def _get_from_queue(
        self,
        queue_name: str,
        *,
        fallback_routing_key: str,
        timeout_seconds: float,
    ) -> IncomingDelivery | None:
        queue = await self._required_channel().get_queue(queue_name, ensure=True)
        raw = await queue.get(no_ack=False, fail=False, timeout=timeout_seconds)
        if raw is None:
            return None
        try:
            envelope = MessageEnvelope.model_validate_json(raw.body)
        except ValueError as error:
            await raw.reject(requeue=False)
            raise BrokerPublishError("Received message has an invalid envelope.") from error
        return IncomingDelivery(
            envelope=envelope,
            headers={str(key): value for key, value in (raw.headers or {}).items()},
            exchange=raw.exchange or self._settings.rabbitmq_events_exchange,
            routing_key=raw.routing_key or fallback_routing_key,
            _message=raw,
        )

    async def retry_or_dead_letter(
        self,
        delivery: IncomingDelivery,
        binding: ConsumerBinding,
        *,
        error_code: str,
        error_summary: str,
    ) -> bool:
        """Schedule the next retry, or dead-letter after the fourth failed retry."""
        await self.connect()
        now = datetime.now(UTC).isoformat()
        raw_attempt = delivery.headers.get("retry_attempt", 0)
        current_attempt = raw_attempt if isinstance(raw_attempt, int) else int(str(raw_attempt))
        next_attempt = current_attempt + 1
        headers = dict(delivery.headers)
        headers.update(
            {
                "retry_attempt": next_attempt,
                "error_code": error_code,
                "error_summary": error_summary[:1000],
                "last_failure_at": now,
                "first_failure_at": headers.get("first_failure_at", now),
                "original_exchange": delivery.exchange,
                "original_routing_key": delivery.routing_key,
                "consumer": binding.consumer_name,
            }
        )
        if next_attempt <= len(self._settings.rabbitmq_retry_delays_ms):
            exchange = self._required_exchange(self._retry)
            routing_key = self._retry_queue_name(binding, next_attempt)
            dead_lettered = False
        else:
            exchange = self._required_exchange(self._dlx)
            routing_key = self._dead_letter_queue_name(binding)
            dead_lettered = True

        try:
            confirmed = await exchange.publish(
                self._message(delivery.envelope, headers=headers),
                routing_key=routing_key,
                mandatory=True,
            )
        except (AMQPException, OSError, TimeoutError) as error:
            raise BrokerPublishError("RabbitMQ retry publication failed.") from error
        if isinstance(confirmed, Basic.Nack | Basic.Reject):
            raise BrokerPublishError("RabbitMQ did not confirm retry publication.")
        await delivery.ack()
        return dead_lettered

    async def purge_consumer(self, binding: ConsumerBinding) -> None:
        """Purge test/maintenance queues without changing durable declarations."""
        await self.declare_consumer(binding)
        channel = self._required_channel()
        queue_names = [
            binding.queue_name,
            self._dead_letter_queue_name(binding),
            *[
                self._retry_queue_name(binding, attempt)
                for attempt in range(1, len(self._settings.rabbitmq_retry_delays_ms) + 1)
            ],
        ]
        for queue_name in queue_names:
            queue = await channel.get_queue(queue_name, ensure=True)
            await queue.purge()

    def _message(
        self,
        envelope: MessageEnvelope,
        *,
        headers: dict[str, object] | None,
    ) -> Message:
        serialized = json.dumps(
            envelope.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return Message(
            serialized,
            headers=cast(HeadersType, headers or {}),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=DeliveryMode.PERSISTENT,
            correlation_id=str(envelope.correlation_id),
            message_id=str(envelope.message_id),
            timestamp=envelope.occurred_at,
            type=envelope.message_type,
            app_id=envelope.producer_module,
        )

    def _required_channel(self) -> AbstractChannel:
        if self._channel is None:
            raise BrokerUnavailableError("RabbitMQ channel is unavailable.")
        return self._channel

    @staticmethod
    def _required_exchange(exchange: AbstractExchange | None) -> AbstractExchange:
        if exchange is None:
            raise BrokerUnavailableError("RabbitMQ exchange is unavailable.")
        return exchange

    @staticmethod
    def _retry_queue_name(binding: ConsumerBinding, attempt: int) -> str:
        return f"{binding.queue_name}.retry.{attempt}"

    @staticmethod
    def _dead_letter_queue_name(binding: ConsumerBinding) -> str:
        return f"{binding.queue_name}.dlq"


__all__ = [
    "BrokerPublishError",
    "BrokerUnavailableError",
    "ConsumerBinding",
    "IncomingDelivery",
    "RabbitMQBroker",
]
