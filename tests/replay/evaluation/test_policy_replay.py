from __future__ import annotations

import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.models import (
    DatasetMode,
    EvaluationLineage,
    ObservationKind,
    OperationalUsability,
)
from dmf_pulse.evaluation.policy_replay import (
    Stage11ReplayAdapter,
    SyntheticManagerState,
    SyntheticReplayExecutor,
    SyntheticReplayPolicy,
    replay_policy,
)
from dmf_pulse.evaluation.service import EvaluationService, load_json
from tests.evaluation_helpers import BASE, ZERO, feature, lineage
from tests.support.stage11_factory import build_fixture

pytestmark = pytest.mark.integration


def test_synthetic_five_gameweek_replay_is_stateful_and_root_action_only(tmp_path: Path) -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    trajectory = EvaluationService().policy(payload, artifact_root=tmp_path)
    assert len(trajectory.steps) == 5
    assert trajectory.cumulative_utility == Decimal(30)
    assert trajectory.root_action_only
    assert tuple(step.executed_action["action"] for step in trajectory.steps) == (
        "HOLD",
        "TRANSFER",
        "TRANSFER",
        "HOLD",
        "TRANSFER",
    )
    assert all(step.outcome_revealed_after_freeze for step in trajectory.steps)
    assert len({step.state_after_sha256 for step in trajectory.steps}) == 5
    assert list((tmp_path / "evaluation" / "forecasts").rglob("*.json"))
    assert list((tmp_path / "evaluation" / "decisions").rglob("*.json"))


def test_replay_does_not_execute_stored_future_policy() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    deadlines = payload["deadlines"]
    assert isinstance(deadlines, list)
    # Future policy deliberately contains an impossible advisory object; executor sees only current_action.
    trajectory = EvaluationService().policy(payload)
    assert all("advisory_only" not in step.executed_action for step in trajectory.steps)


def test_synthetic_b4_replay_requires_complete_parent_binding() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    deadlines = payload["deadlines"]
    assert isinstance(deadlines, list)
    records = deadlines[0]["records"]
    pulse = next(item for item in records if item["kind"] == "PULSE_PROJECTION")
    pulse["values"]["accepted_modules"] = ["MARKETS"]
    payload["deadlines"] = deadlines[:1]
    with pytest.raises(ValueError, match="complete accepted"):
        EvaluationService().policy(payload)


def test_policy_cannot_observe_outcome_raw_records_or_future_branch_before_freeze() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    deadline = ReplayDeadline.model_validate(payload["deadlines"][0])
    base_policy = SyntheticReplayPolicy(lineage())
    observed_attributes: list[tuple[bool, bool, bool]] = []

    class InspectingPolicy:
        def forecast(self, state: object, **kwargs: object) -> object:
            decision_point = kwargs["deadline"]
            observed_attributes.append(
                (
                    hasattr(decision_point, "realised_outcome"),
                    hasattr(decision_point, "records"),
                    hasattr(decision_point, "observed_node_id"),
                )
            )
            return base_policy.forecast(state, **kwargs)  # type: ignore[arg-type]

        def decide(self, state: object, **kwargs: object) -> object:
            decision_point = kwargs["deadline"]
            observed_attributes.append(
                (
                    hasattr(decision_point, "realised_outcome"),
                    hasattr(decision_point, "records"),
                    hasattr(decision_point, "observed_node_id"),
                )
            )
            return base_policy.decide(state, **kwargs)  # type: ignore[arg-type]

    trajectory = replay_policy(
        (deadline,),
        trajectory_id="information-barrier",
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        initial_state=SyntheticManagerState(
            gameweek=1,
            cumulative_points=Decimal(0),
            free_transfers=1,
            action_count=0,
        ),
        policy=InspectingPolicy(),  # type: ignore[arg-type]
        executor=SyntheticReplayExecutor(),
    )
    assert trajectory.steps[0].realised_utility == deadline.realised_outcome
    assert observed_attributes == [(False, False, False), (False, False, False)]


