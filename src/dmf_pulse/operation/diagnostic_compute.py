"""Bounded sibling CPU workers for unchanged, transient diagnostic minutes.

The supervisor owns every process. The source worker remains a daemon and cannot
spawn descendants. Dedicated owner pipes kill even actively computing siblings
when their supervisor disappears. No source transport or authority enters them.

The typed pickle channels are private capabilities held only by reviewed sibling
processes. Their type checks and I/O fence are not an untrusted-pickle sandbox.
No public input, caller-selected channel or serialized callable grants authority.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from multiprocessing.connection import _ConnectionBase
from multiprocessing.context import SpawnContext
from multiprocessing.process import BaseProcess

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot
from dmf_pulse.markets.current import CurrentMarketCanonicalIdentityView
from dmf_pulse.operation.diagnostics import DiagnosticLog, SafeFailure, SafeFailureError
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1 import automatic_inputs as accepted
from dmf_pulse.private_v1.models import PrivateCanonicalPlayerIdentityMap
from dmf_pulse.private_v1.progress import ProgressSink

MAX_COMPUTE_WORKERS = 4


def _deny_external_io(event: str, arguments: tuple[object, ...]) -> None:
    if event in {
        "socket.__new__",
        "socket.connect",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.fork",
    }:
        raise OperationError("DIAGNOSTIC_COMPUTE_EXTERNAL_IO_FORBIDDEN")


def _watch_owner(owner: _ConnectionBase) -> None:
    try:
        # No payload is permitted: only the supervisor owns the writer. EOF is
        # observed in this thread even while the main thread runs the Python DP.
        owner.recv_bytes()
    except BaseException:
        os._exit(2)
    os._exit(2)


def _compute_worker(channel: _ConnectionBase, owner: _ConnectionBase) -> None:
    """Fixed work kind; signed bootstrap has run before application unpickling."""
    try:
        sys.addaudithook(_deny_external_io)
        threading.Thread(target=_watch_owner, args=(owner,), daemon=True).start()
        channel.send(("ready", None))
        while True:
            value = channel.recv()
            if (
                not isinstance(value, tuple)
                or len(value) != 3
                or not isinstance(value[0], DirectFplSnapshot)
                or not isinstance(value[1], PrivateCanonicalPlayerIdentityMap)
                or not isinstance(value[2], tuple)
                or not value[2]
                or any(not isinstance(item, accepted._AutomaticFixtureTarget) for item in value[2])
            ):
                raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
            try:
                snapshot, identity, targets = value
                channel.send(("started", None))
                result = accepted._build_automatic_model_minutes_for_targets(
                    snapshot, identity, targets, progress=None
                )
                channel.send(("minutes", result.minutes_by_gameweek[snapshot.target_gameweek]))
                del snapshot, identity, targets, result, value
            except Exception as error:
                log = DiagnosticLog()
                log.stage = "STAGE7_MINUTES"
                channel.send(("failure", log.failed(error)))
                return
    except (EOFError, BrokenPipeError):
        return
    except BaseException:
        # Never format a traceback, provider value, validation input or message.
        raise SystemExit(2) from None
    finally:
        try:
            channel.close()
            owner.close()
        except BaseException:
            raise SystemExit(2) from None


@dataclass(slots=True)
class _OwnedWorker:
    process: BaseProcess
    client: _ConnectionBase
    child_channel: _ConnectionBase
    owner: _ConnectionBase
    child_owner: _ConnectionBase


def _new_worker(context: SpawnContext) -> _OwnedWorker:
    handles: list[_ConnectionBase] = []
    try:
        client, channel = context.Pipe()
        handles.extend((client, channel))
        owner_reader, owner_writer = context.Pipe(duplex=False)
        handles.extend((owner_reader, owner_writer))
        process = context.Process(target=_compute_worker, args=(channel, owner_reader), daemon=True)
        return _OwnedWorker(process, client, channel, owner_writer, owner_reader)
    except BaseException:
        failed = False
        for handle in handles:
            try:
                handle.close()
            except BaseException:
                failed = True
        if failed:
            raise OperationError("WORKER_CLEANUP_FAILED") from None
        raise


def stop_owned_process(process: BaseProcess) -> None:
    """Attempt termination even if an earlier join/check fails; never assert it."""
    failed = False

    def alive() -> bool:
        nonlocal failed
        try:
            return process.is_alive()
        except BaseException:
            failed = True
            return True

    if process.pid is not None:
        try:
            process.join(timeout=0.1)
        except BaseException:
            failed = True
        for action in (process.terminate, process.kill):
            if alive():
                try:
                    action()
                except BaseException:
                    failed = True
                try:
                    process.join(timeout=3)
                except BaseException:
                    failed = True
        if alive():
            raise OperationError("WORKER_CLEANUP_FAILED")
    try:
        process.close()
    except BaseException:
        failed = True
    if failed:
        raise OperationError("WORKER_CLEANUP_FAILED")


class DiagnosticComputePool:
    """Created and closed only by the same supervisor that owns the source child."""

    def __init__(self) -> None:
        self._workers: list[_OwnedWorker] = []
        self._closed = False
        context = multiprocessing.get_context("spawn")
        try:
            for _ in range(min(MAX_COMPUTE_WORKERS, os.cpu_count() or 1)):
                self._workers.append(_new_worker(context))
        except BaseException:
            self.close()
            raise

    @property
    def connections(self) -> tuple[_ConnectionBase, ...]:
        return tuple(item.client for item in self._workers)

    def start(self) -> None:
        for item in self._workers:
            try:
                item.process.start()
            finally:
                item.child_channel.close()
                item.child_owner.close()

    def release_clients(self) -> None:
        """After source spawn, its copies are the only live client endpoints."""
        failed = False
        for item in self._workers:
            try:
                item.client.close()
            except BaseException:
                failed = True
        if failed:
            raise OperationError("WORKER_CLEANUP_FAILED")

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        for item in self._workers:
            for handle in (item.client, item.owner, item.child_channel, item.child_owner):
                try:
                    handle.close()
                except BaseException:
                    failed = True
        for item in self._workers:
            try:
                stop_owned_process(item.process)
            except BaseException:
                failed = True
        if failed:
            raise OperationError("WORKER_CLEANUP_FAILED")
        self._closed = True


@dataclass(slots=True, repr=False)
class _MinutesScope:
    connections: tuple[_ConnectionBase, ...]
    ready: bool = False
    key: str | None = None
    minutes: tuple[CurrentModelFixtureMinutesInput, ...] | None = None


_scope: ContextVar[_MinutesScope | None] = ContextVar("diagnostic_minutes_scope", default=None)


@contextmanager
def diagnostic_compute_scope(connections: tuple[_ConnectionBase, ...]) -> Iterator[None]:
    if (
        _scope.get() is not None
        or len(connections) > MAX_COMPUTE_WORKERS
        or any(not isinstance(item, _ConnectionBase) for item in connections)
    ):
        raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
    state = _MinutesScope(connections)
    token = _scope.set(state)
    try:
        # The source scope cannot reach even its INITIAL quota GET until every
        # signed compute child has entered its network fence and owner watchdog.
        for channel in connections:
            _receive(channel, "ready")
        state.ready = True
        yield
    finally:
        state.key, state.minutes = None, None
        _scope.reset(token)
        for channel in connections:
            channel.close()


def _targets(
    snapshot: DirectFplSnapshot, market: CurrentMarketCanonicalIdentityView
) -> tuple[accepted._AutomaticFixtureTarget, ...]:
    # Identical target selection to the protected one-GW public builder. Only
    # scheduling changes; each target is executed by its unchanged private helper.
    available = {
        item.provider_fixture_id: item
        for item in snapshot.fpl_input.fixtures
        if item.event_identity == snapshot.fpl_input.target_event.identity
    }
    targets = []
    for fixture in market.fixtures:
        observed = available.get(fixture.official_fpl_fixture_id)
        if observed is None:
            raise IngestionError("MAPPING_CONFLICT", "market fixture is absent from current FPL")
        targets.append(
            accepted._AutomaticFixtureTarget(
                gameweek=snapshot.target_gameweek,
                fixture=observed,
                canonical_fixture_id=fixture.canonical_fixture_id,
                scenario="private-one-command-current",
            )
        )
    return tuple(targets)


def _receive(channel: _ConnectionBase, expected: str) -> object:
    try:
        value: object = channel.recv()
    except (EOFError, OSError):
        raise OperationError("DIAGNOSTIC_COMPUTE_WORKER_STOPPED") from None
    if not isinstance(value, tuple) or len(value) != 2:
        raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
    kind, payload = value
    if kind == "failure" and isinstance(payload, SafeFailure):
        raise SafeFailureError(payload)
    if kind != expected or (expected in {"ready", "started"} and payload is not None):
        raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
    return payload


def build_diagnostic_model_minutes(
    snapshot: DirectFplSnapshot,
    identity: PrivateCanonicalPlayerIdentityMap,
    market: CurrentMarketCanonicalIdentityView,
    *,
    progress: ProgressSink,
) -> tuple[CurrentModelFixtureMinutesInput, ...]:
    state = _scope.get()
    if state is None:
        return accepted.build_automatic_model_minutes(snapshot, identity, market, progress=progress)
    targets = _targets(snapshot, market)
    key = canonical_sha256(
        {
            "snapshot": snapshot.model_dump(mode="json"),
            "identity": identity.model_dump(mode="json"),
            "targets": [
                [
                    item.gameweek,
                    item.fixture.model_dump(mode="json"),
                    str(item.canonical_fixture_id),
                    item.scenario,
                ]
                for item in targets
            ],
        }
    )
    if state.key == key and state.minutes is not None:
        return state.minutes
    if not state.connections:
        minutes = accepted.build_automatic_model_minutes(
            snapshot, identity, market, progress=progress
        )
    else:
        if not state.ready:
            for channel in state.connections:
                _receive(channel, "ready")
            state.ready = True
        pending = []
        for index, channel in enumerate(state.connections):
            partition = targets[index :: len(state.connections)]
            if partition:
                channel.send((snapshot, identity, partition))
                _receive(channel, "started")
                pending.append(channel)
        collected: list[CurrentModelFixtureMinutesInput] = []
        while pending:
            for channel in tuple(pending):
                if not channel.poll(0.1):
                    continue
                result = _receive(channel, "minutes")
                if not isinstance(result, tuple) or any(
                    not isinstance(item, CurrentModelFixtureMinutesInput) for item in result
                ):
                    raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
                collected.extend(result)
                pending.remove(channel)
        minutes = tuple(sorted(collected, key=lambda item: item.fixture_id))
        if sorted(item.fixture_id for item in minutes) != sorted(
            str(item.canonical_fixture_id) for item in targets
        ):
            raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
    state.key, state.minutes = key, minutes
    return minutes
