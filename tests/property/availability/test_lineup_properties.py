"""Deterministic property checks for the MIN-007E sampler."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.availability.lineup import sample_coherent_lineups

pytestmark = pytest.mark.property


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
            "player_id": str(uuid5(NAMESPACE_URL, f"min007e-property-{index}")),
            "player_key": f"property_{index}",
            "position": position,
            "start_weight": "0.500000",
            "bench_weight": "0.500000",
            "hard_ineligible": False,
        }
        for index, position in enumerate(positions)
    ]


@settings(max_examples=6, deadline=None)
@given(st.permutations(tuple(range(23))))
def test_candidate_order_does_not_change_scenarios(
    policy: dict[str, object], permutation: tuple[int, ...]
) -> None:
    candidates = _candidates()
    shuffled = [copy.deepcopy(candidates[index]) for index in permutation]
    kwargs = {
        "fixture_id": str(uuid5(NAMESPACE_URL, "min007e-property-fixture")),
        "team_id": str(uuid5(NAMESPACE_URL, "min007e-property-team")),
        "seed_suffix": "",
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "policy": policy,
    }
    assert sample_coherent_lineups(candidates, **kwargs).model_dump(
        mode="json"
    ) == sample_coherent_lineups(shuffled, **kwargs).model_dump(mode="json")


def test_hard_ineligible_is_never_selected(policy: dict[str, object]) -> None:
    candidates = _candidates()
    candidates[0]["hard_ineligible"] = True
    candidates[0]["start_weight"] = "0"
    candidates[0]["bench_weight"] = "0"
    result = sample_coherent_lineups(
        candidates,
        fixture_id=str(uuid5(NAMESPACE_URL, "min007e-property-fixture")),
        team_id=str(uuid5(NAMESPACE_URL, "min007e-property-team")),
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert result.status == "PROJECTED"
    marginal = next(
        row for row in result.role_marginals if row.player_id == candidates[0]["player_id"]
    )
    assert marginal.p_start == 0 and marginal.p_bench == 0 and marginal.p_out == 1
