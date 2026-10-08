"""A1 certificate, XMLDSig and SEFAZ resilience tests."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from xml.etree import ElementTree

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from erp.modules.fiscal.application import (
    ContingencyMode,
    SefazBatchRequest,
    SefazCancellationRequest,
    SefazEndpoint,
    SefazEnvironment,
    SefazSubmissionMode,
)
from erp.modules.fiscal.domain import FiscalAuthorizationStatus, FiscalDocumentModel
from erp.modules.fiscal.infrastructure import (
    CertificateAdapter,
    CertificateError,
    CertificateSefazGateway,
    CircuitBreaker,
    CircuitState,
    ContingencyPolicy,
    ResilientSefazGateway,
    RetryPolicy,
    SefazCircuitOpenError,
    SefazMockAdapter,
    SefazMockScenario,
    SefazTransientError,
)
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key

DS = "http://www.w3.org/2000/09/xmldsig#"
CNPJ = "12345678000195"


def certificate_material(
    *,
    cnpj: str | None = CNPJ,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> tuple[bytes, rsa.RSAPrivateKey, x509.Certificate]:
    now = datetime.now(UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, "Big Star Fiscal")]
    if cnpj is not None:
        attributes.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, cnpj))
    subject = x509.Name(attributes)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from or now - timedelta(days=1))
        .not_valid_after(valid_until or now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    payload = pkcs12.serialize_key_and_certificates(
        b"fiscal-a1",
        key,
        certificate,
        None,
        serialization.BestAvailableEncryption(b"secret"),
    )
    return payload, key, certificate


def endpoint(
    contingency: ContingencyMode = ContingencyMode.NONE,
) -> SefazEndpoint:
    return SefazEndpoint("sp", SefazEnvironment.HOMOLOGATION, contingency)


def request(
    *,
    model: FiscalDocumentModel = FiscalDocumentModel.NFE,
    mode: SefazSubmissionMode = SefazSubmissionMode.SYNCHRONOUS,
) -> SefazBatchRequest:
    return SefazBatchRequest(
        "000000000000001", (b"<NFe/>",), access_key(model.value), model, mode, endpoint()
    )


def test_a1_certificate_loads_identity_and_signs_verifiable_xmldsig() -> None:
    payload, key, certificate = certificate_material()
    adapter = CertificateAdapter.from_pkcs12(
        payload, "secret", expected_cnpj="12.345.678/0001-95"
    )
    assert adapter.identity.cnpj == CNPJ
    assert adapter.identity.serial_number == certificate.serial_number

    signed = adapter.sign_xml(b'<NFe xmlns="urn:nfe"><infNFe Id="NFe123"/></NFe>', reference_uri="#NFe123")
    root = ElementTree.fromstring(signed)
    signature = root.find(f"{{{DS}}}Signature")
    assert signature is not None
    signed_info = signature.find(f"{{{DS}}}SignedInfo")
    signature_value = signature.findtext(f"{{{DS}}}SignatureValue")
    digest_value = signature.findtext(f".//{{{DS}}}DigestValue")
    assert signed_info is not None
    assert signature_value is not None
    target = root.find("{urn:nfe}infNFe")
    assert target is not None
    assert digest_value == base64.b64encode(sha256(_canonical(target)).digest()).decode()
    key.public_key().verify(
        base64.b64decode(signature_value),
        _canonical(signed_info),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


@pytest.mark.parametrize(
    ("password", "expected", "message"),
    [("wrong", CNPJ, "Unable to open"), ("secret", "00000000000000", "does not match")],
)
def test_a1_certificate_rejects_password_and_holder_mismatch(
    password: str, expected: str, message: str
) -> None:
    payload, _, _ = certificate_material()
    with pytest.raises(CertificateError, match=message):
        CertificateAdapter.from_pkcs12(payload, password, expected_cnpj=expected)


def test_a1_certificate_rejects_expiry_missing_identity_and_naive_clock() -> None:
    now = datetime.now(UTC)
    expired, _, _ = certificate_material(
        valid_from=now - timedelta(days=3), valid_until=now - timedelta(days=1)
    )
    with pytest.raises(CertificateError, match="expired"):
        CertificateAdapter.from_pkcs12(expired, "secret", now=now)
    no_identity, _, _ = certificate_material(cnpj=None)
    with pytest.raises(CertificateError, match="does not expose"):
        CertificateAdapter.from_pkcs12(no_identity, "secret")
    valid, _, _ = certificate_material()
    with pytest.raises(CertificateError, match="timezone-aware"):
        CertificateAdapter.from_pkcs12(valid, "secret", now=datetime.now())  # noqa: DTZ005
    with pytest.raises(CertificateError, match="required"):
        CertificateAdapter.from_pkcs12(b"", "secret")
    with pytest.raises(CertificateError, match="14 digits"):
        CertificateAdapter.from_pkcs12(valid, "secret", expected_cnpj="123")


def test_a1_certificate_requires_an_rsa_private_key() -> None:
    now = datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "EC Fiscal"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, CNPJ),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    payload = pkcs12.serialize_key_and_certificates(
        b"ec", key, certificate, None, serialization.BestAvailableEncryption(b"secret")
    )
    with pytest.raises(CertificateError, match="RSA private key"):
        CertificateAdapter.from_pkcs12(payload, "secret")


@pytest.mark.parametrize(
    ("xml", "reference", "message"),
    [
        (b"<NFe/>", "NFe1", "local XML ID"),
        (b"<NFe>", "#NFe1", "malformed or unsafe"),
        (b'<NFe><a Id="NFe1"/><b Id="NFe1"/></NFe>', "#NFe1", "exactly one"),
    ],
)
def test_xmldsig_rejects_invalid_or_ambiguous_input(
    xml: bytes, reference: str, message: str
) -> None:
    payload, _, _ = certificate_material()
    adapter = CertificateAdapter.from_pkcs12(payload, "secret")
    with pytest.raises(CertificateError, match=message):
        adapter.sign_xml(xml, reference_uri=reference)


def test_retry_uses_exponential_backoff_and_jitter_then_recovers() -> None:
    delays: list[float] = []

    async def sleep(value: float) -> None:
        delays.append(value)

    mock = SefazMockAdapter(
        (SefazMockScenario.TIMEOUT, SefazMockScenario.UNAVAILABLE, SefazMockScenario.AUTHORIZED)
    )
    gateway = ResilientSefazGateway(
        mock,
        retry=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, jitter_ratio=0.5),
        sleep=sleep,
        random_source=lambda: 1.0,
    )
    result = asyncio.run(gateway.submit_batch(request()))
    assert result.status is FiscalAuthorizationStatus.AUTHORIZED
    assert delays == pytest.approx([0.15, 0.30])


def test_resilient_gateway_delegates_signing_and_protocol_queries() -> None:
    mock = SefazMockAdapter()
    gateway = ResilientSefazGateway(mock)
    assert asyncio.run(gateway.sign_xml(b"<NFe/>", reference_uri="#NFe1")).endswith(
        b"<!--mock-signature:#NFe1-->"
    )
    result = asyncio.run(gateway.query_protocol(endpoint(), "REC-1"))
    assert result.status is FiscalAuthorizationStatus.AUTHORIZED


def test_circuit_breaker_opens_rejects_and_half_open_recovers() -> None:
    now = [10.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5, clock=lambda: now[0])
    mock = SefazMockAdapter((SefazMockScenario.UNAVAILABLE, SefazMockScenario.AUTHORIZED))
    gateway = ResilientSefazGateway(
        mock, retry=RetryPolicy(max_attempts=1), circuit_breaker=breaker
    )
    with pytest.raises(SefazTransientError, match="exhausted"):
        asyncio.run(gateway.service_status(endpoint()))
    assert breaker.state("SP:HOMOLOGATION:NONE") is CircuitState.OPEN
    with pytest.raises(SefazCircuitOpenError):
        asyncio.run(gateway.service_status(endpoint()))
    assert len(mock.calls) == 1
    now[0] += 6
    assert asyncio.run(gateway.service_status(endpoint())).available
    assert breaker.state("SP:HOMOLOGATION:NONE") is CircuitState.CLOSED


def test_automatic_and_manual_contingency_route_failed_batches() -> None:
    automatic_mock = SefazMockAdapter(
        (SefazMockScenario.UNAVAILABLE, SefazMockScenario.AUTHORIZED)
    )
    policy = ContingencyPolicy({"SP": ContingencyMode.SVC_AN})
    automatic = ResilientSefazGateway(
        automatic_mock,
        retry=RetryPolicy(max_attempts=1),
        circuit_breaker=CircuitBreaker(failure_threshold=1),
        contingency=policy,
    )
    result = asyncio.run(automatic.submit_batch(request()))
    assert result.endpoint.contingency is ContingencyMode.SVC_AN

    policy.set_manual("SP", ContingencyMode.OFFLINE_NFCE)
    manual_mock = SefazMockAdapter((SefazMockScenario.TIMEOUT, SefazMockScenario.AUTHORIZED))
    manual = ResilientSefazGateway(
        manual_mock, retry=RetryPolicy(max_attempts=1), contingency=policy
    )
    result = asyncio.run(manual.submit_batch(request(model=FiscalDocumentModel.NFCE)))
    assert result.endpoint.contingency is ContingencyMode.OFFLINE_NFCE
    policy.set_manual("SP", None)


def test_failed_batch_without_contingency_propagates_transient_failure() -> None:
    gateway = ResilientSefazGateway(
        SefazMockAdapter((SefazMockScenario.UNAVAILABLE,)),
        retry=RetryPolicy(max_attempts=1),
    )
    with pytest.raises(SefazTransientError):
        asyncio.run(gateway.submit_batch(request()))


def test_contingency_rejects_incompatible_document_models() -> None:
    policy = ContingencyPolicy({"SP": ContingencyMode.OFFLINE_NFCE})
    with pytest.raises(ValueError, match="restricted to NFC-e"):
        policy.select(endpoint(), FiscalDocumentModel.NFE)
    policy.set_manual("SP", ContingencyMode.SVC_RS)
    with pytest.raises(ValueError, match="restricted to NF-e"):
        policy.select(endpoint(), FiscalDocumentModel.NFCE)
    with pytest.raises(ValueError, match="two letters"):
        policy.set_manual("SAO PAULO", ContingencyMode.SVC_AN)


@pytest.mark.parametrize(
    ("scenario", "status", "code"),
    [
        (SefazMockScenario.AUTHORIZED, FiscalAuthorizationStatus.AUTHORIZED, "100"),
        (SefazMockScenario.REJECTED_DUPLICATE, FiscalAuthorizationStatus.REJECTED, "204"),
        (SefazMockScenario.REJECTED_DUPLICATE_KEY, FiscalAuthorizationStatus.REJECTED, "539"),
        (SefazMockScenario.DENIED_301, FiscalAuthorizationStatus.DENIED, "301"),
        (SefazMockScenario.DENIED_302, FiscalAuthorizationStatus.DENIED, "302"),
    ],
)
def test_mock_adapter_maps_deterministic_sefaz_outcomes(
    scenario: SefazMockScenario, status: FiscalAuthorizationStatus, code: str
) -> None:
    mock = SefazMockAdapter((scenario, scenario))
    submitted = asyncio.run(mock.submit_batch(request()))
    queried = asyncio.run(mock.query_protocol(endpoint(), "REC-1"))
    assert (submitted.status, submitted.status_code) == (status, code)
    assert (queried.status, queried.status_code) == (status, code)


def test_mock_supports_async_receipt_status_and_signature() -> None:
    mock = SefazMockAdapter()
    assert asyncio.run(mock.service_status(endpoint())).status_code == "107"
    assert asyncio.run(mock.sign_xml(b"<NFe/>", reference_uri="#NFe1")).endswith(
        b"<!--mock-signature:#NFe1-->"
    )
    submitted = asyncio.run(mock.submit_batch(request(mode=SefazSubmissionMode.ASYNCHRONOUS)))
    assert submitted.status is FiscalAuthorizationStatus.PENDING
    assert submitted.status_code == "103"
    assert submitted.receipt_number == "REC-000000000000001"
    with pytest.raises(ValueError, match="requires XML"):
        asyncio.run(mock.sign_xml(b"", reference_uri="invalid"))


@pytest.mark.parametrize("scenario", [SefazMockScenario.UNAVAILABLE, SefazMockScenario.TIMEOUT])
def test_mock_status_and_protocol_simulate_transport_failures(
    scenario: SefazMockScenario,
) -> None:
    status_mock = SefazMockAdapter((scenario,))
    protocol_mock = SefazMockAdapter((scenario,))
    expected = SefazTransientError if scenario is SefazMockScenario.UNAVAILABLE else TimeoutError
    with pytest.raises(expected):
        asyncio.run(status_mock.service_status(endpoint()))
    with pytest.raises(expected):
        asyncio.run(protocol_mock.query_protocol(endpoint(), "REC-1"))


def test_certificate_gateway_composes_local_signer_and_transport() -> None:
    payload, _, _ = certificate_material()
    gateway = CertificateSefazGateway(
        SefazMockAdapter(), CertificateAdapter.from_pkcs12(payload, "secret")
    )
    assert asyncio.run(gateway.service_status(endpoint())).available
    assert b"Signature" in asyncio.run(
        gateway.sign_xml(b'<NFe><infNFe Id="NFe1"/></NFe>', reference_uri="#NFe1")
    )
    assert asyncio.run(gateway.submit_batch(request())).status_code == "100"
    assert asyncio.run(gateway.query_protocol(endpoint(), "REC-1")).status_code == "100"
    cancellation = SefazCancellationRequest(
        access_key(),
        "135260000000001",
        "Cancelamento operacional autorizado",
        1,
        endpoint(),
    )
    assert asyncio.run(gateway.cancel_document(cancellation)).accepted


def test_resilient_cancellation_supports_contingency_and_failures() -> None:
    request_value = SefazCancellationRequest(
        access_key(),
        "135260000000001",
        "Cancelamento operacional autorizado",
        1,
        endpoint(),
    )
    mock = SefazMockAdapter((SefazMockScenario.TIMEOUT, SefazMockScenario.AUTHORIZED))
    gateway = ResilientSefazGateway(
        mock,
        retry=RetryPolicy(max_attempts=1),
        contingency=ContingencyPolicy({"SP": ContingencyMode.SVC_AN}),
    )
    result = asyncio.run(gateway.cancel_document(request_value))
    assert result.accepted
    assert result.endpoint.contingency is ContingencyMode.SVC_AN

    unavailable = ResilientSefazGateway(
        SefazMockAdapter((SefazMockScenario.UNAVAILABLE,)),
        retry=RetryPolicy(max_attempts=1),
    )
    with pytest.raises(SefazTransientError):
        asyncio.run(unavailable.cancel_document(request_value))


@pytest.mark.parametrize("scenario", [SefazMockScenario.UNAVAILABLE, SefazMockScenario.TIMEOUT])
def test_mock_cancellation_simulates_transport_failures(scenario: SefazMockScenario) -> None:
    mock = SefazMockAdapter((scenario,))
    request_value = SefazCancellationRequest(
        access_key(),
        "135260000000001",
        "Cancelamento operacional autorizado",
        1,
        endpoint(),
    )
    expected = SefazTransientError if scenario is SefazMockScenario.UNAVAILABLE else TimeoutError
    with pytest.raises(expected):
        asyncio.run(mock.cancel_document(request_value))


def test_contracts_and_policy_configuration_fail_closed() -> None:
    with pytest.raises(ValueError, match="two letters"):
        SefazEndpoint("S", SefazEnvironment.PRODUCTION)
    with pytest.raises(ValueError, match="required"):
        SefazBatchRequest(
            "",
            (),
            access_key(),
            FiscalDocumentModel.NFE,
            SefazSubmissionMode.SYNCHRONOUS,
            endpoint(),
        )
    with pytest.raises(ValueError, match="positive"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="delays"):
        RetryPolicy(base_delay_seconds=2, max_delay_seconds=1)
    with pytest.raises(ValueError, match="jitter"):
        RetryPolicy(jitter_ratio=2)
    with pytest.raises(ValueError, match="thresholds"):
        CircuitBreaker(failure_threshold=0)
    assert ContingencyPolicy().select(endpoint(), FiscalDocumentModel.NFE) is None
    with pytest.raises(ValueError, match="at least 15"):
        SefazCancellationRequest(access_key(), "", "short", 1, endpoint())
    with pytest.raises(ValueError, match="positive"):
        SefazCancellationRequest(
            access_key(),
            "135260000000001",
            "Cancelamento operacional autorizado",
            0,
            endpoint(),
        )


def _canonical(element: ElementTree.Element) -> bytes:
    return ElementTree.canonicalize(
        xml_data=ElementTree.tostring(element, encoding="unicode")
    ).encode()
