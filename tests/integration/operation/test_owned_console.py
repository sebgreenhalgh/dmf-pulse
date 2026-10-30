"""One complete console publication through the accepted worker/models, offline."""

from __future__ import annotations

import pytest

from dmf_pulse.dashboard.current import CurrentRefreshSession, current_worker
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.operation.console import publish_runtime

pytestmark = pytest.mark.integration


class Pipe:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send(self, value):
        self.messages.append(value)

    def close(self):
        self.closed = True


class Worker:
    def __init__(self, messages):
        self.messages = list(messages)
        self.closed = False

    def receive(self):
        return self.messages.pop(0) if self.messages else None

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True


def test_complete_owned_current_console_preflight_worker_and_publication(tmp_path):
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    # It is the public same-request preflight; it must not create a reservation.
    preview = session.preflight(1)
    assert preview.ledger.audit.event_count == 0
    launches, workers, views = [], [], []

    def factory(launch):
        launches.append(launch)
        pipe = Pipe()
        current_worker(pipe, 1, launch)
        assert pipe.closed
        worker = Worker(pipe.messages)
        workers.append(worker)
        return worker

    runtime = DeskRuntime(
        current_session=session, current_worker_factory=factory, clock=lambda: DEMO_TIME
    )
    receipt = publish_runtime(runtime, horizon=1, publish=views.append, wait=lambda _: None)
    assert receipt.dataset_mode == "SYNTHETIC_CURRENT_MODE"
    assert len(launches) == len(workers) == len(views) == 1
    view = views[0]
    assert (view.catalogue_count, view.projected_count, view.blocked_count) == (121, 120, 1)
    assert receipt.job_id == view.job_id and len(view.gameweeks) == 1
    assert workers[0].closed and runtime.view() is None
    # Reopen the owned file backend by identity, not by creating/resetting it.
    from dmf_pulse.dashboard.authorization import DurableUsageLedger

    audit = DurableUsageLedger(tmp_path / "usage", launches[0].grant.ledger_id).audit()
    assert (audit.reservation_count, audit.claim_count, audit.attempt_count) == (1, 1, 13)
