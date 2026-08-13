"""Measure secret, portability, and frozen replay network behavior."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
NEEDLES = ("C:" + "\\Users\\", "dmf-" + "pulse-context", "Codex" + "Packs")


def read(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def main() -> int:
    secret = subprocess.run(
        [sys.executable, "scripts/scan_secrets.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    paths = [
        *ROOT.glob("src/dmf_pulse/**/*.py"),
        *ROOT.glob("tests/**/*.py"),
        *ROOT.glob("scripts/**/*.py"),
        *EVIDENCE.glob("*.py"),
    ]
    violations = {
        str(path.relative_to(ROOT)): needle
        for path in paths
        if path.name != "test_audit0073_portability.py"
        for needle in NEEDLES
        if needle in path.read_text(encoding="utf-8", errors="replace")
    }
    attempts = []
    original = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> object:
        host = str(address[0]) if isinstance(address, tuple) and address else ""
        if host not in {"127.0.0.1", "::1", "localhost"}:
            attempts.append(host)
            raise RuntimeError("non-loopback network blocked")
        return original(self, address)

    socket.socket.connect = guarded
    try:
        from dmf_pulse.availability.pipeline import (
            fit_projection_artifact,
            predict_minutes_baseline,
        )

        training = read("fixtures/availability/MIN-007/training_dataset.json")
        policy = read("fixtures/availability/MIN-007G/minutes_baseline_policy.json")
        history = read("fixtures/availability/MIN-007/canonical_history.json")
        context = read("fixtures/availability/MIN-007G/contexts/stable_xi.json")
        result = predict_minutes_baseline(
            history,
            fit_projection_artifact(training, policy=policy),
            context=context,
            policy=policy,
        )
    finally:
        socket.socket.connect = original
    report = {
        "status": "PASS"
        if secret.returncode == 0
        and not violations
        and not attempts
        and result.status == "PROJECTED"
        else "FAIL",
        "secret_scan": {
            "exit_code": secret.returncode,
            "stdout_sha256": hashlib.sha256(secret.stdout.encode()).hexdigest(),
        },
        "portable_source_scan": {"files_scanned": len(paths), "violations": violations},
        "network": {
            "scope": "frozen TEST/REPLAY 701 production smoke",
            "guarded": True,
            "non_loopback_attempts": attempts,
            "non_loopback_count": len(attempts),
            "result_status": result.status,
        },
        "scope": "Only the measured frozen production smoke is covered; no claim is made for unmeasured providers or full-suite network behavior.",
    }
    (EVIDENCE / "security_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["status"] != "PASS":
        raise SystemExit("security portability measurement failed")
    print("PASS: measured security, portability, and zero non-loopback replay attempts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
