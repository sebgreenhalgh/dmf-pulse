from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import TokenStatus, advance_inventory
from dmf_pulse.chips.replay import (
    ChipReplayDeadline,
    ChipReplayRequest,
    replay_chip_policy,
    seal_chip_replay_request,
)
from dmf_pulse.chips.service_models import ChipDecisionAction, ChipServiceRequest
from tests.support.stage14_chip_fixtures import NOW, service_request


def _replay(second_values: tuple[float, float]) -> ChipReplayRequest:
    first = service_request(
        current_values={"TRIPLE_CAPTAIN": (1.0, 1.0)},
        future_values={"TRIPLE_CAPTAIN": (6.0, 6.0)},
        now=NOW,
    )
    second_inventory = advance_inventory(first.inventory, to_gameweek=2)
    second = service_request(
        inventory=second_inventory,
        gameweek=2,
        current_values={"TRIPLE_CAPTAIN": second_values},
        future_values={"TRIPLE_CAPTAIN": (-2.0, -2.0)},
        now=NOW + timedelta(days=7),
    )
    return seal_chip_replay_request(
        ChipReplayRequest(
            replay_id=f"replay-{second_values[0]}",
            initial_inventory=first.inventory,
            deadlines=(
                ChipReplayDeadline(
                    deadline_id="GW1",
                    gameweek=1,
                    request=first,
                    outcome_revealed_at=NOW + timedelta(days=1),
                ),
                ChipReplayDeadline(
                    deadline_id="GW2",
                    gameweek=2,
                    request=second,
                    outcome_revealed_at=NOW + timedelta(days=8),
                ),
            ),
            replay_request_hash="0" * 64,
        )
    )


def test_future_information_changes_later_action_not_earlier_frozen_decision() -> None:
    positive = replay_chip_policy(_replay((8.0, 8.0)))
    negative = replay_chip_policy(_replay((-1.0, -1.0)))

    assert positive.steps[0].artifact_hash == negative.steps[0].artifact_hash
    assert positive.steps[0].decision_hash == negative.steps[0].decision_hash
    assert positive.steps[0].executed_action is ChipDecisionAction.WAIT
    assert negative.steps[0].executed_action is ChipDecisionAction.WAIT
    assert positive.steps[1].executed_action is ChipDecisionAction.USE
    assert negative.steps[1].executed_action is ChipDecisionAction.HOLD


def test_replay_executes_root_only_then_re_solves() -> None:
    request = _replay((8.0, 8.0))

    result = replay_chip_policy(request)

    first, second = result.steps
    assert first.executed_action is ChipDecisionAction.WAIT
    assert first.executed_token_id is None
    assert first.inventory_before_hash == first.inventory_after_root_hash
    assert first.inventory_after_transition_hash == second.inventory_before_hash
    assert first.inventory_after_transition_hash != first.inventory_after_root_hash
    assert first.advisory_future_opportunity_ids
    assert second.executed_action is ChipDecisionAction.USE
    assert second.executed_token_id is not None
    assert second.inventory_after_root_hash != second.inventory_before_hash
    assert second.inventory_after_transition_hash == result.final_inventory.inventory_hash
    assert result.final_inventory.tokens[0].status is TokenStatus.USED
    assert all(step.advisory_schedule_not_executed for step in result.steps)


def test_replay_transitions_expire_unused_token_to_expired() -> None:
    request = service_request(
        activation_end_gameweek=1,
        current_values={"TRIPLE_CAPTAIN": (-1.0, -1.0)},
        future_values={},
    )
    replay = seal_chip_replay_request(
        ChipReplayRequest(
            replay_id="expire-unused",
            initial_inventory=request.inventory,
            deadlines=(
                ChipReplayDeadline(
                    deadline_id="GW1",
                    gameweek=1,
                    request=request,
                    outcome_revealed_at=NOW + timedelta(days=1),
                ),
            ),
            replay_request_hash="0" * 64,
        )
    )

    result = replay_chip_policy(replay)

    assert result.steps[0].executed_action is ChipDecisionAction.EXPIRE_UNUSED
    assert result.steps[0].executed_token_id is None
    assert result.final_inventory.tokens[0].status is TokenStatus.EXPIRED


def test_replay_rejects_future_frozen_request_with_wrong_transitioned_inventory() -> None:
    request = _replay((8.0, 8.0))
    second = request.deadlines[1]
    tampered_service = second.request.model_copy(update={"inventory": request.initial_inventory})
    tampered_deadline = second.model_copy(update={"request": tampered_service})
    tampered = request.model_copy(update={"deadlines": (request.deadlines[0], tampered_deadline)})

    with pytest.raises((ChipError, ValidationError, ValueError)):
        replay_chip_policy(tampered)


def test_executable_request_rejects_perfect_information_opportunity() -> None:
    request = service_request()
    payload = request.model_dump(mode="python")
    payload["schedule_request"]["opportunities"][0]["lineage"]["source_kind"] = (
        "PERFECT_INFORMATION_DIAGNOSTIC"
    )
    payload["schedule_request"]["opportunities"][0]["opportunity_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="forecast opportunities only"):
        ChipServiceRequest.model_validate(payload)


def test_executable_request_rejects_future_usable_at_cutoff_leakage() -> None:
    request = service_request()
    payload = request.model_dump(mode="python")
    lineage = payload["schedule_request"]["opportunities"][0]["lineage"]
    lineage["usable_at"] = NOW + timedelta(seconds=1)
    lineage["forecast_origin"] = NOW + timedelta(seconds=1)
    payload["schedule_request"]["opportunities"][0]["opportunity_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="future-artifact leakage"):
        ChipServiceRequest.model_validate(payload)
