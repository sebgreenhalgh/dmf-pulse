"""Real owned spawn children never format private diagnostic exception context."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dmf_pulse.operation import campaign_execution

DRIVER = r"""
import contextlib, hashlib, json, multiprocessing, socket, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CANARY = "OWNED_CAMPAIGN_PRIVATE_PREFIX_1234_NEVER_PUBLISH_SUFFIX_9876"

def child(mode, family, source_parent, expected_sha, directory):
    directory = Path(directory)
    sys.stderr = (directory / "child-stderr.txt").open("w", encoding="utf-8")
    def denied(*args, **kwargs):
        raise AssertionError("OWNED_EXTERNAL_NETWORK_DENIED")
    socket.create_connection = socket.getaddrinfo = denied
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = denied
    sys.path.insert(0, source_parent)
    from pydantic import BaseModel
    from dmf_pulse.operation import campaign_execution as subject
    from dmf_pulse.operation import campaign_sources
    assert hashlib.sha256(Path(subject.__file__).read_bytes()).hexdigest() == expected_sha
    reader, sender = multiprocessing.Pipe(duplex=False)
    events = []
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)

    class Value(BaseModel):
        field: int

    def fault(*args, **kwargs):
        events.append("OWNED_FAULT_REACHED")
        if family == "key":
            raise KeyError(CANARY)
        if family == "validation":
            Value.model_validate({"field": CANARY})
        if family == "interrupt":
            raise KeyboardInterrupt(CANARY)
        if family == "exit":
            raise SystemExit(CANARY)
        raise AssertionError("OWNED_INVALID_FAULT")

    class Journal:
        def terminate(self, *args, **kwargs):
            events.append("TERMINAL_WRITE_ATTEMPTED")
            if mode == "audit":
                raise BrokenPipeError("OWNED_AUDIT_DISCONNECTED")

    journal = Journal()
    runtime = SimpleNamespace(
        authority=SimpleNamespace(proposal=SimpleNamespace(limits=SimpleNamespace(
            minimum_fpl_credential_remaining_seconds=2100))),
        session=SimpleNamespace(started_at=now),
        journal=journal,
        clock=lambda: now,
    )
    # Windows returns PipeConnection; POSIX returns Connection. Exercise the
    # concrete native pipe rather than accidentally patching another class.
    connection_type = type(sender)
    original_close, original_send = connection_type.close, connection_type.send
    def close(connection):
        if connection is sender:
            events.append("CLOSE_ATTEMPTED")
            if mode == "close":
                raise BrokenPipeError("OWNED_CLOSE_DISCONNECTED")
        return original_close(connection)
    def send(connection, message):
        if connection is sender:
            if message[0] == "terminal":
                events.append("TERMINAL_SEND_ATTEMPTED")
                if mode == "send":
                    reader.close()
            else:
                assert message[0] == "progress"
                assert message[1] in subject.STAGE_LABELS.values()
                events.append("SAFE_STARTUP_PROGRESS_SENT")
        return original_send(connection, message)
    try:
        with (
            patch.object(subject.DiagnosticJournal, "production", return_value=journal),
            patch.object(subject, "diagnostic_source_context", return_value=contextlib.nullcontext(journal)),
            patch.object(subject, "require_runtime", return_value=runtime),
            patch.object(campaign_sources, "require_runtime", return_value=runtime),
            patch.object(subject, "_quota", side_effect=fault),
            patch.object(connection_type, "send", send),
            patch.object(connection_type, "close", close),
        ):
            subject.diagnostic_worker(sender, 1, "f" * 64, now + timedelta(hours=1))
    finally:
        (directory / "observation.json").write_text(json.dumps(events), encoding="utf-8")
        original_close(sender)
        original_close(reader)
        sys.stderr.flush()

if __name__ == "__main__":
    context = multiprocessing.get_context("spawn")
    worker = context.Process(target=child, args=tuple(sys.argv[1:]))
    worker.start()
    worker.join(30)
    if worker.is_alive():
        worker.terminate()
        worker.join(5)
        raise AssertionError("OWNED_CHILD_TIMEOUT")
    exit_code = worker.exitcode
    worker.close()
    print(json.dumps({"child_exit_code": exit_code}))
"""


@pytest.mark.parametrize("family", ["key", "validation"])
@pytest.mark.parametrize("mode", ["send", "audit", "close"])
def test_campaign_error_report_failures_have_fixed_exit_and_empty_stderr(tmp_path, family, mode):
    _check(tmp_path, family, mode)


@pytest.mark.parametrize("family", ["interrupt", "exit"])
def test_campaign_fatal_exception_payloads_are_never_formatted(tmp_path, family):
    _check(tmp_path, family, "send")


def _check(tmp_path, family, mode):
    driver = tmp_path / "owned-campaign-spawn.py"
    driver.write_text(DRIVER, encoding="utf-8")
    source = Path(campaign_execution.__file__).resolve()
    source_parent = str(source.parents[2])
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(driver),
            mode,
            family,
            source_parent,
            source_sha,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
        env={
            **{
                name: os.environ[name]
                for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
                if name in os.environ
            },
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == {"child_exit_code": 2}
    # Empty stderr rejects full and truncated ValidationError input-value text.
    assert (tmp_path / "child-stderr.txt").read_bytes() == b""
    observation = json.loads((tmp_path / "observation.json").read_bytes())
    assert observation.count("SAFE_STARTUP_PROGRESS_SENT") >= 1
    assert observation.count("OWNED_FAULT_REACHED") == 1
    assert observation.count("CLOSE_ATTEMPTED") == 1
    if family in {"key", "validation"}:
        assert observation.count("TERMINAL_WRITE_ATTEMPTED") == 1
        assert observation.count("TERMINAL_SEND_ATTEMPTED") == (0 if mode == "audit" else 1)
    else:
        assert "TERMINAL_WRITE_ATTEMPTED" not in observation
        assert "TERMINAL_SEND_ATTEMPTED" not in observation
