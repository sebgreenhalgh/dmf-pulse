from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import dmf_pulse.fpl_points.rules_adapter as adapter_module
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from tests.support.factories import (
    RULESET_HASH,
    RULESET_ID,
    RULESET_VERSION,
    event_fixture,
    event_player,
    reference_engine,
)


class _Validator:
    @classmethod
    def model_validate(cls, value: Any) -> Any:
        return value


class _Record:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class _FakeAcceptedModels:
    FPLPosition = staticmethod(lambda value: value)
    DefensiveActions = _Validator
    BpsEvents = _Validator
    PlayerScenario = _Record
    FixtureScenario = _Record


class _FakeScore:
    def __init__(self, score: Any) -> None:
        self.bps = score.bps
        self._values = {
            key: value
            for key, value in score.model_dump(mode="python").items()
            if key not in {"bps_competition_rank", "bps_tied_at_rank"}
        }

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return dict(self._values)


def _compiled(
    *,
    status: str = "REFERENCE_ONLY",
    production_eligible: bool = False,
    blockers: tuple[str, ...] = (),
):
    return SimpleNamespace(
        ruleset_id=RULESET_ID,
        ruleset_version=RULESET_VERSION,
        ruleset_hash=RULESET_HASH,
        status=SimpleNamespace(value=status),
        production_eligible=production_eligible,
        unknown_blockers=blockers,
    )


def _approval(*, approved: bool = True, hash_value: str = RULESET_HASH):
    return SimpleNamespace(
        approved=approved,
        ruleset_id=RULESET_ID,
        ruleset_version=RULESET_VERSION,
        ruleset_hash=hash_value,
    )


def test_identity_and_mode_gates_cover_reference_active_approval_and_blockers() -> None:
    reference = AcceptedRulesAdapter(_compiled())
    reference.assert_mode_allowed(ProjectionMode.TEST)
    with pytest.raises(FplPointsError) as exc:
        reference.assert_mode_allowed(ProjectionMode.PRODUCTION)
    assert exc.value.code == "RULESET_NOT_ACTIVE"

    blocked = AcceptedRulesAdapter(_compiled(blockers=("assist_policy",)))
    with pytest.raises(FplPointsError) as exc:
        blocked.assert_mode_allowed(ProjectionMode.REPLAY)
    assert exc.value.code == "RULESET_SCORING_BLOCKED"

    not_eligible = AcceptedRulesAdapter(_compiled(status="ACTIVE"), _approval())
    with pytest.raises(FplPointsError) as exc:
        not_eligible.assert_mode_allowed(ProjectionMode.PRODUCTION)
    assert exc.value.code == "RULESET_NOT_PRODUCTION_ELIGIBLE"

    unapproved = AcceptedRulesAdapter(_compiled(status="ACTIVE", production_eligible=True))
    with pytest.raises(FplPointsError) as exc:
        unapproved.assert_mode_allowed(ProjectionMode.PRODUCTION)
    assert exc.value.code == "RULESET_APPROVAL_MISSING"

    active = AcceptedRulesAdapter(_compiled(status="ACTIVE", production_eligible=True), _approval())
    active.assert_mode_allowed(ProjectionMode.PRODUCTION)
    assert active.identity.human_approval_recorded is True


def test_adapter_delegates_fixture_scoring_and_adds_competition_ranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = event_fixture(
        home_goals=1,
        away_goals=0,
        players=(
            event_player("h-mid", "HOME", PlayerPosition.MID, goals_non_penalty=1),
            event_player("a-fwd", "AWAY", PlayerPosition.FWD, conceded=1),
        ),
    )
    reference_scores = reference_engine().score_fixture(scenario)
    fake_scoring = SimpleNamespace(
        score_fixture=lambda compiled, accepted: SimpleNamespace(
            players={key: _FakeScore(value) for key, value in reference_scores.items()}
        )
    )

    def fake_import(name: str):
        if name == "dmf_pulse.rules.models":
            return _FakeAcceptedModels
        if name == "dmf_pulse.rules.scoring":
            return fake_scoring
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", fake_import)
    adapter = AcceptedRulesAdapter(_compiled())
    actual = adapter.score_fixture(scenario)
    assert actual["h-mid"].goals == reference_scores["h-mid"].goals
    assert actual["h-mid"].bps_competition_rank == 1
    assert set(actual) == {"h-mid", "a-fwd"}


def test_adapter_rejects_scenario_ruleset_mismatch_before_delegation() -> None:
    scenario = event_fixture(
        home_goals=0,
        away_goals=0,
        players=(event_player("h", "HOME", PlayerPosition.FWD),),
    ).model_copy(update={"ruleset_hash": "9" * 64})
    with pytest.raises(FplPointsError) as exc:
        AcceptedRulesAdapter(_compiled()).score_fixture(scenario)
    assert exc.value.code == "RULESET_SCENARIO_MISMATCH"


def test_from_paths_loads_compiled_rules_and_matching_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("{}", encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "ruleset_id": RULESET_ID,
                "ruleset_version": RULESET_VERSION,
                "approved": True,
                "approved_at": "2026-08-01T00:00:00Z",
                "approved_by": "Sebastian",
                "ruleset_hash": RULESET_HASH,
            }
        ),
        encoding="utf-8",
    )
    fake_compiler = SimpleNamespace(load_compiled_ruleset=lambda path: _compiled())
    fake_models = SimpleNamespace(
        ApprovalRecord=SimpleNamespace(model_validate=lambda value: SimpleNamespace(**value))
    )
    monkeypatch.setattr(
        adapter_module.importlib,
        "import_module",
        lambda name: fake_compiler if name.endswith("compiler") else fake_models,
    )
    adapter = AcceptedRulesAdapter.from_paths(rules_path, approval_path)
    assert adapter.identity.human_approval_recorded is True

    approval_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(FplPointsError) as exc:
        AcceptedRulesAdapter.from_paths(rules_path, approval_path)
    assert exc.value.code == "RULESET_APPROVAL_INVALID"
