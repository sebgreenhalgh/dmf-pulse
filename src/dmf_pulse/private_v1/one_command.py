"""Top-level zero-retention orchestration for one current private recommendation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.fpl_points.models import MonteCarloPolicy, ProjectionMode
from dmf_pulse.fpl_points.player_prior import (
    build_automatic_current_gw_stale_prior_policy,
    load_packaged_player_prior,
)
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplClient, DirectFplRunAttestation
from dmf_pulse.ingestion.fpl.direct_payloads import (
    DirectFplSnapshot,
    acquire_direct_fpl_snapshot,
)
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from dmf_pulse.ingestion.odds.automatic_mapping import build_automatic_current_identity_map
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorResult,
    CurrentScorePriorService,
    build_current_score_prior_bundle,
)
from dmf_pulse.markets.current import (
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
    build_transient_current_market_identity_view,
)
from dmf_pulse.private_v1.automatic_inputs import (
    build_automatic_model_minutes,
    build_automatic_ownership,
    build_automatic_player_identity_map,
    build_full_candidate_policy,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateFixtureScorePrior,
    PrivateV1Decision,
    PrivateV1ExecutionInput,
    seal_execution_input,
    seal_fixture_score_prior,
)
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    load_packaged_event_allocation_config,
)
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset, RuleCapability
from dmf_pulse.rules.private_transient import (
    PrivateTransientRulesAuthority,
    seal_private_transient_rules_authority,
)

_COMPETITION_ID = uuid5(UUID("760aa9a3-56a8-57e7-8c3d-924141214e47"), "PL:2026/27")


@dataclass(frozen=True, slots=True)
class OneCommandRequest:
    entry_id: int
    code_sha: str
    run_at: datetime
    run_id: str = "PRIVATE_V1_ONE_COMMAND"
    root_seed: int = 20260901
    scenario_count: int = 256


@dataclass(frozen=True, slots=True)
class OneCommandResult:
    status: Literal["REAL_PRIVATE_TRANSIENT_RECOMMENDATION"]
    decision: PrivateV1Decision
    report: str
    fpl_request_count: int
    fpl_endpoint_classes: tuple[str, ...]
    authenticated_current_state_used: Literal[True] = True
    persistence_performed: Literal[False] = False


def _rules_path() -> Path:
    value = files("dmf_pulse.rules.resources").joinpath("fpl-2026-27")
    path = Path(str(value))
    if not path.is_dir():
        path = Path(__file__).resolve().parents[3] / "config" / "rules" / "fpl-2026-27"
    if not path.is_dir():
        raise IngestionError("RULES_UNAVAILABLE", "packaged 2026/27 rules are unavailable")
    return path


def _rules_authority(
    run_at: datetime,
) -> tuple[CompiledRuleset, CapabilityArtifact, PrivateTransientRulesAuthority]:
    ruleset = compile_ruleset(_rules_path())
    capability = compile_capability_artifact(ruleset, RuleCapability.FULL_SEASON)
    authority = seal_private_transient_rules_authority(
        PrivateTransientRulesAuthority.model_construct(
            ruleset_id=ruleset.ruleset_id,
            ruleset_version=ruleset.ruleset_version,
            ruleset_sha256=ruleset.ruleset_hash,
            capability_sha256=capability.capability_hash,
            operator_approval_reference=(
                "PRIVATE-V1-ONE-COMMAND-001A in-process private VERIFIED-rules authority"
            ),
            operator_approved_at=run_at,
            attestation_sha256="0" * 64,
        )
    )
    return ruleset, capability, authority


def _score_priors(
    source: CurrentScorePriorResult,
    *,
    snapshot: DirectFplSnapshot,
    market_view: object,
    identity_map: object,
) -> tuple[PrivateFixtureScorePrior, ...]:
    from dmf_pulse.markets.current import CurrentMarketCanonicalIdentityView
    from dmf_pulse.private_v1.models import PrivateCanonicalPlayerIdentityMap

    view = CurrentMarketCanonicalIdentityView.model_validate(market_view)
    identities = PrivateCanonicalPlayerIdentityMap.model_validate(identity_map)
    teams = {item.official_fpl_team_id: item.canonical_team_id for item in identities.teams}
    target = {
        item.provider_fixture_id: item
        for item in snapshot.fpl_input.fixtures
        if item.event_identity == snapshot.fpl_input.target_event.identity
    }
    values: list[PrivateFixtureScorePrior] = []
    for item in view.fixtures:
        fixture = target[item.official_fpl_fixture_id]
        home = teams[int(fixture.home_team_identity.external_id_text)]
        away = teams[int(fixture.away_team_identity.external_id_text)]
        bundle = build_current_score_prior_bundle(
            source,
            fixture_id=item.canonical_fixture_id,
            competition_id=_COMPETITION_ID,
            home_team_id=home,
            away_team_id=away,
            as_of=snapshot.fpl_input.provenance.information_cutoff,
        )
        values.append(
            seal_fixture_score_prior(
                PrivateFixtureScorePrior.model_construct(
                    source_class="CURRENT_SCORE_PRIOR_BUNDLE",
                    fixture_id=item.canonical_fixture_id,
                    competition_id=_COMPETITION_ID,
                    home_team_id=home,
                    away_team_id=away,
                    as_of=snapshot.fpl_input.provenance.information_cutoff,
                    score_prior_request=bundle.score_prior_request,
                    current_bundle=bundle,
                    semantic_sha256="0" * 64,
                )
            )
        )
    return tuple(sorted(values, key=lambda value: str(value.fixture_id)))


def _display_report(
    decision: PrivateV1Decision,
    snapshot: DirectFplSnapshot,
    player_identity_map: object,
) -> str:
    from dmf_pulse.private_v1.models import PrivateCanonicalPlayerIdentityMap

    identities = PrivateCanonicalPlayerIdentityMap.model_validate(player_identity_map)
    player_by_element = {item.provider_element_id: item for item in snapshot.fpl_input.players}
    element_by_uuid = {
        str(item.canonical_player_id): item.official_fpl_element_id for item in identities.players
    }

    def label(player_id: str) -> str:
        element_id = element_by_uuid[player_id]
        player = player_by_element[element_id]
        return f"{player.web_name} [{element_id}]"

    transfers = (
        "NO TRANSFER"
        if not decision.transfers
        else ", ".join(
            f"{player_by_element[item.official_fpl_element_out].web_name} -> "
            f"{player_by_element[item.official_fpl_element_in].web_name}"
            for item in decision.transfers
        )
    )
    tactics = decision.tactics
    comparison = decision.paired_comparison
    position_by_id = {
        player_id: player_by_element[element_id].position.value
        for player_id, element_id in element_by_uuid.items()
    }
    formation = "-".join(
        str(sum(position_by_id[item] == position for item in tactics.starting_xi))
        for position in ("DEF", "MID", "FWD")
    )
    warnings = "\n".join(f"- {item}" for item in decision.warnings)
    squad = ", ".join(label(item) for item in decision.resulting_squad)
    xi = ", ".join(label(item) for item in tactics.starting_xi)
    bench = "\n".join(
        (
            f"GK. {label(tactics.bench_goalkeeper)}",
            *(
                f"{index}. {label(item)}"
                for index, item in enumerate(tactics.bench_outfield_order, 1)
            ),
        )
    )
    return (
        f"DMF PULSE - GW{decision.target_gameweek}\n\n"
        "RECOMMENDATION\n"
        f"Transfer: {transfers}\n"
        f"Cost: {len(decision.transfers)} transfer(s)\n"
        f"Hit: -{comparison.transfer_hit_points}\n\n"
        "SQUAD\n"
        f"{squad}\n\n"
        "STARTING XI\n"
        f"Formation: {formation}\n"
        f"{xi}\n\n"
        "BENCH\n"
        f"{bench}\n\n"
        f"Captain: {label(tactics.captain)}\n"
        f"Vice: {label(tactics.vice_captain)}\n\n"
        "PROJECTION\n"
        f"Recommended: {comparison.recommended_expected_points_after_hit:.2f}\n"
        f"No action:   {comparison.no_transfer_expected_points:.2f}\n"
        f"Net uplift:  {comparison.net_expected_uplift:+.2f}\n"
        f"Gain p10 / median / p90: {comparison.gain_p10} / {comparison.gain_median} / "
        f"{comparison.gain_p90}\n"
        "P(recommendation > baseline): "
        f"{comparison.probability_recommended_beats_baseline:.1%}\n\n"
        "WARNINGS\n"
        f"{warnings}\n"
        "- FPL_API_OPERATOR_INITIATED_ACCEPTED_CONTRACTUAL_RISK\n"
        "- RULES_VERIFIED_PRIVATE_IN_PROCESS_AUTHORITY\n"
        "- OFFICIAL_FPL_AND_CURRENT_TEAM_BODIES_NOT_RETAINED\n"
        "- NOT_PRODUCTION_ACTIVE\n"
    )


class PrivateV1OneCommandService:
    """Acquire, assemble, execute, and release one current recommendation in memory."""

    def __init__(
        self,
        *,
        direct_client_factory: Callable[[DirectFplRunAttestation], DirectFplClient] | None = None,
        odds_service_factory: Callable[[Callable[[], datetime]], CurrentOddsTransientService]
        | None = None,
        score_service_factory: Callable[[Callable[[], datetime]], CurrentScorePriorService]
        | None = None,
        recommendation_service: PrivateV1RecommendationService | None = None,
    ) -> None:
        self._direct_client_factory = direct_client_factory or (
            lambda attestation: DirectFplClient(attestation)
        )
        self._odds_service_factory = odds_service_factory or (
            lambda clock: CurrentOddsTransientService(clock=clock)
        )
        self._score_service_factory = score_service_factory or (
            lambda clock: CurrentScorePriorService(clock=clock)
        )
        self._recommendation_service = recommendation_service or PrivateV1RecommendationService()

    def run(self, request: OneCommandRequest) -> OneCommandResult:
        if (
            isinstance(request.entry_id, bool)
            or request.entry_id <= 0
            or request.run_at.tzinfo is None
            or request.run_at.utcoffset() is None
        ):
            raise PrivateV1Error("USAGE_INVALID", "entry ID and run timestamp are invalid")
        run_at = request.run_at.astimezone(UTC)

        def clock() -> datetime:
            return run_at

        try:
            attestation = DirectFplRunAttestation(attested_at=run_at)
            direct_client = self._direct_client_factory(attestation)
            snapshot = acquire_direct_fpl_snapshot(
                direct_client, entry_id=request.entry_id, captured_at=run_at
            )
            ruleset, capability, rules_authority = _rules_authority(run_at)
            manager = CurrentManagerStateService(clock=clock).compile_provider_snapshot(
                snapshot.current_team,
                fpl_input=snapshot.fpl_input,
                ruleset=ruleset,
                capability=capability,
                observed_at=run_at,
                overall_points=snapshot.entry.summary_overall_points,
                overall_rank=snapshot.entry.summary_overall_rank,
                private_rules_authority=rules_authority,
            )
            target_fixtures = tuple(
                item
                for item in snapshot.fpl_input.fixtures
                if item.event_identity == snapshot.fpl_input.target_event.identity
                and item.kickoff_at is not None
            )
            if not target_fixtures:
                raise IngestionError("TARGET_GAMEWEEK_UNRESOLVED", "target fixtures are absent")
            latest_kickoff = max(
                item.kickoff_at for item in target_fixtures if item.kickoff_at is not None
            )
            odds = self._odds_service_factory(clock).acquire(
                information_cutoff=run_at,
                commence_to=latest_kickoff + timedelta(seconds=1),
            )
            bridge = build_automatic_current_identity_map(
                snapshot.fpl_input, odds, decided_at=run_at
            )
            unified_request = bind_current_unified_state_request(
                snapshot.fpl_input, odds, bridge, manager, ruleset, capability
            )
            current = CurrentUnifiedStateService().compose(
                unified_request,
                fpl_input=snapshot.fpl_input,
                odds_input=odds,
                identity_map=bridge,
                manager_state=manager,
                ruleset=ruleset,
                capability=capability,
                private_rules_authority=rules_authority,
            )
            market_view = build_transient_current_market_identity_view(current, resolved_at=run_at)
            markets = CurrentMarketConstraintService().build(
                bind_current_market_constraint_request(current, market_view),
                source=current,
                identity_view=market_view,
            )
            player_map = build_automatic_player_identity_map(snapshot, manager)
            model_minutes = build_automatic_model_minutes(snapshot, player_map, market_view)
            ownership = build_automatic_ownership(snapshot, manager)
            candidates = build_full_candidate_policy(snapshot, manager)
            source_prior = self._score_service_factory(clock).build(
                CurrentScorePriorBuildRequest(
                    information_cutoff=run_at,
                    rights_profile_id="openfootball_football_json_score_prior_v1",
                )
            )
            score_priors = _score_priors(
                source_prior,
                snapshot=snapshot,
                market_view=market_view,
                identity_map=player_map,
            )
            packaged_prior = load_packaged_player_prior()
            carry_forward = (
                None
                if snapshot.target_gameweek == 1
                else build_automatic_current_gw_stale_prior_policy(
                    packaged_prior,
                    snapshot.fpl_input,
                    current_official_fpl_element_ids=tuple(
                        item.official_fpl_element_id for item in player_map.players
                    ),
                    declared_at=run_at,
                )
            )
            mc_policy = MonteCarloPolicy(
                minimum_effective_scenarios=1.0,
                maximum_mean_mcse=100.0,
                maximum_probability_se=1.0,
                maximum_quantile_span=100,
                quantiles=(0.1, 0.5, 0.9),
                thresholds=(5, 10, 15),
                batch_count=2,
            )
            allocation = load_packaged_event_allocation_config()
            execution = seal_execution_input(
                PrivateV1ExecutionInput.model_construct(
                    run_id=request.run_id,
                    code_sha=request.code_sha,
                    projection_mode=ProjectionMode.REPLAY,
                    retention_class="PRIVATE_TRANSIENT_NO_RETENTION",
                    synthetic_source_attestation=None,
                    current_state=current,
                    player_identity_map=player_map,
                    market_identity_view=market_view,
                    market_constraints=markets,
                    score_priors=score_priors,
                    manual_minutes=model_minutes,
                    ownership=ownership,
                    candidate_action_policy=candidates,
                    ruleset=ruleset,
                    full_season_capability=capability,
                    private_rules_authority=rules_authority,
                    player_prior_carry_forward_policy=carry_forward,
                    root_seed=request.root_seed,
                    scenario_count=request.scenario_count,
                    stage9_monte_carlo_policy=mc_policy,
                    stage9_monte_carlo_policy_sha256=canonical_sha256(
                        mc_policy.model_dump(mode="json")
                    ),
                    event_allocation_config=allocation,
                    event_allocation_config_sha256=canonical_sha256(
                        allocation.model_dump(mode="json")
                    ),
                    expected_stage8_policy_sha256=load_score_baseline_policy().sha256,
                    expected_player_prior_artifact_sha256=(packaged_prior.artifact.artifact_sha256),
                    expected_player_prior_acceptance_sha256=(
                        packaged_prior.historical_acceptance.acceptance_sha256
                    ),
                    require_stage9_mc_pass=True,
                    semantic_sha256="0" * 64,
                )
            )
            run = self._recommendation_service.run(execution)
            return OneCommandResult(
                status="REAL_PRIVATE_TRANSIENT_RECOMMENDATION",
                decision=run.decision,
                report=_display_report(run.decision, snapshot, player_map),
                fpl_request_count=snapshot.request_count,
                fpl_endpoint_classes=snapshot.endpoint_classes,
            )
        except PrivateV1Error:
            raise
        except IngestionError as exc:
            raise PrivateV1Error(exc.code, exc.message) from None
        except CurrentMarketConstraintError as exc:
            raise PrivateV1Error(exc.code, exc.message) from None
        except (ValidationError, ValueError, ArithmeticError, KeyError, TypeError):
            raise PrivateV1Error(
                "ONE_COMMAND_INPUT_INVALID", "automatic current input assembly failed"
            ) from None


__all__ = [
    "OneCommandRequest",
    "OneCommandResult",
    "PrivateV1OneCommandService",
]
