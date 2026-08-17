"""Prequential, frozen and stateful sequential policy replay."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import Field, StrictInt, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import (
    persist_artifact,
    seal,
    semantic_sha256,
    verify_sealed,
)
from dmf_pulse.evaluation.benchmarks import (
    STAGE12_PARENT_COMMIT,
    accepted_pulse_point_forecast,
)
from dmf_pulse.evaluation.information_sets import build_information_set
from dmf_pulse.evaluation.models import (
    DatasetMode,
    EvaluationLineage,
    EvaluationModel,
    FeatureRecord,
    ForecastArtifact,
    PolicyDecisionArtifact,
    PolicyTrajectory,
    PolicyTrajectoryStep,
    PositiveInt,
    require_utc,
)

StateT = TypeVar("StateT")
StateT_contra = TypeVar("StateT_contra", contravariant=True)


class ReplayDeadline(EvaluationModel):
    deadline_id: StrictStr
    gameweek: PositiveInt
    forecast_origin: datetime
    information_cutoff: datetime
    records: tuple[FeatureRecord, ...]
    realised_outcome: Decimal
    utility_includes_hit_costs: Literal[True]
    outcome_revealed_at: datetime
    observed_node_id: StrictStr | None = None

    @model_validator(mode="after")
    def deadline_is_temporally_valid(self) -> ReplayDeadline:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        revealed = require_utc(self.outcome_revealed_at, field_name="outcome_revealed_at")
        if cutoff > origin:
            raise ValueError("replay information cutoff cannot follow forecast origin")
        if revealed <= origin:
            raise ValueError("replay outcome must be revealed after forecast freeze")
        return self


class ReplayDecisionPoint(EvaluationModel):
    """The information visible to a policy before forecast and decision freeze."""

    deadline_id: StrictStr
    gameweek: PositiveInt
    forecast_origin: datetime
    information_cutoff: datetime

    @model_validator(mode="after")
    def decision_time_is_valid(self) -> ReplayDecisionPoint:
        origin = require_utc(self.forecast_origin, field_name="forecast_origin")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > origin:
            raise ValueError("decision information cutoff cannot follow forecast origin")
        return self


class ReplayPolicy(Protocol[StateT_contra]):
    def forecast(
        self,
        state: StateT_contra,
        *,
        deadline: ReplayDecisionPoint,
        information_bundle_sha256: str,
        records: tuple[FeatureRecord, ...],
    ) -> ForecastArtifact: ...

    def decide(
        self,
        state: StateT_contra,
        *,
        deadline: ReplayDecisionPoint,
        forecast: ForecastArtifact,
        information_bundle_sha256: str,
    ) -> PolicyDecisionArtifact: ...


class ReplayExecutor(Protocol[StateT]):
    def state_sha256(self, state: StateT) -> str: ...

    def execute_current_action(
        self,
        state: StateT,
        *,
        decision: PolicyDecisionArtifact,
        realised_outcome: Decimal,
        observed_node_id: str | None,
    ) -> tuple[StateT, Decimal]: ...


class SyntheticManagerState(EvaluationModel):
    """Small, explicitly synthetic replay state used only for offline acceptance."""

    gameweek: PositiveInt
    cumulative_points: Decimal
    free_transfers: StrictInt = Field(ge=0)
    action_count: StrictInt = Field(ge=0)


class SyntheticReplayPolicy:
    """Deterministic acceptance policy; not a production forecasting model."""

    def __init__(self, lineage_template: EvaluationLineage) -> None:
        self._lineage = lineage_template

    def _lineage_for(
        self,
        deadline: ReplayDecisionPoint,
        bundle_sha256: str,
    ) -> EvaluationLineage:
        payload = self._lineage.model_dump(mode="python")
        payload.update(
            {
                "forecast_origin": deadline.forecast_origin,
                "information_cutoff": deadline.information_cutoff,
                "usable_at_cutoff": deadline.information_cutoff,
                "input_manifest_sha256": bundle_sha256,
            }
        )
        return EvaluationLineage.model_validate(payload)

    def forecast(
        self,
        state: SyntheticManagerState,
        *,
        deadline: ReplayDecisionPoint,
        information_bundle_sha256: str,
        records: tuple[FeatureRecord, ...],
    ) -> ForecastArtifact:
        if state.gameweek != deadline.gameweek:
            raise ValueError("synthetic replay state Gameweek differs from the current deadline")
        pulse_records = tuple(
            record
            for record in records
            if record.kind.value == "PULSE_PROJECTION" and record.target_id == deadline.deadline_id
        )
        if len(pulse_records) != 1:
            raise ValueError("synthetic replay requires one frozen Pulse projection per deadline")
        if self._lineage.code_commit != STAGE12_PARENT_COMMIT:
            raise ValueError("synthetic B4 replay lineage must bind to the Stage-12 parent")
        point_forecast = accepted_pulse_point_forecast(pulse_records[0])
        value = ForecastArtifact(
            forecast_id=f"forecast:{deadline.deadline_id}",
            benchmark_id="B4_ACCEPTED_PULSE_BASELINE",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            target_id=deadline.deadline_id,
            horizon=1,
            point_forecast=point_forecast,
            lineage=self._lineage_for(deadline, information_bundle_sha256),
            issued_at=deadline.forecast_origin,
            forecast_sha256="0" * 64,
        )
        return seal(value, "forecast_sha256")

    def decide(
        self,
        state: SyntheticManagerState,
        *,
        deadline: ReplayDecisionPoint,
        forecast: ForecastArtifact,
        information_bundle_sha256: str,
    ) -> PolicyDecisionArtifact:
        del information_bundle_sha256
        assert forecast.point_forecast is not None
        action = (
            "TRANSFER"
            if forecast.point_forecast >= Decimal("6") and state.free_transfers > 0
            else "HOLD"
        )
        value = PolicyDecisionArtifact(
            decision_id=f"decision:{deadline.deadline_id}",
            gameweek=deadline.gameweek,
            forecast_origin=deadline.forecast_origin,
            current_action={"action": action, "gameweek": deadline.gameweek},
            future_policy=({"advisory_only": True, "next_gameweek": deadline.gameweek + 1},),
            expected_utility=forecast.point_forecast,
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            lineage=forecast.lineage,
            decision_sha256="0" * 64,
        )
        return seal(value, "decision_sha256")


class SyntheticReplayExecutor:
    """Deterministic state transition for the synthetic acceptance season."""

    def state_sha256(self, state: SyntheticManagerState) -> str:
        return semantic_sha256(state)

    def execute_current_action(
        self,
        state: SyntheticManagerState,
        *,
        decision: PolicyDecisionArtifact,
        realised_outcome: Decimal,
        observed_node_id: str | None,
    ) -> tuple[SyntheticManagerState, Decimal]:
        del observed_node_id
        action = decision.current_action.get("action")
        if action not in {"HOLD", "TRANSFER"}:
            raise ValueError("synthetic executor received an unsupported current action")
        free_transfers = state.free_transfers
        actions = state.action_count
        if action == "TRANSFER":
            if free_transfers <= 0:
                raise ValueError("synthetic transfer cannot consume unavailable free transfer")
            free_transfers -= 1
            actions += 1
        next_state = SyntheticManagerState(
            gameweek=state.gameweek + 1,
            cumulative_points=state.cumulative_points + realised_outcome,
            free_transfers=min(5, free_transfers + 1),
            action_count=actions,
        )
        return next_state, realised_outcome


class Stage11ReplayAdapter:
    """Reuse the actual Stage-11 service path without importing it at package import time.

    The request factory receives the current manager state, sanitized deadline, frozen bundle hash
    and included records, then produces the repository's canonical
    ``MultiGameweekOptimisationRequest``. The adapter calls ``optimise_multi_gameweek`` and freezes
    only the result's root action as executable. The Stage-11 ``advance_current_action`` service
    performs the state transition.
    """

    def __init__(
        self,
        *,
        dataset_mode: DatasetMode,
        request_factory: Any,
        lineage_factory: Any,
    ) -> None:
        self._dataset_mode = dataset_mode
        self._request_factory = request_factory
        self._lineage_factory = lineage_factory
        self._requests: dict[str, Any] = {}
        self._results: dict[str, Any] = {}

    def forecast(
        self,
        state: Any,
        *,
        deadline: ReplayDecisionPoint,
        information_bundle_sha256: str,
        records: tuple[FeatureRecord, ...],
    ) -> ForecastArtifact:
        request = self._request_factory(
            state,
            deadline,
            information_bundle_sha256,
            records,
        )
        if state != request.initial_state or self.state_sha256(state) != self.state_sha256(
            request.initial_state
        ):
            raise ValueError("Stage-11 request initial state differs from replay state")
        lineage = EvaluationLineage.model_validate(
            self._lineage_factory(
                deadline,
                information_bundle_sha256,
                request,
            ).model_dump(mode="python")
        )
        if lineage.code_commit != STAGE12_PARENT_COMMIT:
            raise ValueError("Stage-11 B4 replay lineage must bind to the Stage-12 parent")
        expected: Decimal | None = None
        root = request.scenario_tree.root
        current_squad = request.initial_state.squad_ids
        for tactical in root.tactical_values:
            if tactical.squad_ids == current_squad:
                expected = tactical.expected_points
                break
        if expected is None:
            raise ValueError("Stage-11 request lacks a tactical value for the current squad")
        value = ForecastArtifact(
            forecast_id=f"stage11-forecast:{deadline.deadline_id}",
            benchmark_id="B4_ACCEPTED_PULSE_BASELINE",
            dataset_mode=self._dataset_mode,
            target_id=deadline.deadline_id,
            horizon=max(node.gameweek for node in request.scenario_tree.nodes) - root.gameweek + 1,
            point_forecast=expected,
            lineage=lineage,
            issued_at=deadline.forecast_origin,
            forecast_sha256="0" * 64,
        )
        self._requests[deadline.deadline_id] = request
        return seal(value, "forecast_sha256")

    def decide(
        self,
        state: Any,
        *,
        deadline: ReplayDecisionPoint,
        forecast: ForecastArtifact,
        information_bundle_sha256: str,
    ) -> PolicyDecisionArtifact:
        del state, information_bundle_sha256
        from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

        request = self._requests[deadline.deadline_id]
        result = optimise_multi_gameweek(request)
        if result.recommended_plan is None or result.current_action is None:
            raise ValueError("Stage-11 replay did not produce an executable root action")
        self._results[deadline.deadline_id] = result
        root_decision = result.recommended_plan.current_action
        value = PolicyDecisionArtifact(
            decision_id=f"stage11-decision:{deadline.deadline_id}",
            gameweek=deadline.gameweek,
            forecast_origin=deadline.forecast_origin,
            current_action=root_decision.model_dump(mode="json"),
            future_policy=tuple(item.model_dump(mode="json") for item in result.future_policy),
            expected_utility=result.recommended_plan.utility.expected_horizon_utility,
            dataset_mode=forecast.dataset_mode,
            lineage=forecast.lineage,
            decision_sha256="0" * 64,
        )
        return seal(value, "decision_sha256")

    def state_sha256(self, state: Any) -> str:
        value = getattr(state, "state_sha256", None)
        return str(value) if value is not None else semantic_sha256(state.model_dump(mode="json"))

    def execute_current_action(
        self,
        state: Any,
        *,
        decision: PolicyDecisionArtifact,
        realised_outcome: Decimal,
        observed_node_id: str | None,
    ) -> tuple[Any, Decimal]:
        from dmf_pulse.optimisation.multi_gameweek_service import advance_current_action

        deadline_id = decision.decision_id.removeprefix("stage11-decision:")
        if self.state_sha256(state) != self.state_sha256(self._requests[deadline_id].initial_state):
            raise ValueError("Stage-11 execution state differs from the frozen request")
        advance = advance_current_action(
            self._requests[deadline_id],
            self._results[deadline_id],
            observed_node_id=observed_node_id,
        )
        return advance.manager_state, realised_outcome


def replay_policy[StateT](
    deadlines: tuple[ReplayDeadline, ...],
    *,
    trajectory_id: str,
    dataset_mode: DatasetMode,
    initial_state: StateT,
    policy: ReplayPolicy[StateT],
    executor: ReplayExecutor[StateT],
    artifact_root: Path | None = None,
) -> PolicyTrajectory:
    """Forecast, freeze, decide, freeze, reveal, execute root action, then re-solve."""

    if not deadlines:
        raise ValueError("policy replay requires at least one deadline")
    ordered = tuple(sorted(deadlines, key=lambda item: (item.forecast_origin, item.deadline_id)))
    if deadlines != ordered:
        raise ValueError("replay deadlines must be chronologically ordered")
    deadline_ids = tuple(item.deadline_id for item in deadlines)
    if len(deadline_ids) != len(set(deadline_ids)):
        raise ValueError("replay deadline IDs must be unique")
    gameweeks = tuple(item.gameweek for item in deadlines)
    if any(current >= following for current, following in pairwise(gameweeks)):
        raise ValueError("replay gameweeks must be strictly increasing")
    for current, following in pairwise(deadlines):
        if current.outcome_revealed_at > following.information_cutoff:
            raise ValueError("replay outcome was unavailable by the next information cutoff")
    state = initial_state
    initial_hash = executor.state_sha256(state)
    steps: list[PolicyTrajectoryStep] = []
    for deadline in deadlines:
        decision_point = ReplayDecisionPoint(
            deadline_id=deadline.deadline_id,
            gameweek=deadline.gameweek,
            forecast_origin=deadline.forecast_origin,
            information_cutoff=deadline.information_cutoff,
        )
        bundle = build_information_set(
            deadline.records,
            bundle_id=f"bundle:{deadline.deadline_id}",
            forecast_origin=deadline.forecast_origin,
            information_cutoff=deadline.information_cutoff,
            dataset_mode=dataset_mode,
        )
        state_before = executor.state_sha256(state)
        forecast = ForecastArtifact.model_validate(
            policy.forecast(
                state,
                deadline=decision_point,
                information_bundle_sha256=bundle.bundle_sha256,
                records=bundle.records,
            ).model_dump(mode="python")
        )
        if executor.state_sha256(state) != state_before:
            raise ValueError("replay policy mutated manager state while forecasting")
        verify_sealed(bundle, "bundle_sha256")
        if forecast.dataset_mode is not dataset_mode:
            raise ValueError("forecast dataset mode differs from replay dataset mode")
        if forecast.lineage.forecast_origin != deadline.forecast_origin:
            raise ValueError("forecast lineage origin differs from replay deadline")
        if forecast.lineage.information_cutoff != deadline.information_cutoff:
            raise ValueError("forecast lineage cutoff differs from replay deadline")
        if forecast.lineage.input_manifest_sha256 != bundle.bundle_sha256:
            raise ValueError("forecast lineage is not bound to the frozen information bundle")
        verify_sealed(forecast, "forecast_sha256")
        decision = PolicyDecisionArtifact.model_validate(
            policy.decide(
                state,
                deadline=decision_point,
                forecast=forecast,
                information_bundle_sha256=bundle.bundle_sha256,
            ).model_dump(mode="python")
        )
        if executor.state_sha256(state) != state_before:
            raise ValueError("replay policy mutated manager state while deciding")
        verify_sealed(bundle, "bundle_sha256")
        verify_sealed(forecast, "forecast_sha256")
        if decision.dataset_mode is not dataset_mode:
            raise ValueError("decision dataset mode differs from replay dataset mode")
        if decision.gameweek != deadline.gameweek:
            raise ValueError("decision Gameweek differs from replay deadline")
        if decision.lineage != forecast.lineage:
            raise ValueError("decision lineage differs from its frozen forecast")
        verify_sealed(decision, "decision_sha256")
        if artifact_root is not None:
            persist_artifact(
                bundle,
                artifact_root=artifact_root,
                category="information",
                identity=deadline.deadline_id,
            )
            persist_artifact(
                forecast,
                artifact_root=artifact_root,
                category="forecasts",
                identity=deadline.deadline_id,
            )
            persist_artifact(
                decision,
                artifact_root=artifact_root,
                category="decisions",
                identity=deadline.deadline_id,
            )
        # Outcomes are deliberately not passed to the policy. They are revealed only here.
        state, utility = executor.execute_current_action(
            state,
            decision=decision,
            realised_outcome=deadline.realised_outcome,
            observed_node_id=deadline.observed_node_id,
        )
        verify_sealed(bundle, "bundle_sha256")
        verify_sealed(forecast, "forecast_sha256")
        verify_sealed(decision, "decision_sha256")
        steps.append(
            PolicyTrajectoryStep(
                gameweek=deadline.gameweek,
                forecast_origin=deadline.forecast_origin,
                information_bundle_sha256=bundle.bundle_sha256,
                forecast_sha256=forecast.forecast_sha256,
                decision_sha256=decision.decision_sha256,
                executed_action=decision.current_action,
                realised_utility=utility,
                utility_includes_hit_costs=deadline.utility_includes_hit_costs,
                outcome_revealed_at=deadline.outcome_revealed_at,
                state_before_sha256=state_before,
                state_after_sha256=executor.state_sha256(state),
                outcome_revealed_after_freeze=True,
            )
        )
    value = PolicyTrajectory(
        trajectory_id=trajectory_id,
        dataset_mode=dataset_mode,
        initial_state_sha256=initial_hash,
        steps=tuple(steps),
        cumulative_utility=sum((item.realised_utility for item in steps), Decimal(0)),
        trajectory_sha256="0" * 64,
    )
    value = seal(value, "trajectory_sha256")
    if artifact_root is not None:
        persist_artifact(
            value,
            artifact_root=artifact_root,
            category="trajectories",
            identity=trajectory_id,
        )
    return value
