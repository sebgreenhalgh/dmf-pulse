"""Record the Stage-10 coverage result for independent review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.coverage.read_text(encoding="utf-8"))
    totals = payload.get("totals", {})
    required = {
        "src/dmf_pulse/rules/one_gameweek.py": 95,
        "src/dmf_pulse/optimisation/autosub_evaluator.py": 95,
        "src/dmf_pulse/optimisation/legality.py": 95,
        "src/dmf_pulse/optimisation/tactics.py": 95,
        "src/dmf_pulse/optimisation/artifacts.py": 95,
    }
    files = payload.get("files", {})
    critical: dict[str, float | None] = {}
    for relative in required:
        match = next(
            (value for key, value in files.items() if key.endswith(relative.split("/")[-1])),
            None,
        )
        critical[relative] = (
            match.get("summary", {}).get("percent_branches_covered") if match else None
        )
    report = {
        "totals": totals,
        "critical_branch_percent": critical,
        "required_aggregate_percent": 90,
        "required_critical_branch_percent": 95,
        "ok": totals.get("percent_covered", 0) >= 90
        and all(value is not None and value >= 95 for value in critical.values()),
    }
    output = Path("evidence/tickets/OPT-010/coverage_assurance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
