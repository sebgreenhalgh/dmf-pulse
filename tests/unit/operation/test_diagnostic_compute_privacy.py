"""Adopt independent 094: actual spawn must reach faults without printing data."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dmf_pulse.operation import diagnostic_compute

DRIVER = r"""
import hashlib, multiprocessing, sys
from pathlib import Path

CANARY = "OWNED_PRIVATE_COMPUTE_PREFIX_MIDDLE_SUFFIX_NEVER_DISCLOSE"

def child(source_parent, source_sha, family, mode):
    sys.path.insert(0, source_parent)
    from dmf_pulse.operation import diagnostic_compute as subject
    assert hashlib.sha256(Path(subject.__file__).read_bytes()).hexdigest() == source_sha

    def fail(*args, **kwargs):
        print("WORK_FAULT_REACHED", flush=True)
        if family == "validation":
            from pydantic import TypeAdapter
            TypeAdapter(int).validate_python(CANARY)
        raise KeyError(CANARY)

    class NoThread:
        def __init__(self, *args, **kwargs):
            return None
        def start(self):
            return None

    subject.accepted._build_automatic_model_minutes_for_targets = fail
    subject.threading.Thread = NoThread
    target = object.__new__(subject.accepted._AutomaticFixtureTarget)
    payload = (subject.DirectFplSnapshot.model_construct(),
               subject.PrivateCanonicalPlayerIdentityMap.model_construct(), (target,))

    class Channel:
        def send(self, value):
            if value[0] == "failure":
                print("FAILURE_SEND_ATTEMPTED", flush=True)
                if mode in {"send", "sendclose"}:
                    raise BrokenPipeError("owned disconnected channel")
        def recv(self):
            return payload
        def close(self):
            print("CHANNEL_CLOSE_ATTEMPTED", flush=True)
            if mode in {"close", "sendclose"}:
                raise OSError("owned refused channel close")

    class Owner:
        def close(self):
            print("OWNER_CLOSE_ATTEMPTED", flush=True)
            if mode == "ownerclose":
                raise OSError("owned refused owner close")

    subject._compute_worker(Channel(), Owner())

if __name__ == "__main__":
    process = multiprocessing.get_context("spawn").Process(target=child, args=tuple(sys.argv[1:]))
    try:
        process.start()
        process.join(20)
        if process.is_alive():
            raise RuntimeError("OWNED_CHILD_TIMEOUT")
        print("CHILD_EXIT=" + str(process.exitcode), flush=True)
        expected = 0 if sys.argv[-1] == "send" else 2
        assert process.exitcode == expected
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        process.close()
"""


@pytest.mark.parametrize("family", ["key", "validation"])
@pytest.mark.parametrize("mode", ["send", "close", "sendclose", "ownerclose"])
def test_compute_error_send_and_final_close_never_format_private_context(tmp_path, family, mode):
    driver = tmp_path / "owned-compute-privacy.py"
    driver.write_text(DRIVER, encoding="utf-8")
    source = Path(diagnostic_compute.__file__).resolve()
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(driver), str(source.parents[2]), source_sha, family, mode],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=35,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={
            **{
                name: os.environ[name]
                for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
                if name in os.environ
            },
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
    )
    assert result.returncode == 0 and result.stderr == b""
    observed = set(result.stdout.decode("utf-8").splitlines())
    required = {
        "WORK_FAULT_REACHED",
        "FAILURE_SEND_ATTEMPTED",
        "CHANNEL_CLOSE_ATTEMPTED",
        "CHILD_EXIT=" + str(0 if mode == "send" else 2),
    }
    if mode in {"send", "ownerclose"}:
        required.add("OWNER_CLOSE_ATTEMPTED")
    assert required <= observed
    for forbidden in (b"OWNED_PRIVATE_COMPUTE", b"MIDDLE_SUFFIX", b"input_value=", b"Traceback"):
        assert forbidden not in result.stdout + result.stderr
