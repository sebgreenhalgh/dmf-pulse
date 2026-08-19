"""Sequential Stage-12-compatible replay for frozen Stage-14 chip decisions."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictStr, ValidationError, model_validator

from dmf_pulse.chips.artifacts import (
    persist_decision_artifact,
    seal_decision_artifact,
)
from dmf_pulse.chips.definitions import FrozenModel, Sha256, semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import (
    ChipInventory,
    activate_token,
    advance_inventory,
)
from dmf_pulse.chips.schedule_models import require_utc
from dmf_pulse.chips.service_models import ChipDecisionAction, ChipServiceRequest


class ChipReplayDeadline(FrozenModel):
    """One forecast/freeze/execute/reveal epoch."""

    deadline_id: StrictStr = Field(min_length=1)
    gameweek: int = Field(gt=0)
    request: ChipServiceRequest
    outcome_revealed_at: datetime

    @model_validator(mode="after")
    def deadline_is_coherent(self) -> ChipReplayDeadline:
        revealed = require_utc(self.outcome_revealed_at, field_name="outcome_revealed_at")
        if self.gameweek != self.request.inventory.current_gameweek:
            raise ValueError("chip replay deadline and service request Gameweeks differ")
        if revealed <= self.request.forecast_origin:
            raise ValueError("chip replay reveal must follow forecast/decision freeze")
        return self


class ChipReplayRequest(FrozenModel):
    """Immutable sequence of deadline-safe service requests."""

    replay_id: StrictStr = Field(min_length=1)
    initial_inventory: ChipInventory
    deadlines: tuple[ChipReplayDeadline, ...]
    replay_request_hash: Sha256

    @model_validator(mode="after")
    def replay_is_coherent(self) -> ChipReplayRequest:
        if not self.deadlines:
            raise ValueError("chip replay requires at least one deadline")
        ordered = tuple(
            sorted(
                self.deadlines,
                key=lambda item: (
                    item.request.forecast_origin,
                    item.gameweek,
                    item.deadline_id,
                ),
            )
        )
        if self.deadlines != ordered:
            raise ValueError("chip replay deadlines must be chronologically ordered")
        ids = tuple(item.deadline_id for item in self.deadlines)
        if len(ids) != len(set(ids)):
            raise ValueError("chip replay deadline IDs must be unique")
        gameweeks = tuple(item.gameweek for item in self.deadlines)
        if any(left >= right for left, right in pairwise(gameweeks)):
            raise ValueError("chip replay Gameweeks must be strictly increasing")
        if (
            self.initial_inventory.inventory_hash
            != self.deadlines[0].request.inventory.inventory_hash
        ):
            raise ValueError("chip replay initial inventory differs from first frozen request")
        for current, following in pairwise(self.deadlines):
            if current.outcome_revealed_at > following.request.information_cutoff:
                raise ValueError("new information was not usable by the next replay cutoff")
        payload = self.model_dump(mode="json", exclude={"replay_request_hash"})
        if (
            self.replay_request_hash != "0" * 64
            and semantic_sha256(payload) != self.replay_request_hash
        ):
            raise ValueError("chip replay request hash mismatch")
        return self


class ChipReplayStep(FrozenModel):
    """One frozen root action and resulting inventory transition."""

    deadline_id: StrictStr
    gameweek: int = Field(gt=0)
    service_request_hash: Sha256
    artifact_hash: Sha256
    decision_hash: Sha256
    schedule_policy_hash: Sha256
    executed_action: ChipDecisionAction
    executed_chip: StrictStr | None = None
    executed_token_id: StrictStr | None = None
    advisory_future_opportunity_ids: tuple[StrictStr, ...]
    inventory_before_hash: Sha256
    inventory_after_root_hash: Sha256
    inventory_after_transition_hash: Sha256
    transitioned_to_gameweek: int = Field(gt=0)
    outcome_revealed_at: datetime
    outcome_revealed_after_freeze: Literal[True] = True
    executed_root_only: Literal[True] = True
    advisory_schedule_not_executed: Literal[True] = True
    step_hash: Sha256

    @model_validator(mode="after")
    def step_is_coherent(self) -> ChipReplayStep:
        require_utc(self.outcome_revealed_at, field_name="outcome_revealed_at")
        used = self.executed_action is ChipDecisionAction.USE
        if used != (self.executed_chip is not None):
            raise ValueError("replay USE must identify one executed chip")
        if used != (self.executed_token_id is not None):
            raise ValueError("replay USE must identify one executed token")
        if self.transitioned_to_gameweek <= self.gameweek:
            raise ValueError("replay state transition must advance beyond the frozen Gameweek")
        if self.inventory_after_root_hash == self.inventory_after_transition_hash:
            raise ValueError("replay inventory transition must have a new semantic identity")
        if self.advisory_future_opportunity_ids != tuple(
            sorted(set(self.advisory_future_opportunity_ids))
        ):
            raise ValueError("advisory future opportunity IDs must be sorted and unique")
        payload = self.model_dump(mode="json", exclude={"step_hash"})
        if self.step_hash != "0" * 64 and semantic_sha256(payload) != self.step_hash:
            raise ValueError("chip replay step hash mismatch")
        return self


class ChipReplayResult(FrozenModel):
    """Complete stateful replay trajectory."""

    replay_id: StrictStr
    replay_request_hash: Sha256
    initial_inventory_hash: Sha256
    final_inventory: ChipInventory
    steps: tuple[ChipReplayStep, ...]
    forecast_freeze_execute_root_transition_reveal_resolve: Literal[True] = True
    perfect_information_never_executable: Literal[True] = True
    result_hash: Sha256

    @model_validator(mode="after")
    def result_is_coherent(self) -> ChipReplayResult:
        if not self.steps:
            raise ValueError("chip replay result requires steps")
        if self.steps[0].inventory_before_hash != self.initial_inventory_hash:
            raise ValueError("chip replay initial state hash differs from first step")
        for current, following in pairwise(self.steps):
            if current.inventory_after_transition_hash != following.inventory_before_hash:
                raise ValueError("chip replay state chain differs before re-solving")
            if current.transitioned_to_gameweek != following.gameweek:
                raise ValueError("chip replay transition target differs from next deadline")
        if self.final_inventory.inventory_hash != self.steps[-1].inventory_after_transition_hash:
            raise ValueError("chip replay final inventory differs from the final transition")
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        if self.result_hash != "0" * 64 and semantic_sha256(payload) != self.result_hash:
            raise ValueError("chip replay result hash mismatch")
        return self


def seal_chip_replay_request(value: ChipReplayRequest) -> ChipReplayRequest:
    """Seal a replay request after contract validation."""

    checked = ChipReplayRequest.model_validate(value.model_dump(mode="python"))
    payload = checked.model_dump(mode="json", exclude={"replay_request_hash"})
    return ChipReplayRequest.model_validate(
        checked.model_copy(update={"replay_request_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _seal_step(value: ChipReplayStep) -> ChipReplayStep:
    payload = value.model_dump(mode="json", exclude={"step_hash"})
    return ChipReplayStep.model_validate(
        value.model_copy(update={"step_hash": semantic_sha256(payload)}).model_dump(mode="python")
    )


def _seal_result(value: ChipReplayResult) -> ChipReplayResult:
    payload = value.model_dump(mode="json", exclude={"result_hash"})
    return ChipReplayResult.model_validate(
        value.model_copy(update={"result_hash": semantic_sha256(payload)}).model_dump(mode="python")
    )


def replay_chip_policy(
    request: ChipReplayRequest,
    *,
    artifact_root: Path | None = None,
) -> ChipReplayResult:
    """Freeze, execute only the current action, transition, reveal and re-solve."""

    try:
        checked = ChipReplayRequest.model_validate(request.model_dump(mode="python"))
    except ValidationError as exc:
        raise ChipError(
            "CHIP_REPLAY_REQUEST_UNSEALED",
            "chip replay requires a correctly sealed request",
        ) from exc
    expected_hash = semantic_sha256(
        checked.model_dump(mode="json", exclude={"replay_request_hash"})
    )
    if checked.replay_request_hash != expected_hash:
        raise ChipError(
            "CHIP_REPLAY_REQUEST_UNSEALED",
            "chip replay requires a correctly sealed request",
        )

    inventory = checked.initial_inventory
    steps: list[ChipReplayStep] = []
    for index, deadline in enumerate(checked.deadlines):
        if inventory.current_gameweek != deadline.gameweek:
            raise ChipError(
                "CHIP_REPLAY_GAMEWEEK_MISMATCH",
                "chip replay inventory cannot align to the frozen deadline",
            )
        if inventory.inventory_hash != deadline.request.inventory.inventory_hash:
            raise ChipError(
                "CHIP_REPLAY_STATE_MISMATCH",
                "frozen deadline request does not match the transitioned inventory",
                deadline_id=deadline.deadline_id,
            )

        state_before = inventory.inventory_hash
        artifact = seal_decision_artifact(deadline.request)
        if artifact_root is not None:
            persist_decision_artifact(artifact, artifact_root=artifact_root)
        decision = artifact.decision_set.decision
        policy = artifact.decision_set.schedule_policy

        # The future schedule is explanation only.  Only the current/root action
        # can change state here.
        if decision.recommended_action is ChipDecisionAction.USE:
            assert decision.selected_token_id is not None
            inventory = activate_token(
                inventory,
                deadline.request.chip_bundle,
                token_id=decision.selected_token_id,
            )
        advisory_ids = tuple(
            sorted(
                item.opportunity_id
                for item in policy.selected_schedule.activations
                if item.activation_gameweek > deadline.gameweek
            )
        )
        state_after_root = inventory.inventory_hash
        transition_gameweek = (
            checked.deadlines[index + 1].gameweek
            if index + 1 < len(checked.deadlines)
            else deadline.gameweek + 1
        )
        inventory = advance_inventory(inventory, to_gameweek=transition_gameweek)
        steps.append(
            _seal_step(
                ChipReplayStep(
                    deadline_id=deadline.deadline_id,
                    gameweek=deadline.gameweek,
                    service_request_hash=deadline.request.service_request_hash,
                    artifact_hash=artifact.artifact_hash,
                    decision_hash=decision.decision_hash,
                    schedule_policy_hash=policy.policy_hash,
                    executed_action=decision.recommended_action,
                    executed_chip=decision.selected_chip,
                    executed_token_id=decision.selected_token_id,
                    advisory_future_opportunity_ids=advisory_ids,
                    inventory_before_hash=state_before,
                    inventory_after_root_hash=state_after_root,
                    inventory_after_transition_hash=inventory.inventory_hash,
                    transitioned_to_gameweek=transition_gameweek,
                    outcome_revealed_at=deadline.outcome_revealed_at,
                    step_hash="0" * 64,
                )
            )
        )
        if index + 1 < len(checked.deadlines):
            next_deadline = checked.deadlines[index + 1]
            if deadline.outcome_revealed_at > next_deadline.request.information_cutoff:
                raise ChipError(
                    "CHIP_REPLAY_INFORMATION_NOT_USABLE",
                    "newly revealed information is unavailable at the next cutoff",
                )

    value = ChipReplayResult(
        replay_id=checked.replay_id,
        replay_request_hash=checked.replay_request_hash,
        initial_inventory_hash=checked.initial_inventory.inventory_hash,
        final_inventory=inventory,
        steps=tuple(steps),
        result_hash="0" * 64,
    )
    return _seal_result(value)


__all__ = [
    "ChipReplayDeadline",
    "ChipReplayRequest",
    "ChipReplayResult",
    "ChipReplayStep",
    "replay_chip_policy",
    "seal_chip_replay_request",
]
