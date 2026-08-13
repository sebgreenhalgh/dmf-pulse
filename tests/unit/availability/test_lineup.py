"""Focused MIN-007E coherent-lineup contract tests."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.lineup import (
    PHASES,
    SAMPLE_COUNT,
    BlockedLineupResult,
    InvalidLineupResult,
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
    rows: list[dict[str, object]] = []
    positions = ["GK", "GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 10
    for index, position in enumerate(positions):
        player_id = str(uuid5(NAMESPACE_URL, f"min007e-unit-{index}"))
        rows.append(
            {
                "player_id": player_id,
                "player_key": f"player_{index}",
                "position": position,
                "start_weight": "0.500000",
                "bench_weight": "0.500000",
                "hard_ineligible": False,
            }
        )
    return rows


def test_projected_result_is_coherent_and_decimal(policy: dict[str, object]) -> None:
    result = sample_coherent_lineups(
        _candidates(),
        fixture_id=str(uuid5(NAMESPACE_URL, "min007e-fixture")),
        team_id=str(uuid5(NAMESPACE_URL, "min007e-team")),
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert result.status == "PROJECTED"
    assert result.sample_count == SAMPLE_COUNT
    assert len(result.scenarios) == SAMPLE_COUNT
    assert len(result.first_scenarios) == 3
    for scenario in result.scenarios:
        assert len(scenario.starters) == 11
        assert len(scenario.bench) == 9
        assert set(scenario.starters).isdisjoint(scenario.bench)
        assert sum(member.role == "START" for member in scenario.members) == 11
        assert sum(member.role == "BENCH" for member in scenario.members) == 9
        assert (
            sum(member.position == "GK" and member.role == "START" for member in scenario.members)
            == 1
        )
    assert result.sum_p_start == Decimal(11)
    assert result.sum_p_bench == Decimal(9)
    assert result.sum_p_out == Decimal(3)
    assert all(isinstance(row.p_start, Decimal) for row in result.role_marginals)
    assert result.model_dump(mode="json")["sum_p_start"] == "11.000000000000"
    assert PHASES == ("START_GK", "START_OUTFIELD", "BENCH_GK", "BENCH_OUTFIELD")


def test_order_and_seed_are_deterministic(policy: dict[str, object]) -> None:
    candidates = _candidates()
    kwargs = {
        "fixture_id": str(uuid5(NAMESPACE_URL, "min007e-fixture")),
        "team_id": str(uuid5(NAMESPACE_URL, "min007e-team")),
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "policy": policy,
    }
    first = sample_coherent_lineups(candidates, seed_suffix="", **kwargs)
    reordered = list(reversed(copy.deepcopy(candidates)))
    second = sample_coherent_lineups(reordered, seed_suffix="", **kwargs)
    alternate = sample_coherent_lineups(candidates, seed_suffix="ALT", **kwargs)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.scenario_set_sha256 != alternate.scenario_set_sha256


def test_invalid_and_blocked_results_expose_no_partial_projection(
    policy: dict[str, object],
) -> None:
    candidates = _candidates()
    duplicate = copy.deepcopy(candidates)
    duplicate[1]["player_id"] = duplicate[0]["player_id"]
    invalid = sample_coherent_lineups(
        duplicate,
        fixture_id="fixture",
        team_id="team",
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert isinstance(invalid, InvalidLineupResult)
    assert invalid.error_code == "DUPLICATE_PLAYER_ID"
    blocked_candidates = copy.deepcopy(candidates)
    for row in blocked_candidates:
        row["hard_ineligible"] = True
        row["start_weight"] = "0"
        row["bench_weight"] = "0"
    blocked = sample_coherent_lineups(
        blocked_candidates,
        fixture_id="fixture",
        team_id="team",
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert isinstance(blocked, BlockedLineupResult)
    assert not hasattr(blocked, "scenarios")
