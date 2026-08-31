from __future__ import annotations

from copy import deepcopy

import pytest

from dmf_pulse.fpl_points.allocation import allocate_fixture_events
from dmf_pulse.fpl_points.models import FixtureEventScenario, ProjectionMode, ScorelineCell
from tests.support.factories import (
    A_GK,
    H_DEF,
    allocation_config,
    base_profiles,
    make_request,
    reference_engine,
)


def _allocated(*, penalty: bool = False, saves: bool = False) -> FixtureEventScenario:
    profiles = tuple(
        profile.model_copy(update={"goalkeeper_saves_per90": 20.0})
        if saves and profile.player_id == A_GK
        else profile
        for profile in base_profiles()
    )
    config = allocation_config(
        extra_penalty_attempt_probability=1.0 if penalty else 0.0,
        extra_penalty_save_probability=1.0 if penalty else 0.0,
    )
    request = make_request(scenario_count=1, root_seed=144, profiles=profiles, config=config)
    scenario, _ = allocate_fixture_events(
        cell=ScorelineCell(
            home_goals=0 if penalty or saves else 1,
            away_goals=0,
            probability="1.000000000000",
        ),
        participation=request.participation_scenarios[0],
        profiles=request.allocation_profiles,
        config=request.allocation_config,
        ruleset=reference_engine().identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=request.root_seed,
        scenario_index=0,
    )
    return scenario


def test_fixture_contract_rejects_scorer_outside_exact_interval() -> None:
    scenario = _allocated()
    payload = scenario.model_dump(mode="python")
    payload["goals"][0]["minute"] = 130.0

    with pytest.raises(ValueError, match="outside the on-pitch interval"):
        FixtureEventScenario.model_validate(payload)


def test_fixture_contract_rejects_outfield_or_off_pitch_save_owner() -> None:
    scenario = _allocated(saves=True)
    payload = scenario.model_dump(mode="python")
    assert payload["goalkeeper_saves"]
    payload["goalkeeper_saves"][0]["goalkeeper_player_id"] = H_DEF

    with pytest.raises(ValueError, match="invalid goalkeeper"):
        FixtureEventScenario.model_validate(payload)

    off_pitch = scenario.model_dump(mode="python")
    off_pitch["goalkeeper_saves"][0]["minute"] = 130.0
    with pytest.raises(ValueError, match="outside the on-pitch interval"):
        FixtureEventScenario.model_validate(off_pitch)


def test_fixture_contract_rejects_save_without_compatible_on_target_shot() -> None:
    scenario = _allocated(saves=True)
    payload = scenario.model_dump(mode="python")
    shooter_id = payload["goalkeeper_saves"][0]["shooter_player_id"]
    for player in payload["players"]:
        if player["player_id"] == shooter_id:
            player["bps"]["shots_on_target"] = 0

    with pytest.raises(ValueError, match="exceed compatible shots on target"):
        FixtureEventScenario.model_validate(payload)


def test_fixture_contract_rejects_unlinked_or_wrong_goalkeeper_penalty_save() -> None:
    scenario = _allocated(penalty=True)
    payload = scenario.model_dump(mode="python")
    assert payload["penalties"][0]["outcome"] == "SAVED"
    missing = deepcopy(payload)
    missing["penalties"] = []
    with pytest.raises(ValueError, match="does not match its penalty"):
        FixtureEventScenario.model_validate(missing)

    wrong = deepcopy(payload)
    wrong["penalties"][0]["goalkeeper_player_id"] = H_DEF
    with pytest.raises(ValueError, match="goalkeeper is invalid"):
        FixtureEventScenario.model_validate(wrong)
