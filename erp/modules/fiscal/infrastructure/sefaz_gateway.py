"""Composable SEFAZ resilience, contingency and deterministic test adapter."""

import asyncio
import random
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic

from erp.modules.fiscal.application.sefaz import (
    ContingencyMode,
    SefazBatchRequest,
    SefazCancellationRequest,
    SefazCancellationResult,
    SefazEndpoint,
    SefazGatewayPort,
    SefazProtocolResult,
    SefazServiceStatus,
    SefazSubmissionMode,
    SefazSubmissionResult,
)
from erp.modules.fiscal.domain import FiscalAuthorizationStatus, FiscalDocumentModel, NFeAccessKey
from erp.modules.fiscal.infrastructure.certificate import CertificateAdapter


class SefazGatewayError(RuntimeError):
    """Base failure for an authorizer interaction."""


class SefazTransientError(SefazGatewayError):
    """Retryable network, timeout or temporary service failure."""


class SefazCircuitOpenError(SefazGatewayError):
    """Raised while an authorizer circuit is open."""


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 2.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("Retry attempts must be positive.")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("Retry delays are invalid.")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("Retry jitter ratio must be between zero and one.")

    def delay(self, failed_attempt: int, random_value: float) -> float:
        base = min(self.max_delay_seconds, self.base_delay_seconds * 2.0 ** (failed_attempt - 1))
        return base + base * self.jitter_ratio * random_value


@dataclass(slots=True)
class _Circuit:
    failures: int = 0
    state: CircuitState = CircuitState.CLOSED
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_timeout_seconds <= 0:
            raise ValueError("Circuit breaker thresholds must be positive.")
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._clock = clock
        self._circuits: dict[str, _Circuit] = defaultdict(_Circuit)

    def before_call(self, key: str) -> None:
        circuit = self._circuits[key]
        if circuit.state is not CircuitState.OPEN:
            return
        assert circuit.opened_at is not None
        if self._clock() - circuit.opened_at < self._recovery_timeout:
            raise SefazCircuitOpenError(f"SEFAZ circuit {key} is open.")
        circuit.state = CircuitState.HALF_OPEN

    def success(self, key: str) -> None:
        self._circuits[key] = _Circuit()

    def failure(self, key: str) -> None:
        circuit = self._circuits[key]
        circuit.failures += 1
        if circuit.state is CircuitState.HALF_OPEN or circuit.failures >= self._threshold:
            circuit.state = CircuitState.OPEN
            circuit.opened_at = self._clock()

    def state(self, key: str) -> CircuitState:
        return self._circuits[key].state


class ContingencyPolicy:
    """Explicit operational policy; no volatile state-to-SVC mapping is hard-coded."""

    def __init__(self, automatic_by_state: Mapping[str, ContingencyMode] | None = None) -> None:
        self._automatic = {
            state.strip().upper(): mode for state, mode in (automatic_by_state or {}).items()
        }
        self._manual: dict[str, ContingencyMode] = {}

    def set_manual(self, state_code: str, mode: ContingencyMode | None) -> None:
        state = _state(state_code)
        if mode is None:
            self._manual.pop(state, None)
        else:
            self._manual[state] = mode

    def select(
        self, endpoint: SefazEndpoint, model: FiscalDocumentModel
    ) -> SefazEndpoint | None:
        mode = self._manual.get(endpoint.state_code) or self._automatic.get(endpoint.state_code)
        if mode is None or mode is ContingencyMode.NONE:
            return None
        if mode is ContingencyMode.OFFLINE_NFCE and model is not FiscalDocumentModel.NFCE:
            raise ValueError("Offline contingency is restricted to NFC-e model 65.")
        if mode in {ContingencyMode.SVC_AN, ContingencyMode.SVC_RS} and model is not FiscalDocumentModel.NFE:
            raise ValueError("SVC contingency is restricted to NF-e model 55.")
        return replace(endpoint, contingency=mode)


