"""Weighted scenario effective ownership and leverage."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekScenarioSet
from dmf_pulse.optimisation.models import CandidatePlayer, OneGameweekRulesView
from dmf_pulse.rank_strategy.cohorts import normalised_member_weights, require_permitted_sample
from dmf_pulse.rank_strategy.manager_multipliers import (
    calculate_manager_multipliers,
    raw_projection_hash,
    shared_scenario_set_hash,
)
from dmf_pulse.rank_strategy.models import (
    CohortSample,
    EffectiveOwnershipReport,
    ManagerChip,
    ManagerMultiplierPolicy,
    ManagerTeamPlan,
    PlayerOwnership,
)
from dmf_pulse.rank_strategy.ownership import is_bench_player, saved_multiplier


def _weighted_quantile(values: list[tuple[float, float]], probability: float) -> float:
    ordered = sorted(values, key=lambda item: item[0])
    threshold = probability * sum(weight for _, weight in ordered)
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative + 1e-15 >= threshold:
            return value
    return ordered[-1][0]


def calculate_effective_ownership(
    sample: CohortSample,
    scenario_set: GameweekScenarioSet,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: ManagerMultiplierPolicy,
    *,
    sebastian_plan: ManagerTeamPlan | None = None,
) -> EffectiveOwnershipReport:
    """Calculate EO as weighted mean actual counted multiplier.

    Raw ownership is retained only as a separate descriptive field.  Every manager,
    including Sebastian when supplied, is evaluated against the exact same Stage-9
    scenario set.
    """

    require_permitted_sample(sample)
    weights = normalised_member_weights(sample)
    member_sets = {
        member.manager_plan.manager_id: calculate_manager_multipliers(
            member.manager_plan,
            scenario_set,
            players,
            rules,
            policy,
        )
        for member in sample.members
    }
    sebastian = (
        calculate_manager_multipliers(sebastian_plan, scenario_set, players, rules, policy)
        if sebastian_plan is not None
        else None
    )
    scenario_by_identity = {
        (item.scenario_id, item.outcome_draw_id): item for item in scenario_set.scenarios
    }
    entries: list[PlayerOwnership] = []
    for player_id in sorted(scenario_set.player_ids):
        raw = starting = captain = tc = vice = bb = saved_eo = 0.0
        scenario_eo: dict[str, float] = {}
        for member in sample.members:
            plan = member.manager_plan
            manager_weight = weights[plan.manager_id]
            active = set(plan.active_squad)
            raw += manager_weight * float(player_id in active)
            starting += manager_weight * float(player_id in plan.tactical_configuration.starting_xi)
            captain += manager_weight * float(
                plan.active_chip is not ManagerChip.TRIPLE_CAPTAIN
                and player_id == plan.tactical_configuration.captain
            )
            tc += manager_weight * float(
                plan.active_chip is ManagerChip.TRIPLE_CAPTAIN
                and player_id == plan.tactical_configuration.captain
            )
            vice += manager_weight * float(player_id == plan.tactical_configuration.vice_captain)
            bb += manager_weight * float(
                plan.active_chip is ManagerChip.BENCH_BOOST and is_bench_player(plan, player_id)
            )
            saved_eo += manager_weight * saved_multiplier(
                plan,
                player_id,
                ordinary_captain_multiplier=rules.captain_multiplier,
                policy=policy,
            )
        for identity, _source_scenario in sorted(scenario_by_identity.items()):
            scenario_multiplier_mean = 0.0
            for member in sample.members:
                multiplier_set = member_sets[member.manager_plan.manager_id]
                multiplier = next(
                    item
                    for item in multiplier_set.scenarios
                    if (item.scenario_id, item.outcome_draw_id) == identity
                )
                scenario_multiplier_mean += (
                    weights[member.manager_plan.manager_id]
                    * multiplier.player_multipliers[player_id]
                )
            scenario_eo[f"{identity[0]}|{identity[1]}"] = 100.0 * scenario_multiplier_mean
        expected_eo = sum(
            source_scenario.weight * scenario_eo[f"{identity[0]}|{identity[1]}"]
            for identity, source_scenario in scenario_by_identity.items()
        )
        interval_values = [
            (scenario_eo[f"{identity[0]}|{identity[1]}"], source_scenario.weight)
            for identity, source_scenario in scenario_by_identity.items()
        ]
        sebastian_expected: float | None = None
        leverage: float | None = None
        if sebastian is not None:
            sebastian_expected = sum(
                item.weight * item.player_multipliers[player_id] for item in sebastian.scenarios
            )
            leverage = sebastian_expected - expected_eo / 100.0
        entries.append(
            PlayerOwnership(
                player_id=player_id,
                raw_ownership=100.0 * raw,
                starting_ownership=100.0 * starting,
                normal_captain_ownership=100.0 * captain,
                triple_captain_ownership=100.0 * tc,
                vice_ownership=100.0 * vice,
                bench_boost_counted_ownership=100.0 * bb,
                saved_effective_ownership=100.0 * saved_eo,
                expected_scenario_effective_ownership=expected_eo,
                scenario_effective_ownership=dict(sorted(scenario_eo.items())),
                eo_p10=_weighted_quantile(interval_values, 0.10),
                eo_p90=_weighted_quantile(interval_values, 0.90),
                sebastian_expected_multiplier=sebastian_expected,
                expected_leverage=leverage,
            )
        )
    report = EffectiveOwnershipReport(
        sample_id=sample.sample_id,
        rights_status=sample.rights_status,
        scenario_set_hash=shared_scenario_set_hash(scenario_set),
        raw_projection_hash=raw_projection_hash(scenario_set),
        entries=tuple(entries),
        confidence=sample.confidence,
        report_hash="0" * 64,
    )
    payload = report.model_dump(mode="json", exclude={"report_hash"})
    return report.model_copy(update={"report_hash": semantic_sha256(payload)})
