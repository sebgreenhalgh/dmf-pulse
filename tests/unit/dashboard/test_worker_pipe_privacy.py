"""The real process bootstrap must never format private source exception context."""

import json
import os
import subprocess
import sys

import pytest

DRIVER = r"""
import json, multiprocessing, socket, sys, types
from pathlib import Path

CANARY = "OWNED_PRIVATE_INPUT_PREFIX_1234_NEVER_PUBLISH_SUFFIX_9876"

def child(kind, staged, phase, directory):
    def denied(*args, **kwargs):
        raise AssertionError("OWNED_EXTERNAL_NETWORK_DENIED")
    socket.create_connection = socket.getaddrinfo = denied
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = denied
    directory = Path(directory)
    sys.stderr = (directory / "child-stderr.txt").open("w", encoding="utf-8")
    from pydantic import BaseModel
    from dmf_pulse.dashboard import current

    class OwnedPipe:
        def __init__(self):
            self.accepted, self.attempted, self.closed = [], [], 0
            self.disconnected = False
        def send(self, message):
            label = message[0]
            if label == "diagnostic":
                label = json.loads(message[1])["kind"]
            self.attempted.append(label)
            if self.disconnected or (phase == "failure" and label == "FAILURE") or (
                phase == "terminal" and label == "error"
            ):
                # A disconnected receiver cannot accept a later error packet.
                self.disconnected = True
                raise BrokenPipeError("OWNED_PARENT_DISCONNECTED")
            self.accepted.append(message)
        def close(self):
            self.closed += 1
            if phase == "close":
                raise BrokenPipeError("OWNED_CLOSE_FAILED")

    def fault():
        if kind == "key":
            raise KeyError(CANARY)
        if kind == "interrupt":
            raise KeyboardInterrupt(CANARY)
        if kind == "exit":
            raise SystemExit(CANARY)
        class OwnedPayload(BaseModel):
            value: int
        OwnedPayload.model_validate({"value": CANARY})

    def injected(launch, progress):
        if staged:
            with progress.stage(started="Acquiring current FPL state...",
                                completed="FPL state ready", failed="current FPL state"):
                fault()
        else:
            fault()

    current.run_current_recommendation = injected
    launch = types.SimpleNamespace(grant=types.SimpleNamespace(
        request=types.SimpleNamespace(horizon=1)))
    pipe = OwnedPipe()
    try:
        current.current_worker(pipe, 1, launch)
    finally:
        (directory / "observation.json").write_text(json.dumps({
            "accepted": pipe.accepted, "attempted": pipe.attempted, "closed": pipe.closed
        }), encoding="utf-8")
        sys.stderr.flush()

if __name__ == "__main__":
    context = multiprocessing.get_context("spawn")
    worker = context.Process(target=child, args=(sys.argv[1], sys.argv[2] == "1",
                                               sys.argv[3], sys.argv[4]))
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


@pytest.mark.parametrize("kind", ["key", "validation"])
@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("phase", ["failure", "terminal", "close"])
def test_disconnected_worker_has_fixed_exit_and_no_stderr_context(tmp_path, kind, staged, phase):
    _check(tmp_path, kind, staged, phase)


@pytest.mark.parametrize("kind", ["interrupt", "exit"])
def test_fatal_worker_exception_payload_is_never_formatted(tmp_path, kind):
    _check(tmp_path, kind, True, "terminal")


def _check(tmp_path, kind, staged, phase):
    driver = tmp_path / "owned-spawn.py"
    driver.write_text(DRIVER, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(driver), kind, str(int(staged)), phase, str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == {"child_exit_code": 2}
    # Empty stderr also rejects truncated ValidationError input-value disclosures.
    assert (tmp_path / "child-stderr.txt").read_bytes() == b""
    observation = json.loads((tmp_path / "observation.json").read_bytes())
    assert observation["closed"] == 1
    assert "OWNED_PRIVATE_INPUT_PREFIX" not in json.dumps(observation["accepted"])
    assert "NEVER_PUBLISH_SUFFIX" not in json.dumps(observation["accepted"])
    assert observation["attempted"].count("error") <= 1
