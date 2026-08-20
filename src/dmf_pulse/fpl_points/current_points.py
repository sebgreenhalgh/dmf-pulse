"""Governed transient current-player distributions from the accepted Stage 9.

This adapter is deliberately non-production.  It binds the Checkpoint-2.3
handoff to the exact verified target-season PLAYER_POINTS capability, executes
the accepted fixture service, and assembles its shared-draw Gameweek output.
It neither activates a ruleset nor persists official-FPL raw or derived data.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability import current_player_id
from dmf_pulse.fpl_points.current import CurrentFootballEventBundle
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.gameweek import assemble_gameweek
from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
from dmf_pulse.fpl_points.models import (
    FixtureProjectionResult,
    FixtureReadiness,
    FixtureSimulationRequest,
    GameweekProjectionResult,
    MonteCarloPolicy,
    PlayerPosition,
    ProjectionMode,
    SimulationStatus,
)
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.fpl_points.seed import RNG_ALGORITHM
from dmf_pulse.fpl_points.service import FplPointsService, load_mc_policy
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import CapabilityArtifact, RuleCapability, RulesetStatus

CURRENT_FPL_POINTS_ADAPTER_VERSION = "gw1-current-fpl-points-stage9-v1"
TARGET_RULESET_ID: Literal["fpl-2026-27"] = "fpl-2026-27"
TARGET_RULESET_VERSION: Literal["1.0.0"] = "1.0.0"
TARGET_RULESET_HASH: Literal["c2883ad9bf1497dad9c2eba69422e14937ddc072f9b3a95c5005a312c38f7d56"] = (
    "c2883ad9bf1497dad9c2eba69422e14937ddc072f9b3a95c5005a312c38f7d56"
)
TARGET_RULESET_FILE_SHA256: Literal[
    "aa45ce9b3cbaadd15fe97738cf6bdc4656aebeb58fe28c60717afb7ef424ce77"
] = "aa45ce9b3cbaadd15fe97738cf6bdc4656aebeb58fe28c60717afb7ef424ce77"
TARGET_PLAYER_POINTS_CAPABILITY_HASH: Literal[
    "fafb9518ec25989f6e0470215e83cc61008532b64c5bd5d026b4fb1a897fc5e8"
] = "fafb9518ec25989f6e0470215e83cc61008532b64c5bd5d026b4fb1a897fc5e8"
TARGET_MC_POLICY_FILE_SHA256: Literal[
    "14107f715769abb2d1bfc2937753c820a7d3eb02c23ae8e8a76350eaa88c0454"
] = "14107f715769abb2d1bfc2937753c820a7d3eb02c23ae8e8a76350eaa88c0454"
TARGET_MC_POLICY_SHA256: Literal[
    "6a09bb75b346bb80bc49c84cfc7d180677631c068aeeaa08f334d4e22a43f799"
] = "6a09bb75b346bb80bc49c84cfc7d180677631c068aeeaa08f334d4e22a43f799"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


def _file_sha256(path: Path, *, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise IngestionError("QUALITY_BLOCKED", f"{label} is unavailable") from exc


def _mc_policy_sha256(policy: MonteCarloPolicy) -> str:
    return canonical_sha256(policy.model_dump(mode="json"))


def _revalidate_source(value: CurrentFootballEventBundle) -> CurrentFootballEventBundle:
    try:
        return CurrentFootballEventBundle.model_validate_json(value.model_dump_json())
    except (ValueError, IngestionError) as exc:
        raise IngestionError(
            "SOURCE_LINEAGE_INVALID",
            "Checkpoint-2.3 football-event input failed independent revalidation",
        ) from exc


def _load_target_rules(
    ruleset_path: Path,
) -> tuple[AcceptedRulesAdapter, CapabilityArtifact, str]:
    file_sha256 = _file_sha256(ruleset_path, label="target ruleset artifact")
    try:
        compiled = load_compiled_ruleset(ruleset_path)
        capability = compile_capability_artifact(compiled, RuleCapability.PLAYER_POINTS)
        adapter = AcceptedRulesAdapter(compiled)
        adapter.assert_mode_allowed(ProjectionMode.PRESEASON_DECISION_SUPPORT)
    except RulesError as exc:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "target ruleset cannot support current PLAYER_POINTS evaluation",
            details={"error_code": exc.code},
        ) from exc
    except FplPointsError as exc:
        # Avoid leaking paths or rule contents through the current operator
        # boundary while preserving the stable failure code for diagnostics.
        raise IngestionError(
            "QUALITY_BLOCKED",
            "target ruleset cannot support current PLAYER_POINTS evaluation",
            details={"error_code": exc.code},
        ) from exc
    identity = adapter.identity
    if (
        file_sha256 != TARGET_RULESET_FILE_SHA256
        or compiled.schema_version != "1.1"
        or compiled.season_code != "2026/2027"
        or compiled.status is not RulesetStatus.VERIFIED
        or identity.ruleset_id != TARGET_RULESET_ID
        or identity.ruleset_version != TARGET_RULESET_VERSION
        or identity.ruleset_hash != TARGET_RULESET_HASH
        or identity.status != "VERIFIED"
        or not identity.production_eligible
        or identity.human_approval_recorded
        or identity.activation_evidence is not None
        or identity.unknown_blockers
        or capability.capability is not RuleCapability.PLAYER_POINTS
        or capability.capability_hash != TARGET_PLAYER_POINTS_CAPABILITY_HASH
        or not capability.source_backed
        or not capability.production_eligible
        or capability.blockers
    ):
        raise IngestionError(
            "QUALITY_BLOCKED",
            "target ruleset or PLAYER_POINTS capability differs from the accepted revision",
        )
    return adapter, capability, file_sha256


def _load_target_mc_policy(path: Path) -> tuple[MonteCarloPolicy, str, str]:
    file_sha256 = _file_sha256(path, label="Stage-9 Monte Carlo policy")
    try:
        policy = load_mc_policy(path)
    except FplPointsError as exc:
        raise IngestionError(
            "QUALITY_BLOCKED", "Stage-9 Monte Carlo policy is unavailable or invalid"
        ) from exc
    semantic_sha256 = _mc_policy_sha256(policy)
    if file_sha256 != TARGET_MC_POLICY_FILE_SHA256 or semantic_sha256 != TARGET_MC_POLICY_SHA256:
        raise IngestionError(
            "QUALITY_BLOCKED", "Stage-9 Monte Carlo policy differs from the accepted revision"
        )
    return policy, file_sha256, semantic_sha256


class CurrentFplPointsRunConfig(_FrozenModel):
    """Deterministic non-production configuration; this is not an approval."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_FPL_POINTS_RUN_CONFIG"] = "GW1_CURRENT_FPL_POINTS_RUN_CONFIG"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    projection_mode: Literal[ProjectionMode.PRESEASON_DECISION_SUPPORT] = (
        ProjectionMode.PRESEASON_DECISION_SUPPORT
    )
    source_event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_event_prior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_event_input_sha256_by_fixture: dict[str, str]
    source_stage7_team_result_sha256_by_fixture_team: dict[str, str]
    source_stage7_player_projection_sha256_by_fixture_player: dict[str, str]
    information_cutoff: datetime
    root_seed: StrictInt = Field(ge=0, le=2**63 - 1)
    scenario_count: StrictInt = Field(ge=1, le=1_000_000)
    ruleset_id: Literal["fpl-2026-27"] = "fpl-2026-27"
    ruleset_version: Literal["1.0.0"] = "1.0.0"
    ruleset_hash: Literal["c2883ad9bf1497dad9c2eba69422e14937ddc072f9b3a95c5005a312c38f7d56"] = (
        TARGET_RULESET_HASH
    )
    ruleset_status: Literal["VERIFIED"] = "VERIFIED"
    ruleset_file_sha256: Literal[
        "aa45ce9b3cbaadd15fe97738cf6bdc4656aebeb58fe28c60717afb7ef424ce77"
    ] = TARGET_RULESET_FILE_SHA256
    player_points_capability_hash: Literal[
        "fafb9518ec25989f6e0470215e83cc61008532b64c5bd5d026b4fb1a897fc5e8"
    ] = TARGET_PLAYER_POINTS_CAPABILITY_HASH
    human_activation_recorded: Literal[False] = False
    mc_policy_file_sha256: Literal[
        "14107f715769abb2d1bfc2937753c820a7d3eb02c23ae8e8a76350eaa88c0454"
    ] = TARGET_MC_POLICY_FILE_SHA256
    mc_policy_sha256: Literal[
        "6a09bb75b346bb80bc49c84cfc7d180677631c068aeeaa08f334d4e22a43f799"
    ] = TARGET_MC_POLICY_SHA256
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_config_hash(self) -> CurrentFplPointsRunConfig:
        if self.config_sha256 != _run_config_sha256(self):
            raise ValueError("current FPL-points run configuration hash is inconsistent")
        return self


