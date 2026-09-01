"""Strict private-GW1 donor prior loading and current canonical identity binding.

The packaged values are preserved byte-for-byte from the immutable donor. Donor UUIDs are
verified as historical integrity evidence only; runtime profiles use explicit current Stage-7
UUIDs bound through the current official-FPL identity contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import resources
from math import isfinite
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    ParticipationScenario,
    PlayerAllocationProfile,
    PlayerPosition,
    PlayerPriorIdentity,
)

if TYPE_CHECKING:
    from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle

_RESOURCE_PACKAGE = "dmf_pulse.fpl_points.resources"
_PRIOR_RESOURCE = "gw1_private_player_allocation_prior_v1.json"
_ACCEPTANCE_RESOURCE = "gw1_private_player_allocation_acceptance_v1.json"
_DONOR_IDENTITY_NAMESPACE = UUID("7151293c-5b5d-5cc3-9689-c4e728ea8b55")
_DONOR_IDENTITY_VERSION = "gw1-current-availability-stage7-v1"
_DONOR_HEAD: Final[Literal["f4d75dc5b107901a3619f136c3d3d7d1d7632a3c"]] = (
    "f4d75dc5b107901a3619f136c3d3d7d1d7632a3c"
)
_CENTRAL_ARTIFACT_SHA256 = "629d6c288f9faa7aa7763f5c578e662511c03d514169f683cbeb6ee81af695be"
_ACCEPTANCE_SHA256 = "39737c6b96e2664f63f19b4ea0c34038d7c0ec5d9afc9f60cc1c6b89749a3352"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        canonical = str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a canonical UUID string") from exc
    if canonical != value:
        raise ValueError(f"{label} must be a canonical UUID string")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc_text(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


class PriceAdjustmentPolicy(_StrictModel):
    policy_version: Literal["GW1_PRICE_SPARSE_PRIOR_V1"]
    world: Literal["PRICE_OFF"]
    sparse_evidence_minutes: Annotated[float, Field(gt=0.0)]
    moderate_max_relative_adjustment: Annotated[float, Field(ge=0.0, le=1.0)]
    strong_max_relative_adjustment: Annotated[float, Field(ge=0.0, le=1.0)]
    parameter_status: Literal["TEMPORARY_CANDIDATE_PARAMETERS"]


class PlayerProfileLineage(_StrictModel):
    player_id: str
    source_player_id: Annotated[int, Field(gt=0)]
    goal_source_level: Literal["INDIVIDUAL", "TACTICAL_ROLE", "FPL_POSITION", "LEAGUE_GENERIC"]
    assist_source_level: Literal["INDIVIDUAL", "TACTICAL_ROLE", "FPL_POSITION", "LEAGUE_GENERIC"]
    auxiliary_source_level: Literal["INDIVIDUAL", "TACTICAL_ROLE", "FPL_POSITION", "LEAGUE_GENERIC"]
    fallback_reason: Annotated[str, Field(min_length=1, max_length=400)]
    prior_version: Annotated[str, Field(min_length=1)]
    limitations: tuple[str, ...]

    @field_validator("player_id")
    @classmethod
    def player_id_is_canonical(cls, value: str) -> str:
        return _canonical_uuid(value, label="lineage player_id")


class PlayerAllocationPriorArtifact(_StrictModel):
    schema_version: Literal["gw1-player-allocation-candidate-v1"]
    status: Literal["CANDIDATE_NOT_ACCEPTED"]
    information_cutoff: datetime
    posterior_artifact_sha256: Sha256
    price_policy: PriceAdjustmentPolicy
    degraded_player_allocation: bool
    profiles: Annotated[tuple[PlayerAllocationProfile, ...], Field(min_length=1)]
    lineage: Annotated[tuple[PlayerProfileLineage, ...], Field(min_length=1)]
    limitations: tuple[str, ...]
    artifact_sha256: Sha256

    @field_validator("information_cutoff")
    @classmethod
    def cutoff_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prior information cutoff must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def profiles_are_exact_and_hash_bound(self) -> Self:
        profile_ids = [profile.player_id for profile in self.profiles]
        lineage_ids = [lineage.player_id for lineage in self.lineage]
        source_ids = [lineage.source_player_id for lineage in self.lineage]
        for profile in self.profiles:
            _canonical_uuid(profile.player_id, label="profile player_id")
            _canonical_uuid(profile.team_id, label="profile team_id")
            numeric_values = (
                profile.goal_share,
                profile.assist_share,
                profile.penalty_taker_share,
                profile.own_goal_share,
                profile.goalkeeper_saves_per90,
                profile.yellow_cards_per90,
                profile.red_cards_per90,
                profile.clearances_per90,
                profile.blocks_per90,
                profile.interceptions_per90,
                profile.tackles_per90,
                profile.ball_recoveries_per90,
                *tuple(profile.bps_auxiliary.model_dump(mode="python").values()),
            )
            if not all(
                isinstance(item, (int, float)) and isfinite(item) for item in numeric_values
            ):
                raise ValueError("prior profile contains a non-finite numeric value")
        if (
            profile_ids != sorted(profile_ids)
            or lineage_ids != sorted(lineage_ids)
            or len(profile_ids) != len(set(profile_ids))
            or len(lineage_ids) != len(set(lineage_ids))
            or len(source_ids) != len(set(source_ids))
            or profile_ids != lineage_ids
        ):
            raise ValueError("prior profiles and lineage must be unique, sorted, and one-to-one")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected:
            raise ValueError("player prior artifact hash is invalid")
        if self.artifact_sha256 != _CENTRAL_ARTIFACT_SHA256:
            raise ValueError("player prior is not the pinned donor central overlay")
        return self


class AcceptedArtifacts(_StrictModel):
    catalogue_semantic_sha256: Sha256
    central_allocation_sha256: Sha256
    central_posterior_sha256: Sha256
    high_allocation_sha256: Sha256
    low_allocation_sha256: Sha256
    penalty_assignment_artifact_sha256: Sha256
    penalty_role_receipt_sha256: Sha256
    sensitivity_artifact_sha256: Sha256


class ClassificationCounts(_StrictModel):
    CLEAR_PRIMARY: Annotated[int, Field(ge=0)]
    MULTIPLE_CANDIDATES: Annotated[int, Field(ge=0)]
    PRIMARY_WITH_BACKUP: Annotated[int, Field(ge=0)]
    UNKNOWN: Annotated[int, Field(ge=0)]


class IdentityCoverage(_StrictModel):
    expected_player_count: Annotated[int, Field(gt=0)]
    expected_team_count: Annotated[int, Field(gt=0)]
    player_count: Annotated[int, Field(gt=0)]
    team_count: Annotated[int, Field(gt=0)]
    unresolved_mapping_count: Annotated[int, Field(ge=0)]


class AcceptanceInvariants(_StrictModel):
    penalty_responsibility_affects_penalty_taker_share_only: Literal[True]
    raw_official_fpl_history_persisted: Literal[False]
    role_override_count: Annotated[int, Field(ge=0)]
    stage7_expected_minutes_separate: Literal[True]
    zero_exposure_discipline_lineage_preserved: Literal[True]


class AcceptedLimitations(_StrictModel):
    blocks_and_ball_recoveries_incompletely_calibrated: Literal[True]
    defensive_contribution_model_completeness: Literal["PARTIAL"]
    maximum_goal_or_assist_share_movement: Annotated[float, Field(ge=0.0)]
    players_at_or_above_0_02_goal_or_assist_threshold: Annotated[int, Field(ge=0)]
    sensitivity_disclosed: Literal[True]


class AcceptanceValidation(_StrictModel):
    conclusion: Literal["SUCCESS"]
    head_sha: GitSha
    run_id: Annotated[int, Field(gt=0)]
    run_url: Annotated[str, Field(pattern=r"^https://github\.com/.+/actions/runs/\d+$")]


class PlayerPriorHistoricalAcceptance(_StrictModel):
    schema_version: Literal["gw1-player-allocation-human-acceptance-v1"]
    status: Literal["HUMAN_ACCEPTED_PRIVATE_GW1_ONLY"]
    accepted_scope: Literal["PRIVATE_2026_27_GW1_ONLY"]
    acceptance_source: Literal["USER_DIRECTIVE"]
    accepted_at: str
    implementation_sha: GitSha
    accepted_artifacts: AcceptedArtifacts
    identity_coverage: IdentityCoverage
    classification_counts: ClassificationCounts
    invariants: AcceptanceInvariants
    limitations_accepted: AcceptedLimitations
    validation: AcceptanceValidation
    production_activation: Literal[False]
    acceptance_sha256: Sha256

    @field_validator("accepted_at")
    @classmethod
    def accepted_at_is_utc(cls, value: str) -> str:
        _parse_utc_text(value, label="accepted_at")
        return value

    @model_validator(mode="after")
    def acceptance_is_exact_and_hash_bound(self) -> Self:
        if (
            self.accepted_artifacts.central_allocation_sha256 != _CENTRAL_ARTIFACT_SHA256
            or self.identity_coverage.player_count != self.identity_coverage.expected_player_count
            or self.identity_coverage.team_count != self.identity_coverage.expected_team_count
            or self.identity_coverage.unresolved_mapping_count != 0
        ):
            raise ValueError("historical acceptance coverage does not bind the central overlay")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"acceptance_sha256"}))
        if self.acceptance_sha256 != expected or self.acceptance_sha256 != _ACCEPTANCE_SHA256:
            raise ValueError("historical player-prior acceptance hash is invalid")
        return self


class GovernedPlayerPrior(_StrictModel):
    donor_head: Literal["f4d75dc5b107901a3619f136c3d3d7d1d7632a3c"] = _DONOR_HEAD
    artifact: PlayerAllocationPriorArtifact
    historical_acceptance: PlayerPriorHistoricalAcceptance

    @model_validator(mode="after")
    def acceptance_matches_artifact(self) -> Self:
        if (
            self.historical_acceptance.accepted_artifacts.central_allocation_sha256
            != self.artifact.artifact_sha256
        ):
            raise ValueError("historical acceptance does not bind the loaded player prior")
        return self


class PlayerPriorIdentityEntry(_StrictModel):
    current_player_id: str
    current_team_id: str
    position: PlayerPosition
    source_player_id: Annotated[int, Field(gt=0)]
    source_team_id: Annotated[int, Field(gt=0)]
    source_player_identity_sha256: Sha256
    source_team_identity_sha256: Sha256
    donor_player_id: str
    donor_team_id: str

    @field_validator("current_player_id", "current_team_id", "donor_player_id", "donor_team_id")
    @classmethod
    def ids_are_canonical(cls, value: str, info: Any) -> str:
        return _canonical_uuid(value, label=str(info.field_name))


class PlayerPriorIdentityBinding(_StrictModel):
    schema_version: Literal["current-player-prior-identity-binding-v1"] = (
        "current-player-prior-identity-binding-v1"
    )
    source_bundle_sha256: Sha256
    source_bootstrap_sha256: Sha256
    prior_artifact_sha256: Sha256
    historical_acceptance_sha256: Sha256
    entries: Annotated[tuple[PlayerPriorIdentityEntry, ...], Field(min_length=1)]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def binding_is_unique_sorted_and_hash_bound(self) -> Self:
        current_players = [entry.current_player_id for entry in self.entries]
        current_teams = [entry.current_team_id for entry in self.entries]
        source_players = [entry.source_player_id for entry in self.entries]
        donor_players = [entry.donor_player_id for entry in self.entries]
        if (
            current_players != sorted(current_players)
            or len(current_players) != len(set(current_players))
            or len(source_players) != len(set(source_players))
            or len(donor_players) != len(set(donor_players))
            or len(set(current_teams)) > len({entry.source_team_id for entry in self.entries})
        ):
            raise ValueError("player-prior identity binding is ambiguous or unsorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"semantic_sha256"}))
        if self.semantic_sha256 != expected:
            raise ValueError("player-prior identity binding hash is invalid")
        return self


class CurrentGwPriorFallbackAssignment(_StrictModel):
    """One explicit operator selection of an existing position-fallback donor profile."""

    current_official_fpl_element_id: Annotated[int, Field(gt=0)]
    fallback_official_fpl_element_id: Annotated[int, Field(gt=0)]
    fallback_level: Literal["FPL_POSITION"] = "FPL_POSITION"
    operator_reason: Annotated[str, Field(min_length=1, max_length=400)]


class CurrentGwStalePriorCarryForwardPolicy(_StrictModel):
    """Distinct non-acceptance policy for stale GW1 evidence after the first Gameweek."""

    schema_version: Literal["private-current-gw-stale-prior-carry-forward-v1"] = (
        "private-current-gw-stale-prior-carry-forward-v1"
    )
    policy_id: Literal["PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"] = (
        "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"
    )
    target_gameweek: Annotated[int, Field(gt=1)]
    current_fpl_bundle_sha256: Sha256
    prior_artifact_sha256: Sha256
    historical_acceptance_sha256: Sha256
    original_evidence_cutoff: datetime
    evidence_grade: Literal["E"] = "E"
    source_artifact_status: Literal["CANDIDATE_NOT_ACCEPTED"] = "CANDIDATE_NOT_ACCEPTED"
    historical_accepted_scope: Literal["PRIVATE_2026_27_GW1_ONLY"] = "PRIVATE_2026_27_GW1_ONLY"
    current_use_acceptance_coverage: Literal["NOT_COVERED_BY_HISTORICAL_ACCEPTANCE"] = (
        "NOT_COVERED_BY_HISTORICAL_ACCEPTANCE"
    )
    current_player_history_created: Literal[False] = False
    production_activation: Literal[False] = False
    declared_at: datetime
    fallback_assignments: tuple[CurrentGwPriorFallbackAssignment, ...] = ()
    semantic_sha256: Sha256

    @field_validator("original_evidence_cutoff", "declared_at")
    @classmethod
    def policy_times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("carry-forward policy timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def policy_is_canonical_and_sealed(self) -> Self:
        current_ids = tuple(
            item.current_official_fpl_element_id for item in self.fallback_assignments
        )
        if current_ids != tuple(sorted(current_ids)) or len(current_ids) != len(set(current_ids)):
            raise ValueError("carry-forward fallback assignments must be unique and sorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"semantic_sha256"}))
        if self.semantic_sha256 != expected:
            raise ValueError("carry-forward policy semantic hash is invalid")
        return self


def seal_current_gw_stale_prior_policy(
    value: CurrentGwStalePriorCarryForwardPolicy,
) -> CurrentGwStalePriorCarryForwardPolicy:
    payload = value.model_dump(mode="python")
    payload["semantic_sha256"] = canonical_sha256(
        value.model_dump(mode="json", exclude={"semantic_sha256"})
    )
    return CurrentGwStalePriorCarryForwardPolicy.model_validate(payload)


def build_automatic_current_gw_stale_prior_policy(
    prior: GovernedPlayerPrior,
    current_fpl: CurrentFplInputBundle,
    *,
    current_official_fpl_element_ids: tuple[int, ...],
    declared_at: datetime,
) -> CurrentGwStalePriorCarryForwardPolicy:
    """Deterministically assign only required accepted position-fallback donor profiles."""

    current_players = {item.provider_element_id: item for item in current_fpl.players}
    donor_profiles = {item.player_id: item for item in prior.artifact.profiles}
    donor_lineage = {item.source_player_id: item for item in prior.artifact.lineage}
    fallback_by_position: dict[str, int] = {}
    for source_id, lineage in sorted(donor_lineage.items()):
        source_player = current_players.get(source_id)
        profile = donor_profiles.get(lineage.player_id)
        if (
            source_player is not None
            and profile is not None
            and {
                lineage.goal_source_level,
                lineage.assist_source_level,
                lineage.auxiliary_source_level,
            }
            == {"FPL_POSITION"}
        ):
            fallback_by_position.setdefault(source_player.position.value, source_id)
    assignments: list[CurrentGwPriorFallbackAssignment] = []
    for source_id in current_official_fpl_element_ids:
        current = current_players.get(source_id)
        if current is None:
            raise FplPointsError(
                "PLAYER_PRIOR_MISSING", "automatic prior scope contains an unknown player"
            )
        current_lineage = donor_lineage.get(source_id)
        profile = (
            donor_profiles.get(current_lineage.player_id) if current_lineage is not None else None
        )
        exact = (
            current_lineage is not None
            and profile is not None
            and current_lineage.player_id
            == _donor_transient_id("player", current.identity.canonical_lookup_sha256)
            and profile.team_id
            == _donor_transient_id("team", current.team_identity.canonical_lookup_sha256)
        )
        if exact:
            continue
        fallback_id = fallback_by_position.get(current.position.value)
        if fallback_id is None:
            raise FplPointsError(
                "PLAYER_PRIOR_FALLBACK_UNAVAILABLE",
                "no governed position fallback is available for a current player",
            )
        assignments.append(
            CurrentGwPriorFallbackAssignment(
                current_official_fpl_element_id=source_id,
                fallback_official_fpl_element_id=fallback_id,
                operator_reason=(
                    "PRIVATE-V1-ONE-COMMAND-001A deterministic same-position carry-forward; "
                    "no current player history is created."
                ),
            )
        )
    return seal_current_gw_stale_prior_policy(
        CurrentGwStalePriorCarryForwardPolicy.model_construct(
            target_gameweek=current_fpl.target_gameweek,
            current_fpl_bundle_sha256=current_fpl.semantic_sha256,
            prior_artifact_sha256=prior.artifact.artifact_sha256,
            historical_acceptance_sha256=prior.historical_acceptance.acceptance_sha256,
            original_evidence_cutoff=prior.artifact.information_cutoff,
            declared_at=declared_at,
            fallback_assignments=tuple(assignments),
            semantic_sha256="0" * 64,
        )
    )


class CurrentGwPlayerPriorBindingEntry(_StrictModel):
    current_player_id: str
    current_team_id: str
    position: PlayerPosition
    source_player_id: Annotated[int, Field(gt=0)]
    source_team_id: Annotated[int, Field(gt=0)]
    source_player_identity_sha256: Sha256
    source_team_identity_sha256: Sha256
    assignment_level: Literal["INDIVIDUAL_SAME_TEAM", "FPL_POSITION_FALLBACK"]
    donor_source_player_id: Annotated[int, Field(gt=0)]
    donor_player_id: str
    donor_team_id: str

    @field_validator("current_player_id", "current_team_id", "donor_player_id", "donor_team_id")
    @classmethod
    def current_binding_ids_are_canonical(cls, value: str, info: Any) -> str:
        return _canonical_uuid(value, label=str(info.field_name))


class CurrentGwPlayerPriorBinding(_StrictModel):
    schema_version: Literal["current-gw-player-prior-carry-forward-binding-v1"] = (
        "current-gw-player-prior-carry-forward-binding-v1"
    )
    policy_id: Literal["PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"]
    policy_sha256: Sha256
    source_bundle_sha256: Sha256
    source_bootstrap_sha256: Sha256
    prior_artifact_sha256: Sha256
    historical_acceptance_sha256: Sha256
    entries: Annotated[tuple[CurrentGwPlayerPriorBindingEntry, ...], Field(min_length=1)]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def binding_is_unique_sorted_and_hash_bound(self) -> Self:
        current_players = tuple(entry.current_player_id for entry in self.entries)
        source_players = tuple(entry.source_player_id for entry in self.entries)
        if (
            current_players != tuple(sorted(current_players))
            or len(current_players) != len(set(current_players))
            or len(source_players) != len(set(source_players))
        ):
            raise ValueError("current-GW player-prior binding is ambiguous or unsorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"semantic_sha256"}))
        if self.semantic_sha256 != expected:
            raise ValueError("current-GW player-prior binding hash is invalid")
        return self


def _strict_json_bytes(value: bytes | str | Mapping[str, object], *, code: str) -> bytes:
    try:
        if isinstance(value, bytes):
            encoded = value
        elif isinstance(value, str):
            encoded = value.encode("utf-8")
        else:
            encoded = json.dumps(
                dict(value),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        raw: object = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FplPointsError(code, "player-prior resource is malformed") from exc
    if not isinstance(raw, dict):
        raise FplPointsError(code, "player-prior resource must be a JSON object")
    return encoded


def parse_player_prior(value: bytes | str | Mapping[str, object]) -> PlayerAllocationPriorArtifact:
    try:
        return PlayerAllocationPriorArtifact.model_validate_json(
            _strict_json_bytes(value, code="PLAYER_PRIOR_INVALID"), strict=True
        )
    except (ValidationError, ValueError) as exc:
        raise FplPointsError(
            "PLAYER_PRIOR_INVALID", "player prior failed strict validation"
        ) from exc


def parse_player_prior_acceptance(
    value: bytes | str | Mapping[str, object],
) -> PlayerPriorHistoricalAcceptance:
    try:
        return PlayerPriorHistoricalAcceptance.model_validate_json(
            _strict_json_bytes(value, code="PLAYER_PRIOR_ACCEPTANCE_INVALID"), strict=True
        )
    except (ValidationError, ValueError) as exc:
        raise FplPointsError(
            "PLAYER_PRIOR_ACCEPTANCE_INVALID",
            "historical player-prior acceptance failed strict validation",
        ) from exc


def load_packaged_player_prior() -> GovernedPlayerPrior:
    """Load the exact wheel-contained donor resources without filesystem assumptions."""

    try:
        package = resources.files(_RESOURCE_PACKAGE)
        artifact = parse_player_prior(package.joinpath(_PRIOR_RESOURCE).read_bytes())
        acceptance = parse_player_prior_acceptance(
            package.joinpath(_ACCEPTANCE_RESOURCE).read_bytes()
        )
        return GovernedPlayerPrior(artifact=artifact, historical_acceptance=acceptance)
    except FplPointsError:
        raise
    except (OSError, ModuleNotFoundError, ValidationError, ValueError) as exc:
        raise FplPointsError(
            "PLAYER_PRIOR_UNAVAILABLE", "packaged private player prior is unavailable"
        ) from exc


def _donor_transient_id(kind: Literal["player", "team"], identity_sha256: str) -> str:
    material = "\x1f".join((_DONOR_IDENTITY_VERSION, kind, identity_sha256))
    return str(uuid5(_DONOR_IDENTITY_NAMESPACE, material))


def _mapping_uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise FplPointsError("PLAYER_IDENTITY_MISMATCH", f"{label} must be a canonical UUID")
    try:
        return _canonical_uuid(value, label=label)
    except ValueError as exc:
        raise FplPointsError("PLAYER_IDENTITY_MISMATCH", str(exc)) from exc


def build_player_prior_identity_binding(
    prior: GovernedPlayerPrior,
    current_fpl: CurrentFplInputBundle,
    *,
    canonical_player_ids_by_source_id: Mapping[int, str],
    canonical_team_ids_by_source_id: Mapping[int, str],
) -> PlayerPriorIdentityBinding:
    """Bind a requested current-player subset without names, fuzzy matching, or fallback."""

    if (
        current_fpl.competition_key != "PL"
        or current_fpl.season_code != "2026/27"
        or current_fpl.target_gameweek != 1
    ):
        raise FplPointsError(
            "PLAYER_PRIOR_SCOPE_MISMATCH", "private donor prior is restricted to 2026/27 GW1"
        )
    if current_fpl.provenance.information_cutoff < prior.artifact.information_cutoff:
        raise FplPointsError(
            "PLAYER_PRIOR_POST_CUTOFF", "donor prior is later than the current information cutoff"
        )
    if not canonical_player_ids_by_source_id:
        raise FplPointsError("PLAYER_PRIOR_MISSING", "no current player identities were supplied")
    if any(
        isinstance(key, bool) or not isinstance(key, int)
        for key in canonical_player_ids_by_source_id
    ):
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH", "official-FPL player identity keys must be integers"
        )
    if any(
        isinstance(key, bool) or not isinstance(key, int) for key in canonical_team_ids_by_source_id
    ):
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH", "official-FPL team identity keys must be integers"
        )

    current_players = {player.provider_element_id: player for player in current_fpl.players}
    current_teams = {team.provider_team_id: team for team in current_fpl.teams}
    donor_profiles = {profile.player_id: profile for profile in prior.artifact.profiles}
    donor_lineage = {lineage.source_player_id: lineage for lineage in prior.artifact.lineage}
    entries: list[PlayerPriorIdentityEntry] = []
    required_team_ids: set[int] = set()
    for source_player_id, raw_current_player_id in canonical_player_ids_by_source_id.items():
        current_player = current_players.get(source_player_id)
        lineage = donor_lineage.get(source_player_id)
        if current_player is None or lineage is None:
            raise FplPointsError(
                "PLAYER_PRIOR_MISSING", "a requested official-FPL player has no exact donor prior"
            )
        donor_profile = donor_profiles[lineage.player_id]
        source_team_id = int(current_player.team_identity.external_id_text)
        current_team = current_teams.get(source_team_id)
        if current_team is None:
            raise FplPointsError(
                "PLAYER_IDENTITY_MISMATCH", "current player team is absent from current FPL input"
            )
        required_team_ids.add(source_team_id)
        raw_current_team_id = canonical_team_ids_by_source_id.get(source_team_id)
        if raw_current_team_id is None:
            raise FplPointsError(
                "PLAYER_IDENTITY_MISMATCH", "a requested player team has no canonical identity"
            )
        donor_player_id = _donor_transient_id(
            "player", current_player.identity.canonical_lookup_sha256
        )
        donor_team_id = _donor_transient_id(
            "team", current_player.team_identity.canonical_lookup_sha256
        )
        if donor_player_id != lineage.player_id or donor_profile.team_id != donor_team_id:
            raise FplPointsError(
                "PLAYER_IDENTITY_MISMATCH",
                "current official-FPL player/team identity differs from the donor prior",
            )
        if current_player.position.value != "GK" and donor_profile.goalkeeper_saves_per90 != 0.0:
            raise FplPointsError(
                "PLAYER_PRIOR_INVALID", "outfield donor profile contains goalkeeper save evidence"
            )
        entries.append(
            PlayerPriorIdentityEntry(
                current_player_id=_mapping_uuid(
                    raw_current_player_id, label="current player identity"
                ),
                current_team_id=_mapping_uuid(raw_current_team_id, label="current team identity"),
                position=PlayerPosition(current_player.position.value),
                source_player_id=source_player_id,
                source_team_id=source_team_id,
                source_player_identity_sha256=current_player.identity.canonical_lookup_sha256,
                source_team_identity_sha256=current_player.team_identity.canonical_lookup_sha256,
                donor_player_id=donor_player_id,
                donor_team_id=donor_team_id,
            )
        )
    if set(canonical_team_ids_by_source_id) != required_team_ids:
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH",
            "canonical team mapping must cover exactly the requested player teams",
        )
    ordered = tuple(sorted(entries, key=lambda entry: entry.current_player_id))
    body = {
        "schema_version": "current-player-prior-identity-binding-v1",
        "source_bundle_sha256": current_fpl.semantic_sha256,
        "source_bootstrap_sha256": current_fpl.provenance.bootstrap_semantic_sha256,
        "prior_artifact_sha256": prior.artifact.artifact_sha256,
        "historical_acceptance_sha256": prior.historical_acceptance.acceptance_sha256,
        "entries": ordered,
    }
    hash_body = {
        **body,
        "entries": tuple(entry.model_dump(mode="json") for entry in ordered),
    }
    try:
        return PlayerPriorIdentityBinding(
            schema_version="current-player-prior-identity-binding-v1",
            source_bundle_sha256=current_fpl.semantic_sha256,
            source_bootstrap_sha256=current_fpl.provenance.bootstrap_semantic_sha256,
            prior_artifact_sha256=prior.artifact.artifact_sha256,
            historical_acceptance_sha256=prior.historical_acceptance.acceptance_sha256,
            entries=ordered,
            semantic_sha256=canonical_sha256(hash_body),
        )
    except ValidationError as exc:
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH", "current player-prior identity binding is invalid"
        ) from exc


def build_current_gw_player_prior_binding(
    prior: GovernedPlayerPrior,
    current_fpl: CurrentFplInputBundle,
    policy: CurrentGwStalePriorCarryForwardPolicy,
    *,
    canonical_player_ids_by_source_id: Mapping[int, str],
    canonical_team_ids_by_source_id: Mapping[int, str],
) -> CurrentGwPlayerPriorBinding:
    """Bind stale evidence to current identities with explicit position fallbacks only."""

    if (
        current_fpl.competition_key != "PL"
        or current_fpl.season_code != "2026/27"
        or current_fpl.target_gameweek <= 1
    ):
        raise FplPointsError(
            "PLAYER_PRIOR_SCOPE_MISMATCH",
            "current-GW stale carry-forward is restricted to 2026/27 after GW1",
        )
    if (
        policy.target_gameweek != current_fpl.target_gameweek
        or policy.current_fpl_bundle_sha256 != current_fpl.semantic_sha256
        or policy.prior_artifact_sha256 != prior.artifact.artifact_sha256
        or policy.historical_acceptance_sha256 != prior.historical_acceptance.acceptance_sha256
        or policy.original_evidence_cutoff != prior.artifact.information_cutoff
        or policy.declared_at > current_fpl.provenance.information_cutoff
        or current_fpl.provenance.information_cutoff < prior.artifact.information_cutoff
    ):
        raise FplPointsError(
            "PLAYER_PRIOR_POLICY_MISMATCH",
            "stale carry-forward policy differs from its exact current or historical sources",
        )
    if not canonical_player_ids_by_source_id:
        raise FplPointsError("PLAYER_PRIOR_MISSING", "no current player identities were supplied")
    if any(
        isinstance(key, bool) or not isinstance(key, int)
        for key in canonical_player_ids_by_source_id
    ) or any(
        isinstance(key, bool) or not isinstance(key, int) for key in canonical_team_ids_by_source_id
    ):
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH", "official-FPL identity keys must be integers"
        )

    current_players = {player.provider_element_id: player for player in current_fpl.players}
    current_teams = {team.provider_team_id: team for team in current_fpl.teams}
    donor_profiles = {profile.player_id: profile for profile in prior.artifact.profiles}
    donor_lineage = {lineage.source_player_id: lineage for lineage in prior.artifact.lineage}
    assignments = {
        item.current_official_fpl_element_id: item for item in policy.fallback_assignments
    }
    entries: list[CurrentGwPlayerPriorBindingEntry] = []
    required_team_ids: set[int] = set()
    required_fallback_ids: set[int] = set()
    for source_player_id, raw_current_player_id in canonical_player_ids_by_source_id.items():
        current_player = current_players.get(source_player_id)
        if current_player is None:
            raise FplPointsError(
                "PLAYER_PRIOR_MISSING", "requested player is absent from current official FPL"
            )
        source_team_id = int(current_player.team_identity.external_id_text)
        current_team = current_teams.get(source_team_id)
        raw_current_team_id = canonical_team_ids_by_source_id.get(source_team_id)
        if current_team is None or raw_current_team_id is None:
            raise FplPointsError(
                "PLAYER_IDENTITY_MISMATCH", "requested current player team is not mapped exactly"
            )
        required_team_ids.add(source_team_id)
        lineage = donor_lineage.get(source_player_id)
        donor_profile = donor_profiles.get(lineage.player_id) if lineage is not None else None
        exact_player_id = _donor_transient_id(
            "player", current_player.identity.canonical_lookup_sha256
        )
        exact_team_id = _donor_transient_id(
            "team", current_player.team_identity.canonical_lookup_sha256
        )
        exact_relationship = (
            lineage is not None
            and donor_profile is not None
            and lineage.player_id == exact_player_id
            and donor_profile.team_id == exact_team_id
        )
        if exact_relationship:
            if source_player_id in assignments:
                raise FplPointsError(
                    "PLAYER_PRIOR_POLICY_MISMATCH",
                    "fallback was supplied for a valid same-team individual profile",
                )
            assert lineage is not None and donor_profile is not None
            donor_source_player_id = source_player_id
            assignment_level: Literal["INDIVIDUAL_SAME_TEAM", "FPL_POSITION_FALLBACK"] = (
                "INDIVIDUAL_SAME_TEAM"
            )
        else:
            assignment = assignments.get(source_player_id)
            if assignment is None:
                raise FplPointsError(
                    "PLAYER_PRIOR_FALLBACK_REQUIRED",
                    "current player requires an explicit governed position fallback",
                )
            required_fallback_ids.add(source_player_id)
            donor_source_player_id = assignment.fallback_official_fpl_element_id
            fallback_player = current_players.get(donor_source_player_id)
            fallback_lineage = donor_lineage.get(donor_source_player_id)
            if fallback_player is None or fallback_lineage is None:
                raise FplPointsError(
                    "PLAYER_PRIOR_FALLBACK_UNAVAILABLE",
                    "selected fallback donor is not a current player with governed lineage",
                )
            donor_profile = donor_profiles.get(fallback_lineage.player_id)
            if (
                donor_profile is None
                or fallback_player.position.value != current_player.position.value
                or {
                    fallback_lineage.goal_source_level,
                    fallback_lineage.assist_source_level,
                    fallback_lineage.auxiliary_source_level,
                }
                != {"FPL_POSITION"}
            ):
                raise FplPointsError(
                    "PLAYER_PRIOR_FALLBACK_UNAVAILABLE",
                    "selected donor is not a governed fallback for the same FPL position",
                )
            lineage = fallback_lineage
            assignment_level = "FPL_POSITION_FALLBACK"
        assert lineage is not None and donor_profile is not None
        entries.append(
            CurrentGwPlayerPriorBindingEntry(
                current_player_id=_mapping_uuid(
                    raw_current_player_id, label="current player identity"
                ),
                current_team_id=_mapping_uuid(raw_current_team_id, label="current team identity"),
                position=PlayerPosition(current_player.position.value),
                source_player_id=source_player_id,
                source_team_id=source_team_id,
                source_player_identity_sha256=current_player.identity.canonical_lookup_sha256,
                source_team_identity_sha256=current_player.team_identity.canonical_lookup_sha256,
                assignment_level=assignment_level,
                donor_source_player_id=donor_source_player_id,
                donor_player_id=lineage.player_id,
                donor_team_id=donor_profile.team_id,
            )
        )
    if set(canonical_team_ids_by_source_id) != required_team_ids:
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH",
            "canonical team mapping must cover exactly the requested current teams",
        )
    if not required_fallback_ids <= set(assignments):
        raise FplPointsError(
            "PLAYER_PRIOR_POLICY_MISMATCH",
            "fallback assignments do not cover the players requiring fallback",
        )
    ordered = tuple(sorted(entries, key=lambda entry: entry.current_player_id))
    body = {
        "schema_version": "current-gw-player-prior-carry-forward-binding-v1",
        "policy_id": policy.policy_id,
        "policy_sha256": policy.semantic_sha256,
        "source_bundle_sha256": current_fpl.semantic_sha256,
        "source_bootstrap_sha256": current_fpl.provenance.bootstrap_semantic_sha256,
        "prior_artifact_sha256": prior.artifact.artifact_sha256,
        "historical_acceptance_sha256": prior.historical_acceptance.acceptance_sha256,
        "entries": tuple(entry.model_dump(mode="json") for entry in ordered),
    }
    try:
        return CurrentGwPlayerPriorBinding(
            schema_version="current-gw-player-prior-carry-forward-binding-v1",
            policy_id=policy.policy_id,
            policy_sha256=policy.semantic_sha256,
            source_bundle_sha256=current_fpl.semantic_sha256,
            source_bootstrap_sha256=current_fpl.provenance.bootstrap_semantic_sha256,
            prior_artifact_sha256=prior.artifact.artifact_sha256,
            historical_acceptance_sha256=prior.historical_acceptance.acceptance_sha256,
            entries=ordered,
            semantic_sha256=canonical_sha256(body),
        )
    except ValidationError as exc:
        raise FplPointsError(
            "PLAYER_IDENTITY_MISMATCH", "current-GW player-prior binding is invalid"
        ) from exc


def bind_current_gw_fixture_allocation_profiles(
    prior: GovernedPlayerPrior,
    binding: CurrentGwPlayerPriorBinding,
    participation_scenarios: tuple[ParticipationScenario, ...],
) -> tuple[tuple[PlayerAllocationProfile, ...], PlayerPriorIdentity]:
    """Adapt exact or explicit fallback donor profiles to one current fixture."""

    if not participation_scenarios:
        raise FplPointsError("PLAYER_PRIOR_MISSING", "participation scenario set is empty")
    if (
        binding.prior_artifact_sha256 != prior.artifact.artifact_sha256
        or binding.historical_acceptance_sha256 != prior.historical_acceptance.acceptance_sha256
    ):
        raise FplPointsError(
            "PLAYER_PRIOR_TAMPERED", "carry-forward binding differs from the packaged prior"
        )
    expected: dict[str, tuple[str, PlayerPosition]] = {}
    for scenario in participation_scenarios:
        for participant in scenario.participants:
            fact = (participant.team_id, participant.position)
            previous = expected.setdefault(participant.player_id, fact)
            if previous != fact:
                raise FplPointsError(
                    "PLAYER_IDENTITY_MISMATCH", "Stage-7 player identity changes across scenarios"
                )
    entries = {entry.current_player_id: entry for entry in binding.entries}
    if set(entries) != set(expected):
        raise FplPointsError(
            "PLAYER_PRIOR_MISSING", "carry-forward binding does not cover the fixture exactly"
        )
    donor_profiles = {profile.player_id: profile for profile in prior.artifact.profiles}
    adapted: list[PlayerAllocationProfile] = []
    for current_player_id in sorted(expected):
        entry = entries[current_player_id]
        expected_team, expected_position = expected[current_player_id]
        if entry.current_team_id != expected_team or entry.position is not expected_position:
            raise FplPointsError(
                "PLAYER_IDENTITY_MISMATCH", "carry-forward binding differs from Stage-7 identity"
            )
        donor_profile = donor_profiles.get(entry.donor_player_id)
        if donor_profile is None:
            raise FplPointsError("PLAYER_PRIOR_MISSING", "bound donor profile is unavailable")
        payload = donor_profile.model_dump(mode="python")
        payload.update(player_id=current_player_id, team_id=expected_team)
        adapted.append(PlayerAllocationProfile.model_validate(payload))
    limitations = tuple(
        sorted(
            {
                *prior.artifact.limitations,
                "CURRENT_GW_USE_NOT_COVERED_BY_HISTORICAL_GW1_ACCEPTANCE",
                "CURRENT_PLAYER_HISTORY_NOT_CREATED",
                "HISTORICAL_GW1_PRIOR_CUTOFF_2026_08_21",
                "PLAYER_ALLOCATION_PRIOR_GRADE_E_CANDIDATE_NOT_ACCEPTED",
                "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1",
                "NOT_PRODUCTION_ACTIVE",
            }
        )
    )
    identity = PlayerPriorIdentity(
        source_type="GOVERNED_STALE_CURRENT_GW_CARRY_FORWARD",
        artifact_schema_version=prior.artifact.schema_version,
        artifact_sha256=prior.artifact.artifact_sha256,
        historical_acceptance_schema_version=prior.historical_acceptance.schema_version,
        historical_acceptance_sha256=prior.historical_acceptance.acceptance_sha256,
        historical_acceptance_status=prior.historical_acceptance.status,
        accepted_scope=prior.historical_acceptance.accepted_scope,
        production_activation=False,
        information_cutoff_utc=_utc_text(prior.artifact.information_cutoff),
        current_fpl_bundle_sha256=binding.source_bundle_sha256,
        current_identity_binding_sha256=binding.semantic_sha256,
        confidence_grade="E",
        limitations=limitations,
    )
    return tuple(adapted), identity


def bind_fixture_allocation_profiles(
    prior: GovernedPlayerPrior,
    binding: PlayerPriorIdentityBinding,
    participation_scenarios: tuple[ParticipationScenario, ...],
) -> tuple[tuple[PlayerAllocationProfile, ...], PlayerPriorIdentity]:
    """Adapt donor profiles to one exact current Stage-7 participant universe."""

    if not participation_scenarios:
        raise FplPointsError("PLAYER_PRIOR_MISSING", "participation scenario set is empty")
    if (
        binding.prior_artifact_sha256 != prior.artifact.artifact_sha256
        or binding.historical_acceptance_sha256 != prior.historical_acceptance.acceptance_sha256
    ):
        raise FplPointsError(
            "PLAYER_PRIOR_TAMPERED", "identity binding does not match the loaded donor prior"
        )
    expected: dict[str, tuple[str, PlayerPosition]] = {}
    for scenario in participation_scenarios:
        for participant in scenario.participants:
            fact = (participant.team_id, participant.position)
            previous = expected.setdefault(participant.player_id, fact)
            if previous != fact:
                raise FplPointsError(
                    "PLAYER_IDENTITY_MISMATCH", "Stage-7 player identity changes across scenarios"
                )
    entries = {entry.current_player_id: entry for entry in binding.entries}
    if set(entries) != set(expected):
        raise FplPointsError(
            "PLAYER_PRIOR_MISSING",
            "player-prior binding must cover the Stage-7 participant universe exactly",
        )
    donor_profiles = {profile.player_id: profile for profile in prior.artifact.profiles}
    adapted: list[PlayerAllocationProfile] = []
    for current_player_id in sorted(expected):
        entry = entries[current_player_id]
        expected_team, expected_position = expected[current_player_id]
        if entry.current_team_id != expected_team or entry.position is not expected_position:
            raise FplPointsError(
                "PLAYER_IDENTITY_MISMATCH", "player-prior binding differs from Stage-7 identity"
            )
        donor_profile = donor_profiles[entry.donor_player_id]
        payload = donor_profile.model_dump(mode="python")
        payload.update(player_id=current_player_id, team_id=expected_team)
        adapted.append(PlayerAllocationProfile.model_validate(payload))
    limitations = tuple(
        sorted(
            {
                *prior.artifact.limitations,
                "DONOR_PRIVATE_ACCEPTANCE_IS_NOT_PORT_ACCEPTANCE",
                "HISTORICAL_GW1_PRIOR_CUTOFF_2026_08_21",
                "NOT_PRODUCTION_ACTIVE",
            }
        )
    )
    identity = PlayerPriorIdentity(
        source_type="GOVERNED_DONOR_PRIVATE_GW1",
        artifact_schema_version=prior.artifact.schema_version,
        artifact_sha256=prior.artifact.artifact_sha256,
        historical_acceptance_schema_version=prior.historical_acceptance.schema_version,
        historical_acceptance_sha256=prior.historical_acceptance.acceptance_sha256,
        historical_acceptance_status=prior.historical_acceptance.status,
        accepted_scope=prior.historical_acceptance.accepted_scope,
        production_activation=False,
        information_cutoff_utc=_utc_text(prior.artifact.information_cutoff),
        current_fpl_bundle_sha256=binding.source_bundle_sha256,
        current_identity_binding_sha256=binding.semantic_sha256,
        confidence_grade="E",
        limitations=limitations,
    )
    return tuple(adapted), identity


__all__ = [
    "CurrentGwPlayerPriorBinding",
    "CurrentGwPlayerPriorBindingEntry",
    "CurrentGwPriorFallbackAssignment",
    "CurrentGwStalePriorCarryForwardPolicy",
    "GovernedPlayerPrior",
    "PlayerAllocationPriorArtifact",
    "PlayerPriorHistoricalAcceptance",
    "PlayerPriorIdentityBinding",
    "bind_current_gw_fixture_allocation_profiles",
    "bind_fixture_allocation_profiles",
    "build_automatic_current_gw_stale_prior_policy",
    "build_current_gw_player_prior_binding",
    "build_player_prior_identity_binding",
    "load_packaged_player_prior",
    "parse_player_prior",
    "parse_player_prior_acceptance",
    "seal_current_gw_stale_prior_policy",
]