def test_policy_cannot_mutate_replay_state_while_forecasting() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    deadline = ReplayDeadline.model_validate(payload["deadlines"][0])
    base_policy = SyntheticReplayPolicy(lineage())

    class MutatingPolicy:
        def forecast(self, state: dict[str, object], **kwargs: object) -> object:
            forecast = base_policy.forecast(
                SyntheticManagerState(
                    gameweek=1,
                    cumulative_points=Decimal(0),
                    free_transfers=1,
                    action_count=0,
                ),
                **kwargs,  # type: ignore[arg-type]
            )
            state["tampered"] = True
            return forecast

        def decide(self, state: dict[str, object], **kwargs: object) -> object:
            return base_policy.decide(state, **kwargs)  # type: ignore[arg-type]

    class MappingExecutor:
        def state_sha256(self, state: dict[str, object]) -> str:
            return semantic_sha256(state)

        def execute_current_action(self, state: dict[str, object], **kwargs: object) -> object:
            raise AssertionError("mutated replay state must block before execution")

    with pytest.raises(ValueError, match="mutated manager state"):
        replay_policy(
            (deadline,),
            trajectory_id="mutable-state",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state={"gameweek": 1},
            policy=MutatingPolicy(),
            executor=MappingExecutor(),  # type: ignore[arg-type]
        )