def _run_config_sha256(value: CurrentFplPointsRunConfig) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"config_sha256"}))


def _make_run_config(
    source: CurrentFootballEventBundle,
    *,
    ruleset_path: Path,
    mc_policy_path: Path,
    root_seed: int,
    scenario_count: int,
) -> CurrentFplPointsRunConfig:
    _, _, rules_file_sha256 = _load_target_rules(ruleset_path)
    _, mc_file_sha256, mc_sha256 = _load_target_mc_policy(mc_policy_path)
    availability = source.source_availability
    fpl = availability.source_market.source_input.fpl_input
    values: dict[str, Any] = {
        "source_event_semantic_sha256": source.semantic_sha256,
        "source_availability_semantic_sha256": availability.semantic_sha256,
        "source_fpl_input_semantic_sha256": fpl.semantic_sha256,
        "source_event_prior_artifact_sha256": (source.approval.prior_artifact.artifact_sha256),
        "source_event_input_sha256_by_fixture": {
            str(row.transient_fixture_id): row.result_sha256 for row in source.fixtures
        },
        "source_stage7_team_result_sha256_by_fixture_team": {
            f"{row.transient_fixture_id}/{row.transient_team_id}": row.result_sha256
            for row in availability.team_projections
        },
        "source_stage7_player_projection_sha256_by_fixture_player": {
            f"{row.transient_fixture_id}/{player.player_id}": player.projection_sha256
            for row in availability.team_projections
            for player in row.posterior_projection.players
        },
        "information_cutoff": source.decision_information_at,
        "root_seed": root_seed,
        "scenario_count": scenario_count,
        "ruleset_file_sha256": rules_file_sha256,
        "mc_policy_file_sha256": mc_file_sha256,
        "mc_policy_sha256": mc_sha256,
    }
    provisional = CurrentFplPointsRunConfig.model_construct(**values, config_sha256="0" * 64)
    return CurrentFplPointsRunConfig(**values, config_sha256=_run_config_sha256(provisional))


