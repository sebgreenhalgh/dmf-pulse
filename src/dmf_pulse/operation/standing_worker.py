"""Supervisor-owned ordinary source and numerical siblings; no descendant spawning."""

from __future__ import annotations

import multiprocessing
import threading
from multiprocessing.connection import Connection, _ConnectionBase
from multiprocessing.process import BaseProcess
from typing import cast

from dmf_pulse.dashboard.current import CurrentLaunch, current_worker
from dmf_pulse.operation.diagnostic_compute import (
    DiagnosticComputePool,
    _watch_owner,
    diagnostic_compute_scope,
    stop_owned_process,
)
from dmf_pulse.operation.models import OperationError


def _standing_worker(
    pipe: _ConnectionBase,
    horizon: int,
    launch: CurrentLaunch,
    compute_connections: tuple[_ConnectionBase, ...],
    owner: _ConnectionBase,
) -> None:
    """Signed child bootstrap precedes this fixed, private spawn target."""
    try:
        if (
            not isinstance(pipe, _ConnectionBase)
            or not isinstance(owner, _ConnectionBase)
            or type(horizon) is not int
            or horizon != 1
            or launch.grant.request.horizon != 1
            or not launch.grant.request.authorization_id.startswith("OPR001-")
        ):
            raise OperationError("DIAGNOSTIC_COMPUTE_PROTOCOL_INVALID")
        threading.Thread(target=_watch_owner, args=(owner,), daemon=True).start()
        with diagnostic_compute_scope(compute_connections):
            current_worker(cast(Connection, pipe), 1, launch)
    except BaseException:
        # Never let multiprocessing render an exception carrying source data.
        raise SystemExit(2) from None
    finally:
        failed = False
        for handle in (pipe, owner):
            try:
                handle.close()
            except BaseException:
                failed = True
        if failed:
            raise SystemExit(2) from None


class StandingWorker:
    """All five daemons, handles and owner lifelines belong to this supervisor."""

    def __init__(self, launch: CurrentLaunch) -> None:
        if (
            launch.grant.request.horizon != 1
            or not launch.grant.request.authorization_id.startswith("OPR001-")
        ):
            raise OperationError("AUTHORIZATION_HORIZON_NOT_APPROVED")
        context = multiprocessing.get_context("spawn")
        self._compute = DiagnosticComputePool()
        self._process: BaseProcess | None = None
        self._handles: list[_ConnectionBase] = []
        self._closed = False
        try:
            self._reader, sender = context.Pipe(duplex=False)
            self._handles.extend((self._reader, sender))
            owner_reader, owner_writer = context.Pipe(duplex=False)
            self._handles.extend((owner_reader, owner_writer))
            self._process = context.Process(
                target=_standing_worker,
                args=(sender, 1, launch, self._compute.connections, owner_reader),
                daemon=True,
            )
            self._compute.start()
            try:
                self._process.start()
            finally:
                sender.close()
                owner_reader.close()
                self._compute.release_clients()
        except BaseException:
            try:
                self.close()
            except BaseException:
                raise OperationError("WORKER_CLEANUP_FAILED") from None
            raise

    def receive(self) -> tuple[str, object] | None:
        if not self._reader.poll():
            return None
        value: object = self._reader.recv()
        if not isinstance(value, tuple) or len(value) != 2 or not isinstance(value[0], str):
            raise ValueError("invalid worker response")
        return value[0], value[1]

    def alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        for handle in self._handles:
            try:
                handle.close()
            except BaseException:
                failed = True
        if self._process is not None:
            try:
                stop_owned_process(self._process)
            except BaseException:
                failed = True
        try:
            self._compute.close()
        except BaseException:
            failed = True
        if failed:
            raise OperationError("WORKER_CLEANUP_FAILED")
        self._closed = True
