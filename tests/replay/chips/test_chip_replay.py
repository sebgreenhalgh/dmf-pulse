from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import TokenStatus, advance_inventory
from dmf_pulse.chips.replay import (
    ChipReplayDeadline,
    ChipReplayRequest,
    ChipReplayResult,
    ChipReplayStep,
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


def _reject(model: type, payload: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(payload)


def test_replay_deadline_rejects_temporal_and_gameweek_mismatches() -> None:
    deadline = _replay((8.0, 8.0)).deadlines[0]
    payload = deadline.model_dump(mode="python")
    payload["gameweek"] = 2
    _reject(ChipReplayDeadline, payload, "Gameweeks differ")

    payload = deadline.model_dump(mode="python")
    payload["outcome_revealed_at"] = deadline.request.forecast_origin
    _reject(ChipReplayDeadline, payload, "reveal must follow")


def test_replay_request_rejects_incoherent_trajectory_and_hash() -> None:
    request = _replay((8.0, 8.0))
    base = request.model_dump(mode="python")

    payload = dict(base, deadlines=(), replay_request_hash="0" * 64)
    _reject(ChipReplayRequest, payload, "at least one deadline")

    payload = dict(
        base,
        deadlines=tuple(reversed(base["deadlines"])),
        replay_request_hash="0" * 64,
    )
    _reject(ChipReplayRequest, payload, "chronologically ordered")

    deadlines = [item.model_dump(mode="python") for item in request.deadlines]
    deadlines[1]["deadline_id"] = deadlines[0]["deadline_id"]
    payload = dict(base, deadlines=deadlines, replay_request_hash="0" * 64)
    _reject(ChipReplayRequest, payload, "IDs must be unique")

    first = request.deadlines[0].model_dump(mode="python")
    repeated = dict(first, deadline_id="GW1-B")
    payload = dict(base, deadlines=(first, repeated), replay_request_hash="0" * 64)
    _reject(ChipReplayRequest, payload, "Gameweeks must be strictly increasing")

    payload = dict(
        base,
        initial_inventory=request.deadlines[1].request.inventory,
        replay_request_hash="0" * 64,
    )
    _reject(ChipReplayRequest, payload, "initial inventory differs")

    deadlines = [item.model_dump(mode="python") for item in request.deadlines]
    deadlines[0]["outcome_revealed_at"] = request.deadlines[
        1
    ].request.information_cutoff + timedelta(seconds=1)
    payload = dict(base, deadlines=deadlines, replay_request_hash="0" * 64)
    _reject(ChipReplayRequest, payload, "information was not usable")

    payload = dict(base, replay_request_hash="f" * 64)
    _reject(ChipReplayRequest, payload, "request hash mismatch")


def test_replay_step_rejects_non_root_or_ambiguous_state_changes() -> None:
    step = replay_chip_policy(_replay((8.0, 8.0))).steps[0]
    base = step.model_dump(mode="python")
    cases = (
        (
            dict(base, executed_action="USE", step_hash="0" * 64),
            "USE must identify one executed chip",
        ),
        (
            dict(
                base,
                executed_action="USE",
                executed_chip="TRIPLE_CAPTAIN",
                step_hash="0" * 64,
            ),
            "USE must identify one executed token",
        ),
        (
            dict(base, transitioned_to_gameweek=step.gameweek, step_hash="0" * 64),
            "must advance beyond",
        ),
        (
            dict(
                base,
                inventory_after_transition_hash=step.inventory_after_root_hash,
                step_hash="0" * 64,
            ),
            "must have a new semantic identity",
        ),
        (
            dict(
                base,
                advisory_future_opportunity_ids=("z", "a"),
                step_hash="0" * 64,
            ),
            "must be sorted and unique",
        ),
        (dict(base, step_hash="f" * 64), "step hash mismatch"),
    )
    for payload, match in cases:
        _reject(ChipReplayStep, payload, match)


def test_replay_result_rejects_broken_state_chain_and_hash() -> None:
    request = _replay((8.0, 8.0))
    result = replay_chip_policy(request)
    base = result.model_dump(mode="python")

    cases: list[tuple[dict[str, object], str]] = [
        (dict(base, steps=(), result_hash="0" * 64), "requires steps"),
        (
            dict(base, initial_inventory_hash="f" * 64, result_hash="0" * 64),
            "initial state hash differs",
        ),
    ]
    steps = [item.model_dump(mode="python") for item in result.steps]
    steps[1]["inventory_before_hash"] = "f" * 64
    steps[1]["step_hash"] = "0" * 64
    cases.append(
        (
            dict(base, steps=steps, result_hash="0" * 64),
            "state chain differs",
        )
    )
    steps = [item.model_dump(mode="python") for item in result.steps]
    steps[0]["transitioned_to_gameweek"] = 3
    steps[0]["step_hash"] = "0" * 64
    cases.append(
        (
            dict(base, steps=steps, result_hash="0" * 64),
            "transition target differs",
        )
    )
    cases.extend(
        (
            (
                dict(
                    base,
                    final_inventory=request.initial_inventory,
                    result_hash="0" * 64,
                ),
                "final inventory",
            ),
            (dict(base, result_hash="f" * 64), "result hash mismatch"),
        )
    )
    for payload, match in cases:
        _reject(ChipReplayResult, payload, match)