def build_current_fpl_points_run_config(
    source: CurrentFootballEventBundle,
    *,
    ruleset_path: Path,
    mc_policy_path: Path,
    root_seed: int,
    scenario_count: int,
) -> CurrentFplPointsRunConfig:
    """Bind a repeatable Stage-9 decision-support run without approving it."""

    validated = _revalidate_source(source)
    fpl_rights = validated.source_availability.source_market.source_input.fpl_input.rights
    if (
        fpl_rights.raw_storage != "DENY"
        or fpl_rights.derived_storage != "DENY"
        or fpl_rights.database_accessed
        or fpl_rights.raw_storage_performed
        or fpl_rights.derived_storage_performed
    ):
        raise IngestionError("RIGHTS_BLOCKED", "official FPL retention boundary is invalid")
    return _make_run_config(
        validated,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
        root_seed=root_seed,
        scenario_count=scenario_count,
    )


class CurrentFixturePointsProjection(_FrozenModel):
    official_fpl_fixture_id: int = Field(gt=0)
    transient_fixture_id: UUID
    source_event_inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection: FixtureProjectionResult

    @model_validator(mode="after")
    def validate_projection_identity(self) -> CurrentFixturePointsProjection:
        if (
            self.projection.status is not SimulationStatus.SUCCESS
            or self.projection.fixture_id != str(self.transient_fixture_id)
            or self.projection.result_sha256 is None
        ):
            raise ValueError("current fixture points projection is blocked or misidentified")
        return self


class CurrentPlayerPointsUncertainty(_FrozenModel):
    stage7_confidence_grade: Literal["A", "B", "C", "D", "E"]
    stage9_confidence_grade: Literal["A", "B", "C", "D", "E"]
    points_variance: float = Field(ge=0.0)
    points_standard_deviation: float = Field(ge=0.0)
    monte_carlo_mean_se: float = Field(ge=0.0)
    threshold_probability_se: dict[str, Annotated[float, Field(ge=0.0)]]
    quantile_stability_max_span: dict[str, Annotated[int, Field(ge=0)]]
    scenario_effective_sample_size: float = Field(gt=0.0)
    monte_carlo_stopping_result: Literal["PASS", "CONTINUE", "BLOCKED"]
    monte_carlo_stopping_reasons: tuple[str, ...]
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_diagnostic_keys(self) -> CurrentPlayerPointsUncertainty:
        if set(self.threshold_probability_se) != {"5", "10", "15"} or set(
            self.quantile_stability_max_span
        ) != {"p10", "p50", "p90"}:
            raise ValueError("current player numerical uncertainty is incomplete")
        return self


class CurrentPlayerPointsProvenance(_FrozenModel):
    official_fpl_player_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_fpl_team_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_stage7_team_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_stage7_player_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_stage8_sha256s: tuple[str, ...] = Field(min_length=1)
    source_fixture_result_sha256s: tuple[str, ...] = Field(min_length=1)
    source_event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_event_prior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_id: Literal["fpl-2026-27"]
    ruleset_version: Literal["1.0.0"]
    ruleset_hash: Literal["c2883ad9bf1497dad9c2eba69422e14937ddc072f9b3a95c5005a312c38f7d56"]
    ruleset_status: Literal["VERIFIED"]
    player_points_capability_hash: Literal[
        "fafb9518ec25989f6e0470215e83cc61008532b64c5bd5d026b4fb1a897fc5e8"
    ]
    mc_policy_sha256: Literal["6a09bb75b346bb80bc49c84cfc7d180677631c068aeeaa08f334d4e22a43f799"]


