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


def authenticate_source(body: bytes, source: EvidenceSource) -> None:
    """Reject unsupported source/purpose/bytes before parsing or feature construction."""
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
