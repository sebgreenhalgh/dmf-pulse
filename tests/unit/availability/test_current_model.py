"""Accepted Stage-7 model to private transient scenario adaptation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import combinations, permutations, product
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.current_model import (
    CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_WARNING,
    CurrentModelTeamScenarios,
    CurrentTeamMinuteReconciliation,
    CurrentTeamPathPolicy,
    build_current_model_fixture_minutes,
    current_team_minute_reconciliation_sha256,
    load_current_team_path_policy,
    reconcile_current_team_scenario,
    validate_current_team_path,
)
from dmf_pulse.availability.manual_override import ManualScenarioPlayer, ManualWeightedScenario
from dmf_pulse.availability.pipeline import fit_projection_artifact, predict_minutes_baseline

pytestmark = pytest.mark.unit

TEAM_ID = "90000000-0000-4000-8000-000000000001"
STARTER_IDS = tuple(f"10000000-0000-4000-8000-{index:012d}" for index in range(1, 12))
BENCH_IDS = tuple(f"20000000-0000-4000-8000-{index:012d}" for index in range(1, 10))


def _raw_scenario(
    *,
    starter_minutes: dict[str, int] | None = None,
    bench_minutes: dict[str, int] | None = None,
) -> ManualWeightedScenario:
    starter_minutes = starter_minutes or {}
    bench_minutes = bench_minutes or {}
    starter_positions = ("GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD")
    bench_positions = ("GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD")
    players = [
        ManualScenarioPlayer(
            player_id=player_id,
            position=position,
            role="START",
            official_minutes=starter_minutes.get(player_id, 90),
        )
        for player_id, position in zip(STARTER_IDS, starter_positions, strict=True)
    ]
    players.extend(
        ManualScenarioPlayer(
            player_id=player_id,
            position=position,
            role="BENCH",
            official_minutes=bench_minutes.get(player_id, 0),
        )
        for player_id, position in zip(BENCH_IDS, bench_positions, strict=True)
    )
    return ManualWeightedScenario(
        scenario_id="S000",
        count=1,
        players=tuple(sorted(players, key=lambda item: item.player_id)),
    )


def _minutes(value: ManualWeightedScenario) -> dict[str, int]:
    return {item.player_id: item.official_minutes for item in value.players}


def _on_pitch_count(value: ManualWeightedScenario, minute: int) -> tuple[int, int]:
    active = tuple(
        item
        for item in value.players
        if (item.role == "START" and minute < item.official_minutes)
        or (
            item.role == "BENCH"
            and item.official_minutes > 0
            and minute >= 90 - item.official_minutes
        )
    )
    return len(active), sum(item.position == "GK" for item in active)


def test_current_team_path_policy_is_current_season_bound_and_sealed() -> None:
    policy = load_current_team_path_policy()

    assert policy.competition_code == "PL"
    assert policy.season_code == "2026/27"
    assert policy.match_minutes == 90
    assert policy.players_on_pitch == 11
    assert policy.goalkeepers_on_pitch == 1
    assert policy.maximum_standard_substitutions == 5
    assert policy.exceptional_substitutions_modelled is False
    assert policy.source_locator == "Premier League Handbook 2026/27, Rule L.29, page 237"


def test_live_shape_958_minutes_is_reconciled_as_one_coherent_goalkeeper_change() -> None:
    raw = _raw_scenario(
        starter_minutes={STARTER_IDS[0]: 18, STARTER_IDS[1]: 82},
        bench_minutes={BENCH_IDS[0]: 48},
    )
    assert sum(item.official_minutes for item in raw.players) == 958
    assert _on_pitch_count(raw, 27) == (10, 0)

    reconciled, metrics = reconcile_current_team_scenario(raw)
    minutes = _minutes(reconciled)

    validate_current_team_path(reconciled)
    assert sum(minutes.values()) == 990
    assert minutes[STARTER_IDS[0]] == 18
    assert minutes[BENCH_IDS[0]] == 72
    assert metrics.original_team_minutes == 958
    assert metrics.reconciled_team_minutes == 990
    assert metrics.adjusted_player_count == 2
    assert metrics.total_absolute_minute_adjustment == 32
    assert metrics.maximum_absolute_player_adjustment == 24
    assert metrics.substitution_count == 1
    assert {_on_pitch_count(reconciled, minute) for minute in range(90)} == {(11, 1)}


def test_reconciliation_caps_excess_bench_targets_and_repairs_unmatched_exits() -> None:
    starters = {player_id: 30 for player_id in STARTER_IDS[1:7]}
    benches = {player_id: 80 for player_id in BENCH_IDS[1:7]}
    raw = _raw_scenario(starter_minutes=starters, bench_minutes=benches)
    assert sum(item.official_minutes for item in raw.players) > 990

    reconciled, metrics = reconcile_current_team_scenario(raw)
    minutes = _minutes(reconciled)

    validate_current_team_path(reconciled)
    assert metrics.substitution_count == 5
    assert sum(minutes[player_id] < 90 for player_id in STARTER_IDS) == 5
    assert sum(minutes[player_id] > 0 for player_id in BENCH_IDS) == 5
    assert sum(minutes.values()) == 990

    unmatched_raw = _raw_scenario(starter_minutes={STARTER_IDS[1]: 20})
    repaired, repaired_metrics = reconcile_current_team_scenario(unmatched_raw)
    validate_current_team_path(repaired)
    assert _minutes(repaired)[STARTER_IDS[1]] == 90
    assert repaired_metrics.substitution_count == 0


def test_goalkeeper_stays_or_is_replaced_only_by_the_bench_goalkeeper() -> None:
    unused_raw = _raw_scenario(bench_minutes={BENCH_IDS[0]: 60})
    unused, unused_metrics = reconcile_current_team_scenario(unused_raw)
    assert _minutes(unused)[STARTER_IDS[0]] == 90
    assert _minutes(unused)[BENCH_IDS[0]] == 0
    assert unused_metrics.substitution_count == 0

    changed_raw = _raw_scenario(
        starter_minutes={STARTER_IDS[0]: 10},
        bench_minutes={BENCH_IDS[0]: 80},
    )
    changed, changed_metrics = reconcile_current_team_scenario(changed_raw)
    validate_current_team_path(changed)
    assert _minutes(changed)[STARTER_IDS[0]] == 10
    assert _minutes(changed)[BENCH_IDS[0]] == 80
    assert changed_metrics.substitution_count == 1


def test_all_ninety_and_halftime_paths_are_exact_and_deterministic() -> None:
    untouched, untouched_metrics = reconcile_current_team_scenario(_raw_scenario())
    validate_current_team_path(untouched)
    assert untouched_metrics.adjusted_player_count == 0
    assert untouched_metrics.substitution_count == 0

    raw = _raw_scenario(
        starter_minutes={STARTER_IDS[1]: 45},
        bench_minutes={BENCH_IDS[1]: 45},
    )
    first = reconcile_current_team_scenario(raw)
    second = reconcile_current_team_scenario(raw)
    assert first == second
    assert _minutes(first[0])[STARTER_IDS[1]] == 45
    assert _minutes(first[0])[BENCH_IDS[1]] == 45


def test_equal_distortion_prefers_fewer_substitutions_then_stable_identity() -> None:
    no_change, metrics = reconcile_current_team_scenario(
        _raw_scenario(bench_minutes={BENCH_IDS[1]: 60})
    )
    assert metrics.substitution_count == 0
    assert _minutes(no_change)[BENCH_IDS[1]] == 0

    raw = _raw_scenario(
        starter_minutes={STARTER_IDS[1]: 45, STARTER_IDS[2]: 45},
        bench_minutes={BENCH_IDS[1]: 45},
    )
    reconciled, metrics = reconcile_current_team_scenario(raw)
    assert metrics.total_absolute_minute_adjustment == 45
    assert metrics.substitution_count == 1
    assert _minutes(reconciled)[STARTER_IDS[1]] == 45
    assert _minutes(reconciled)[STARTER_IDS[2]] == 90


def test_small_exhaustive_golden_has_no_lower_feasible_l1_cost() -> None:
    active_starters = STARTER_IDS[1:3]
    active_bench = BENCH_IDS[1:3]
    raw = _raw_scenario(
        starter_minutes={active_starters[0]: 20, active_starters[1]: 70},
        bench_minutes={active_bench[0]: 65, active_bench[1]: 15},
    )
    reconciled, metrics = reconcile_current_team_scenario(raw)
    brute_costs: list[int] = []
    for substitution_count in range(3):
        for selected_starters in combinations(active_starters, substitution_count):
            for selected_bench in combinations(active_bench, substitution_count):
                for paired_starters in permutations(selected_starters):
                    for times in product(range(1, 90), repeat=substitution_count):
                        legal = {player_id: 90 for player_id in STARTER_IDS}
                        legal.update({player_id: 0 for player_id in BENCH_IDS})
                        for entrant, outgoing, minute in zip(
                            selected_bench, paired_starters, times, strict=True
                        ):
                            legal[outgoing] = minute
                            legal[entrant] = 90 - minute
                        brute_costs.append(
                            sum(
                                abs(legal[item.player_id] - item.official_minutes)
                                for item in raw.players
                            )
                        )

    validate_current_team_path(reconciled)
    assert metrics.total_absolute_minute_adjustment == min(brute_costs)


def test_team_path_validator_rejects_unpaired_exits_excess_substitutions_and_gk_swap() -> None:
    with pytest.raises(ValueError, match="paired"):
        validate_current_team_path(_raw_scenario(starter_minutes={STARTER_IDS[1]: 45}))

    with pytest.raises(ValueError, match="substitution limit"):
        validate_current_team_path(
            _raw_scenario(
                starter_minutes={player_id: 30 for player_id in STARTER_IDS[1:7]},
                bench_minutes={player_id: 60 for player_id in BENCH_IDS[1:7]},
            )
        )

    with pytest.raises(ValueError, match="goalkeeper"):
        validate_current_team_path(
            _raw_scenario(
                starter_minutes={STARTER_IDS[0]: 45},
                bench_minutes={BENCH_IDS[1]: 45},
            )
        )


def test_reconciliation_contracts_fail_closed_on_hostile_tampering() -> None:
    policy = load_current_team_path_policy()
    tampered_policy = policy.model_dump(mode="python")
    tampered_policy["semantic_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="policy semantic hash"):
        CurrentTeamPathPolicy.model_validate(tampered_policy)

    untouched, zero_metrics = reconcile_current_team_scenario(_raw_scenario())
    zero_payload = zero_metrics.model_dump(mode="python")
    zero_payload["total_absolute_minute_adjustment"] = 1
    with pytest.raises(ValueError, match="zero minute distortion"):
        CurrentTeamMinuteReconciliation.model_validate(zero_payload)

    _, positive_metrics = reconcile_current_team_scenario(
        _raw_scenario(
            starter_minutes={STARTER_IDS[1]: 40},
            bench_minutes={BENCH_IDS[1]: 40},
        )
    )
    positive_payload = positive_metrics.model_dump(mode="python")
    positive_payload["maximum_absolute_player_adjustment"] = (
        positive_metrics.total_absolute_minute_adjustment + 1
    )
    with pytest.raises(ValueError, match="coherent minute distortion"):
        CurrentTeamMinuteReconciliation.model_validate(positive_payload)

    players = list(untouched.players)
    starter_index = next(index for index, item in enumerate(players) if item.role == "START")
    players[starter_index] = ManualScenarioPlayer.model_construct(
        **{
            **players[starter_index].model_dump(mode="python"),
            "role": "BENCH",
        }
    )
    fewer_starters = ManualWeightedScenario.model_construct(
        scenario_id="S000", count=1, players=tuple(players)
    )
    with pytest.raises(ValueError, match="kickoff starters"):
        validate_current_team_path(fewer_starters, policy)

    players = list(untouched.players)
    goalkeeper_index = next(
        index
        for index, item in enumerate(players)
        if item.role == "START" and item.position == "GK"
    )
    players[goalkeeper_index] = ManualScenarioPlayer.model_construct(
        **{
            **players[goalkeeper_index].model_dump(mode="python"),
            "position": "DEF",
        }
    )
    no_starting_goalkeeper = ManualWeightedScenario.model_construct(
        scenario_id="S000", count=1, players=tuple(players)
    )
    with pytest.raises(ValueError, match="kickoff goalkeeper"):
        validate_current_team_path(no_starting_goalkeeper, policy)

    with pytest.raises(ValueError, match="strictly after kickoff"):
        validate_current_team_path(_raw_scenario(bench_minutes={BENCH_IDS[1]: 90}), policy)

    out_player = ManualScenarioPlayer.model_construct(
        player_id="30000000-0000-4000-8000-000000000001",
        position="DEF",
        role="OUT",
        official_minutes=1,
    )
    out_enters = ManualWeightedScenario.model_construct(
        scenario_id="S000",
        count=1,
        players=(*untouched.players, out_player),
    )
    with pytest.raises(ValueError, match="OUT players"):
        validate_current_team_path(out_enters, policy)

    bench_payload = _raw_scenario().model_dump(mode="python")
    bench_payload["players"][11]["role"] = "OUT"
    reduced_bench = ManualWeightedScenario.model_validate(bench_payload)
    with pytest.raises(ValueError, match="configured nine-player bench"):
        validate_current_team_path(reduced_bench, policy)
    with pytest.raises(ValueError, match="invalid role allocation"):
        reconcile_current_team_scenario(reduced_bench, policy)


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_current_model_adapter_preserves_accepted_coherent_role_scenarios(
    repository_root: Path,
) -> None:
    root = repository_root / "src/dmf_pulse/availability/resources"
    history = _read(root / "MIN-007/canonical_history.json")
    training = _read(root / "MIN-007/training_dataset.json")
    policy = _read(root / "MIN-007G/minutes_baseline_policy.json")
    context = _read(root / "MIN-007G/contexts/stable_xi.json")
    assert isinstance(history, dict)
    assert isinstance(context, dict)
    fixture_id = str(uuid5(NAMESPACE_URL, "dmf-pulse:current-model-test-fixture"))
    context["fixture_id"] = fixture_id
    artifact = fit_projection_artifact(training, policy=policy)
    home = predict_minutes_baseline(history, artifact, context=context, policy=policy)

    rosters = history["rosters"]
    assert isinstance(rosters, dict)
    beta = rosters["beta"]
    assert isinstance(beta, list)
    beta_context = dict(context)
    beta_context.update(
        {
            "team_key": "beta",
            "team_id": beta[0]["team_id"],
            "manager_regime_id": str(uuid5(NAMESPACE_URL, "dmf-pulse:beta-regime")),
            "focus_player_key": beta[0]["player_key"],
        }
    )
    away = predict_minutes_baseline(history, artifact, context=beta_context, policy=policy)

    first = build_current_model_fixture_minutes(
        home,
        away,
        information_cutoff=datetime(2026, 8, 14, 17, 30, tzinfo=UTC),
        observed_history_sha256="1" * 64,
        warnings=("EARLY_SEASON_SHRINKAGE_ACTIVE",),
    )
    second = build_current_model_fixture_minutes(
        home,
        away,
        information_cutoff=datetime(2026, 8, 14, 17, 30, tzinfo=UTC),
        observed_history_sha256="1" * 64,
        warnings=("EARLY_SEASON_SHRINKAGE_ACTIVE",),
    )

    assert first == second
    assert first.model_derived is True
    assert first.model_family == "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
    assert len(first.home.scenarios) == 256
    assert len(first.away.scenarios) == 256
    assert all(item.count == 1 for item in first.home.scenarios)
    assert tuple(item.scenario_id for item in first.home.scenarios) == tuple(
        item.scenario_id for item in first.away.scenarios
    )
    assert all(
        len([player for player in scenario.players if player.role == "START"]) == 11
        for scenario in first.home.scenarios
    )
    assert all(
        player.official_minutes < 90
        for scenario in first.home.scenarios
        for player in scenario.players
        if player.role == "BENCH"
    )
    assert first.home_projection == home.projection
    assert first.away_projection == away.projection
    assert first.training_dataset_sha256 == home.projection.dataset_sha256
    assert first.model_artifact_sha256 == home.projection.model_artifact_sha256
    assert CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_WARNING in first.warnings
    assert all(item.reconciled_team_minutes == 990 for item in first.home.reconciliations)
    assert all(item.reconciled_team_minutes == 990 for item in first.away.reconciliations)
    assert all(
        sum(player.official_minutes for player in scenario.players) == 990
        for scenario in (*first.home.scenarios, *first.away.scenarios)
    )

    tampered_team = first.home.model_dump(mode="python")
    tampered_scenario = tampered_team["scenarios"][0]
    starter = next(
        item
        for item in tampered_scenario["players"]
        if item["role"] == "START" and item["position"] != "GK" and item["official_minutes"] == 90
    )
    starter["official_minutes"] = 89
    with pytest.raises(ValueError, match="paired"):
        CurrentModelTeamScenarios.model_validate(tampered_team)

    bad_sequence = first.home.model_dump(mode="python")
    bad_sequence["scenarios"][0]["count"] = 2
    with pytest.raises(ValueError, match="exact 256-sample sequence"):
        CurrentModelTeamScenarios.model_validate(bad_sequence)

    bad_reconciliation_sequence = first.home.model_dump(mode="python")
    bad_reconciliation_payload = bad_reconciliation_sequence["reconciliations"][0]
    bad_reconciliation_payload["scenario_id"] = "S999"
    bad_reconciliation = CurrentTeamMinuteReconciliation.model_construct(
        **bad_reconciliation_payload
    )
    bad_reconciliation_payload["semantic_sha256"] = current_team_minute_reconciliation_sha256(
        bad_reconciliation
    )
    with pytest.raises(ValueError, match="reconciliation indices"):
        CurrentModelTeamScenarios.model_validate(bad_reconciliation_sequence)

    changed_roster = first.home.model_dump(mode="python")
    changed_player = next(
        item
        for item in changed_roster["scenarios"][1]["players"]
        if item["position"] == "DEF" and item["role"] == "BENCH"
    )
    changed_player["position"] = "MID"
    with pytest.raises(ValueError, match="roster changes"):
        CurrentModelTeamScenarios.model_validate(changed_roster)

    invalid_hard = first.home.model_dump(mode="python")
    invalid_hard["hard_ineligible_player_ids"] = ("f0000000-0000-4000-8000-000000000001",)
    with pytest.raises(ValueError, match="hard-ineligible identities"):
        CurrentModelTeamScenarios.model_validate(invalid_hard)

    active_hard = first.home.model_dump(mode="python")
    active_hard["hard_ineligible_player_ids"] = (
        next(item.player_id for item in first.home.scenarios[0].players if item.role == "START"),
    )
    with pytest.raises(ValueError, match="not OUT"):
        CurrentModelTeamScenarios.model_validate(active_hard)

    mismatched_metric_team = first.home.model_dump(mode="python")
    metric_payload = mismatched_metric_team["reconciliations"][0]
    metric_payload["substitution_count"] = (
        metric_payload["substitution_count"] + 1
        if metric_payload["substitution_count"] < 5
        else metric_payload["substitution_count"] - 1
    )
    provisional_metric = CurrentTeamMinuteReconciliation.model_construct(**metric_payload)
    metric_payload["semantic_sha256"] = current_team_minute_reconciliation_sha256(
        provisional_metric
    )
    with pytest.raises(ValueError, match="does not bind"):
        CurrentModelTeamScenarios.model_validate(mismatched_metric_team)

    tampered_metrics = first.home.reconciliations[0].model_dump(mode="python")
    tampered_metrics["original_team_minutes"] += 1
    with pytest.raises(ValueError, match="semantic hash"):
        CurrentTeamMinuteReconciliation.model_validate(tampered_metrics)