class CurrentPlayerPointsProjection(_FrozenModel):
    """Private transient row; names, prices, and distributions are not CLI-safe."""

    official_fpl_player_id: int = Field(gt=0)
    transient_player_id: UUID
    player_name: str = Field(min_length=1, max_length=200)
    official_fpl_team_id: int = Field(gt=0)
    transient_team_id: UUID
    team_name: str = Field(min_length=1, max_length=200)
    position: PlayerPosition
    current_price_tenths: int = Field(gt=0)
    probability_appearance: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    probability_start: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    expected_minutes: str = Field(pattern=r"^\d{1,3}\.\d{6}$")
    mean_expected_fpl_points: float
    median_fpl_points: int
    selected_percentiles: dict[str, int]
    points_pmf: dict[int, Annotated[float, Field(ge=0.0, le=1.0)]]
    probability_negative_points: float = Field(ge=0.0, le=1.0)
    probability_zero_points: float = Field(ge=0.0, le=1.0)
    probability_5_plus: float = Field(ge=0.0, le=1.0)
    probability_10_plus: float = Field(ge=0.0, le=1.0)
    uncertainty: CurrentPlayerPointsUncertainty
    gameweek_id: UUID
    transient_fixture_ids: tuple[UUID, ...] = Field(min_length=1)
    outcome_draw_count: int = Field(gt=0)
    root_seed: int = Field(ge=0, le=2**63 - 1)
    rng_algorithm: Literal["python-mt19937-pts-v1"] = RNG_ALGORITHM
    gameweek_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    information_cutoff: datetime
    provenance: CurrentPlayerPointsProvenance
    row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_player_row(self) -> CurrentPlayerPointsProjection:
        if (
            self.row_sha256 != _player_row_sha256(self)
            or abs(sum(self.points_pmf.values()) - 1.0) > 1e-10
            or set(self.selected_percentiles)
            != {"p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"}
            or tuple(sorted(set(self.transient_fixture_ids), key=str)) != self.transient_fixture_ids
        ):
            raise ValueError("current player points row is inconsistent")
        return self


def _player_row_sha256(value: CurrentPlayerPointsProjection) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"row_sha256"}))


def _build_fixture_results(
    source: CurrentFootballEventBundle,
    config: CurrentFplPointsRunConfig,
    service: FplPointsService,
) -> tuple[CurrentFixturePointsProjection, ...]:
    rows: list[CurrentFixturePointsProjection] = []
    for fixture in source.fixtures:
        request = FixtureSimulationRequest(
            schema_version="fpl-points-fixture-request-v1",
            gameweek_id=str(fixture.gameweek_id),
            projection_mode=ProjectionMode.PRESEASON_DECISION_SUPPORT,
            as_of_utc=fixture.score_distribution.as_of,
            information_cutoff_utc=fixture.score_distribution.information_cutoff,
            root_seed=config.root_seed,
            scenario_count=config.scenario_count,
            fixture_readiness=FixtureReadiness(fixture.fixture_readiness),
            score_distribution=fixture.score_distribution,
            participation_scenarios=fixture.participation_scenarios,
            allocation_profiles=fixture.allocation_profiles,
            allocation_config=fixture.allocation_config,
            expected_ruleset_id=config.ruleset_id,
            expected_ruleset_version=config.ruleset_version,
            expected_ruleset_hash=config.ruleset_hash,
        )
        result = service.project(request)
        if result.status is not SimulationStatus.SUCCESS:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "accepted Stage-9 service blocked a current fixture projection",
                details={
                    "official_fpl_fixture_id": fixture.official_fpl_fixture_id,
                    "error_code": result.error_code,
                },
            )
        rows.append(
            CurrentFixturePointsProjection(
                official_fpl_fixture_id=fixture.official_fpl_fixture_id,
                transient_fixture_id=fixture.transient_fixture_id,
                source_event_inputs_sha256=fixture.result_sha256,
                projection=result,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.official_fpl_fixture_id))


def _player_material(
    source: CurrentFootballEventBundle,
) -> tuple[dict[str, Any], dict[int, Any], dict[int, Any]]:
    availability = source.source_availability
    fpl = availability.source_market.source_input.fpl_input
    team_by_hash = {team.identity.canonical_lookup_sha256: team for team in fpl.teams}
    projections_by_team: dict[int, Any] = {}
    for projection in availability.team_projections:
        if projection.official_fpl_team_id in projections_by_team:
            raise IngestionError(
                "QUALITY_BLOCKED",
                "current player table requires one target fixture per team",
            )
        projections_by_team[projection.official_fpl_team_id] = projection
    players_by_transient_id: dict[str, Any] = {}
    for player in fpl.players:
        team = team_by_hash.get(player.team_identity.canonical_lookup_sha256)
        if team is None or team.provider_team_id not in projections_by_team:
            continue
        players_by_transient_id[str(current_player_id(player))] = player
    return (
        players_by_transient_id,
        projections_by_team,
        {team.provider_team_id: team for team in team_by_hash.values()},
    )


