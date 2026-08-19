from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.chips.replay import ChipReplayRequest, replay_chip_policy
from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.chips.service_models import ChipDecisionSet, ChipServiceRequest
from dmf_pulse.evaluation.artifacts import canonical_json_bytes

pytestmark = pytest.mark.golden

FIXTURE_ROOT = Path("fixtures/chips/stage14")


def test_stage14_service_decision_matches_frozen_golden() -> None:
    request = ChipServiceRequest.model_validate_json(
        (FIXTURE_ROOT / "service_request.json").read_bytes()
    )
    expected = ChipDecisionSet.model_validate_json(
        (FIXTURE_ROOT / "decision_set.json").read_bytes()
    )

    actual = evaluate_chip_opportunities(request)

    assert actual == expected
    assert canonical_json_bytes(actual) == (FIXTURE_ROOT / "decision_set.json").read_bytes()
    assert actual.decision.selected_chip == "FREE_HIT"


def test_stage14_replay_golden_executes_wait_then_re_solves_use() -> None:
    request = ChipReplayRequest.model_validate_json(
        (FIXTURE_ROOT / "replay_request.json").read_bytes()
    )

    result = replay_chip_policy(request)

    assert [step.executed_action.value for step in result.steps] == ["WAIT", "USE"]
    assert result.steps[0].decision_hash != result.steps[1].decision_hash
    assert result.final_inventory.tokens[0].status.value == "USED"


def test_golden_files_are_canonical_json() -> None:
    for path in sorted(FIXTURE_ROOT.glob("*.json")):
        raw = path.read_bytes()
        value = json.loads(raw)
        assert raw == canonical_json_bytes(value)
