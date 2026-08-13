"""Measure security and network behavior at the installed public 701 boundary."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

from installed_wheel_runtime import ROOT, WheelRuntimeError, run_installed_wheel

EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
NEEDLES = ("C:" + "\\Users\\", "dmf-" + "pulse-context", "Codex" + "Packs")
SCOPE = (
    "the isolated installed-wheel public REPLAY external-ID-701 CLI produced zero measured "
    "non-loopback network attempts under this guard"
)


def main() -> int:
    secret = subprocess.run(
        [sys.executable, "scripts/scan_secrets.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        secret_value = json.loads(secret.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("secret scan output is not JSON") from exc
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
    try:
        installed = run_installed_wheel(network_guard=True, additional_contexts=False)
    except WheelRuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    public = installed.get("public_701")
    network = installed.get("network_guard")
    if not isinstance(public, dict) or not isinstance(network, dict):
        raise SystemExit("installed public network measurement is incomplete")
    report = {
        "network": {
            **network,
            "claim": SCOPE,
            "command": public["command"],
            "entry_point": public["entry_point"],
            "exit_code": public["exit_code"],
            "fixture_external_id": public["fixture_external_id"],
            "fixture_id": public["fixture_id"],
            "installed_interpreter": installed["isolated_runtime"]["interpreter"],
            "mapping_provider": public["mapping_provider"],
            "mapping_resolution_success": public["mapping_resolution_success"],
            "result_sha256": public["result_sha256"],
            "status": public["status"],
            "stdout_sha256": public["stdout_sha256"],
            "team_id": public["team_id"],
        },
        "portable_source_scan": {"files_scanned": len(paths), "violations": violations},
        "scope": SCOPE,
        "secret_scan": {
            "exit_code": secret.returncode,
            "finding_count": secret_value.get("finding_count"),
            "status": secret_value.get("status"),
            "stdout_sha256": hashlib.sha256(secret.stdout.encode()).hexdigest(),
        },
    }
    report["status"] = (
        "PASS"
        if secret.returncode == 0
        and report["secret_scan"]["status"] == "PASS"
        and report["secret_scan"]["finding_count"] == 0
        and not violations
        and public["exit_code"] == 0
        and public["status"] == "PROJECTED"
        and network["guard_active"] is True
        and network["non_loopback_count"] == 0
        else "FAIL"
    )
    (EVIDENCE / "security_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["status"] != "PASS":
        raise SystemExit("installed public 701 security measurement failed")
    print("PASS: isolated installed-wheel public 701 measured zero non-loopback attempts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
