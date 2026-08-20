"""GW1 preseason integration gates around the accepted Stage-10 rules view."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.candidate_pool import snapshot_hash
from dmf_pulse.optimisation.current_initial_squad import _select_portfolios
from dmf_pulse.optimisation.models import (
    CandidatePoolSnapshot,
    OneGameweekOptimisationRequest,
    OptimisationStatus,
    SearchScope,
)
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import RuleCapability
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import players, projection, seal_request

pytestmark = pytest.mark.unit


def test_preseason_requires_exact_initial_squad_capability(repository_root: Path) -> None:
    compiled = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    player_points = compile_capability_artifact(compiled, RuleCapability.PLAYER_POINTS)
    initial_squad = compile_capability_artifact(compiled, RuleCapability.GW1_INITIAL_SQUAD)

    for capability in (None, player_points):
        with pytest.raises(
            RulesValidationError, match="GW1_INITIAL_SQUAD capability is unavailable"
        ):
            build_one_gameweek_rules_view(
                compiled,
                projection_mode=ProjectionMode.PRESEASON_DECISION_SUPPORT,
                capability=capability,
            )

    view = build_one_gameweek_rules_view(
        compiled,
        projection_mode=ProjectionMode.PRESEASON_DECISION_SUPPORT,
        capability=initial_squad,
    )
    assert view.manager_capability == RuleCapability.GW1_INITIAL_SQUAD
    assert view.manager_capability_hash == initial_squad.capability_hash
    assert view.initial_budget_tenths == 1000
    assert view.squad_size == 15
    assert view.max_players_per_club == 3


def test_verified_target_rules_remain_blocked_for_production(repository_root: Path) -> None:
    compiled = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    full_season = compile_capability_artifact(compiled, RuleCapability.FULL_SEASON)

    with pytest.raises(RulesValidationError, match="FULL_SEASON manager-tactics") as blocked:
        build_one_gameweek_rules_view(
            compiled,
            projection_mode=ProjectionMode.PRODUCTION,
            capability=full_season,
        )
    assert blocked.value.code == "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE"


def test_factorized_preseason_search_preserves_exact_stage10_with_1000_scenarios(
    repository_root: Path,
) -> None:
    compiled = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    capability = compile_capability_artifact(compiled, RuleCapability.GW1_INITIAL_SQUAD)
    candidate_values = tuple(
        player.model_copy(update={"initial_selection_cost_tenths": 50}) for player in players()
    )
    pool = CandidatePoolSnapshot(
        information_cutoff_utc="2026-08-16T00:00:00Z",
        players=candidate_values,
        snapshot_sha256="0" * 64,
    )
    pool = pool.model_copy(update={"snapshot_sha256": snapshot_hash(pool)})
    request = seal_request(
        OneGameweekOptimisationRequest(
            request_id="gw1-preseason-factorized",
            projection_mode=ProjectionMode.PRESEASON_DECISION_SUPPORT,
            gameweek_id="GW1",
            information_cutoff_utc=pool.information_cutoff_utc,
            search_scope=SearchScope.BOUNDED_PLAYER_POOL,
            candidate_pool=pool,
            request_sha256="0" * 64,
        )
    )
    values = tuple(
        {player.player_id: (index % 5 if player.player_id == "p00" else 0) for player in players()}
        for index in range(1000)
    )
    stage9 = projection(
        compiled.ruleset_hash,
        values=values,
        weights=tuple(1 / 1000 for _ in range(1000)),
    )

    missing = optimise_one_gameweek(request, stage9, compiled)
    assert missing.status is OptimisationStatus.BLOCKED
    assert missing.error_code == "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE"

    result = optimise_one_gameweek(request, stage9, compiled, capability=capability)
    assert result.status is OptimisationStatus.SUCCESS
    assert result.recommended_plan is not None
    assert result.lineage.manager_capability == RuleCapability.GW1_INITIAL_SQUAD
    assert result.lineage.manager_capability_hash == capability.capability_hash
    assert result.recommended_plan.total_cost_tenths == 750
    assert result.recommended_plan.remaining_budget_tenths == 250
    assert result.recommended_plan.legality.legal
    assert result.recommended_plan.expected_manager_points == Decimal(4)
    assert result.recommended_plan.tactical_configuration.captain == "p00"
    assert len(result.recommended_plan.scenario_scores) == 1000
    assert result.solver_status.tactical_configurations_evaluated == 363_000
    assert result.solver_status.scenario_operation_upper_bound < 20_000_000
    assert 363_000 * 1000 > 20_000_000


def test_current_candidate_beam_builds_three_distinct_legal_portfolios() -> None:
    positions = (
        (PlayerPosition.GK, 2),
        (PlayerPosition.DEF, 6),
        (PlayerPosition.MID, 6),
        (PlayerPosition.FWD, 4),
    )
    rows = []
    player_index = 0
    for position, count in positions:
        for position_index in range(count):
            rows.append(
                SimpleNamespace(
                    transient_player_id=f"player-{player_index:02d}",
                    transient_team_id=f"club-{player_index:02d}",
                    position=position,
                    current_price_tenths=50,
                    mean_expected_fpl_points=float(20 - position_index),
                    probability_start=f"0.{900000000000 - position_index:012d}",
                    probability_appearance="0.950000000000",
                    probability_10_plus=float(position_index) / 10,
                    selected_percentiles={
                        "p10": position_index,
                        "p90": position_index * 2,
                    },
                    uncertainty=SimpleNamespace(points_standard_deviation=position_index),
                )
            )
            player_index += 1
    quotas = {
        PlayerPosition.GK: 2,
        PlayerPosition.DEF: 5,
        PlayerPosition.MID: 5,
        PlayerPosition.FWD: 3,
    }
    rules = SimpleNamespace(
        position_squad_quota=quotas,
        initial_budget_tenths=1000,
        max_players_per_club=3,
    )

    portfolios = _select_portfolios(tuple(rows), rules)
    assert set(portfolios) == {"EXPECTED_POINTS", "CONSERVATIVE", "HIGHER_UPSIDE"}
    assert len(set(portfolios.values())) == 3
    for squad in portfolios.values():
        assert len(squad) == 15
        selected = [row for row in rows if row.transient_player_id in squad]
        assert sum(row.current_price_tenths for row in selected) <= 1000
        for position, quota in quotas.items():
            assert sum(row.position is position for row in selected) == quota