class ResilientSefazGateway:
    def __init__(
        self,
        gateway: SefazGatewayPort,
        *,
        retry: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        contingency: ContingencyPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._gateway = gateway
        self._retry = retry or RetryPolicy()
        self._circuit = circuit_breaker or CircuitBreaker()
        self._contingency = contingency or ContingencyPolicy()
        self._sleep = sleep
        self._random = random_source

    async def service_status(self, endpoint: SefazEndpoint) -> SefazServiceStatus:
        return await self._execute(endpoint, lambda: self._gateway.service_status(endpoint))

    async def sign_xml(self, xml: bytes, *, reference_uri: str) -> bytes:
        return await self._gateway.sign_xml(xml, reference_uri=reference_uri)

    async def submit_batch(self, request: SefazBatchRequest) -> SefazSubmissionResult:
        try:
            return await self._execute(
                request.endpoint, lambda: self._gateway.submit_batch(request)
            )
        except (SefazTransientError, SefazCircuitOpenError):
            endpoint = self._contingency.select(request.endpoint, request.model)
            if endpoint is None:
                raise
            fallback = replace(request, endpoint=endpoint)
            return await self._execute(endpoint, lambda: self._gateway.submit_batch(fallback))

    async def query_protocol(
        self, endpoint: SefazEndpoint, receipt_number: str
    ) -> SefazProtocolResult:
        return await self._execute(
            endpoint, lambda: self._gateway.query_protocol(endpoint, receipt_number)
        )

    async def cancel_document(
        self, request: SefazCancellationRequest
    ) -> SefazCancellationResult:
        try:
            return await self._execute(
                request.endpoint, lambda: self._gateway.cancel_document(request)
            )
        except (SefazTransientError, SefazCircuitOpenError):
            model = FiscalDocumentModel(request.access_key.model)
            endpoint = self._contingency.select(request.endpoint, model)
            if endpoint is None:
                raise
            fallback = replace(request, endpoint=endpoint)
            return await self._execute(
                endpoint, lambda: self._gateway.cancel_document(fallback)
            )

    async def _execute[T](
        self, endpoint: SefazEndpoint, operation: Callable[[], Awaitable[T]]
    ) -> T:
        key = _circuit_key(endpoint)
        self._circuit.before_call(key)
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                result = await operation()
            except (TimeoutError, ConnectionError, SefazTransientError) as error:
                if attempt == self._retry.max_attempts:
                    self._circuit.failure(key)
                    raise SefazTransientError("SEFAZ operation exhausted retry attempts.") from error
                await self._sleep(self._retry.delay(attempt, self._random()))
            else:
                self._circuit.success(key)
                return result
        raise AssertionError("Retry loop must return or raise.")  # pragma: no cover


class CertificateSefazGateway:
    """Compose local A1 signing with an independently replaceable SEFAZ transport."""

    def __init__(self, transport: SefazGatewayPort, certificate: CertificateAdapter) -> None:
        self._transport = transport
        self._certificate = certificate

    async def service_status(self, endpoint: SefazEndpoint) -> SefazServiceStatus:
        return await self._transport.service_status(endpoint)

    async def sign_xml(self, xml: bytes, *, reference_uri: str) -> bytes:
        return self._certificate.sign_xml(xml, reference_uri=reference_uri)

    async def submit_batch(self, request: SefazBatchRequest) -> SefazSubmissionResult:
        return await self._transport.submit_batch(request)

    async def query_protocol(
        self, endpoint: SefazEndpoint, receipt_number: str
    ) -> SefazProtocolResult:
        return await self._transport.query_protocol(endpoint, receipt_number)

    async def cancel_document(
        self, request: SefazCancellationRequest
    ) -> SefazCancellationResult:
        return await self._transport.cancel_document(request)


class SefazMockScenario(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_DUPLICATE_KEY = "REJECTED_DUPLICATE_KEY"
    DENIED_301 = "DENIED_301"
    DENIED_302 = "DENIED_302"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"


class SefazMockAdapter:
    """Deterministic adapter for unit and integration tests."""

    def __init__(self, scenarios: tuple[SefazMockScenario, ...] = ()) -> None:
        self._scenarios = deque(scenarios)
        self.calls: list[tuple[str, SefazEndpoint]] = []
        self._receipts: dict[str, tuple[NFeAccessKey, str]] = {}

    async def service_status(self, endpoint: SefazEndpoint) -> SefazServiceStatus:
        self.calls.append(("status", endpoint))
        scenario = self._next()
        if scenario is SefazMockScenario.UNAVAILABLE:
            raise SefazTransientError("Mock SEFAZ unavailable.")
        if scenario is SefazMockScenario.TIMEOUT:
            raise TimeoutError("Mock SEFAZ timeout.")
        return SefazServiceStatus(True, "107", "Servico em operacao", datetime.now(UTC), endpoint)

    async def sign_xml(self, xml: bytes, *, reference_uri: str) -> bytes:
        if not xml or not reference_uri.startswith("#"):
            raise ValueError("Mock signature requires XML and a local reference.")
        return xml + f"<!--mock-signature:{reference_uri}-->".encode()

    async def submit_batch(self, request: SefazBatchRequest) -> SefazSubmissionResult:
        self.calls.append(("submit", request.endpoint))
        scenario = self._next()
        if scenario is SefazMockScenario.UNAVAILABLE:
            raise SefazTransientError("Mock SEFAZ unavailable.")
        if scenario is SefazMockScenario.TIMEOUT:
            raise TimeoutError("Mock SEFAZ timeout.")
        status, code, message = _mock_outcome(scenario)
        asynchronous = request.mode is SefazSubmissionMode.ASYNCHRONOUS
        receipt = f"REC-{request.batch_id}" if asynchronous else None
        if receipt is not None:
            self._receipts[receipt] = (request.access_key, request.signed_documents[0].decode())
        authorized = status is FiscalAuthorizationStatus.AUTHORIZED
        return SefazSubmissionResult(
            FiscalAuthorizationStatus.PENDING if asynchronous else status,
            "103" if asynchronous else code,
            "Lote recebido" if asynchronous else message,
            request.endpoint,
            request.batch_id,
            receipt_number=receipt,
            protocol="135260000000001"
            if not asynchronous and authorized
            else None,
            access_key=request.access_key if not asynchronous and authorized else None,
            authorized_at=datetime.now(UTC) if not asynchronous and authorized else None,
            authorized_xml=request.signed_documents[0].decode()
            if not asynchronous and authorized
            else None,
        )

    async def query_protocol(
        self, endpoint: SefazEndpoint, receipt_number: str
    ) -> SefazProtocolResult:
        self.calls.append(("query", endpoint))
        scenario = self._next()
        if scenario is SefazMockScenario.UNAVAILABLE:
            raise SefazTransientError("Mock SEFAZ unavailable.")
        if scenario is SefazMockScenario.TIMEOUT:
            raise TimeoutError("Mock SEFAZ timeout.")
        status, code, message = _mock_outcome(scenario)
        receipt = self._receipts.get(receipt_number)
        authorized = status is FiscalAuthorizationStatus.AUTHORIZED
        return SefazProtocolResult(
            status,
            code,
            message,
            endpoint,
            receipt_number,
            protocol="135260000000001"
            if authorized
            else None,
            access_key=receipt[0] if authorized and receipt is not None else None,
            authorized_at=datetime.now(UTC) if authorized else None,
            authorized_xml=receipt[1] if authorized and receipt is not None else None,
        )

    async def cancel_document(
        self, request: SefazCancellationRequest
    ) -> SefazCancellationResult:
        self.calls.append(("cancel", request.endpoint))
        scenario = self._next()
        if scenario is SefazMockScenario.UNAVAILABLE:
            raise SefazTransientError("Mock SEFAZ unavailable.")
        if scenario is SefazMockScenario.TIMEOUT:
            raise TimeoutError("Mock SEFAZ timeout.")
        accepted = scenario is SefazMockScenario.AUTHORIZED
        return SefazCancellationResult(
            accepted,
            "135" if accepted else "573",
            "Evento registrado e vinculado a NF-e" if accepted else "Rejeicao do evento",
            request.endpoint,
            protocol="135260000000002" if accepted else None,
            cancelled_at=datetime.now(UTC) if accepted else None,
            event_xml="<procEventoNFe tpEvento='110111'/>" if accepted else None,
        )

    def _next(self) -> SefazMockScenario:
        return self._scenarios.popleft() if self._scenarios else SefazMockScenario.AUTHORIZED


def _mock_outcome(
    scenario: SefazMockScenario,
) -> tuple[FiscalAuthorizationStatus, str, str]:
    outcomes = {
        SefazMockScenario.AUTHORIZED: (
            FiscalAuthorizationStatus.AUTHORIZED,
            "100",
            "Autorizado o uso da NF-e",
        ),
        SefazMockScenario.REJECTED_DUPLICATE: (
            FiscalAuthorizationStatus.REJECTED,
            "204",
            "Duplicidade de NF-e",
        ),
        SefazMockScenario.REJECTED_DUPLICATE_KEY: (
            FiscalAuthorizationStatus.REJECTED,
            "539",
            "Duplicidade de NF-e com diferenca na chave",
        ),
        SefazMockScenario.DENIED_301: (
            FiscalAuthorizationStatus.DENIED,
            "301",
            "Uso denegado: irregularidade fiscal do emitente",
        ),
        SefazMockScenario.DENIED_302: (
            FiscalAuthorizationStatus.DENIED,
            "302",
            "Uso denegado: irregularidade fiscal do destinatario",
        ),
    }
    return outcomes.get(scenario, outcomes[SefazMockScenario.AUTHORIZED])


def _state(value: str) -> str:
    state = value.strip().upper()
    if len(state) != 2 or not state.isalpha():
        raise ValueError("SEFAZ state code must contain two letters.")
    return state


def _circuit_key(endpoint: SefazEndpoint) -> str:
    return f"{endpoint.state_code}:{endpoint.environment}:{endpoint.contingency}"


__all__ = [
    "CertificateSefazGateway",
    "CircuitBreaker",
    "CircuitState",
    "ContingencyPolicy",
    "ResilientSefazGateway",
    "RetryPolicy",
    "SefazCircuitOpenError",
    "SefazGatewayError",
    "SefazMockAdapter",
    "SefazMockScenario",
    "SefazTransientError",
]
