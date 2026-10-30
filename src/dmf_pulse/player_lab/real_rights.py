"""Real research uses the installed qualified-source boundary, never caller assertions."""

from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from typing import Literal

from pydantic import field_serializer, model_validator

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.rights import require_rights
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha
from dmf_pulse.player_lab.contracts import FinalPlayerOutcome, SourceRef
from dmf_pulse.player_lab.rights import profile_identity


class RealSourceQualification(Metadata):
    source: SourceRef
    profile: RightsProfile
    purpose: Literal["PLAYER_FORECAST_RETENTION_AND_EVALUATION"]
    source_classification: Literal["INDEPENDENTLY_QUALIFIED_REAL"]
    decision_ref: Ref
    independent_review_sha256: Sha
    terms_evidence_sha256: Sha
    qualified_at: datetime
    valid_until: datetime
    qualified_label_sha256s: tuple[Sha, ...] = ()
    qualified_population_sha256s: tuple[Sha, ...] = ()

    @model_validator(mode="after")
    def coherent_qualification(self) -> RealSourceQualification:
        if (
            self.qualified_at >= self.valid_until
            or self.qualified_at < self.source.usable_at
            or self.source.profile_id != self.profile.rights_profile_id
            or self.source.profile_sha256 != profile_identity(self.profile)
            or len(self.qualified_label_sha256s) != len(set(self.qualified_label_sha256s))
            or len(self.qualified_population_sha256s) != len(set(self.qualified_population_sha256s))
        ):
            raise ValueError("real source qualification is inconsistent")
        return self

    @field_serializer("profile", when_used="json")
    def profile_json(self, profile: RightsProfile) -> dict[str, object]:
        value = profile.model_dump(mode="json", exclude={"capabilities"})
        value["capabilities"] = {
            key.value: item.value for key, item in profile.capabilities.items()
        }
        return value


class HistoricalFreezeProof(Metadata):
    artifact_semantic_sha256: Sha
    artifact_kind: Literal["POINT_FORECAST", "DEADLINE_POPULATION"]
    original_artifact_format: Literal[
        "QUALIFIED_POINT_ADAPTER_V1", "PLAYER_FORECAST_V1", "DEADLINE_POPULATION_V1"
    ]
    original_semantic_sha256: Sha
    information_grade: Literal["LIVE_OBSERVED", "RAW_OBSERVED"] | None = None
    sources: tuple[SourceRef, ...]
    original_artifact_byte_sha256: Sha
    original_frozen_at: datetime
    external_predeadline_evidence_sha256: Sha
    independent_review_sha256: Sha
    accepted_at: datetime

    @model_validator(mode="after")
    def original_identity(self) -> HistoricalFreezeProof:
        population = self.artifact_kind == "DEADLINE_POPULATION"
        if (
            not self.sources
            or self.accepted_at < self.original_frozen_at
            or population != (self.original_artifact_format == "DEADLINE_POPULATION_V1")
            or (
                self.original_artifact_format == "PLAYER_FORECAST_V1"
                and self.information_grade is None
            )
            or (
                self.original_artifact_format != "PLAYER_FORECAST_V1"
                and self.original_semantic_sha256 != self.artifact_semantic_sha256
            )
        ):
            raise ValueError("historical original and admitted adapter identities required")
        return self


class AcceptedProtocolIntent(Metadata):
    intent_sha256: Sha
    owner_decision_ref: Ref
    independent_review_sha256: Sha
    accepted_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def acceptance_window(self) -> AcceptedProtocolIntent:
        if self.accepted_at >= self.expires_at:
            raise ValueError("accepted intent window is empty")
        return self


class RealSourceRegistry(Metadata):
    schema_version: Literal["qualified-real-player-sources-v1"] = "qualified-real-player-sources-v1"
    sources: tuple[RealSourceQualification, ...] = ()
    historical_freezes: tuple[HistoricalFreezeProof, ...] = ()
    accepted_protocol_intents: tuple[AcceptedProtocolIntent, ...] = ()

    @model_validator(mode="after")
    def unique_authority(self) -> RealSourceRegistry:
        for values in (
            tuple(row.source.source_id for row in self.sources),
            tuple(row.semantic_sha256 for row in self.historical_freezes),
            tuple(row.intent_sha256 for row in self.accepted_protocol_intents),
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate installed real authority")
        return self


def _registry_or_none() -> RealSourceRegistry | None:
    try:
        body = (
            files("dmf_pulse.player_lab.resources")
            .joinpath("real-source-registry.json")
            .read_bytes()
        )
        if len(body) > 4 * 1024 * 1024:
            return None

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate real source metadata")
                result[key] = value
            return result

        value = json.loads(body, object_pairs_hook=unique)
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "sources",
            "historical_freezes",
            "accepted_protocol_intents",
        }:
            return None
        return RealSourceRegistry.model_validate_json(json.dumps(value, allow_nan=False))
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def real_source_registry() -> RealSourceRegistry:
    result = _registry_or_none()
    if result is None:
        raise OperationError("REAL_PLAYER_SOURCE_REGISTRY_INVALID")
    return result


def require_real_sources(sources: tuple[SourceRef, ...], *, now: datetime) -> None:
    now = MetadataTime(checked_at=now).checked_at
    registry = real_source_registry()
    if not sources:
        raise OperationError("REAL_PLAYER_SOURCE_LINEAGE_REQUIRED")
    for source in sources:
        rows = [row for row in registry.sources if row.source == source]
        if len(rows) != 1:
            raise OperationError("REAL_PLAYER_SOURCE_NOT_QUALIFIED")
        row = rows[0]
        if (
            row.profile.provider_key.startswith("synthetic")
            or row.profile.rights_profile_id != source.profile_id
            or profile_identity(row.profile) != source.profile_sha256
            or not row.qualified_at <= now < row.valid_until
        ):
            raise OperationError("REAL_PLAYER_SOURCE_NOT_QUALIFIED")
        if (
            row.profile.approved_purpose != "PLAYER_FORECAST_RETENTION_AND_EVALUATION"
            or row.profile.retention_seconds is not None
            or row.profile.termination_deletion_required
        ):
            raise OperationError("REAL_PLAYER_IMMUTABLE_RETENTION_AND_PURPOSE_REQUIRED")
        denied = False
        for capability in (
            RightsCapability.DERIVED_STORAGE,
            RightsCapability.PRIVATE_INTERNAL_USE,
            RightsCapability.TRANSIENT_PROCESSING,
        ):
            try:
                require_rights(row.profile, capability, checked_at=now)
            except IngestionError:
                denied = True
                break
        if denied:
            raise OperationError("REAL_PLAYER_SOURCE_CAPABILITY_DENIED")


def require_real_population(source: SourceRef, population_sha256: str, *, now: datetime) -> None:
    require_real_sources((source,), now=now)
    rows = [row for row in real_source_registry().sources if row.source == source]
    if population_sha256 not in rows[0].qualified_population_sha256s:
        raise OperationError("REAL_PLAYER_COMPLETE_CATALOGUE_NOT_QUALIFIED")


def require_real_outcome(label: FinalPlayerOutcome, *, now: datetime) -> None:
    if label.dataset_mode != "PROSPECTIVE_REAL":
        raise OperationError("SYNTHETIC_PLAYER_LABEL_CANNOT_BE_REAL")
    require_real_sources((label.source,), now=now)
    rows = [row for row in real_source_registry().sources if row.source == label.source]
    if label.semantic_sha256 not in rows[0].qualified_label_sha256s:
        raise OperationError("REAL_PLAYER_LABEL_VALUES_NOT_QUALIFIED")
