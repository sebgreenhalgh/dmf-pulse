"""Immutable rights-profile loading and fail-closed capability decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsDecision,
    RightsProfile,
    RightsProfileStatus,
)

PROFILE_RESOURCE = "ingestion/resources/fpl_profiles.json"


def _profile_bytes(path: Path | None = None) -> bytes:
    if path is not None:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise IngestionError(
                "CONFIGURATION_INVALID", "rights profile configuration is unavailable"
            ) from exc
    repository_candidate = Path(__file__).resolve().parents[3] / "config/rights/fpl_profiles.json"
    if repository_candidate.is_file():
        return repository_candidate.read_bytes()
    try:
        return resources.files("dmf_pulse").joinpath(PROFILE_RESOURCE).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "rights profile configuration is unavailable"
        ) from exc


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate rights registry key")
        value[key] = item
    return value


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _registry_value(path: Path | None = None) -> dict[str, object]:
    value = json.loads(
        _profile_bytes(path).decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("invalid profile registry")
    return value


def load_rights_profiles(path: Path | None = None) -> dict[str, RightsProfile]:
    try:
        value = _registry_value(path)
        if value.get("schema_version") != "1.0.0":
            raise ValueError("invalid profile registry")
        raw_profiles = value.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("invalid profile registry")
        profiles = [RightsProfile.model_validate(item, strict=False) for item in raw_profiles]
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "rights profile configuration is invalid"
        ) from exc
    result = {profile.rights_profile_id: profile for profile in profiles}
    if len(result) != len(profiles):
        raise IngestionError("CONFIGURATION_INVALID", "rights profile identifiers are duplicated")
    return result


def rights_config_sha256(path: Path | None = None) -> str:
    try:
        return canonical_sha256(_registry_value(path))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "rights profile configuration is invalid"
        ) from exc


def decide_rights(
    profile: RightsProfile,
    capability: RightsCapability,
    *,
    checked_at: datetime | None = None,
) -> RightsDecision:
    value = profile.capabilities[capability]
    approved = profile.status is RightsProfileStatus.HUMAN_APPROVED
    allowed = approved and value is CapabilityValue.ALLOW
    reason = (
        "CAPABILITY_ALLOWED"
        if allowed
        else "PROFILE_NOT_APPROVED"
        if not approved
        else "CAPABILITY_UNKNOWN_DENIED"
        if value is CapabilityValue.UNKNOWN
        else "CAPABILITY_DENIED"
    )
    return RightsDecision(
        profile_id=profile.rights_profile_id,
        profile_version=profile.profile_version,
        capability=capability.value,
        decision="ALLOW" if allowed else "DENY",
        reason=reason,
        checked_at=(checked_at or datetime.now(UTC)).astimezone(UTC),
    )


def require_rights(
    profile: RightsProfile,
    capability: RightsCapability,
    *,
    checked_at: datetime | None = None,
) -> RightsDecision:
    decision = decide_rights(profile, capability, checked_at=checked_at)
    if decision.decision != "ALLOW":
        raise IngestionError(
            "RIGHTS_BLOCKED",
            "operation is not permitted by the selected rights profile",
            details={
                "capability": capability.value,
                "decision": decision.model_dump(mode="json"),
                "transport_call_count": 0,
            },
        )
    return decision