def _build_player_rows(
    source: CurrentFootballEventBundle,
    config: CurrentFplPointsRunConfig,
    fixture_rows: tuple[CurrentFixturePointsProjection, ...],
    gameweek: GameweekProjectionResult,
) -> tuple[CurrentPlayerPointsProjection, ...]:
    players, projections_by_team, teams = _player_material(source)
    availability = source.source_availability
    fpl = availability.source_market.source_input.fpl_input
    fixture_by_id = {str(row.transient_fixture_id): row for row in fixture_rows}
    expected_ids = set(gameweek.player_summaries)
    if set(players) != expected_ids:
        raise IngestionError("MAPPING_CONFLICT", "Stage-9 and official-FPL player universes differ")
    assert gameweek.result_sha256 is not None
    output: list[CurrentPlayerPointsProjection] = []
    for player_id in sorted(expected_ids):
        player = players[player_id]
        official_team = next(
            (
                team
                for team in teams.values()
                if team.identity.canonical_lookup_sha256
                == player.team_identity.canonical_lookup_sha256
            ),
            None,
        )
        if official_team is None:
            raise IngestionError("MAPPING_CONFLICT", "current player team is unavailable")
        team_projection = projections_by_team[official_team.provider_team_id]
        stage7_players = {
            row.player_id: row for row in team_projection.posterior_projection.players
        }
        stage7 = stage7_players.get(player_id)
        fixture = fixture_by_id.get(str(team_projection.transient_fixture_id))
        if stage7 is None or fixture is None or fixture.projection.result_sha256 is None:
            raise IngestionError(
                "MAPPING_CONFLICT", "current player Stage-7/9 lineage is incomplete"
            )
        summary = gameweek.player_summaries[player_id]
        diagnostics = gameweek.monte_carlo
        event_input = next(
            row
            for row in source.fixtures
            if row.transient_fixture_id == fixture.transient_fixture_id
        )
        limitations = tuple(
            sorted(
                {
                    *team_projection.limitations,
                    *event_input.limitations,
                    *diagnostics.stopping_reasons,
                    "VERIFIED_RULESET_NOT_GLOBALLY_ACTIVE",
                    "NON_PRODUCTION_PRESEASON_DECISION_SUPPORT",
                }
            )
        )
        provenance = CurrentPlayerPointsProvenance(
            official_fpl_player_identity_sha256=player.identity.canonical_lookup_sha256,
            official_fpl_team_identity_sha256=official_team.identity.canonical_lookup_sha256,
            source_fpl_input_semantic_sha256=fpl.semantic_sha256,
            source_availability_semantic_sha256=availability.semantic_sha256,
            source_stage7_team_result_sha256=team_projection.result_sha256,
            source_stage7_player_projection_sha256=stage7.projection_sha256,
            source_stage8_sha256s=summary.upstream_stage8_sha256s,
            source_fixture_result_sha256s=(fixture.projection.result_sha256,),
            source_event_semantic_sha256=source.semantic_sha256,
            source_event_prior_artifact_sha256=(source.approval.prior_artifact.artifact_sha256),
            ruleset_id=config.ruleset_id,
            ruleset_version=config.ruleset_version,
            ruleset_hash=config.ruleset_hash,
            ruleset_status=config.ruleset_status,
            player_points_capability_hash=config.player_points_capability_hash,
            mc_policy_sha256=config.mc_policy_sha256,
        )
        values: dict[str, Any] = {
            "official_fpl_player_id": player.provider_element_id,
            "transient_player_id": UUID(player_id),
            "player_name": player.web_name,
            "official_fpl_team_id": official_team.provider_team_id,
            "transient_team_id": team_projection.transient_team_id,
            "team_name": official_team.official_name,
            "position": PlayerPosition(player.position.value),
            "current_price_tenths": player.current_price_tenths,
            "probability_appearance": stage7.p_appearance,
            "probability_start": stage7.p_start,
            "expected_minutes": stage7.expected_minutes,
            "mean_expected_fpl_points": summary.expected_points,
            "median_fpl_points": summary.median_points,
            "selected_percentiles": summary.selected_percentiles,
            "points_pmf": summary.pmf,
            "probability_negative_points": summary.probability_negative_points,
            "probability_zero_points": summary.probability_zero_points,
            "probability_5_plus": summary.probability_5_plus,
            "probability_10_plus": summary.probability_10_plus,
            "uncertainty": CurrentPlayerPointsUncertainty(
                stage7_confidence_grade=stage7.confidence_grade,
                stage9_confidence_grade=summary.confidence_grade,
                points_variance=summary.points_variance,
                points_standard_deviation=summary.points_standard_deviation,
                monte_carlo_mean_se=summary.monte_carlo_mean_se,
                threshold_probability_se=summary.threshold_probability_se,
                quantile_stability_max_span=(
                    diagnostics.quantile_stability_max_span_by_player[player_id]
                ),
                scenario_effective_sample_size=summary.scenario_effective_sample_size,
                monte_carlo_stopping_result=diagnostics.stopping_result,
                monte_carlo_stopping_reasons=diagnostics.stopping_reasons,
                limitations=limitations,
            ),
            "gameweek_id": UUID(gameweek.scenario_set.gameweek_id),
            "transient_fixture_ids": (fixture.transient_fixture_id,),
            "outcome_draw_count": len(gameweek.scenario_set.scenarios),
            "root_seed": config.root_seed,
            "gameweek_result_sha256": gameweek.result_sha256,
            "information_cutoff": config.information_cutoff,
            "provenance": provenance,
        }
        provisional = CurrentPlayerPointsProjection.model_construct(**values, row_sha256="0" * 64)
        output.append(
            CurrentPlayerPointsProjection(**values, row_sha256=_player_row_sha256(provisional))
        )
    return tuple(sorted(output, key=lambda row: row.official_fpl_player_id))


