"""A1 PKCS#12 certificate loading, validation and XMLDSig signing."""

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from xml.etree import ElementTree

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from defusedxml import ElementTree as SafeElementTree

DS = "http://www.w3.org/2000/09/xmldsig#"
EXCLUSIVE_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"


class CertificateError(ValueError):
    """Raised when an A1 certificate or XML signature request is invalid."""


@dataclass(frozen=True, slots=True)
class CertificateIdentity:
    cnpj: str
    subject: str
    serial_number: int
    valid_from: datetime
    valid_until: datetime


class CertificateAdapter:
    """Validated in-memory A1 certificate; passwords are never retained."""

    def __init__(
        self,
        private_key: rsa.RSAPrivateKey,
        certificate: x509.Certificate,
        *,
        expected_cnpj: str | None = None,
        now: datetime | None = None,
    ) -> None:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise CertificateError("Certificate validation time must be timezone-aware.")
        if not certificate.not_valid_before_utc <= instant <= certificate.not_valid_after_utc:
            raise CertificateError("A1 certificate is expired or not yet valid.")
        cnpj = _certificate_cnpj(certificate)
        normalized_expected = None if expected_cnpj is None else _cnpj(expected_cnpj)
        if normalized_expected is not None and cnpj != normalized_expected:
            raise CertificateError("A1 certificate holder does not match the expected CNPJ.")
        self._private_key = private_key
        self._certificate = certificate
        self._identity = CertificateIdentity(
            cnpj=cnpj,
            subject=certificate.subject.rfc4514_string(),
            serial_number=certificate.serial_number,
            valid_from=certificate.not_valid_before_utc,
            valid_until=certificate.not_valid_after_utc,
        )

    @classmethod
    def from_pkcs12(
        cls,
        payload: bytes,
        password: str,
        *,
        expected_cnpj: str | None = None,
        now: datetime | None = None,
    ) -> CertificateAdapter:
        if not payload or not password:
            raise CertificateError("PKCS#12 payload and password are required.")
        try:
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                payload, password.encode("utf-8")
            )
        except (TypeError, ValueError) as error:
            raise CertificateError("Unable to open the PKCS#12 certificate.") from error
        if certificate is None or not isinstance(private_key, rsa.RSAPrivateKey):
            raise CertificateError("PKCS#12 must contain an RSA private key and certificate.")
        return cls(private_key, certificate, expected_cnpj=expected_cnpj, now=now)

    @property
    def identity(self) -> CertificateIdentity:
        return self._identity

    def sign_xml(self, xml: bytes, *, reference_uri: str) -> bytes:
        reference = reference_uri.strip()
        if not reference.startswith("#") or len(reference) == 1:
            raise CertificateError("XMLDSig reference URI must target a local XML ID.")
        try:
            root = SafeElementTree.fromstring(xml)
        except Exception as error:
            raise CertificateError("Fiscal XML is malformed or unsafe.") from error
        target_id = reference[1:]
        targets = [
            element
            for element in root.iter()
            if target_id in {element.get("Id"), element.get("ID"), element.get("id")}
        ]
        if len(targets) != 1:
            raise CertificateError("XMLDSig reference must resolve to exactly one element.")
        digest = base64.b64encode(sha256(_canonical(targets[0])).digest()).decode("ascii")
        signature = ElementTree.Element(f"{{{DS}}}Signature")
        signed_info = ElementTree.SubElement(signature, f"{{{DS}}}SignedInfo")
        ElementTree.SubElement(
            signed_info, f"{{{DS}}}CanonicalizationMethod", Algorithm=EXCLUSIVE_C14N
        )
        ElementTree.SubElement(
            signed_info, f"{{{DS}}}SignatureMethod", Algorithm=RSA_SHA256
        )
        reference_node = ElementTree.SubElement(
            signed_info, f"{{{DS}}}Reference", URI=reference
        )
        transforms = ElementTree.SubElement(reference_node, f"{{{DS}}}Transforms")
        ElementTree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=ENVELOPED)
        ElementTree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=EXCLUSIVE_C14N)
        ElementTree.SubElement(reference_node, f"{{{DS}}}DigestMethod", Algorithm=SHA256)
        ElementTree.SubElement(reference_node, f"{{{DS}}}DigestValue").text = digest
        signed = self._private_key.sign(
            _canonical(signed_info), padding.PKCS1v15(), hashes.SHA256()
        )
        ElementTree.SubElement(signature, f"{{{DS}}}SignatureValue").text = base64.b64encode(
            signed
        ).decode("ascii")
        key_info = ElementTree.SubElement(signature, f"{{{DS}}}KeyInfo")
        x509_data = ElementTree.SubElement(key_info, f"{{{DS}}}X509Data")
        ElementTree.SubElement(x509_data, f"{{{DS}}}X509Certificate").text = base64.b64encode(
            self._certificate.public_bytes(serialization.Encoding.DER)
        ).decode("ascii")
        root.append(signature)
        return bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))


def _canonical(element: ElementTree.Element) -> bytes:
    serialized = ElementTree.tostring(element, encoding="unicode")
    return ElementTree.canonicalize(xml_data=serialized).encode("utf-8")


def _certificate_cnpj(certificate: x509.Certificate) -> str:
    candidates = [attribute.value for attribute in certificate.subject]
    for value in candidates:
        match = re.search(r"(?<!\d)(\d{14})(?!\d)", str(value))
        if match is not None:
            return _cnpj(match.group(1))
    raise CertificateError("A1 certificate does not expose the holder CNPJ.")


def _cnpj(value: str) -> str:
    normalized = "".join(character for character in value if character.isdigit())
    if len(normalized) != 14:
        raise CertificateError("CNPJ must contain 14 digits.")
    return normalized


__all__ = ["CertificateAdapter", "CertificateError", "CertificateIdentity"]
