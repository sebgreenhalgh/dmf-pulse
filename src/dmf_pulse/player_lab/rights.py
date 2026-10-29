"""Closed trusted-source registry; caller assertions never confer retention rights."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from importlib.resources import files

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.rights import load_rights_profiles, require_rights
from dmf_pulse.player_lab.actuals import (
    ActualsError,
    ActualsQuality,
    FinalityContext,
    parse_actuals,
)
from dmf_pulse.player_lab.contracts import FinalPlayerOutcome, PlayerForecast, SourceRef


def profile_identity(profile: RightsProfile) -> str:
    payload = profile.model_dump(mode="json", exclude={"capabilities"})
    payload["capabilities"] = {
        key.value: value.value for key, value in profile.capabilities.items()
    }
    return canonical_sha256(payload)


def require_sources(sources: Iterable[SourceRef], capability: RightsCapability) -> None:
    profiles = load_rights_profiles()
    registry = json.loads(
        files("dmf_pulse.player_lab.resources")
        .joinpath("source-registry.json")
        .read_text(encoding="utf-8")
    )
    values = tuple(sources)
    if not values:
        raise ActualsError("SOURCE_LINEAGE_REQUIRED")
    for source in values:
        profile = profiles.get(source.profile_id)
        if profile is None or profile_identity(profile) != source.profile_sha256:
            raise ActualsError("SOURCE_PROFILE_NOT_AUTHENTICATED")
        require_rights(profile, capability)
        record = registry["sources"].get(source.source_id)
        if record is None or (
            source.profile_id != record["profile_id"]
            or source.payload_sha256 != record["payload_sha256"]
            or source.observed_at.isoformat() != record["observed_at"]
            or source.usable_at.isoformat() != record["usable_at"]
        ):
            raise ActualsError("SOURCE_NOT_IN_QUALIFIED_REGISTRY")
        body = files("dmf_pulse.player_lab.resources").joinpath(record["resource"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != record["payload_sha256"]:
            raise ActualsError("SOURCE_RESOURCE_IDENTITY_MISMATCH")


def ingest_offline_actuals(body: bytes, context: FinalityContext) -> ActualsQuality:
    require_sources((context.source,), RightsCapability.TRANSIENT_PROCESSING)
    registry = json.loads(
        files("dmf_pulse.player_lab.resources")
        .joinpath("source-registry.json")
        .read_text(encoding="utf-8")
    )
    record = registry["sources"][context.source.source_id]
    if hashlib.sha256(body).hexdigest() != context.source.payload_sha256 or canonical_sha256(
        context.model_dump(mode="json")
    ) != record.get("context_sha256"):
        raise ActualsError("ACTUALS_SOURCE_IDENTITY_MISMATCH")
    return parse_actuals(body, context)


def acquire_actuals(source: SourceRef, transport: Callable[[], bytes]) -> bytes:
    """No new live entitlement: the sole registered synthetic profile denies transport."""
    require_sources((source,), RightsCapability.AUTOMATED_ACCESS)
    return transport()


def require_qualified_outcome(label: FinalPlayerOutcome) -> None:
    """A source reference alone cannot authenticate different invented label values."""
    require_sources((label.source,), RightsCapability.DERIVED_STORAGE)
    root = files("dmf_pulse.player_lab.resources")
    registry = json.loads(root.joinpath("source-registry.json").read_text(encoding="utf-8"))
    record = registry["sources"][label.source.source_id]
    if "context_resource" not in record:
        raise ActualsError("LABEL_SOURCE_NOT_QUALIFIED")
    context = FinalityContext.model_validate_json(
        root.joinpath(record["context_resource"]).read_bytes()
    )
    quality = ingest_offline_actuals(root.joinpath(record["resource"]).read_bytes(), context)
    if label.semantic_sha256 not in {item.semantic_sha256 for item in quality.labels}:
        raise ActualsError("LABEL_VALUES_DIFFER_FROM_QUALIFIED_SOURCE")


def require_qualified_forecast(forecast: PlayerForecast) -> None:
    require_sources(forecast.sources, RightsCapability.DERIVED_STORAGE)
    registry = json.loads(
        files("dmf_pulse.player_lab.resources")
        .joinpath("source-registry.json")
        .read_text(encoding="utf-8")
    )
    if forecast.dataset_mode != "SYNTHETIC" or not any(
        forecast.semantic_sha256
        in registry["sources"][source.source_id].get("qualified_forecast_sha256s", [])
        for source in forecast.sources
    ):
        raise ActualsError("FORECAST_VALUES_NOT_QUALIFIED_FOR_RETENTION")
