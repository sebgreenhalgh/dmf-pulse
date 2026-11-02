"""Public-key verification of reviewed releases; private signing is engineering-only.

The verifier implements the exact RSA3072/SHA256 EMSA-PKCS1-v1_5 encoding from
RFC8017. It accepts no alternate digest, key size, padding or trailing bytes.
No key, file, process or native credential operation occurs at import.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.operation.models import Metadata, OperationError, Ref, Sha

_KEY_BYTES = 384
_DOMAIN = b"DMF-PULSE-OPERATOR-RELEASE-V1\0"
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _decode(value: str, expected_length: int) -> bytes:
    try:
        body = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise OperationError("RELEASE_SIGNATURE_ENCODING_INVALID") from None
    if len(body) != expected_length or base64.b64encode(body).decode("ascii") != value:
        raise OperationError("RELEASE_SIGNATURE_ENCODING_INVALID")
    return body


class ReviewPublicKey(Metadata):
    algorithm: Literal["RSA3072_SHA256_PKCS1_V1_5"] = "RSA3072_SHA256_PKCS1_V1_5"
    modulus_b64: Annotated[str, Field(min_length=512, max_length=512)]
    exponent: Literal[65537] = 65537

    @field_validator("exponent", mode="before")
    @classmethod
    def exact_exponent(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("review key exponent requires an exact integer")
        return value

    @model_validator(mode="after")
    def exact_key(self) -> Self:
        modulus = int.from_bytes(_decode(self.modulus_b64, _KEY_BYTES), "big")
        if modulus.bit_length() != 3072 or modulus % 2 != 1:
            raise ValueError("review public key must be RSA3072")
        return self

    @property
    def fingerprint_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class ReleaseManifest(Metadata):
    schema_version: Literal["operator-reviewed-release-v1"] = "operator-reviewed-release-v1"
    wheel_sha256: Sha
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    protected_numerical_sha256: Sha
    material_policy_sha256: Sha
    owner_acceptance_sha256: Sha
    original_ledger_id: Sha
    independent_review_sha256: Sha
    installation_inventory_sha256: Sha
    reviewer_ref: Ref
    reviewed_at: datetime
    release_class: Literal["INITIAL_STANDING_INSTALL", "WITHIN_POLICY_COMPATIBILITY"]
    database_schema_revision: Literal["20261101_0010"] = "20261101_0010"
    test_evidence_sha256: Annotated[tuple[Sha, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_evidence(self) -> Self:
        if len(set(self.test_evidence_sha256)) != len(self.test_evidence_sha256):
            raise ValueError("release test evidence contains duplicates")
        return self


class SignedReleaseManifest(Metadata):
    schema_version: Literal["operator-signed-release-v1"] = "operator-signed-release-v1"
    manifest: ReleaseManifest
    review_public_key_sha256: Sha
    signature_b64: Annotated[str, Field(min_length=512, max_length=512)]


def release_signing_bytes(manifest: ReleaseManifest) -> bytes:
    checked = ReleaseManifest.model_validate(manifest)
    return _DOMAIN + canonical_json_bytes(checked.model_dump(mode="json"))


def verify_rsa_signature(key: ReviewPublicKey, message: bytes, signature_b64: str) -> bool:
    """No permissive ASN.1 parsing or partial-padding comparison is performed."""
    try:
        checked = ReviewPublicKey.model_validate(key)
        modulus = int.from_bytes(_decode(checked.modulus_b64, _KEY_BYTES), "big")
        signature = int.from_bytes(_decode(signature_b64, _KEY_BYTES), "big")
        if not 0 < signature < modulus:
            return False
        encoded = pow(signature, checked.exponent, modulus).to_bytes(_KEY_BYTES, "big")
        digest_info = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
        padding_length = _KEY_BYTES - len(digest_info) - 3
        expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
        return padding_length >= 8 and hmac.compare_digest(encoded, expected)
    except (OperationError, ValueError, TypeError, OverflowError):
        return False


def verify_signed_manifest(signed: SignedReleaseManifest, key: ReviewPublicKey) -> ReleaseManifest:
    signed = SignedReleaseManifest.model_validate(signed)
    key = ReviewPublicKey.model_validate(key)
    if signed.review_public_key_sha256 != key.fingerprint_sha256 or not verify_rsa_signature(
        key, release_signing_bytes(signed.manifest), signed.signature_b64
    ):
        raise OperationError("RELEASE_REVIEW_SIGNATURE_INVALID")
    return signed.manifest
