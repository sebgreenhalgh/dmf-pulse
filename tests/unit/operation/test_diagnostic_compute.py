"""Real spawn, exact unchanged minutes, transient reuse and fail-closed cleanup."""

from __future__ import annotations

import multiprocessing
import socket
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
)
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)
from dmf_pulse.operation import diagnostic_compute as subject
from dmf_pulse.operation.diagnostic_pipeline import (
    assemble_diagnostic_execution,
    prepare_diagnostic_fpl,
)
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1.models import seal_canonical_player_identity_map
from dmf_pulse.private_v1.one_command import OneCommandRequest
from dmf_pulse.private_v1.progress import NullProgress
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.private_v1.test_one_command import (
    RUN_AT,
    _DirectTransport,
    _odds_input,
    _provider_sources,
)


@pytest.fixture(scope="module")
def minute_case(repository_root):
    bodies, _ = _provider_sources(repository_root)
    transport = _DirectTransport(bodies)
    snapshot = acquire_direct_fpl_snapshot(
        DirectFplClient(
            DirectFplRunAttestation(attested_at=RUN_AT - timedelta(minutes=1)),
            transport=transport,
            credential_provider=DirectFplCredentialProvider(
                {"DMF_FPL_BEARER_TOKEN": "owned-" + "synthetic-placeholder"}
            ),
            clock=lambda: RUN_AT,
            sleeper=lambda _: None,
            pace_seconds=0,
        ),
        entry_id=42,
        captured_at=RUN_AT,
        clock=lambda: RUN_AT,
    )
    prepared = prepare_diagnostic_fpl(
        snapshot, approved_at=RUN_AT - timedelta(minutes=1), observed_at=RUN_AT
    )
    config, scores = synthetic_snapshot()
    prior = CurrentScorePriorService(
        provider_config=config,
        rights_profiles=load_rights_profiles(),
        transport=FakeTransport(scores),
        clock=lambda: RUN_AT,
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    ).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=RUN_AT, rights_profile_id="openfootball_football_json_score_prior_v1"
        )
    )
    execution = assemble_diagnostic_execution(
        prepared,
        _odds_input(repository_root),
        prior,
        OneCommandRequest(
            entry_id=42,
            code_sha="a" * 40,
            run_at=RUN_AT,
            operator_approved_at=RUN_AT - timedelta(minutes=1),
            scenario_count=256,
            root_seed=42,
        ),
        resolved_at=RUN_AT,
    )
    return snapshot, execution


def _assert_joined(pids):
    assert not set(pids).intersection(item.pid for item in multiprocessing.active_children())


def test_real_spawn_matches_every_protected_minute_and_reuses_only_same_session(minute_case):
    snapshot, execution = minute_case
    pool = subject.DiagnosticComputePool()
    pids = []
    try:
        pool.start()
        pids = [item.process.pid for item in pool._workers]
        assert len(pids) <= 4 and all(item.process.daemon for item in pool._workers)
        with subject.diagnostic_compute_scope(pool.connections):
            observed = subject.build_diagnostic_model_minutes(
                snapshot,
                execution.player_identity_map,
                execution.market_identity_view,
                progress=NullProgress(),
            )
            assert [item.model_dump(mode="json") for item in observed] == [
                item.model_dump(mode="json") for item in execution.manual_minutes
            ]
            # Provider bookkeeping is not a minutes input. Source validation
            # still runs independently for each complete controlled/real kernel.
            same_targets = execution.market_identity_view.model_copy(
                update={"semantic_sha256": "b" * 64}
            )
            repeated = subject.build_diagnostic_model_minutes(
                snapshot, execution.player_identity_map, same_targets, progress=NullProgress()
            )
            assert repeated is observed
        assert subject._scope.get() is None
    finally:
        pool.close()
    _assert_joined(pids)


