"""Explicit bounded diagnostic launcher; ordinary standing start is unchanged."""

from __future__ import annotations

import json
import multiprocessing
import os
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.credentials.service import CredentialService
from dmf_pulse.dashboard.runtime import ProcessWorker
from dmf_pulse.dashboard.views import DeskView
from dmf_pulse.operation.campaign import SessionMode
from dmf_pulse.operation.campaign_authority import load_verified_campaign
from dmf_pulse.operation.campaign_execution import diagnostic_worker
from dmf_pulse.operation.campaign_journal import DiagnosticJournal
from dmf_pulse.operation.diagnostics import STAGE_LABELS, DiagnosticLog, Stage
from dmf_pulse.operation.maintenance import _safe_path, operator_root
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.start import PORT, BlockedRuntime, RetainedRuntime, _open_when_ready


class DiagnosticWorker(ProcessWorker):
    """Assign the supervisor handle before start, including failed spawn cleanup."""

    def __init__(self, key: str, credential_expires_at: datetime) -> None:
        context = multiprocessing.get_context("spawn")
        self._reader, self._sender = context.Pipe(duplex=False)
        self._process = context.Process(
            target=diagnostic_worker,
            args=(self._sender, 1, key, credential_expires_at),
            daemon=True,
        )

    def start(self) -> None:
        try:
            self._process.start()
        finally:
            self._sender.close()

    def close(self) -> None:
        self._sender.close()
        if self._process.pid is None:
            self._reader.close()
            self._process.close()
        else:
            super().close()


def ensure_campaign_credential() -> datetime:
    """Read metadata only; the existing hidden local prompt decodes actual JWT expiry."""
    from dmf_pulse.cli.credentials import prompt_fpl_jwt

    authority = load_verified_campaign()
    service = CredentialService()
    status = service.status("fpl")
    now = datetime.now(UTC)
    minimum = authority.proposal.limits.minimum_fpl_credential_remaining_seconds
    maximum = authority.normal_policy.limits.credential_maximum_remaining_seconds
    if (
        status.configured
        and status.registered_at is not None
        and status.expires_at is not None
        and now + timedelta(seconds=minimum)
        <= status.expires_at
        <= now + timedelta(seconds=maximum)
    ):
        return status.expires_at
    return prompt_fpl_jwt(
        minimum_remaining_seconds=minimum, maximum_remaining_seconds=maximum, service=service
    )


def _export_receipt(journal: DiagnosticJournal, key: str) -> Path:
    receipt = journal.session_receipt(key)
    receipt["original_custody"] = journal.verify_original_custody()
    digest = canonical_sha256(receipt)
    body = canonical_json_bytes({**receipt, "semantic_sha256": digest}) + b"\n"
    base = _safe_path(operator_root().parent / "GW10-diagnostics/audits")
    base.mkdir(parents=True, exist_ok=True)
    target = _safe_path(base / f"SESSION-{key}-{digest}.json")
    if target.exists():
        if target.read_bytes() != body:
            raise OperationError("DIAGNOSTIC_IMMUTABLE_RECEIPT_COLLISION")
        return target
    with target.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return target


