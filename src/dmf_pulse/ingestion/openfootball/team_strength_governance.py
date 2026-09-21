"""Governed precursor contracts for CURRENT-TEAM-STRENGTH-001A.

This module validates rights-adjacent identity and policy artifacts only. It does not fit a
statistical model, produce fixture rates, or activate any downstream behavior.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError

IDENTITY_RESOURCE = "ingestion/resources/openfootball_historical_team_identity.json"
POLICY_RESOURCE = "ingestion/resources/current_team_strength_governance.json"
IDENTITY_REPOSITORY_PATH = "config/providers/openfootball_historical_team_identity.json"
POLICY_REPOSITORY_PATH = "config/models/current_team_strength_governance.json"

TEAM_STRENGTH_RIGHTS_PROFILE_ID = "openfootball_football_json_team_strength_v1"
TEAM_STRENGTH_APPROVAL_ID = "CURRENT-TEAM-STRENGTH-001A#openfootball_football_json_team_strength_v1"
IDENTITY_MAPPING_DECISION_ID = "CURRENT-TEAM-STRENGTH-001A-P0#historical-club-identity-v1"
IDENTITY_SOURCE_COMMIT = "40b3e1b7391932d133287115106304444bf297e1"
APPROVED_IDENTITY_SEMANTIC_SHA256 = (
    "b0c0a73f97f9369aea217db0fba31dcd41d52be8a597dc10741ef4bf2fa19876"
)
APPROVED_GOVERNANCE_SEMANTIC_SHA256 = (
    "ff04de46f08711d85fb0de24f5a9257618b82d7422ae349bff2e033d082f4d21"
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
SeasonCode = Annotated[str, Field(pattern=r"^20\d{2}/\d{2}$")]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


def _semantic_body(model: BaseModel, hash_field: str = "semantic_sha256") -> dict[str, Any]:
    return model.model_dump(mode="json", exclude={hash_field})


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _json_value(data: bytes) -> object:
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def _resource_bytes(name: str, repository_path: str, path: Path | None) -> bytes:
    if path is not None:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise IngestionError(
                "CONFIGURATION_INVALID", "governance artifact is unavailable"
            ) from exc
    candidate = Path(__file__).resolve().parents[4] / repository_path
    if candidate.is_file():
        try:
            return candidate.read_bytes()
        except OSError as exc:
            raise IngestionError(
                "CONFIGURATION_INVALID", "governance artifact is unavailable"
            ) from exc
    try:
        return resources.files("dmf_pulse").joinpath(name).read_bytes()
    except (OSError, ModuleNotFoundError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "governance artifact is unavailable") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class SourceSnapshotIdentity(_FrozenModel):
    commit_sha: CommitSha
    content_sha256: Sha256
    dataset_mode: Literal["RECONSTRUCTED"]
    path: str = Field(pattern=r"^20\d{2}-\d{2}/en\.1\.json$")
    season_code: SeasonCode
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.path != f"{self.season_code.replace('/', '-')}/en.1.json":
            raise ValueError("source snapshot path does not match season")
        if canonical_sha256(_semantic_body(self)) != self.semantic_sha256:
            raise ValueError("source snapshot semantic hash mismatch")
        return self


class SeasonScopedExternalIdentifier(_FrozenModel):
    external_id_text: str = Field(pattern=r"^[1-9]\d*$")
    mapping_method: Literal["MANUAL"]
    mapping_status: Literal["HUMAN_VERIFIED"]
    observed_display_name: str = Field(min_length=1, max_length=80)
    provider_key: Literal["official_fpl"]
    season_scope: Literal["2026/27"]


class CanonicalClubRegistration(_FrozenModel):
    canonical_name: str = Field(min_length=1, max_length=100)
    canonical_team_id: UUID
    canonical_team_identity_sha256: Sha256
    continuity_note: str = Field(min_length=1, max_length=160)
    current_fpl_external_identifier: SeasonScopedExternalIdentifier | None
    entity_type: Literal["TEAM"]
    evidence: tuple[str, ...] = Field(min_length=1)
    id_generation_method: Literal["NONDETERMINISTIC_UUIDV7_REGISTRATION"]
    openfootball_aliases: tuple[str, ...] = Field(min_length=1)
    registered_at: datetime
    registration_authority: Literal["CURRENT-TEAM-STRENGTH-001A-P0#historical-club-identity-v1"]
    season_membership: tuple[SeasonCode, ...] = Field(min_length=1)
    semantic_sha256: Sha256

    @field_validator("registered_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_registration(self) -> Self:
        if self.canonical_team_id.version != 7:
            raise ValueError("canonical team ID must be UUIDv7")
        if self.openfootball_aliases != tuple(sorted(set(self.openfootball_aliases))):
            raise ValueError("OpenFootball aliases must be unique and sorted")
        if self.season_membership != tuple(sorted(set(self.season_membership))):
            raise ValueError("season membership must be unique and sorted")
        identity = {
            "canonical_team_id": str(self.canonical_team_id),
            "entity_type": self.entity_type,
            "id_generation_method": self.id_generation_method,
            "registered_at": self.registered_at.isoformat().replace("+00:00", "Z"),
            "registration_authority": self.registration_authority,
        }
        if canonical_sha256(identity) != self.canonical_team_identity_sha256:
            raise ValueError("canonical team identity hash mismatch")
        if canonical_sha256(_semantic_body(self)) != self.semantic_sha256:
            raise ValueError("canonical club semantic hash mismatch")
        return self


class OpenFootballAliasMapping(_FrozenModel):
    canonical_team_id: UUID
    canonical_team_identity_sha256: Sha256
    decided_at: datetime
    evidence: tuple[str, ...] = Field(min_length=1)
    mapping_authority: Literal["Sebastian Greenhalgh"]
    mapping_decision_id: Literal["CURRENT-TEAM-STRENGTH-001A-P0#historical-club-identity-v1"]
    season_scope: tuple[SeasonCode, ...] = Field(min_length=1)
    source_identity_sha256: Sha256
    source_snapshot_identity: Sha256
    source_team_name: str = Field(min_length=1, max_length=100)
    semantic_sha256: Sha256

    @field_validator("decided_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        if self.canonical_team_id.version != 7:
            raise ValueError("mapping target must be UUIDv7")
        if self.source_team_name != self.source_team_name.strip():
            raise ValueError("source alias must preserve a bounded exact spelling")
        if self.season_scope != tuple(sorted(set(self.season_scope))):
            raise ValueError("mapping season scope must be unique and sorted")
        source_identity = {
            "competition": "English Premier League",
            "provider_key": "openfootball_football_json",
            "season_scope": list(self.season_scope),
            "source_team_name": self.source_team_name,
        }
        if canonical_sha256(source_identity) != self.source_identity_sha256:
            raise ValueError("source identity hash mismatch")
        if canonical_sha256(_semantic_body(self)) != self.semantic_sha256:
            raise ValueError("alias mapping semantic hash mismatch")
        return self


class OpenFootballHistoricalTeamIdentityV1(_FrozenModel):
    additional_alias_count: int = Field(ge=0)
    alias_count: int = Field(ge=0)
    ambiguous_mapping_count: int = Field(ge=0)
    canonical_club_count: int = Field(gt=0)
    canonical_clubs: tuple[CanonicalClubRegistration, ...]
    canonical_ordering: Literal["canonical_team_id,source_team_name,season_scope"]
    competition: Literal["English Premier League"]
    decided_at: datetime
    mapping_authority: Literal["Sebastian Greenhalgh"]
    mapping_decision_id: Literal["CURRENT-TEAM-STRENGTH-001A-P0#historical-club-identity-v1"]
    provider_key: Literal["openfootball_football_json"]
    record_count: int = Field(gt=0)
    records: tuple[OpenFootballAliasMapping, ...]
    root_semantic_sha256: Sha256
    schema_version: Literal["openfootball-historical-team-identity-v1"]
    seasons_covered: tuple[SeasonCode, ...]
    source_commit_sha: Literal["40b3e1b7391932d133287115106304444bf297e1"]
    source_snapshots: tuple[SourceSnapshotIdentity, ...]
    unresolved_club_count: int = Field(ge=0)

    @field_validator("decided_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_complete_registry(self) -> Self:
        if (
            self.canonical_club_count != 42
            or self.record_count != 56
            or self.alias_count != 56
            or self.additional_alias_count != 14
            or len(self.seasons_covered) != 17
            or self.unresolved_club_count != 0
            or self.ambiguous_mapping_count != 0
        ):
            raise ValueError("historical identity completeness counts are not accepted")
        if len(self.canonical_clubs) != self.canonical_club_count:
            raise ValueError("canonical club count mismatch")
        if len(self.records) != self.record_count:
            raise ValueError("alias record count mismatch")
        if len({item.source_team_name for item in self.records}) != self.alias_count:
            raise ValueError("source alias count mismatch")
        if len(self.source_snapshots) != len(self.seasons_covered):
            raise ValueError("source snapshot count mismatch")
        if self.seasons_covered != tuple(sorted(set(self.seasons_covered))):
            raise ValueError("covered seasons must be unique and sorted")
        if tuple(item.season_code for item in self.source_snapshots) != self.seasons_covered:
            raise ValueError("source snapshots must cover the exact ordered seasons")
        if any(item.commit_sha != self.source_commit_sha for item in self.source_snapshots):
            raise ValueError("source snapshot commit mismatch")

        clubs_by_id = {item.canonical_team_id: item for item in self.canonical_clubs}
        if len(clubs_by_id) != len(self.canonical_clubs):
            raise ValueError("different clubs cannot share a canonical ID")
        if tuple(str(item.canonical_team_id) for item in self.canonical_clubs) != tuple(
            sorted(str(item.canonical_team_id) for item in self.canonical_clubs)
        ):
            raise ValueError("canonical club registrations are not canonically ordered")
        expected_record_order = tuple(
            sorted(
                self.records,
                key=lambda item: (
                    str(item.canonical_team_id),
                    item.source_team_name,
                    item.season_scope,
                ),
            )
        )
        if self.records != expected_record_order:
            raise ValueError("alias records are not canonically ordered")

        snapshot_by_season = {item.season_code: item for item in self.source_snapshots}
        expanded: dict[tuple[str, str], UUID] = {}
        records_by_club: dict[UUID, list[OpenFootballAliasMapping]] = {
            team_id: [] for team_id in clubs_by_id
        }
        for record in self.records:
            club = clubs_by_id.get(record.canonical_team_id)
            if club is None:
                raise ValueError("mapping target is not a registered canonical club")
            if record.canonical_team_identity_sha256 != club.canonical_team_identity_sha256:
                raise ValueError("mapping target identity hash mismatch")
            if any(season not in snapshot_by_season for season in record.season_scope):
                raise ValueError("mapping references a season without a source snapshot")
            snapshots = [
                snapshot_by_season[season].semantic_sha256 for season in record.season_scope
            ]
            if canonical_sha256(snapshots) != record.source_snapshot_identity:
                raise ValueError("mapping snapshot identity mismatch")
            records_by_club[record.canonical_team_id].append(record)
            for season in record.season_scope:
                key = (season, record.source_team_name)
                if key in expanded:
                    raise ValueError("duplicate or ambiguous alias mapping")
                expanded[key] = record.canonical_team_id

        for team_id, club in clubs_by_id.items():
            club_records = records_by_club[team_id]
            aliases = tuple(sorted(item.source_team_name for item in club_records))
            seasons = tuple(
                sorted({season for item in club_records for season in item.season_scope})
            )
            if aliases != club.openfootball_aliases or seasons != club.season_membership:
                raise ValueError("club alias or season coverage is incomplete")

        fpl_ids = [
            item.current_fpl_external_identifier.external_id_text
            for item in self.canonical_clubs
            if item.current_fpl_external_identifier is not None
        ]
        if len(fpl_ids) != 20 or len(fpl_ids) != len(set(fpl_ids)):
            raise ValueError("current FPL external identifiers must be season-scoped and unique")
        if (
            canonical_sha256(_semantic_body(self, "root_semantic_sha256"))
            != self.root_semantic_sha256
        ):
            raise ValueError("identity root semantic hash mismatch")
        if self.root_semantic_sha256 != APPROVED_IDENTITY_SEMANTIC_SHA256:
            raise ValueError("historical identity is not the approved immutable artifact")
        return self


class HumanApprovalPolicy(_FrozenModel):
    approval_id: Literal["CURRENT-TEAM-STRENGTH-001A#openfootball_football_json_team_strength_v1"]
    approved_at: datetime
    approved_by: Literal["Sebastian Greenhalgh"]
    rights_profile_id: Literal["openfootball_football_json_team_strength_v1"]
    rights_profile_version: Literal["1.0.0"]

    @field_validator("approved_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class MaterialityPolicy(_FrozenModel):
    calibration_relative_harm_limit: Decimal
    player_xp_materiality_per_gw: Decimal
    production_promotion_requires_separate_human_approval: StrictBool
    prospective_min_gameweeks: int = Field(gt=0)
    prospective_min_labelled_fixtures: int = Field(gt=0)
    root_action_switch_always_material: StrictBool
    subgroup_relative_harm_limit: Decimal
    transfer_horizon_gameweeks: int = Field(gt=0)
    transfer_horizon_materiality_points: Decimal

    @model_validator(mode="after")
    def validate_locked_values(self) -> Self:
        if (
            self.calibration_relative_harm_limit != Decimal("0.01")
            or self.subgroup_relative_harm_limit != Decimal("0.01")
            or self.player_xp_materiality_per_gw != Decimal("0.15")
            or self.transfer_horizon_materiality_points != Decimal("0.50")
            or self.transfer_horizon_gameweeks != 3
            or self.prospective_min_gameweeks != 10
            or self.prospective_min_labelled_fixtures != 100
            or not self.root_action_switch_always_material
            or not self.production_promotion_requires_separate_human_approval
        ):
            raise ValueError("materiality policy differs from human approval")
        return self


class ParameterUncertaintyPolicy(_FrozenModel):
    covariance_retained: Literal[True]
    hessian_retained: Literal[True]
    plugin_prediction_status: Literal["SHADOW_ONLY"]
    uncertainty_ticket_required_before_production: Literal["CURRENT-TEAM-STRENGTH-001U"]


class SelectedShadowPolicy(_FrozenModel):
    attack_effective_prior_matches: Literal[12]
    decimal_boundary: Literal["SERIALIZED_RATE_AND_ARTIFACT_ONLY"]
    defence_effective_prior_matches: Literal[12]
    entrant_policy: Literal["HISTORICAL_PROMOTED_CLUB_COHORT_CENTRE"]
    fitting_algorithm: Literal["FLOAT64_ANALYTIC_DAMPED_NEWTON"]
    half_life_days: Literal[365]
    home_advantage: Literal["ONE_FITTED_GLOBAL_EFFECT"]
    maximum_output_rate: Decimal
    model_family: Literal["REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"]
    parameter_uncertainty: ParameterUncertaintyPolicy
    public_contract: Literal["INDEPENDENT_POISSON_V1_SCORE_PRIOR_REQUEST_UNCHANGED"]
    training_evidence: Literal["ALL_ELIGIBLE_RESULTS_STRICTLY_BEFORE_FORECAST_CUTOFF"]
    training_start_season: Literal["2010/11"]

    @field_validator("maximum_output_rate")
    @classmethod
    def validate_maximum_rate(cls, value: Decimal) -> Decimal:
        if value != Decimal("8.000000"):
            raise ValueError("maximum output rate differs from the approved policy")
        return value


class SourceFinalityPolicy(_FrozenModel):
    ambiguous_or_abandoned_action: Literal["QUARANTINE_PENDING_GOVERNED_RESOLUTION"]
    correction_policy: Literal["NEW_IMMUTABLE_DESCENDANT_NO_FROZEN_FORECAST_MUTATION"]
    eligibility_not_before: Literal["00:00:00Z_ON_SOURCE_MATCH_DATE_PLUS_2_CALENDAR_DAYS"]
    live_required_conditions: tuple[str, ...]
    match_date_lag_calendar_days: Literal[2]
    postponed_policy: Literal["REVISED_PLAYED_DATE_MUST_SATISFY_FULL_POLICY"]
    reconstructed_policy: Literal[
        "FINAL_CURRENT_VINTAGE_RECONSTRUCTED_ONLY_NO_HISTORICAL_AVAILABILITY_CLAIM"
    ]
    same_day_use_allowed: Literal[False]

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        expected = (
            "IMMUTABLE_COMMIT_AND_VALIDATED_FILE_HASH",
            "RECEIVED_AND_VALIDATED_BEFORE_CUTOFF",
            "RECEIVED_AT_NO_LATER_THAN_CUTOFF",
            "USABLE_AT_NO_LATER_THAN_CUTOFF",
            "EXACTLY_ONE_CANONICAL_FIXTURE_AND_TWO_CANONICAL_CLUBS",
            "RECOGNIZED_FULL_TIME_SCORE",
            "NO_NON_FINAL_STATUS",
            "UNKNOWN_NONEMPTY_STATUS_QUARANTINED",
            "ELIGIBILITY_LAG_SATISFIED",
        )
        if self.live_required_conditions != expected:
            raise ValueError("source finality conditions differ from approval")
        return self


class FreshStatePolicy(_FrozenModel):
    action: Literal["TEAM_STRENGTH_REFIT_ALLOWED"]
    maximum_retrieval_age_hours_inclusive: Literal[24]
    missing_due_must_equal: Literal[0]
    validation_must_pass: Literal[True]


class DegradedStatePolicy(_FrozenModel):
    action: Literal["RETAIN_LATEST_SEALED_ARTIFACT_WITH_VISIBLE_WARNING_NO_CURRENT_REFIT_CLAIM"]
    maximum_retrieval_age_hours_inclusive: Literal[72]
    minimum_retrieval_age_hours_exclusive: Literal[24]
    missing_due_must_equal: Literal[0]
    validation_must_pass: Literal[True]


class StaleStatePolicy(_FrozenModel):
    action: Literal["NO_NEW_CURRENT_ARTIFACT_USE_GOVERNED_LEAGUE_PRIOR_FALLBACK_IF_LEGAL"]
    any_condition: tuple[str, ...]

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        expected = (
            "MISSING_DUE_GREATER_THAN_ZERO",
            "RETRIEVAL_AGE_GREATER_THAN_72_HOURS",
            "UNRESOLVED_CANONICAL_MAPPING",
            "AMBIGUOUS_STATUS",
            "INVALID_SCHEMA",
            "INVALID_SOURCE_LINEAGE",
        )
        if self.any_condition != expected:
            raise ValueError("stale source conditions differ from approval")
        return self


class SourceFreshnessPolicy(_FrozenModel):
    degraded: DegradedStatePolicy
    due_definition: Literal["SCHEDULED_ROWS_WITH_ELIGIBILITY_NOT_BEFORE_NO_LATER_THAN_CUTOFF"]
    fresh: FreshStatePolicy
    missing_due_definition: Literal["DUE_ROWS_WITHOUT_AN_ELIGIBLE_FINAL_SCORE"]
    repository_commit_age_alone_defines_freshness: Literal[False]
    retrieval_age_definition: Literal[
        "CUTOFF_MINUS_LATEST_SUCCESSFUL_USABLE_OPENFOOTBALL_SNAPSHOT_RETRIEVAL"
    ]
    stale_blocked: StaleStatePolicy


class StatisticalResearchEvidence(_FrozenModel):
    baseline_exact_score_log_loss: Decimal
    bootstrap_block: Literal["GAMEWEEK"]
    candidate_minus_baseline: Decimal
    classification: Literal["RECONSTRUCTED_OUT_OF_TIME_SHADOW_EVIDENCE"]
    confidence_interval_95: tuple[Decimal, Decimal]
    production_superiority_claimed: Literal[False]
    selected_exact_score_log_loss: Decimal

    @model_validator(mode="after")
    def validate_accepted_evidence(self) -> Self:
        if (
            self.baseline_exact_score_log_loss != Decimal("2.951989")
            or self.selected_exact_score_log_loss != Decimal("2.887816")
            or self.candidate_minus_baseline != Decimal("-0.064172")
            or self.confidence_interval_95 != (Decimal("-0.100400"), Decimal("-0.028708"))
        ):
            raise ValueError("statistical evidence differs from the approved research record")
        return self


class CurrentTeamStrengthGovernanceV1(_FrozenModel):
    human_approval: HumanApprovalPolicy
    materiality_policy: MaterialityPolicy
    model_implementation_present: Literal[False]
    production_active: Literal[False]
    schema_version: Literal["current-team-strength-governance-v1"]
    selected_shadow_policy: SelectedShadowPolicy
    semantic_sha256: Sha256
    source_finality_policy: SourceFinalityPolicy
    source_freshness_policy: SourceFreshnessPolicy
    statistical_research_evidence: StatisticalResearchEvidence
    status: Literal["GOVERNANCE_ONLY_NO_MODEL_IMPLEMENTATION"]
    ticket_id: Literal["CURRENT-TEAM-STRENGTH-001A-P0"]

    @model_validator(mode="after")
    def validate_semantic_identity(self) -> Self:
        if canonical_sha256(_semantic_body(self)) != self.semantic_sha256:
            raise ValueError("team-strength governance semantic hash mismatch")
        if self.semantic_sha256 != APPROVED_GOVERNANCE_SEMANTIC_SHA256:
            raise ValueError("team-strength governance is not the approved immutable artifact")
        return self


class SourceFreshnessState(StrEnum):
    FRESH = "FRESH"
    DEGRADED = "DEGRADED"
    STALE_BLOCKED = "STALE_BLOCKED"


def load_historical_team_identity(
    path: Path | None = None,
) -> OpenFootballHistoricalTeamIdentityV1:
    try:
        value = _json_value(_resource_bytes(IDENTITY_RESOURCE, IDENTITY_REPOSITORY_PATH, path))
        return OpenFootballHistoricalTeamIdentityV1.model_validate_json(
            json.dumps(value, allow_nan=False, ensure_ascii=False), strict=True
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "historical team identity artifact is invalid"
        ) from exc


def load_current_team_strength_governance(
    path: Path | None = None,
) -> CurrentTeamStrengthGovernanceV1:
    try:
        value = _json_value(_resource_bytes(POLICY_RESOURCE, POLICY_REPOSITORY_PATH, path))
        return CurrentTeamStrengthGovernanceV1.model_validate_json(
            json.dumps(value, allow_nan=False, ensure_ascii=False), strict=True
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "team-strength governance artifact is invalid"
        ) from exc


def resolve_openfootball_team(
    identity: OpenFootballHistoricalTeamIdentityV1,
    *,
    season_code: str,
    source_team_name: str,
) -> UUID:
    matches = [
        item.canonical_team_id
        for item in identity.records
        if item.source_team_name == source_team_name and season_code in item.season_scope
    ]
    if len(matches) != 1:
        raise IngestionError("MAPPING_FAILED", "OpenFootball team mapping is not exactly resolved")
    return matches[0]


def eligibility_not_before(match_date: date) -> datetime:
    return datetime.combine(match_date + timedelta(days=2), time.min, tzinfo=UTC)


def classify_source_freshness(
    *,
    cutoff: datetime,
    latest_successful_usable_retrieval: datetime,
    missing_due: int,
    canonical_mapping_valid: bool,
    status_unambiguous: bool,
    schema_valid: bool,
    source_lineage_valid: bool,
) -> SourceFreshnessState:
    cutoff_utc = _utc(cutoff)
    retrieval_utc = _utc(latest_successful_usable_retrieval)
    if missing_due < 0:
        raise ValueError("missing_due must be nonnegative")
    if retrieval_utc > cutoff_utc:
        return SourceFreshnessState.STALE_BLOCKED
    if (
        missing_due > 0
        or not canonical_mapping_valid
        or not status_unambiguous
        or not schema_valid
        or not source_lineage_valid
    ):
        return SourceFreshnessState.STALE_BLOCKED
    age = cutoff_utc - retrieval_utc
    if age > timedelta(hours=72):
        return SourceFreshnessState.STALE_BLOCKED
    if age > timedelta(hours=24):
        return SourceFreshnessState.DEGRADED
    return SourceFreshnessState.FRESH


__all__ = [
    "APPROVED_GOVERNANCE_SEMANTIC_SHA256",
    "APPROVED_IDENTITY_SEMANTIC_SHA256",
    "CurrentTeamStrengthGovernanceV1",
    "OpenFootballHistoricalTeamIdentityV1",
    "SourceFreshnessState",
    "classify_source_freshness",
    "eligibility_not_before",
    "load_current_team_strength_governance",
    "load_historical_team_identity",
    "resolve_openfootball_team",
]
