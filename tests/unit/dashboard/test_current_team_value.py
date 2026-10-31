"""Authenticated current values retain their source meaning through the dashboard."""

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.dashboard import synthetic
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.dashboard.views import TeamView, desk_view
from dmf_pulse.private_v1.progress import NullProgress

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def current_values_run():
    # The source's value intentionally differs from both its 15 selling prices
    # (750) and those prices plus bank (887). Keep every source/model owned.
    import json

    inputs = synthetic.demo_inputs()
    current = json.loads(inputs["fpl-6.json"])
    current["transfers"].update(bank=137, value=913)
    assert sum(pick["selling_price"] for pick in current["picks"]) == 750
    inputs["fpl-6.json"] = json.dumps(current).encode()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(synthetic, "demo_inputs", lambda: inputs)
        yield synthetic.run_synthetic_recommendation(1, NullProgress())


def _view(result):
    return desk_view(
        result,
        job_id="owned-current-values",
        mode="SYNTHETIC_DEMONSTRATION",
        generated_at=DEMO_TIME,
        expires_at=DEMO_TIME + timedelta(minutes=1),
    )


def test_authenticated_reported_values_are_preserved_without_price_reconstruction(
    current_values_run,
):
    result = current_values_run
    assert result.presentation.current_bank_tenths == 137
    assert result.presentation.current_team_value_tenths == 913
    team = _view(result).team
    assert team.current_bank_tenths == 137
    assert team.current_team_value_tenths == 913
    assert team.decision == result.decision
    assert result.persistence_performed is False


def test_absent_older_presentation_values_remain_unavailable(current_values_run):
    original = current_values_run.presentation
    payload = original.model_dump(mode="python")
    payload.pop("current_bank_tenths")
    payload.pop("current_team_value_tenths")
    older = type(original).model_validate(payload)
    view = _view(replace(current_values_run, presentation=older))
    assert view.team.current_bank_tenths is None
    assert view.team.current_team_value_tenths is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_bank_tenths", -1),
        ("current_bank_tenths", True),
        ("current_bank_tenths", 1.5),
        ("current_bank_tenths", "137"),
        ("current_team_value_tenths", 0),
        ("current_team_value_tenths", -1),
        ("current_team_value_tenths", True),
        ("current_team_value_tenths", 913.5),
        ("current_team_value_tenths", "913"),
    ],
)
def test_current_values_require_exact_source_integer_units(current_values_run, field, value):
    original = current_values_run.presentation
    payload = original.model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError):
        type(original).model_validate(payload)
    team = _view(current_values_run).team.model_dump(mode="python")
    team[field] = value
    with pytest.raises(ValidationError):
        TeamView.model_validate(team)


def test_zero_current_bank_is_an_observation_not_missing(current_values_run):
    original = current_values_run.presentation
    payload = original.model_dump(mode="python")
    payload["current_bank_tenths"] = 0
    presentation = type(original).model_validate(payload)
    assert (
        _view(replace(current_values_run, presentation=presentation)).team.current_bank_tenths == 0
    )