def run_bounded_session(
    journal: DiagnosticJournal,
    mode: SessionMode,
    credential_expires_at: datetime,
    *,
    progress: Callable[[str], None],
) -> tuple[str, dict[str, object]]:
    """No loop creates a second session; a separate inspection is mandatory."""
    journal.verify_original_custody()
    started = time.monotonic()
    session = journal.begin_session(mode, now=datetime.now(UTC))
    worker: DiagnosticWorker | None = None
    code: str | None = None
    last_observed_stage: Stage = "WORKER_START"
    try:
        progress(
            f"GW10 diagnostic session {session.session_index} admitted ({mode}); source bodies transient."
        )
        worker = DiagnosticWorker(session.session_key, credential_expires_at)
        worker.start()
        last_heartbeat = started
        last_custody_check = started
        ceiling = session.lease_until
        while worker.alive():
            if time.monotonic() - last_custody_check >= 1:
                ceiling = min(ceiling, journal.execution_ceiling(session.session_key))
                last_custody_check = time.monotonic()
            if time.monotonic() - started >= 1800 or datetime.now(UTC) >= ceiling:
                code = "RUN_TIMEOUT"
                break
            message = worker.receive()
            if message is not None:
                kind, value = message
                if (
                    kind in {"phase", "progress", "terminal"}
                    and type(value) is str
                    and len(value) <= 200
                ):
                    progress(value)
                    if kind == "progress":
                        for stage, label in STAGE_LABELS.items():
                            if value == label:
                                last_observed_stage = stage
                    if kind == "phase":
                        ceiling = min(ceiling, journal.execution_ceiling(session.session_key))
                else:
                    code = "DIAGNOSTIC_PROTOCOL_INVALID"
                    break
            if time.monotonic() - last_heartbeat >= 30:
                progress("GW10 diagnostic worker remains active; no automatic retry.")
                last_heartbeat = time.monotonic()
            time.sleep(0.1)
    except BaseException:
        code = "WORKER_STOPPED"
    finally:
        if worker is not None:
            # close() verifies terminate/kill/join; on failure preserve the live
            # lease and refuse to mark custody closed or run another worker.
            try:
                worker.close()
            except BaseException:
                raise OperationError("WORKER_CLEANUP_FAILED") from None
    receipt = journal.session_receipt(session.session_key)
    if receipt["terminal"] is None:
        log = DiagnosticLog()
        log.stage = last_observed_stage
        log.failed(OperationError(code or "WORKER_STOPPED"))
        journal.terminate(
            session.session_key,
            diagnostics=log.report().model_copy(update={"chronology_complete": False}),
            error_code=code or "WORKER_STOPPED",
            now=datetime.now(UTC),
        )
    journal.close(session.session_key, worker_and_transports_quiescent=True, now=datetime.now(UTC))
    exported = _export_receipt(journal, session.session_key)
    progress(f"Immutable private diagnostic receipt: {exported}")
    return session.session_key, journal.session_receipt(session.session_key)


def inspect_session(key: str) -> dict[str, object]:
    """Separate explicit inspection step; it cannot invoke or reserve a provider."""
    from dmf_pulse.operation.local_control import recover_local_control

    authority = load_verified_campaign()
    recover_local_control(authority.normal_policy)
    journal = DiagnosticJournal.production()
    receipt = journal.session_receipt(key)
    terminal = receipt["terminal_sha256"]
    if type(terminal) is not str:
        raise OperationError("DIAGNOSTIC_TERMINAL_RESULT_REQUIRED")
    journal.inspect_previous(key, terminal, now=datetime.now(UTC))
    _export_receipt(journal, key)
    return {"session_key": key, "inspected_terminal_sha256": terminal, "provider_requests": 0}


def run_diagnostic_start(mode: SessionMode, *, progress: Callable[[str], None]) -> None:
    """Fixed loopback private UI; Refresh/reload never starts another acquisition."""
    import uvicorn

    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.operation.local_control import recover_local_control

    authority = load_verified_campaign()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    runtime: RetainedRuntime | BlockedRuntime | None = None
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", PORT))
        listener.listen(8)
        recover_local_control(authority.normal_policy)
        journal = DiagnosticJournal.production()
        journal.verify_original_custody()
        journal.preflight_session(mode, now=datetime.now(UTC))
        expiry = ensure_campaign_credential()
        _, receipt = run_bounded_session(journal, mode, expiry, progress=progress)
        terminal = receipt["terminal"]
        if isinstance(terminal, dict) and terminal.get("outcome") == "REAL_PUBLICATION":
            view = DeskView.model_validate_json(json.dumps(terminal["view"]))
            runtime = RetainedRuntime(view)
            progress(view.team.report)
        else:
            code = (
                terminal.get("error_code", "WORKER_STOPPED")
                if isinstance(terminal, dict)
                else "WORKER_STOPPED"
            )
            runtime = BlockedRuntime(code)
        app = create_app(
            runtime=runtime,
            pairing_code="unused-diagnostic-local-session",
            port=PORT,
            trusted_local_navigation=True,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=PORT,
                access_log=False,
                log_config=None,
                log_level="critical",
                proxy_headers=False,
                server_header=False,
                limit_concurrency=8,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=10,
            )
        )
        threading.Thread(target=_open_when_ready, kwargs={"port": PORT}, daemon=True).start()
        progress(
            f"Seb's Desk: http://127.0.0.1:{PORT} â€” GW10 diagnostic / forecasts unvalidated."
        )
        server.run(sockets=[listener])
    except OSError:
        raise OperationError("LOCAL_DASHBOARD_OR_DIAGNOSTIC_PROCESS_UNAVAILABLE") from None
    finally:
        if runtime is not None:
            runtime.close()
        listener.close()
