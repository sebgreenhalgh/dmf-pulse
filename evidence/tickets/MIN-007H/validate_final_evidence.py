"""Recompute critical durable evidence facts and reject stale/transient files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
EXCLUSION = re.compile(
    r"pragma\s*:\s*no\s*(?:cover|branch)|coverage\s*:\s*(?:ignore|exclude)|no[-_ ]cover", re.I
)
REQUIRED = (
    "PLAN.md",
    "assurance_plan.json",
    "acceptance_ledger.json",
    "RESULT.md",
    "full_test_summary.json",
    "coverage.json",
    "coverage_summary.json",
    "math_core_manifest.json",
    "migration_report.json",
    "installed_wheel_report.json",
    "frozen_identity_report.json",
    "security_report.json",
    "audit_closure_history.md",
)
TRANSIENT = {
    "focused_core_coverage.json",
    "full_test_output.txt",
    "full_test_error.txt",
    "full_test_exit.txt",
    "full_test_launcher_pid.txt",
    "stage7_changed_files.txt",
    "stage7_diffstat.txt",
    "raw_stdout.txt",
    "raw_stderr.txt",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    missing = [name for name in REQUIRED if not (args.evidence / name).is_file()]
    stale = [name for name in TRANSIENT if (args.evidence / name).exists()]
    if missing or stale:
        raise SystemExit(f"missing={missing} stale={stale}")
    subprocess.run(
        ["uv", "run", "python", "evidence/tickets/MIN-007H/validate_acceptance_ledger.py"],
        cwd=ROOT,
        check=True,
    )
    manifest = json.loads((args.evidence / "math_core_manifest.json").read_text(encoding="utf-8"))
    coverage = json.loads((args.evidence / "coverage.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or len(manifest.get("modules", {})) != 6:
        raise SystemExit("core manifest incomplete")
    for path, item in manifest["modules"].items():
        if EXCLUSION.search((ROOT / path).read_text(encoding="utf-8")):
            raise SystemExit(f"source exclusion: {path}")
        found = [
            value
            for key, value in coverage["files"].items()
            if key.replace("\\", "/").endswith(path)
        ]
        if (
            len(found) != 1
            or found[0].get("excluded_lines", []) != []
            or found[0]["missing_lines"] != item["raw_missing_lines"]
            or found[0]["missing_branches"] != item["raw_missing_branches"]
        ):
            raise SystemExit(f"coverage mismatch: {path}")
        if (
            item["reachable"]["covered_lines"] != item["reachable"]["num_statements"]
            or item["reachable"]["covered_branches"] != item["reachable"]["num_branches"]
        ):
            raise SystemExit(f"reachable gap: {path}")
    identities = json.loads(
        (args.evidence / "frozen_identity_report.json").read_text(encoding="utf-8")
    )
    security = json.loads((args.evidence / "security_report.json").read_text(encoding="utf-8"))
    if identities.get("status") != "PASS" or not all(
        item.get("expected") == item.get("observed")
        and item.get("derived")
        and item.get("status") == "PASS"
        for item in identities.get("identities", {}).values()
    ):
        raise SystemExit("identity evidence mismatch")
    if (
        security.get("status") != "PASS"
        or security.get("network", {}).get("non_loopback_count") != 0
        or security.get("network", {}).get("guarded") is not True
    ):
        raise SystemExit("security measurement mismatch")
    banned = ("C:" + "\\Users\\", "dmf-" + "pulse-context", "Codex" + "Packs")
    for path in args.evidence.glob("*.py"):
        if any(token in path.read_text(encoding="utf-8") for token in banned):
            raise SystemExit(f"nonportable helper: {path.name}")
    print("PASS: final evidence facts recomputed and fail closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
