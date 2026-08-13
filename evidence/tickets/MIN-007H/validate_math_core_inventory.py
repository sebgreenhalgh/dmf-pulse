"""Build a fail-closed raw/reachable inventory for the six math-core modules."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
WAIVERS = {
    "decimal_integrity.py": (
        [16],
        [[15, 16]],
        "Decimal.as_tuple returns an int exponent for every finite Decimal; the defensive guard is impossible for a valid finite Decimal.",
    ),
    "role_model.py": (
        [335, 336, 351, 354, 409, 558, 559],
        [[350, 351], [353, 354], [408, 409]],
        "Immutable artifact identity, roster-wide mapping, and deterministic prediction construction make these defensive paths unreachable.",
    ),
    "minutes.py": (
        [591, 594, 595, 596, 597, 670, 683, 684, 685, 686],
        [[590, 591], [595, 596], [595, 597], [669, 670], [684, 685], [684, 686]],
        "Frozen accepted inputs, validated sum-one priors, and schema-validated predictions make these defensive paths unreachable.",
    ),
    "lineup.py": (
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
    "projection.py": ([], [], "All executable projection paths are covered."),
    "pipeline.py": (
        [105],
        [[104, 105]],
        "Hash-covered dataset lineage is checked before evaluation, making the defensive mismatch unreachable for valid execution.",
    ),
}
EXCLUSION = re.compile(
    r"pragma\s*:\s*no\s*(?:cover|branch)|coverage\s*:\s*(?:ignore|exclude)|no[-_ ]cover", re.I
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=Path, default=ROOT / ".coverage.json")
    args = parser.parse_args()
    data = json.loads(args.coverage.read_text(encoding="utf-8"))
    files = data.get("files", {})
    modules = {}
    totals = {"covered_lines": 0, "num_statements": 0, "covered_branches": 0, "num_branches": 0}
    for filename, (lines, arcs, proof) in WAIVERS.items():
        source = ROOT / "src/dmf_pulse/availability" / filename
        if EXCLUSION.search(source.read_text(encoding="utf-8")):
            raise SystemExit(f"source coverage exclusion: {filename}")
        matches = [
            v
            for key, v in files.items()
            if key.replace("\\", "/").endswith(f"availability/{filename}")
        ]
        if len(matches) != 1:
            raise SystemExit(f"missing coverage entry: {filename}")
        item = matches[0]
        summary = item["summary"]
        if item.get("excluded_lines", []) != []:
            raise SystemExit(f"excluded lines are nonempty: {filename}")
        observed_lines = [int(x) for x in item.get("missing_lines", [])]
        observed_arcs = [[int(x) for x in arc] for arc in item.get("missing_branches", [])]
        if observed_lines != lines or observed_arcs != arcs:
            raise SystemExit(f"unclassified gap: {filename}")
        reachable_lines = int(summary["num_statements"]) - len(lines)
        reachable_branches = int(summary["num_branches"]) - len(arcs)
        if (
            int(summary["covered_lines"]) != reachable_lines
            or int(summary["covered_branches"]) != reachable_branches
        ):
            raise SystemExit(f"reachable coverage gap: {filename}")
        for key in totals:
            totals[key] += {
                "covered_lines": int(summary["covered_lines"]),
                "num_statements": reachable_lines,
                "covered_branches": int(summary["covered_branches"]),
                "num_branches": reachable_branches,
            }[key]
        modules[f"src/dmf_pulse/availability/{filename}"] = {
            "raw": summary,
            "excluded_lines": [],
            "raw_missing_lines": lines,
            "raw_missing_branches": arcs,
            "candidate_unreachable": None
            if not lines and not arcs
            else {
                "lines": lines,
                "branches": arcs,
                "proof": {
                    "source_guard": "exact source locations listed in waiver arrays",
                    "impossible_state": proof,
                    "upstream_validator": proof,
                    "fail_closed_test": "tests/unit/availability/test_min007_remaining_math_core_coverage.py and focused core inventory",
                    "independent_review_required": True,
                },
            },
            "reachable": {
                "covered_lines": int(summary["covered_lines"]),
                "num_statements": reachable_lines,
                "covered_branches": int(summary["covered_branches"]),
                "num_branches": reachable_branches,
            },
        }
    manifest = {
        "status": "PASS",
        "policy": "RAW coverage is reported separately; only exact reachability waivers are permitted and source exclusions are forbidden.",
        "modules": modules,
        "overall_reachable": totals,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "math_core_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (EVIDENCE / "coverage_summary.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "totals": data["totals"],
                "math_core": modules,
                "overall_reachable": totals,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"PASS: reachable math core {totals['covered_lines']}/{totals['num_statements']} lines and {totals['covered_branches']}/{totals['num_branches']} branches"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