@pytest.mark.parametrize("changed", ["snapshot", "identity", "fixture"])
def test_reuse_requires_full_snapshot_identity_and_target_equality(
    minute_case, monkeypatch, changed
):
    snapshot, execution = minute_case
    identity = execution.player_identity_map
    market = execution.market_identity_view
    calls = []

    def calculate(*args, **kwargs):
        calls.append(args)
        return execution.manual_minutes

    monkeypatch.setattr(subject.accepted, "build_automatic_model_minutes", calculate)
    with subject.diagnostic_compute_scope(()):
        subject.build_diagnostic_model_minutes(snapshot, identity, market, progress=NullProgress())
        subject.build_diagnostic_model_minutes(snapshot, identity, market, progress=NullProgress())
        assert len(calls) == 1
        if changed == "snapshot":
            snapshot = snapshot.model_copy(update={"request_count": snapshot.request_count + 1})
        elif changed == "identity":
            payload = identity.model_dump(mode="python")
            payload.update(teams=identity.teams, players=identity.players)
            payload["resolved_at"] -= timedelta(microseconds=1)
            identity = seal_canonical_player_identity_map(type(identity).model_construct(**payload))
        else:
            market = market.model_copy(update={"fixtures": tuple(reversed(market.fixtures))})
        subject.build_diagnostic_model_minutes(snapshot, identity, market, progress=NullProgress())
        assert len(calls) == 2
    # No cross-session cache, including when an execution exits abnormally.
    with pytest.raises(RuntimeError), subject.diagnostic_compute_scope(()):
        subject.build_diagnostic_model_minutes(snapshot, identity, market, progress=NullProgress())
        raise RuntimeError("owned failure")
    assert subject._scope.get() is None and len(calls) == 3


def test_lifeline_stops_worker_during_actual_unchanged_computation(minute_case):
    snapshot, execution = minute_case
    pool = subject.DiagnosticComputePool()
    pids = []
    try:
        pool.start()
        pids = [item.process.pid for item in pool._workers]
        selected = pool._workers[0]
        assert selected.client.poll(30)
        subject._receive(selected.client, "ready")
        selected.client.send(
            (
                snapshot,
                execution.player_identity_map,
                subject._targets(snapshot, execution.market_identity_view),
            )
        )
        assert selected.client.poll(30)
        subject._receive(selected.client, "started")
        time.sleep(0.2)
        assert selected.process.is_alive() and not selected.client.poll()
        # Exactly the EOF produced by supervisor process death: no writer was
        # passed to the source child or any other compute child.
        selected.owner.close()
        selected.process.join(5)
        assert not selected.process.is_alive() and selected.process.exitcode == 2
    finally:
        pool.close()
    _assert_joined(pids)


class _SocketDuringUnpickle:
    def __reduce__(self):
        return socket.socket, ()


@pytest.mark.parametrize("payload", [_SocketDuringUnpickle(), ("owned-private-canary",)])
def test_fence_precedes_payload_decoding_and_bad_tasks_never_print(payload, capfd):
    pool = subject.DiagnosticComputePool()
    try:
        pool.start()
        selected = pool._workers[0]
        assert selected.client.poll(30)
        subject._receive(selected.client, "ready")
        selected.client.send(payload)
        selected.process.join(10)
        assert not selected.process.is_alive() and selected.process.exitcode == 2
    finally:
        pool.close()
    output = capfd.readouterr()
    assert "owned-private-canary" not in output.out + output.err
    assert "Traceback" not in output.err


def test_partial_spawn_still_closes_every_assigned_handle(monkeypatch):
    pool = subject.DiagnosticComputePool()
    if len(pool._workers) < 2:
        pool.close()
        pytest.skip("partial second spawn requires two CPU workers")
    pids = []

    def refuse():
        raise OSError("owned spawn refusal")

    monkeypatch.setattr(pool._workers[1].process, "start", refuse)
    try:
        with pytest.raises(OSError, match="owned spawn refusal"):
            pool.start()
        pids = [item.process.pid for item in pool._workers if item.process.pid is not None]
    finally:
        pool.close()
    assert pool._closed
    _assert_joined(pids)


def _idle_source(pipe, horizon, key, expiry, connections):
    for channel in connections:
        subject._receive(channel, "ready")
    pipe.send(("progress", "owned siblings ready"))
    time.sleep(120)


