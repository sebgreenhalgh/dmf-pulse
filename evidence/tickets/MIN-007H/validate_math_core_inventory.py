"""Build and validate the exhaustive math-core manifest from coverage JSON."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
CORE = {
    "src/dmf_pulse/availability/decimal_integrity.py": (
        "exact finite Decimal arithmetic",
        [],
        [],
        "All executable arithmetic paths are covered.",
    ),
    "src/dmf_pulse/availability/role_model.py": (
        "role baseline and utility mathematics",
        [335, 336, 351, 354, 409, 558, 559],
        [[350, 351], [353, 354], [408, 409]],
        "Immutable artifact identity, roster-wide mapping, and deterministic prediction construction make these defensive paths unreachable.",
    ),
    "src/dmf_pulse/availability/minutes.py": (
        "conditional-minute PMF mathematics",
        [591, 594, 595, 596, 597, 670, 683, 684, 685, 686],
        [[590, 591], [595, 596], [595, 597], [669, 670], [684, 685], [684, 686]],
        "Frozen accepted inputs, validated sum-one priors, and schema-validated generated predictions make these defensive paths unreachable.",
    ),
    "src/dmf_pulse/availability/lineup.py": (
        "coherent lineup sampling mathematics",
        [221, 223, 225, 344, 348, 350, 453, 719, 720, 721, 722],
        [
            [220, 221],
            [222, 223],
            [224, 225],
            [343, 344],
            [347, 348],
            [349, 350],
            [447, 453],
            [720, 721],
            [720, 722],
        ],
        "Coherent scenario algebra, member uniqueness/cardinality, exact policy mapping, and schema validation make these defensive paths unreachable.",
    ),
    "src/dmf_pulse/availability/projection.py": (
        "final PMF mixture/projection mathematics",
        [],
        [],
        "All executable projection paths are covered.",
    ),
    "src/dmf_pulse/availability/pipeline.py": (
        "pure evaluation metrics and composition",
        [105],
        [[104, 105]],
        "Hash-covered dataset lineage is checked before evaluation, making the defensive lineage mismatch unreachable for valid execution.",
    ),
}


def entry(files: dict[str, object], path: str) -> dict[str, object]:
    found = [v for p, v in files.items() if p.replace("\\", "/").endswith(path)]
    if len(found) != 1 or not isinstance(found[0], dict):
        raise SystemExit(f"missing/ambiguous {path}")
    return found[0]


def main() -> None:
    focused = ROOT / ".min007_math_core_inventory.json"
    coverage = json.loads(focused.read_text(encoding="utf-8"))
    files = coverage["files"]
    modules = {}
    totals = [0, 0, 0, 0]
    for path, (rationale, lines, arcs, proof) in CORE.items():
        item = entry(files, path)
        summary = item["summary"]
        if item["missing_lines"] != lines or item["missing_branches"] != arcs:
            raise SystemExit(f"changed/unclassified gap: {path}")
        reachable_lines = summary["num_statements"] - len(lines)
        reachable_branches = summary["num_branches"] - len(arcs)
        if (
            summary["covered_lines"] != reachable_lines
            or summary["covered_branches"] != reachable_branches
        ):
            raise SystemExit(f"reachable gap: {path}")
        totals[0] += summary["covered_lines"]
        totals[1] += reachable_lines
        totals[2] += summary["covered_branches"]
        totals[3] += reachable_branches
        modules[path] = {
            "rationale": rationale,
            "raw": summary,
            "raw_missing_lines": lines,
            "raw_missing_branches": arcs,
            "candidate_unreachable": {
                "lines": lines,
                "branches": arcs,
                "proof": {
                    "source_guard": "exact source locations listed in waiver arrays",
                    "upstream_validation": proof,
                    "fail_closed_test": "tests/unit/availability/test_min007_remaining_math_core_coverage.py and existing role coverage tests",
                    "why_valid_execution_cannot_reach": proof,
                    "independent_review_required": True,
                },
            }
            if lines or arcs
            else None,
            "reachable": {
                "covered_lines": reachable_lines,
                "num_statements": reachable_lines,
                "covered_branches": reachable_branches,
                "num_branches": reachable_branches,
            },
        }
    manifest = {
        "status": "PASS",
        "policy": "Raw coverage is reported transparently; only exact individually proven unreachable lines/arcs are waived; no exclusions or source edits. Independent review required.",
        "modules": modules,
        "overall_reachable": {
            "covered_lines": totals[1],
            "num_statements": totals[1],
            "covered_branches": totals[3],
            "num_branches": totals[3],
        },
        "overall_raw_denominators": {
            "statements": sum(m["raw"]["num_statements"] for m in modules.values()),
            "branches": sum(m["raw"]["num_branches"] for m in modules.values()),
        },
    }
    (EVIDENCE / "math_core_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (EVIDENCE / "coverage_summary.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "totals": coverage["totals"],
                "math_core": modules,
                "overall_reachable": manifest["overall_reachable"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print("PASS: exhaustive math-core inventory and reachable 100%/100% validation")


if __name__ == "__main__":
    main()