class CurrentFplPointsSummary(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["PROJECTED_WITH_MATERIAL_LIMITATIONS"] = "PROJECTED_WITH_MATERIAL_LIMITATIONS"
    contract: Literal["GW1_CURRENT_FPL_POINTS_DISTRIBUTIONS"] = (
        "GW1_CURRENT_FPL_POINTS_DISTRIBUTIONS"
    )
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    ruleset_id: Literal["fpl-2026-27"] = "fpl-2026-27"
    ruleset_status: Literal["VERIFIED"] = "VERIFIED"
    human_activation_recorded: Literal[False] = False
    fixture_count: int = Field(gt=0)
    player_count: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    confidence_grades: dict[str, int]
    monte_carlo_stopping_result: Literal["PASS", "CONTINUE", "BLOCKED"]
    monte_carlo_stopping_reasons: tuple[str, ...]
    information_cutoff: datetime
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    handcrafted_xp: Literal[False] = False
    source_event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    player_points_capability_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    gameweek_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    next_checkpoint: Literal["2.5_PROJECTION_ACCEPTANCE"] = "2.5_PROJECTION_ACCEPTANCE"


class CurrentFplPointsBundle(_FrozenModel):
    """Hash-bound in-memory Stage-9 result and private current player table."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_FPL_POINTS_DISTRIBUTIONS"] = (
        "GW1_CURRENT_FPL_POINTS_DISTRIBUTIONS"
    )
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    projection_mode: Literal[ProjectionMode.PRESEASON_DECISION_SUPPORT] = (
        ProjectionMode.PRESEASON_DECISION_SUPPORT
    )
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    fpl_raw_storage: Literal["DENY"] = "DENY"
    fpl_derived_storage: Literal["DENY"] = "DENY"
    production_calibration_claim: Literal[False] = False
    handcrafted_xp: Literal[False] = False
    adapter_version: Literal["gw1-current-fpl-points-stage9-v1"] = (
        "gw1-current-fpl-points-stage9-v1"
    )
    source_event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_config: CurrentFplPointsRunConfig
    fixture_projections: tuple[CurrentFixturePointsProjection, ...] = Field(min_length=1)
    gameweek_projection: GameweekProjectionResult
    player_table: tuple[CurrentPlayerPointsProjection, ...] = Field(min_length=1)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bundle(self) -> CurrentFplPointsBundle:
        fixtures = self.fixture_projections
        fixture_ids = [row.official_fpl_fixture_id for row in fixtures]
        transient_fixture_ids = [str(row.transient_fixture_id) for row in fixtures]
        results = tuple(row.projection for row in fixtures)
        result_hashes: dict[str, str] = {}
        for row in fixtures:
            assert row.projection.result_sha256 is not None
            result_hashes[row.projection.fixture_id] = row.projection.result_sha256
        gameweek = self.gameweek_projection
        player_ids = tuple(str(row.transient_player_id) for row in self.player_table)
        stage7_by_player: dict[str, tuple[str, str, Any]] = {}
        fixture_result_hashes_by_player: dict[str, list[str]] = {}
        for result in results:
            participation = result.simulation_request.participation_scenarios[0]
            for team_projection in (
                participation.stage7_home_projection,
                participation.stage7_away_projection,
            ):
                for player in team_projection.players:
                    if player.player_id in stage7_by_player:
                        raise ValueError(
                            "current FPL-points bundle contains duplicate player fixtures"
                        )
                    stage7_by_player[player.player_id] = (
                        result.fixture_id,
                        team_projection.team_id,
                        player,
                    )
                    assert result.result_sha256 is not None
                    fixture_result_hashes_by_player.setdefault(player.player_id, []).append(
                        result.result_sha256
                    )
        event_input_hashes = {
            str(row.transient_fixture_id): row.source_event_inputs_sha256 for row in fixtures
        }
        if (
            self.source_event_semantic_sha256 != self.run_config.source_event_semantic_sha256
            or fixture_ids != sorted(fixture_ids)
            or len(fixture_ids) != len(set(fixture_ids))
            or len(transient_fixture_ids) != len(set(transient_fixture_ids))
            or event_input_hashes != self.run_config.source_event_input_sha256_by_fixture
            or any(
                result.projection_mode is not ProjectionMode.PRESEASON_DECISION_SUPPORT
                or result.ruleset.status != "VERIFIED"
                or result.ruleset.human_approval_recorded
                or result.simulation_request.root_seed != self.run_config.root_seed
                or result.simulation_request.scenario_count != self.run_config.scenario_count
                or result.ruleset.ruleset_hash != self.run_config.ruleset_hash
                for result in results
            )
            or gameweek.scenario_set.fixture_result_sha256_by_fixture != result_hashes
            or gameweek.scenario_set.ruleset_hash != self.run_config.ruleset_hash
            or tuple(sorted(player_ids)) != tuple(sorted(gameweek.player_summaries))
            or set(stage7_by_player) != set(player_ids)
            or len(player_ids) != len(set(player_ids))
            or any(
                self._player_row_differs(row, stage7_by_player, fixture_result_hashes_by_player)
                for row in self.player_table
            )
            or self.semantic_sha256 != _bundle_sha256(self)
        ):
            raise ValueError("current FPL-points bundle lineage is inconsistent")
        return self

    def _player_row_differs(
        self,
        row: CurrentPlayerPointsProjection,
        stage7_by_player: dict[str, tuple[str, str, Any]],
        fixture_result_hashes_by_player: dict[str, list[str]],
    ) -> bool:
        player_id = str(row.transient_player_id)
        fixture_id, team_id, stage7 = stage7_by_player[player_id]
        summary = self.gameweek_projection.player_summaries[player_id]
        diagnostics = self.gameweek_projection.monte_carlo
        provenance = row.provenance
        fixture_player_key = f"{fixture_id}/{player_id}"
        fixture_team_key = f"{fixture_id}/{team_id}"
        return bool(
            row.gameweek_id != UUID(self.gameweek_projection.scenario_set.gameweek_id)
            or row.transient_fixture_ids != (UUID(fixture_id),)
            or str(row.transient_team_id) != team_id
            or row.position.value != stage7.position
            or row.probability_appearance != stage7.p_appearance
            or row.probability_start != stage7.p_start
            or row.expected_minutes != stage7.expected_minutes
            or row.gameweek_result_sha256 != self.gameweek_projection.result_sha256
            or row.outcome_draw_count != len(self.gameweek_projection.scenario_set.scenarios)
            or row.root_seed != self.run_config.root_seed
            or row.information_cutoff != self.run_config.information_cutoff
            or row.mean_expected_fpl_points != summary.expected_points
            or row.median_fpl_points != summary.median_points
            or row.selected_percentiles != summary.selected_percentiles
            or row.points_pmf != summary.pmf
            or row.probability_negative_points != summary.probability_negative_points
            or row.probability_zero_points != summary.probability_zero_points
            or row.probability_5_plus != summary.probability_5_plus
            or row.probability_10_plus != summary.probability_10_plus
            or row.uncertainty.stage7_confidence_grade != stage7.confidence_grade
            or row.uncertainty.stage9_confidence_grade != summary.confidence_grade
            or row.uncertainty.points_variance != summary.points_variance
            or row.uncertainty.points_standard_deviation != summary.points_standard_deviation
            or row.uncertainty.monte_carlo_mean_se != summary.monte_carlo_mean_se
            or row.uncertainty.threshold_probability_se != summary.threshold_probability_se
            or row.uncertainty.quantile_stability_max_span
            != diagnostics.quantile_stability_max_span_by_player[player_id]
            or row.uncertainty.scenario_effective_sample_size
            != summary.scenario_effective_sample_size
            or row.uncertainty.monte_carlo_stopping_result != diagnostics.stopping_result
            or row.uncertainty.monte_carlo_stopping_reasons != diagnostics.stopping_reasons
            or provenance.source_fpl_input_semantic_sha256
            != self.run_config.source_fpl_input_semantic_sha256
            or provenance.source_availability_semantic_sha256
            != self.run_config.source_availability_semantic_sha256
            or provenance.source_stage7_team_result_sha256
            != self.run_config.source_stage7_team_result_sha256_by_fixture_team.get(
                fixture_team_key
            )
            or provenance.source_stage7_player_projection_sha256
            != self.run_config.source_stage7_player_projection_sha256_by_fixture_player.get(
                fixture_player_key
            )
            or provenance.source_stage7_player_projection_sha256 != stage7.projection_sha256
            or provenance.source_stage8_sha256s != summary.upstream_stage8_sha256s
            or provenance.source_fixture_result_sha256s
            != tuple(fixture_result_hashes_by_player[player_id])
            or provenance.source_event_semantic_sha256 != self.source_event_semantic_sha256
            or provenance.source_event_prior_artifact_sha256
            != self.run_config.source_event_prior_artifact_sha256
            or provenance.ruleset_hash != self.run_config.ruleset_hash
            or provenance.player_points_capability_hash
            != self.run_config.player_points_capability_hash
            or provenance.mc_policy_sha256 != self.run_config.mc_policy_sha256
        )

    def safe_summary(self) -> CurrentFplPointsSummary:
        gameweek = self.gameweek_projection
        assert gameweek.result_sha256 is not None
        grades = Counter(row.uncertainty.stage9_confidence_grade for row in self.player_table)
        return CurrentFplPointsSummary(
            fixture_count=len(self.fixture_projections),
            player_count=len(self.player_table),
            scenario_count=len(gameweek.scenario_set.scenarios),
            confidence_grades=dict(sorted(grades.items())),
            monte_carlo_stopping_result=gameweek.monte_carlo.stopping_result,
            monte_carlo_stopping_reasons=gameweek.monte_carlo.stopping_reasons,
            information_cutoff=self.run_config.information_cutoff,
            source_event_semantic_sha256=self.source_event_semantic_sha256,
            ruleset_hash=self.run_config.ruleset_hash,
            player_points_capability_hash=self.run_config.player_points_capability_hash,
            gameweek_result_sha256=gameweek.result_sha256,
            semantic_sha256=self.semantic_sha256,
        )


def _bundle_sha256(value: CurrentFplPointsBundle) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def build_current_fpl_points(
    source: CurrentFootballEventBundle,
    config: CurrentFplPointsRunConfig,
    *,
    ruleset_path: Path,
    mc_policy_path: Path,
) -> CurrentFplPointsBundle:
    """Execute the accepted Stage-9 service in governed preseason mode."""

    validated = _revalidate_source(source)
    expected_config = _make_run_config(
        validated,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
        root_seed=config.root_seed,
        scenario_count=config.scenario_count,
    )
    if config != expected_config:
        raise IngestionError(
            "SOURCE_LINEAGE_INVALID",
            "current FPL-points run configuration is not bound to the supplied inputs",
        )
    rules, _, _ = _load_target_rules(ruleset_path)
    policy, _, _ = _load_target_mc_policy(mc_policy_path)
    fixture_rows = _build_fixture_results(validated, config, FplPointsService(rules, policy))
    scenario_set = assemble_gameweek(tuple(row.projection for row in fixture_rows))
    gameweek = build_gameweek_projection(scenario_set, policy)
    player_rows = _build_player_rows(validated, config, fixture_rows, gameweek)
    values: dict[str, Any] = {
        "source_event_semantic_sha256": validated.semantic_sha256,
        "run_config": config,
        "fixture_projections": fixture_rows,
        "gameweek_projection": gameweek,
        "player_table": player_rows,
    }
    provisional = CurrentFplPointsBundle.model_construct(**values, semantic_sha256="0" * 64)
    return CurrentFplPointsBundle(**values, semantic_sha256=_bundle_sha256(provisional))


__all__ = [
    "CURRENT_FPL_POINTS_ADAPTER_VERSION",
    "TARGET_MC_POLICY_FILE_SHA256",
    "TARGET_MC_POLICY_SHA256",
    "TARGET_PLAYER_POINTS_CAPABILITY_HASH",
    "TARGET_RULESET_FILE_SHA256",
    "TARGET_RULESET_HASH",
    "TARGET_RULESET_ID",
    "TARGET_RULESET_VERSION",
    "CurrentFixturePointsProjection",
    "CurrentFplPointsBundle",
    "CurrentFplPointsRunConfig",
    "CurrentFplPointsSummary",
    "CurrentPlayerPointsProjection",
    "CurrentPlayerPointsProvenance",
    "CurrentPlayerPointsUncertainty",
    "build_current_fpl_points",
    "build_current_fpl_points_run_config",
]
