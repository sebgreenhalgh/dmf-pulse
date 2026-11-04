"""Owned fake-handle/spawn faults only; no actual process, socket or service starts."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from dmf_pulse.operation import standing_worker as subject
from dmf_pulse.operation.models import OperationError

CANARY = "OWNED_PRIVATE_WORKER_FAULT_7811"


class Handle:
    def __init__(self, name, events, *, fail=False):
        self.name, self.events, self.fail = name, events, fail

    def close(self):
        self.events.append("close:" + self.name)
        if self.fail:
            raise OSError(CANARY)

    def poll(self):
        return False


@pytest.fixture
def fake(monkeypatch):
    events, handles = [], []
    state = SimpleNamespace(
        pipe_failure=None,
        process_failure=False,
        pool_start_failure=False,
        source_start_failure=False,
        stop_failure=False,
        pool_close_failure=False,
    )

    class Process:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.pid = None

        def start(self):
            events.append("source:start")
            if state.source_start_failure:
                raise OSError(CANARY)
            self.pid = 7

        def is_alive(self):
            return self.pid is not None

    class Context:
        def Pipe(self, *args, **kwargs):
            index = len(handles) // 2
            events.append("pipe:" + str(index))
            if state.pipe_failure == index:
                raise OSError(CANARY)
            pair = (Handle(str(index) + "reader", events), Handle(str(index) + "writer", events))
            handles.extend(pair)
            return pair

        def Process(self, **kwargs):
            events.append("source:construct")
            if state.process_failure:
                raise OSError(CANARY)
            process = Process(**kwargs)
            state.source = process
            return process

    class Pool:
        def __init__(self):
            events.append("pool:construct")
            self.connections = ()
            state.pool = self

        def start(self):
            events.append("pool:start")
            if state.pool_start_failure:
                raise OSError(CANARY)

        def release_clients(self):
            events.append("pool:release_clients")

        def close(self):
            events.append("pool:close")
            if state.pool_close_failure:
                raise OSError(CANARY)

    def stop(process):
        events.append("source:stop")
        if state.stop_failure:
            raise OSError(CANARY)
        process.pid = None

    monkeypatch.setattr(subject.multiprocessing, "get_context", lambda mode: Context())
    monkeypatch.setattr(subject, "DiagnosticComputePool", Pool)
    monkeypatch.setattr(subject, "stop_owned_process", stop)
    state.events, state.handles = events, handles
    return state


def launch(horizon=1, authorization="OPR001-OWNED-WORKER"):
    return SimpleNamespace(
        grant=SimpleNamespace(
            request=SimpleNamespace(horizon=horizon, authorization_id=authorization)
        )
    )


def test_compute_pool_starts_before_source_and_everything_is_supervisor_owned(fake):
    worker = subject.StandingWorker(launch())
    assert fake.events.index("pool:start") < fake.events.index("source:start")
    assert fake.source.kwargs["target"] is subject._standing_worker
    assert fake.source.kwargs["daemon"] is True
    assert fake.source.kwargs["args"][3] is fake.pool.connections
    assert fake.source.kwargs["args"][4] is fake.handles[2]
    worker.close()
    assert worker._closed is True
    assert "source:stop" in fake.events and "pool:close" in fake.events
    for handle in fake.handles:
        assert "close:" + handle.name in fake.events


@pytest.mark.parametrize(
    "fault", ["first_pipe", "second_pipe", "process_constructor", "pool_start", "source_start"]
)
def test_partial_constructor_or_spawn_fault_closes_all_assigned_resources(fake, fault):
    if fault == "first_pipe":
        fake.pipe_failure = 0
    elif fault == "second_pipe":
        fake.pipe_failure = 1
    elif fault == "process_constructor":
        fake.process_failure = True
    elif fault == "pool_start":
        fake.pool_start_failure = True
    else:
        fake.source_start_failure = True
    with pytest.raises(OSError):
        subject.StandingWorker(launch())
    assert "pool:close" in fake.events
    for handle in fake.handles:
        assert "close:" + handle.name in fake.events
    if hasattr(fake, "source"):
        assert "source:stop" in fake.events


def test_cleanup_fault_does_not_skip_remaining_handles_source_or_pool(fake):
    worker = subject.StandingWorker(launch())
    fake.events.clear()
    fake.handles[0].fail = True
    fake.stop_failure = fake.pool_close_failure = True
    with pytest.raises(OperationError) as caught:
        worker.close()
    assert caught.value.code == "WORKER_CLEANUP_FAILED"
    assert worker._closed is False
    for handle in fake.handles:
        assert "close:" + handle.name in fake.events
    assert "source:stop" in fake.events and "pool:close" in fake.events


def test_successful_cleanup_is_idempotent(fake):
    worker = subject.StandingWorker(launch())
    worker.close()
    snapshot = list(fake.events)
    worker.close()
    assert fake.events == snapshot


@pytest.mark.parametrize(
    "horizon,authorization", [(3, "OPR001-OWNED"), (1, "OPR003-OWNED"), (1, "CALLER")]
)
def test_wrong_execution_path_allocates_no_handles_or_pool(fake, horizon, authorization):
    with pytest.raises(OperationError):
        subject.StandingWorker(launch(horizon, authorization))
    assert fake.events == []


@pytest.fixture
def wrapped(monkeypatch):
    events = []
    state = SimpleNamespace(events=events, scope_failure=False, current_failure=False)

    class Thread:
        def __init__(self, **kwargs):
            events.append("watchdog:construct")
            assert kwargs["daemon"] is True and kwargs["target"] is subject._watch_owner

        def start(self):
            events.append("watchdog:start")

    @contextmanager
    def scope(connections):
        events.append("scope:enter")
        if state.scope_failure:
            raise KeyError(CANARY)
        try:
            yield
        finally:
            events.append("scope:exit")

    def current(*args):
        events.append("current:invoke")
        if state.current_failure:
            raise KeyboardInterrupt(CANARY)

    monkeypatch.setattr(subject, "_ConnectionBase", Handle)
    monkeypatch.setattr(subject.threading, "Thread", Thread)
    monkeypatch.setattr(subject, "diagnostic_compute_scope", scope)
    monkeypatch.setattr(subject, "current_worker", current)
    state.pipe, state.owner = Handle("pipe", events), Handle("owner", events)
    return state


def test_outer_lifeline_starts_before_ready_wait_and_current_worker(wrapped):
    subject._standing_worker(wrapped.pipe, 1, launch(), (), wrapped.owner)
    assert wrapped.events.index("watchdog:start") < wrapped.events.index("scope:enter")
    assert wrapped.events.index("scope:enter") < wrapped.events.index("current:invoke")
    assert "close:pipe" in wrapped.events and "close:owner" in wrapped.events


@pytest.mark.parametrize("fault", ["scope", "current"])
def test_wrapper_fault_never_formats_private_context_and_attempts_closure(wrapped, capsys, fault):
    setattr(wrapped, fault + "_failure", True)
    with pytest.raises(SystemExit) as caught:
        subject._standing_worker(wrapped.pipe, 1, launch(), (), wrapped.owner)
    assert caught.value.code == 2
    assert "close:pipe" in wrapped.events and "close:owner" in wrapped.events
    assert CANARY not in "".join(capsys.readouterr())


def test_wrapper_attempts_owner_close_even_when_result_pipe_close_refuses(wrapped, capsys):
    wrapped.pipe.fail = True
    with pytest.raises(SystemExit) as caught:
        subject._standing_worker(wrapped.pipe, 1, launch(), (), wrapped.owner)
    assert caught.value.code == 2
    assert "close:owner" in wrapped.events
    assert CANARY not in "".join(capsys.readouterr())
