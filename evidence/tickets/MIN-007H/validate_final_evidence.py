from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
E = ROOT / "evidence/tickets/MIN-007H"
REQ = [
    "PLAN.md",
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
    "stage7_changed_files.txt",
    "stage7_diffstat.txt",
]


def main():
    missing = [x for x in REQ if not (E / x).is_file()]
    if missing:
        raise SystemExit("missing evidence: " + ", ".join(missing))
    if len(json.loads((E / "acceptance_ledger.json").read_text()).get("records", [])) != 31:
        raise SystemExit("ledger length")
    for name in [
        "coverage_summary.json",
        "migration_report.json",
        "installed_wheel_report.json",
        "frozen_identity_report.json",
        "security_report.json",
    ]:
        if json.loads((E / name).read_text()).get("status") != "PASS":
            raise SystemExit("not PASS: " + name)
    print("Final H evidence: PASS")


if __name__ == "__main__":
    main()
