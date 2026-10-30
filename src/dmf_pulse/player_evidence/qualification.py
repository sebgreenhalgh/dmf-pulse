"""Closed byte-authenticated owned-evidence qualification; no provider transport."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

from pydantic import ValidationError

from dmf_pulse.player_evidence.contracts import (
    EvidenceError,
    EvidenceSource,
    ParticipationDataset,
)

OWNED_SOURCE_ID = "accel003-owned-fixture-participation-v1"
OWNED_PAYLOAD_SHA256 = "6369d05ed2c4616d4029bd11e658749ea7180696b9032dd20f36dd2e4a097d0c"
OWNED_WYSCOUT_NATIVE_SHA256 = "566c3631f423c792e657ab5e38db858b611855ca8deead3332a2053789451aed"
OWNED_WYSCOUT_BINDINGS_SHA256 = "1f074333f89ce1b326db33491eca4a363aa13939c9745ff20491a8b58599ad61"
OWNED_WYSCOUT_PAYLOAD_SHA256 = "cdb1ec3a066e25e38cd6d66d34ea76c3b065217d16b2e59a384dd279d6b56dc3"
MAX_BODY_BYTES = 262_144


def owned_body() -> bytes:
    """Read only the packaged owned fixture on explicit invocation."""
    return (
        files("dmf_pulse.player_evidence.resources")
        .joinpath("owned-participation-v1.json")
        .read_bytes()
    )


def owned_source() -> EvidenceSource:
    return EvidenceSource(
        source_id=OWNED_SOURCE_ID,
        provider_id="dmf-owned-synthetic",
        payload_sha256=OWNED_PAYLOAD_SHA256,
        licence_id="REPOSITORY_OWNED_SYNTHETIC_ONLY",
        approval_id="DMF-PULSE-ACCEL-003#offline-evidence-acceptance",
        purpose="DESCRIPTIVE_EVIDENCE",
        mode="SYNTHETIC",
        qualification="OWNED_QUALIFIED",
    )


def _resource(name: str) -> bytes:
    return files("dmf_pulse.player_evidence.resources").joinpath(name).read_bytes()


def owned_wyscout_native_body() -> bytes:
    return _resource("owned-wyscout-native-v1.json")


def owned_wyscout_bindings_body() -> bytes:
    return _resource("owned-wyscout-bindings-v1.json")


def owned_wyscout_body() -> bytes:
    return _resource("owned-wyscout-participation-v1.json")


def _wyscout_owned_source(source_id: str, digest: str) -> EvidenceSource:
    return EvidenceSource(
        source_id=source_id,
        provider_id="dmf-owned-synthetic-wyscout-shape",
        payload_sha256=digest,
        licence_id="REPOSITORY_OWNED_SYNTHETIC_ONLY",
        approval_id="DMF-PULSE-ACCEL-004#owned-native-shape-only",
        purpose="DESCRIPTIVE_EVIDENCE",
        mode="SYNTHETIC",
        qualification="OWNED_QUALIFIED",
    )


def owned_wyscout_native_source() -> EvidenceSource:
    return _wyscout_owned_source("accel004-owned-wyscout-native-v1", OWNED_WYSCOUT_NATIVE_SHA256)


def owned_wyscout_source() -> EvidenceSource:
    return _wyscout_owned_source(
        "accel004-owned-wyscout-participation-v1", OWNED_WYSCOUT_PAYLOAD_SHA256
    )


def _authenticate_exact(body: bytes, expected: str, packaged: bytes) -> None:
    if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
        raise EvidenceError("EVIDENCE_BODY_BOUND_EXCEEDED")
    if hashlib.sha256(body).hexdigest() != expected:
        raise EvidenceError("SOURCE_BYTES_NOT_AUTHENTICATED")
    if len(packaged) > MAX_BODY_BYTES or hashlib.sha256(packaged).hexdigest() != expected:
        raise EvidenceError("PACKAGED_SOURCE_IDENTITY_CHANGED")


def authenticate_wyscout_native(body: bytes, source: EvidenceSource) -> None:
    """Only the exact fictional native fixture is admitted; real releases stay closed."""
    if source != owned_wyscout_native_source():
        raise EvidenceError("SOURCE_NOT_QUALIFIED_FOR_NATIVE_ADAPTER")
    _authenticate_exact(body, OWNED_WYSCOUT_NATIVE_SHA256, owned_wyscout_native_body())


def authenticate_source(body: bytes, source: EvidenceSource) -> None:
    """Reject unsupported source/purpose/bytes before parsing or feature construction."""
    if source == owned_wyscout_source():
        _authenticate_exact(body, OWNED_WYSCOUT_PAYLOAD_SHA256, owned_wyscout_body())
        _authenticate_exact(
            owned_wyscout_native_body(), OWNED_WYSCOUT_NATIVE_SHA256, owned_wyscout_native_body()
        )
        _authenticate_exact(
            owned_wyscout_bindings_body(),
            OWNED_WYSCOUT_BINDINGS_SHA256,
            owned_wyscout_bindings_body(),
        )
        return
    if source != owned_source():
        raise EvidenceError("SOURCE_NOT_QUALIFIED_FOR_DESCRIPTIVE_EVIDENCE")
    if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
        raise EvidenceError("EVIDENCE_BODY_BOUND_EXCEEDED")
    if hashlib.sha256(body).hexdigest() != OWNED_PAYLOAD_SHA256:
        raise EvidenceError("SOURCE_BYTES_NOT_AUTHENTICATED")
    if hashlib.sha256(owned_body()).hexdigest() != OWNED_PAYLOAD_SHA256:
        raise EvidenceError("PACKAGED_SOURCE_IDENTITY_CHANGED")


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate evidence JSON key")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise ValueError("non-integer evidence JSON number")


def decode_dataset(body: bytes) -> ParticipationDataset:
    """Validate schema only. This grants no rights and constructs no features."""
    if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
        raise EvidenceError("EVIDENCE_BODY_BOUND_EXCEEDED")
    try:
        value = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_number,
            parse_float=_reject_number,
        )
        pending: list[tuple[object, int]] = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 20:
                raise ValueError("evidence JSON depth exceeds bound")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        # JSON validation preserves strict JSON representations for UUID/datetime/tuples.
        return ParticipationDataset.model_validate_json(body)
    except (ValueError, TypeError, RecursionError, UnicodeError, ValidationError) as exc:
        raise EvidenceError("PARTICIPATION_SCHEMA_INVALID") from exc
