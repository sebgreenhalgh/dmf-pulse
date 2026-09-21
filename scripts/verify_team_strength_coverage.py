"""Enforce >=90% actual branch coverage, not combined line/branch percentage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json

OWNED = (
    "src/dmf_pulse/ingestion/openfootball/team_strength_acquisition.py",
    "src/dmf_pulse/ingestion/openfootball/team_strength_corpus.py",
    "src/dmf_pulse/ingestion/openfootball/team_strength_data.py",
    "src/dmf_pulse/football_events/team_strength_numerics.py",
    "src/dmf_pulse/football_events/team_strength_model.py",
    "src/dmf_pulse/football_events/team_strength_store.py",
    "src/dmf_pulse/football_events/team_strength_adapter.py",
)


def verify(path: Path) -> dict[str, object]:
    report = json.loads(path.read_bytes())
    if report["meta"]["branch_coverage"] is not True:
        raise ValueError("branch instrumentation is required")
    files = {name.replace("\\", "/"): values for name, values in report["files"].items()}
    summaries = {name: files[name]["summary"] for name in OWNED}
    if any(row["excluded_lines"] or row["num_branches"] <= 0 for row in summaries.values()):
        raise ValueError("owned modules must have measured branches and no exclusions")
    covered = sum(row["covered_branches"] for row in summaries.values())
    total = sum(row["num_branches"] for row in summaries.values())
    if covered * 100 < total * 90:
        raise ValueError("team-strength actual branch coverage is below 90%")
    return {
        "status": "PASS",
        "branch_coverage_percent": covered * 100 / total,
        "covered_branches": covered,
        "total_branches": total,
        "excluded_lines": 0,
        "modules": summaries,
        "basis": "ACTUAL_BRANCHES_NOT_COMBINED_LINE_BRANCH_PERCENTAGE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.coverage_json)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(pretty_json(result), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "modules"}, sort_keys=True))


if __name__ == "__main__":
    main()
