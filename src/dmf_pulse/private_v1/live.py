"""Zero-retention composition of approved current inputs around private V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.manual_override import ManualFixtureMinutesInput
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.fpl_points.models import EventAllocationConfig, MonteCarloPolicy, ProjectionMode
from dmf_pulse.fpl_points.player_prior import (
    CurrentGwPriorFallbackAssignment,
    CurrentGwStalePriorCarryForwardPolicy,
    load_packaged_player_prior,
    seal_current_gw_stale_prior_policy,
)
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateService,
    bind_current_manager_state_request,
)
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.identity import (
    bind_current_fixture_resolution_request,
    bind_current_team_resolution_request,
    resolve_current_fixture_identities,
    resolve_current_team_identities,
)
from dmf_pulse.ingestion.odds.mapping import CurrentFixtureMappingPlan, CurrentTeamAliasPlan
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCurrentOwnership,
    PrivateFixtureScorePrior,
    PrivateV1Decision,
    PrivateV1ExecutionInput,
    seal_execution_input,
)
from dmf_pulse.private_v1.service import PrivateV1RecommendationService
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.private_transient import PrivateTransientRulesAuthority


class _FrozenInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class PrivateLiveScorePriorInput(_FrozenInputModel):
    score_priors: Annotated[tuple[PrivateFixtureScorePrior, ...], Field(min_length=1)]


class PrivateLiveStage7Input(_FrozenInputModel):
    fixtures: Annotated[tuple[ManualFixtureMinutesInput, ...], Field(min_length=1)]


class PrivateLivePriorFallbackInput(_FrozenInputModel):
    policy_id: Literal["PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"] = (
        "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"
    )
    declared_at: datetime
    assignments: tuple[CurrentGwPriorFallbackAssignment, ...] = ()

    @field_validator("declared_at")
    @classmethod
    def declared_time_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prior fallback declaration time must be timezone-aware")
        return value.astimezone(UTC)


@dataclass(frozen=True)
class PrivateV1LiveTransientRequest:
    """Operator-owned sources and already-approved non-FPL current inputs."""

    run_id: str
    code_sha: str
    bootstrap_path: Path
    fixtures_path: Path
    manager_declaration_path: Path
    target_gameweek: int
    captured_at: datetime
    information_cutoff: datetime
    ruleset: CompiledRuleset
    full_season_capability: CapabilityArtifact
    private_rules_authority: PrivateTransientRulesAuthority
    odds_input: OddsProviderCurrentInput
    team_alias_plan: CurrentTeamAliasPlan
    fixture_mapping_plan: CurrentFixtureMappingPlan
    mapping_decided_at: datetime
    market_identity_view: CurrentMarketCanonicalIdentityView
    player_identity_map: PrivateCanonicalPlayerIdentityMap
    score_priors: tuple[PrivateFixtureScorePrior, ...]
    manual_minutes: tuple[ManualFixtureMinutesInput, ...]
    ownership: PrivateCurrentOwnership
    candidate_action_policy: PrivateCandidateActionPolicy
    prior_fallbacks: PrivateLivePriorFallbackInput | None
    root_seed: int
    scenario_count: int
    stage9_monte_carlo_policy: MonteCarloPolicy
    event_allocation_config: EventAllocationConfig


@dataclass(frozen=True)
class PrivateV1LiveTransientResult:
    """Display-lifetime result that carries no raw FPL or replay-capable state."""

    execution_status: Literal["REAL_PRIVATE_TRANSIENT_RECOMMENDATION"]
    replay_retention: Literal["FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE"]
    persistent_artifacts_created: Literal[0]
    decision: PrivateV1Decision
    report: str


class PrivateV1LiveTransientService:
    """Compile and execute one current recommendation without a write boundary."""

    def __init__(
        self,
        *,
        fpl_service: CurrentFplInputService | None = None,
        manager_service: CurrentManagerStateService | None = None,
        recommendation_service: PrivateV1RecommendationService | None = None,
    ) -> None:
        self._fpl_service = fpl_service or CurrentFplInputService()
        self._manager_service = manager_service or CurrentManagerStateService()
        self._recommendation_service = recommendation_service or PrivateV1RecommendationService()

    def run(self, request: PrivateV1LiveTransientRequest) -> PrivateV1LiveTransientResult:
        """Run the accepted boundaries in memory and return display-only material."""

        try:
            self._validate_boundary_before_read(request)
            fpl_input = self._fpl_service.compile(
                CurrentFplInputRequest(
                    bootstrap_path=request.bootstrap_path,
                    fixtures_path=request.fixtures_path,
                    competition_key="PL",
                    season_code="2026/27",
                    target_gameweek=request.target_gameweek,
                    captured_at=request.captured_at,
                    information_cutoff=request.information_cutoff,
                    rights_profile_id="fpl_official_private_manual_v1",
                )
            )
            manager_request = bind_current_manager_state_request(
                request.manager_declaration_path,
                fpl_input,
                request.ruleset,
                request.full_season_capability,
            )
            manager = self._manager_service.compile(
                manager_request,
                fpl_input=fpl_input,
                ruleset=request.ruleset,
                capability=request.full_season_capability,
                private_rules_authority=request.private_rules_authority,
            )
            team_request = bind_current_team_resolution_request(
                fpl_input,
                request.odds_input,
                request.team_alias_plan,
                mapping_decided_at=request.mapping_decided_at,
            )
            team_map = resolve_current_team_identities(
                fpl_input, request.odds_input, request.team_alias_plan, team_request
            )
            fixture_request = bind_current_fixture_resolution_request(
                fpl_input,
                request.odds_input,
                request.team_alias_plan,
                team_map,
                request.fixture_mapping_plan,
                mapping_decided_at=request.mapping_decided_at,
            )
            identity_map = resolve_current_fixture_identities(
                fpl_input,
                request.odds_input,
                request.team_alias_plan,
                team_map,
                request.fixture_mapping_plan,
                fixture_request,
            )
            unified_request = bind_current_unified_state_request(
                fpl_input,
                request.odds_input,
                identity_map,
                manager,
                request.ruleset,
                request.full_season_capability,
            )
            current_state = CurrentUnifiedStateService().compose(
                unified_request,
                fpl_input=fpl_input,
                odds_input=request.odds_input,
                identity_map=identity_map,
                manager_state=manager,
                ruleset=request.ruleset,
                capability=request.full_season_capability,
                private_rules_authority=request.private_rules_authority,
            )
            market_request = bind_current_market_constraint_request(
                current_state, request.market_identity_view
            )
            markets = CurrentMarketConstraintService().build(
                market_request,
                source=current_state,
                identity_view=request.market_identity_view,
            )
            prior = load_packaged_player_prior()
            carry_forward: CurrentGwStalePriorCarryForwardPolicy | None = None
            if request.target_gameweek > 1:
                prior_fallbacks = cast(PrivateLivePriorFallbackInput, request.prior_fallbacks)
                carry_forward = seal_current_gw_stale_prior_policy(
                    CurrentGwStalePriorCarryForwardPolicy.model_construct(
                        target_gameweek=request.target_gameweek,
                        current_fpl_bundle_sha256=fpl_input.semantic_sha256,
                        prior_artifact_sha256=prior.artifact.artifact_sha256,
                        historical_acceptance_sha256=(
                            prior.historical_acceptance.acceptance_sha256
                        ),
                        original_evidence_cutoff=prior.artifact.information_cutoff,
                        declared_at=prior_fallbacks.declared_at,
                        fallback_assignments=prior_fallbacks.assignments,
                        semantic_sha256="0" * 64,
                    )
                )
            execution = seal_execution_input(
                PrivateV1ExecutionInput.model_construct(
                    run_id=request.run_id,
                    code_sha=request.code_sha,
                    projection_mode=ProjectionMode.REPLAY,
                    retention_class="PRIVATE_TRANSIENT_NO_RETENTION",
                    synthetic_source_attestation=None,
                    current_state=current_state,
                    player_identity_map=request.player_identity_map,
                    market_identity_view=request.market_identity_view,
                    market_constraints=markets,
                    score_priors=request.score_priors,
                    manual_minutes=request.manual_minutes,
                    ownership=request.ownership,
                    candidate_action_policy=request.candidate_action_policy,
                    ruleset=request.ruleset,
                    full_season_capability=request.full_season_capability,
                    private_rules_authority=request.private_rules_authority,
                    player_prior_carry_forward_policy=carry_forward,
                    root_seed=request.root_seed,
                    scenario_count=request.scenario_count,
                    stage9_monte_carlo_policy=request.stage9_monte_carlo_policy,
                    stage9_monte_carlo_policy_sha256=canonical_sha256(
                        request.stage9_monte_carlo_policy.model_dump(mode="json")
                    ),
                    event_allocation_config=request.event_allocation_config,
                    event_allocation_config_sha256=canonical_sha256(
                        request.event_allocation_config.model_dump(mode="json")
                    ),
                    expected_stage8_policy_sha256=load_score_baseline_policy().sha256,
                    expected_player_prior_artifact_sha256=prior.artifact.artifact_sha256,
                    expected_player_prior_acceptance_sha256=(
                        prior.historical_acceptance.acceptance_sha256
                    ),
                    require_stage9_mc_pass=True,
                    semantic_sha256="0" * 64,
                )
            )
            run = self._recommendation_service.run(execution)
            return PrivateV1LiveTransientResult(
                execution_status="REAL_PRIVATE_TRANSIENT_RECOMMENDATION",
                replay_retention="FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE",
                persistent_artifacts_created=0,
                decision=run.decision,
                report=(
                    run.report
                    + "\nZERO-RETENTION BOUNDARY\n"
                    + "Persistent artifacts created by live-transient: 0\n"
                    + "FPL raw and derived runtime references were released after execution.\n"
                    + "Operator-owned manual source files were not copied or modified and remain "
                    + "subject to the approved operator-delete requirement.\n"
                ),
            )
        except PrivateV1Error:
            raise
        except IngestionError as exc:
            raise PrivateV1Error(exc.code, "live current source validation failed") from None
        except CurrentMarketConstraintError as exc:
            raise PrivateV1Error(exc.code, "live current market validation failed") from None
        except (ValidationError, ValueError, ArithmeticError, TypeError):
            raise PrivateV1Error(
                "LIVE_TRANSIENT_INPUT_INVALID", "live transient input failed validation"
            ) from None

    @staticmethod
    def _validate_boundary_before_read(request: PrivateV1LiveTransientRequest) -> None:
        """Reject disallowed authorities before opening any operator-owned source file."""

        if request.target_gameweek > 1 and request.prior_fallbacks is None:
            raise PrivateV1Error(
                "PLAYER_PRIOR_POLICY_MISSING",
                "post-GW1 execution requires an explicit stale-prior policy input",
            )
        if request.target_gameweek == 1 and request.prior_fallbacks is not None:
            raise PrivateV1Error(
                "PLAYER_PRIOR_POLICY_INVALID", "GW1 execution cannot claim carry-forward"
            )
        if any(item.source_class != "CURRENT_SCORE_PRIOR_BUNDLE" for item in request.score_priors):
            raise PrivateV1Error(
                "SCORE_PRIOR_SOURCE_INVALID",
                "live transient execution requires authenticated current score-prior bundles",
            )
        if request.player_identity_map.source_class != "DAT_003_OPERATOR_EXPORT":
            raise PrivateV1Error(
                "PLAYER_IDENTITY_SOURCE_INVALID",
                "live transient execution requires an operator DAT-003 player identity export",
            )
        if request.market_identity_view.authority != "DAT_003_READ_ONLY":
            raise PrivateV1Error(
                "MARKET_IDENTITY_SOURCE_INVALID",
                "live transient execution requires the accepted DAT-003 market identity view",
            )
        if request.event_allocation_config.source_tag == "TEST_SYNTHETIC":
            raise PrivateV1Error(
                "STAGE9_POLICY_INVALID", "live transient execution rejects synthetic policy"
            )


__all__ = [
    "PrivateLivePriorFallbackInput",
    "PrivateLiveScorePriorInput",
    "PrivateLiveStage7Input",
    "PrivateV1LiveTransientRequest",
    "PrivateV1LiveTransientResult",
    "PrivateV1LiveTransientService",
]
