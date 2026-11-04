"""A normal-return inner close failure must never orphan work or admit a new job."""

import pytest

from dmf_pulse.dashboard.runtime import DeskRuntime, JobState
from dmf_pulse.operation.analysis_store import AnalysisStore
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime


class UnclosableWorker:
    def close(self):
        raise RuntimeError("owned close failure")

    def alive(self):
        return True

    def receive(self):
        return None


@pytest.mark.parametrize("action", ["cancel", "tick"])
def test_cancel_and_terminal_paths_keep_unclosed_worker_and_close_admission(tmp_path, action):
    store = AnalysisStore(tmp_path / "cleanup" / "history.sqlite")
    store.initialize()
    facade = PersistentDeskRuntime(
        store,
        local_check=lambda: None,
        register=lambda _: pytest.fail("credential registration"),
        prepare=lambda *_: pytest.fail("new job"),
        provenance="OWNED_SYNTHETIC",
    )
    inner = DeskRuntime(demo=True)
    worker = UnclosableWorker()
    inner._worker = worker
    inner._state = JobState(status="BLOCKED", error_code="WORKER_CLEANUP_FAILED")
    inner._closed = True
    facade._active = inner
    facade._attempt_id = "owned-cleanup-fault"
    facade._state = JobState(status="RUNNING")
    with pytest.raises(OperationError, match="WORKER_CLEANUP_FAILED"):
        getattr(facade, action)()
    assert facade._active is inner and inner._worker is worker and worker.alive()
    assert facade._closed and not facade.cleanup_complete()
    assert facade.refresh(1).error_code == "WORKER_CLEANUP_FAILED"
    assert store.query("select error_code from failed_attempts") == [
        {"error_code": "WORKER_CLEANUP_FAILED"}
    ]
