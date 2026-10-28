"""Real synthetic input assembly; controlled compute/render crossings of expiry."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from dmf_pulse.private_v1 import one_command
from dmf_pulse.private_v1.errors import PrivateV1Error
from tests.unit.private_v1 import test_one_command as inherited

DEADLINE = datetime(2026, 9, 4, 17, 30, tzinfo=UTC)


@pytest.mark.parametrize("horizon", [1, 3])
@pytest.mark.parametrize("phase", ["before_solver", "during_solver", "during_render"])
def test_one_command_withholds_expired_output(repository_root, monkeypatch, horizon, phase):
    state = {"now": inherited.RUN_AT, "solves": 0, "renders": 0}
    progress = []
    original_init = one_command.PrivateV1OneCommandService.__init__
    original_seal = (
        one_command.seal_execution_input
        if horizon == 1
        else one_command.seal_rolling_execution_input
    )

    def seal(value):
        result = original_seal(value)
        if phase == "before_solver":
            state["now"] = DEADLINE
        return result

    class Solver:
        def run(self, *args, **kwargs):
            state["solves"] += 1
            if phase == "during_solver":
                state["now"] = DEADLINE
            # Deliberately no numerical result: only the expiry boundary is under test.
            return SimpleNamespace(
                decision=SimpleNamespace(semantic_sha256="a" * 64), stage_timings=()
            )

    def render(*args):
        state["renders"] += 1
        if phase == "during_render":
            state["now"] = DEADLINE
        return "SYNTHETIC_EXPIRED_ACTION"

    def initialize(self, **kwargs):
        kwargs["clock"] = lambda: state["now"]
        kwargs["recommendation_service"] = Solver()
        kwargs["rolling_recommendation_service"] = Solver()
        kwargs["progress"] = inherited.HumanCliProgress(write=progress.append)
        original_init(self, **kwargs)

    monkeypatch.setattr(one_command.PrivateV1OneCommandService, "__init__", initialize)
    monkeypatch.setattr(
        one_command,
        "seal_execution_input" if horizon == 1 else "seal_rolling_execution_input",
        seal,
    )
    monkeypatch.setattr(
        one_command, "_display_report" if horizon == 1 else "_display_rolling_report", render
    )
    demonstration = (
        inherited.test_network_blocked_synthetic_one_command_runs_actual_decision_stack
        if horizon == 1
        else inherited.test_explicit_three_gameweek_one_command_runs_from_one_current_cutoff
    )
    with pytest.raises(PrivateV1Error) as failure:
        demonstration(repository_root)
    assert failure.value.code == "DECISION_DEADLINE_PASSED"
    assert state["solves"] == (0 if phase == "before_solver" else 1)
    assert state["renders"] == (0 if phase == "before_solver" else 1)
    assert "Recommendation ready" not in "\n".join(progress)
    assert "SYNTHETIC_EXPIRED_ACTION" not in "\n".join(progress)
