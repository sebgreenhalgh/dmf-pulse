"""Adversarial regressions for the MIN-007E lineup audit remediation."""

from __future__ import annotations

import copy
import json
from decimal import Decimal, getcontext
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.lineup import (
    SAMPLE_COUNT,
    BlockedLineupResult,
    InvalidLineupResult,
    LineupModelValidationError,
    ProjectedLineupResult,
    RoleMarginal,
    sample_coherent_lineups,
)

pytestmark = pytest.mark.unit


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def policy(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(value, dict)
    return value


def _candidates() -> list[dict[str, object]]:
    positions = ["GK", "GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 10
    return [
        {
            "player_id": str(uuid5(NAMESPACE_URL, f"min007e-remediation-{index}")),
            "player_key": f"remediation_{index}",
            "position": position,
            "start_weight": "0.500000",
            "bench_weight": "0.500000",
            "hard_ineligible": False,
        }
        for index, position in enumerate(positions)
    ]


def _kwargs(policy: dict[str, object]) -> dict[str, object]:
    return {
        "fixture_id": str(uuid5(NAMESPACE_URL, "min007e-remediation-fixture")),
        "team_id": str(uuid5(NAMESPACE_URL, "min007e-remediation-team")),
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "policy": policy,
    }


def _projected(policy: dict[str, object]) -> ProjectedLineupResult:
    result = sample_coherent_lineups(_candidates(), seed_suffix="", **_kwargs(policy))
    assert isinstance(result, ProjectedLineupResult)
    return result


def _payload(result: ProjectedLineupResult) -> dict[str, object]:
    value = copy.deepcopy(result.model_dump(mode="python"))
    assert isinstance(value, dict)
    scenarios = value["scenarios"]
    assert isinstance(scenarios, tuple)
    value["scenarios"] = [dict(scenario) for scenario in scenarios]
    for scenario in value["scenarios"]:
        scenario["starters"] = list(scenario["starters"])
        scenario["bench"] = list(scenario["bench"])
        scenario["members"] = [dict(member) for member in scenario["members"]]
    first = value["first_scenarios"]
    assert isinstance(first, tuple)
    value["first_scenarios"] = [dict(item) for item in first]
    for item in value["first_scenarios"]:
        item["starters"] = list(item["starters"])
        item["bench"] = list(item["bench"])
    marginals = value["role_marginals"]
    assert isinstance(marginals, tuple)
    value["role_marginals"] = [dict(item) for item in marginals]
    return value


def _assert_invalid(payload: dict[str, object]) -> None:
    with pytest.raises((ValidationError, LineupModelValidationError, ValueError)):
        ProjectedLineupResult.model_validate(payload)


def test_duplicate_player_id_and_uuid_alias_are_rejected(policy: dict[str, object]) -> None:
    candidates = _candidates()
    candidates[1]["player_id"] = candidates[0]["player_id"]
    duplicate = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    assert isinstance(duplicate, InvalidLineupResult)
    assert duplicate.error_code == "DUPLICATE_PLAYER_ID"

    aliases = _candidates()
    player_id = str(aliases[0]["player_id"])
    aliases[1]["player_id"] = "{" + player_id.upper() + "}"
    alias_duplicate = sample_coherent_lineups(aliases, seed_suffix="", **_kwargs(policy))
    assert isinstance(alias_duplicate, InvalidLineupResult)
    assert alias_duplicate.error_code == "DUPLICATE_PLAYER_ID"


def test_player_key_identity_is_one_to_one(policy: dict[str, object]) -> None:
    candidates = _candidates()
    candidates[1]["player_key"] = candidates[0]["player_key"]
    duplicate_key = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    assert isinstance(duplicate_key, InvalidLineupResult)
    assert duplicate_key.error_code == "DUPLICATE_PLAYER_KEY"

    conflicting_id = _candidates()
    conflicting_id[1]["player_id"] = conflicting_id[0]["player_id"]
    conflicting_id[1]["player_key"] = "different-key"
    same_id = sample_coherent_lineups(conflicting_id, seed_suffix="", **_kwargs(policy))
    assert isinstance(same_id, InvalidLineupResult)
    assert same_id.error_code == "DUPLICATE_PLAYER_ID"


@pytest.mark.parametrize("player_key", ["", None, False, 0, b"key"])
def test_player_key_is_strict_non_empty(policy: dict[str, object], player_key: object) -> None:
    candidates = _candidates()
    candidates[0]["player_key"] = player_key
    result = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    assert isinstance(result, InvalidLineupResult)


@pytest.mark.parametrize("ambient_precision", [28, 60])
def test_weight_constraint_uses_integrity_precision(
    policy: dict[str, object], ambient_precision: int
) -> None:
    candidates = _candidates()
    candidates[0]["start_weight"] = Decimal("0.99999999999999999999999999996")
    candidates[0]["bench_weight"] = Decimal("0.00000000000000000000000000005")
    previous = getcontext().prec
    try:
        getcontext().prec = ambient_precision
        result = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    finally:
        getcontext().prec = previous
    assert isinstance(result, InvalidLineupResult)
    assert result.error_code == "INVALID_ROLE_WEIGHTS"


@pytest.mark.parametrize("weight", ["NaN", "Infinity", "-Infinity", "-0.1"])
def test_nonfinite_and_negative_weights_rejected(policy: dict[str, object], weight: str) -> None:
    candidates = _candidates()
    candidates[0]["start_weight"] = weight
    result = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    assert isinstance(result, InvalidLineupResult)


def test_empty_seed_is_valid_and_nonempty_seed_changes_identity(
    policy: dict[str, object],
) -> None:
    empty = sample_coherent_lineups(_candidates(), seed_suffix="", **_kwargs(policy))
    alternate = sample_coherent_lineups(_candidates(), seed_suffix="ALT", **_kwargs(policy))
    assert isinstance(empty, ProjectedLineupResult)
    assert isinstance(alternate, ProjectedLineupResult)
    assert empty.scenario_set_sha256 != alternate.scenario_set_sha256


@pytest.mark.parametrize("seed_suffix", [None, False, 0, Decimal(0), b""])
def test_non_string_seed_is_rejected(policy: dict[str, object], seed_suffix: object) -> None:
    result = sample_coherent_lineups(_candidates(), seed_suffix=seed_suffix, **_kwargs(policy))  # type: ignore[arg-type]
    assert isinstance(result, InvalidLineupResult)
    assert result.error_code == "INVALID_SEED_SUFFIX"


def test_projected_result_rejects_fabricated_empty_state(policy: dict[str, object]) -> None:
    payload = _payload(_projected(policy))
    payload["scenarios"] = []
    payload["first_scenarios"] = []
    payload["role_marginals"] = []
    _assert_invalid(payload)


def test_projected_result_rejects_scenario_index_corruption(policy: dict[str, object]) -> None:
    payload = _payload(_projected(policy))
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[1]["scenario_index"] = 0
    _assert_invalid(payload)


def test_projected_result_rejects_scenario_coherence_corruption(
    policy: dict[str, object],
) -> None:
    payload = _payload(_projected(policy))
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    scenario["starters"][0] = scenario["bench"][0]
    _assert_invalid(payload)


def test_projected_result_rejects_wrong_xi_bench_and_goalkeeper_counts(
    policy: dict[str, object],
) -> None:
    payload = _payload(_projected(policy))
    scenario = payload["scenarios"][0]
    scenario["starters"] = scenario["starters"][:-1]
    _assert_invalid(payload)

    payload = _payload(_projected(policy))
    scenario = payload["scenarios"][0]
    scenario["bench"] = scenario["bench"][:-1]
    _assert_invalid(payload)

    payload = _payload(_projected(policy))
    scenario = payload["scenarios"][0]
    marginals = payload["role_marginals"]
    goalkeeper = next(item["player_id"] for item in marginals if item["position"] == "GK")
    outfield = next(item["player_id"] for item in marginals if item["position"] != "GK")
    index = scenario["starters"].index(goalkeeper)
    scenario["starters"][index] = outfield
    _assert_invalid(payload)


def test_projected_result_rejects_scenario_hash_corruption(policy: dict[str, object]) -> None:
    payload = _payload(_projected(policy))
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["scenario_sha256"] = "0" * 64
    _assert_invalid(payload)


def test_projected_result_rejects_scenario_set_hash_corruption(
    policy: dict[str, object],
) -> None:
    payload = _payload(_projected(policy))
    payload["scenario_set_sha256"] = "0" * 64
    _assert_invalid(payload)


def test_projected_result_rejects_first_three_corruption(policy: dict[str, object]) -> None:
    payload = _payload(_projected(policy))
    first = payload["first_scenarios"]
    assert isinstance(first, list)
    first[0]["scenario_sha256"] = "0" * 64
    _assert_invalid(payload)


def test_projected_result_rejects_marginal_identity_corruption(
    policy: dict[str, object],
) -> None:
    payload = _payload(_projected(policy))
    marginals = payload["role_marginals"]
    assert isinstance(marginals, list)
    marginals[1]["player_id"] = marginals[0]["player_id"]
    _assert_invalid(payload)


def test_projected_result_rejects_marginal_frequency_corruption(
    policy: dict[str, object],
) -> None:
    payload = _payload(_projected(policy))
    marginals = payload["role_marginals"]
    assert isinstance(marginals, list)
    marginals[0]["p_start"], marginals[0]["p_bench"] = (
        marginals[0]["p_bench"],
        marginals[0]["p_start"],
    )
    _assert_invalid(payload)


def test_projected_result_rejects_team_sum_corruption(policy: dict[str, object]) -> None:
    payload = _payload(_projected(policy))
    payload["sum_p_start"] = Decimal(10)
    _assert_invalid(payload)


def test_role_marginal_rejects_nonfinite_probability() -> None:
    with pytest.raises((ValidationError, LineupModelValidationError, ValueError)):
        RoleMarginal(
            player_id=str(uuid5(NAMESPACE_URL, "nonfinite-marginal")),
            player_key="nonfinite",
            position="MID",
            p_start=Decimal("NaN"),
            p_bench=Decimal(0),
            p_out=Decimal(1),
        )


def test_blocked_to_projected_copy_is_rejected(policy: dict[str, object]) -> None:
    candidates = _candidates()
    for candidate in candidates:
        candidate["hard_ineligible"] = True
        candidate["start_weight"] = "0"
        candidate["bench_weight"] = "0"
    blocked = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    assert isinstance(blocked, BlockedLineupResult)
    with pytest.raises((ValidationError, LineupModelValidationError, ValueError)):
        blocked.model_copy(update={"status": "PROJECTED"})


def test_valid_safe_copy_and_input_order_invariance(policy: dict[str, object]) -> None:
    candidates = _candidates()
    original = copy.deepcopy(candidates)
    result = sample_coherent_lineups(candidates, seed_suffix="", **_kwargs(policy))
    reordered = sample_coherent_lineups(
        list(reversed(candidates)), seed_suffix="", **_kwargs(policy)
    )
    assert isinstance(result, ProjectedLineupResult)
    assert isinstance(reordered, ProjectedLineupResult)
    assert result == result.model_copy(update={"sum_p_start": result.sum_p_start})
    assert result.model_dump(mode="json") == reordered.model_dump(mode="json")
    assert candidates == original


def test_result_models_revalidate_merged_updates(policy: dict[str, object]) -> None:
    result = _projected(policy)
    with pytest.raises((ValidationError, LineupModelValidationError, ValueError)):
        result.model_copy(update={"scenario_set_sha256": "0" * 64})
    assert result.model_copy(update={"team_id": result.team_id}) == result


def test_scenario_members_have_exact_roster_identity(policy: dict[str, object]) -> None:
    payload = _payload(_projected(policy))
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    members = scenarios[0]["members"]
    assert isinstance(members, list)
    members.pop()
    _assert_invalid(payload)


def test_scenario_position_and_goalkeeper_coherence_is_revalidated(
    policy: dict[str, object],
) -> None:
    payload = _payload(_projected(policy))
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    member = scenarios[0]["members"][0]
    member["position"] = "GK" if member["position"] != "GK" else "DEF"
    _assert_invalid(payload)


def test_sample_count_and_first_scenarios_are_fixed(policy: dict[str, object]) -> None:
    result = _projected(policy)
    assert result.sample_count == SAMPLE_COUNT
    assert [item.scenario_index for item in result.first_scenarios] == [0, 1, 2]