def test_source_shutdown_closes_all_real_siblings(monkeypatch, repository_root):
    from dmf_pulse.operation import campaign_start

    # pytest's importlib loader can import this owned target without adding the
    # repository namespace to sys.path. Native spawn must import it independently.
    monkeypatch.syspath_prepend(str(repository_root))
    monkeypatch.setattr(campaign_start, "diagnostic_worker", _idle_source)
    worker = campaign_start.DiagnosticWorker("f" * 64, datetime.now(UTC) + timedelta(hours=1))
    pids = []
    try:
        worker.start()
        pids = [worker._process.pid, *(item.process.pid for item in worker._compute._workers)]
        assert worker._reader.poll(30)
        assert worker.receive() == ("progress", "owned siblings ready")
        worker._process.terminate()
        worker._process.join(5)
    finally:
        worker.close()
    _assert_joined(pids)


def test_nested_scope_or_invalid_connections_are_rejected():
    with (
        subject.diagnostic_compute_scope(()),
        pytest.raises(OperationError, match="DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID"),
        subject.diagnostic_compute_scope(()),
    ):
        pytest.fail("nested scope was admitted")
    with (
        pytest.raises(OperationError, match="DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID"),
        subject.diagnostic_compute_scope((object(),)),
    ):
        pytest.fail("non-pipe endpoint was admitted")


def test_unconfirmed_process_or_handle_cleanup_attempts_every_sibling():
    events = []

    class Handle:
        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(self.name)
            if self.name == "client0":
                raise OSError("owned handle closure refused")

    class Process:
        def __init__(self, index):
            self.index, self.pid = index, index + 1

        def join(self, timeout):
            events.append(f"join{self.index}")

        def is_alive(self):
            return self.index == 0

        def terminate(self):
            events.append("terminate0")

        def kill(self):
            events.append("kill0")

        def close(self):
            events.append(f"closed{self.index}")

    pool = object.__new__(subject.DiagnosticComputePool)
    pool._closed = False
    pool._workers = [
        SimpleNamespace(
            process=Process(index),
            **{
                name: Handle(f"{name}{index}")
                for name in ("client", "owner", "child_channel", "child_owner")
            },
        )
        for index in range(4)
    ]
    with pytest.raises(OperationError, match="WORKER_CLEANUP_FAILED"):
        pool.close()
    assert not pool._closed
    assert "terminate0" in events and "kill0" in events
    for index in range(1, 4):
        assert f"closed{index}" in events
        assert f"owner{index}" in events


def test_constructor_failure_closes_previously_created_and_partial_handles(monkeypatch):
    real = multiprocessing.get_context("spawn")
    endpoints = []
    processes = []

    class Context:
        def Pipe(self, *args, **kwargs):
            pair = real.Pipe(*args, **kwargs)
            endpoints.extend(pair)
            return pair

        def Process(self, **kwargs):
            if processes:
                raise OSError("owned constructor refusal")
            value = real.Process(**kwargs)
            processes.append(value)
            return value

    monkeypatch.setattr(subject.multiprocessing, "get_context", lambda _: Context())
    monkeypatch.setattr(subject.os, "cpu_count", lambda: 4)
    with pytest.raises(OSError, match="owned constructor refusal"):
        subject.DiagnosticComputePool()
    assert len(endpoints) == 8 and all(item.closed for item in endpoints)


@pytest.mark.parametrize("code", ["MAPPING_CONFLICT", "CURRENT_MINUTES_MODEL_BLOCKED"])
def test_fixed_failure_code_survives_ipc_without_the_private_message(code):
    reader, writer = multiprocessing.Pipe()
    try:
        log = subject.DiagnosticLog()
        log.stage = "STAGE7_MINUTES"
        failure = log.failed(IngestionError(code, "owned-private-canary"))
        writer.send(("failure", failure))
        with pytest.raises(subject.SafeFailureError) as caught:
            subject._receive(reader, "minutes")
        observed = subject.DiagnosticLog().failed(caught.value)
        assert observed.model_dump(mode="json") == failure.model_dump(mode="json")
        assert "owned-private-canary" not in str(caught.value)
        writer.send(("unknown", "owned-private-canary"))
        with pytest.raises(OperationError, match="DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID"):
            subject._receive(reader, "minutes")
    finally:
        reader.close()
        writer.close()