def test_policy_cannot_mutate_frozen_information_record_payloads() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    deadline = ReplayDeadline.model_validate(payload["deadlines"][0])
    base_policy = SyntheticReplayPolicy(lineage())

    class MutatingRecordPolicy:
        def forecast(self, state: object, **kwargs: object) -> object:
            records = kwargs["records"]
            records[0].values["expected_points"] = "99"
            return base_policy.forecast(state, **kwargs)  # type: ignore[arg-type]

        def decide(self, state: object, **kwargs: object) -> object:
            return base_policy.decide(state, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(EvaluationError, match="semantic payload"):
        replay_policy(
            (deadline,),
            trajectory_id="mutable-record",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state=SyntheticManagerState(
                gameweek=1,
                cumulative_points=Decimal(0),
                free_transfers=1,
                action_count=0,
            ),
            policy=MutatingRecordPolicy(),  # type: ignore[arg-type]
            executor=SyntheticReplayExecutor(),
        )


def test_replay_requires_chronological_deadlines() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    policy = SyntheticReplayPolicy(lineage())
    executor = SyntheticReplayExecutor()
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    deadlines = tuple(ReplayDeadline.model_validate(item) for item in payload["deadlines"])
    with pytest.raises(ValueError, match="chronologically"):
        replay_policy(
            tuple(reversed(deadlines)),
            trajectory_id="bad",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state=SyntheticManagerState(
                gameweek=1,
                cumulative_points=Decimal(0),
                free_transfers=1,
                action_count=0,
            ),
            policy=policy,
            executor=executor,
        )


def test_synthetic_replay_rejects_state_gameweek_drift() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    payload["initial_state"]["gameweek"] = 2
    payload["deadlines"] = payload["deadlines"][:1]
    with pytest.raises(ValueError, match="state Gameweek"):
        EvaluationService().policy(payload)


def test_replay_requires_outcome_reveal_after_freeze_and_before_next_decision() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    invalid = dict(payload["deadlines"][0])
    invalid["outcome_revealed_at"] = invalid["forecast_origin"]
    with pytest.raises(ValueError, match="revealed after"):
        ReplayDeadline.model_validate(invalid)

    deadlines = [ReplayDeadline.model_validate(item) for item in payload["deadlines"][:2]]
    deadlines[0] = ReplayDeadline.model_validate(
        {
            **payload["deadlines"][0],
            "outcome_revealed_at": "2026-08-09T10:00:00Z",
        }
    )
    with pytest.raises(ValueError, match="next information cutoff"):
        replay_policy(
            tuple(deadlines),
            trajectory_id="late-reveal",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state=SyntheticManagerState(
                gameweek=1,
                cumulative_points=Decimal(0),
                free_transfers=1,
                action_count=0,
            ),
            policy=SyntheticReplayPolicy(lineage()),
            executor=SyntheticReplayExecutor(),
        )


def test_stage11_adapter_calls_actual_service_symbols_and_advances_root_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = ModuleType("dmf_pulse.optimisation.multi_gameweek_service")
    calls: list[str] = []
    action = SimpleNamespace(model_dump=lambda mode="json": {"action_id": "hold"})
    root_decision = SimpleNamespace(
        model_dump=lambda mode="json": {
            "action": {"action_id": "hold"},
            "paid_transfers": 0,
            "hit_points": 0,
        }
    )
    decision_node = SimpleNamespace(model_dump=lambda mode="json": {"node_id": "future"})
    utility = SimpleNamespace(expected_horizon_utility=Decimal(5))
    result = SimpleNamespace(
        recommended_plan=SimpleNamespace(utility=utility, current_action=root_decision),
        current_action=action,
        future_policy=(decision_node,),
    )

    def optimise_multi_gameweek(request: object) -> object:
        calls.append("optimise")
        return result

    def advance_current_action(
        request: object, value: object, *, observed_node_id: str | None
    ) -> object:
        calls.append(f"advance:{observed_node_id}")
        return SimpleNamespace(manager_state=SimpleNamespace(state_sha256="1" * 64))

    service_module.optimise_multi_gameweek = optimise_multi_gameweek  # type: ignore[attr-defined]
    service_module.advance_current_action = advance_current_action  # type: ignore[attr-defined]
    package = ModuleType("dmf_pulse.optimisation")
    monkeypatch.setitem(sys.modules, "dmf_pulse.optimisation", package)
    monkeypatch.setitem(
        sys.modules, "dmf_pulse.optimisation.multi_gameweek_service", service_module
    )

    tactical = SimpleNamespace(squad_ids=("a",), expected_points=Decimal(4))
    root = SimpleNamespace(gameweek=1, tactical_values=(tactical,))
    tree = SimpleNamespace(root=root, nodes=(root, SimpleNamespace(gameweek=2)))
    state = SimpleNamespace(squad_ids=("a",), state_sha256="2" * 64)
    request = SimpleNamespace(scenario_tree=tree, initial_state=state)
    adapter = Stage11ReplayAdapter(
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        request_factory=lambda current, deadline, bundle, records: request,
        lineage_factory=lambda deadline, bundle, req: lineage(deadline.forecast_origin),
    )
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    deadline = ReplayDeadline.model_validate(payload["deadlines"][0])
    forecast = adapter.forecast(
        state,
        deadline=deadline,
        information_bundle_sha256=ZERO,
        records=(),
    )
    decision = adapter.decide(
        state,
        deadline=deadline,
        forecast=forecast,
        information_bundle_sha256=ZERO,
    )
    advanced, utility_value = adapter.execute_current_action(
        state,
        decision=decision,
        realised_outcome=Decimal(7),
        observed_node_id="child",
    )
    assert calls == ["optimise", "advance:child"]
    assert decision.current_action == {
        "action": {"action_id": "hold"},
        "paid_transfers": 0,
        "hit_points": 0,
    }
    assert utility_value == Decimal(7)
    assert advanced.state_sha256 == "1" * 64


def test_stage11_adapter_replays_real_accepted_service_path() -> None:
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    request = build_fixture("simple_one_ft")
    pulse = feature(
        "accepted-pulse",
        kind=ObservationKind.PULSE_PROJECTION,
        mode=DatasetMode.COUNTERFACTUAL,
        usability=OperationalUsability.COUNTERFACTUAL_ONLY,
        values={"expected_points": "5"},
    ).model_copy(update={"target_id": "gw1"})
    deadline = ReplayDeadline(
        deadline_id="gw1",
        gameweek=1,
        forecast_origin=BASE,
        information_cutoff=BASE,
        records=(pulse,),
        realised_outcome=Decimal(7),
        utility_includes_hit_costs=True,
        outcome_revealed_at=BASE + timedelta(days=1),
        observed_node_id="n2",
    )

    def lineage_factory(
        replay_deadline: object,
        bundle_sha256: str,
        stage11_request: object,
    ) -> EvaluationLineage:
        del stage11_request
        assert hasattr(replay_deadline, "forecast_origin")
        payload = lineage(replay_deadline.forecast_origin).model_dump(mode="python")
        payload["input_manifest_sha256"] = bundle_sha256
        return EvaluationLineage.model_validate(payload)

    adapter = Stage11ReplayAdapter(
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        request_factory=lambda state, replay_deadline, bundle_sha256, records: request,
        lineage_factory=lineage_factory,
    )
    captured_states: list[object] = []

    class RecordingExecutor:
        def state_sha256(self, state: object) -> str:
            return adapter.state_sha256(state)

        def execute_current_action(self, state: object, **kwargs: object) -> tuple[object, Decimal]:
            next_state, utility = adapter.execute_current_action(state, **kwargs)
            captured_states.append(next_state)
            return next_state, utility

    trajectory = replay_policy(
        (deadline,),
        trajectory_id="stage11-real-path",
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        initial_state=request.initial_state,
        policy=adapter,
        executor=RecordingExecutor(),
    )
    assert trajectory.steps[0].realised_utility == Decimal(7)
    assert trajectory.steps[0].executed_action
    assert trajectory.steps[0].state_after_sha256 != trajectory.initial_state_sha256
    assert trajectory.steps[0].executed_action["paid_transfers"] == 0
    assert trajectory.steps[0].executed_action["hit_points"] == 0
    assert trajectory.steps[0].executed_action["bank_before_tenths"] == 0
    assert trajectory.steps[0].executed_action["bank_after_tenths"] == 0
    assert trajectory.steps[0].executed_action["free_transfers_before"] == 1
    assert trajectory.steps[0].executed_action["free_transfers_after"] == 1
    assert trajectory.steps[0].executed_action["selling_prices"] == [
        {"player_id": "mid_1", "price_tenths": 50}
    ]
    assert trajectory.steps[0].executed_action["buying_prices"] == [
        {"player_id": "mid_6", "price_tenths": 50}
    ]
    advanced = captured_states[0]
    assert advanced.current_gameweek == 2
    assert advanced.bank_tenths == 0
    assert advanced.free_transfers == 1
    assert "mid_6" in advanced.squad_ids and "mid_1" not in advanced.squad_ids
    assert advanced.active_by_player["mid_6"].purchase_price_tenths == 50


def test_replay_blocks_dataset_mode_or_bundle_lineage_mismatch() -> None:
    from dmf_pulse.evaluation.policy_replay import ReplayDeadline

    payload = load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json"))
    deadline = ReplayDeadline.model_validate(payload["deadlines"][0])
    base_policy = SyntheticReplayPolicy(lineage())
    executor = SyntheticReplayExecutor()

    class WrongModePolicy:
        def forecast(self, state: object, **kwargs: object) -> object:
            value = base_policy.forecast(state, **kwargs)  # type: ignore[arg-type]
            return value.model_copy(update={"dataset_mode": DatasetMode.RECONSTRUCTED})

        def decide(self, state: object, **kwargs: object) -> object:
            return base_policy.decide(state, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="forecast dataset mode"):
        replay_policy(
            (deadline,),
            trajectory_id="wrong-mode",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state=SyntheticManagerState(
                gameweek=1,
                cumulative_points=Decimal(0),
                free_transfers=1,
                action_count=0,
            ),
            policy=WrongModePolicy(),  # type: ignore[arg-type]
            executor=executor,
        )

    class WrongBundlePolicy:
        def forecast(self, state: object, **kwargs: object) -> object:
            value = base_policy.forecast(state, **kwargs)  # type: ignore[arg-type]
            bad_lineage = value.lineage.model_copy(update={"input_manifest_sha256": "f" * 64})
            return value.model_copy(update={"lineage": bad_lineage})

        def decide(self, state: object, **kwargs: object) -> object:
            return base_policy.decide(state, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="frozen information bundle"):
        replay_policy(
            (deadline,),
            trajectory_id="wrong-bundle",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state=SyntheticManagerState(
                gameweek=1,
                cumulative_points=Decimal(0),
                free_transfers=1,
                action_count=0,
            ),
            policy=WrongBundlePolicy(),  # type: ignore[arg-type]
            executor=executor,
        )

    class TamperedForecastPolicy:
        def forecast(self, state: object, **kwargs: object) -> object:
            value = base_policy.forecast(state, **kwargs)  # type: ignore[arg-type]
            return value.model_copy(update={"point_forecast": Decimal(99)})

        def decide(self, state: object, **kwargs: object) -> object:
            return base_policy.decide(state, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(EvaluationError, match="semantic payload"):
        replay_policy(
            (deadline,),
            trajectory_id="tampered-forecast",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            initial_state=SyntheticManagerState(
                gameweek=1,
                cumulative_points=Decimal(0),
                free_transfers=1,
                action_count=0,
            ),
            policy=TamperedForecastPolicy(),  # type: ignore[arg-type]
            executor=executor,
        )
