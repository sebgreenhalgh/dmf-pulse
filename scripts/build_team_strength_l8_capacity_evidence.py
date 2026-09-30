"""Authenticate the four L8 offline D7 capacity-oracle reruns."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_team_strength_l7_d7_evidence import _case, _load

from dmf_pulse.assurance.canonical import canonical_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-governed", type=Path, required=True)
    parser.add_argument("--baseline-high", type=Path, required=True)
    parser.add_argument("--shifted-governed", type=Path, required=True)
    parser.add_argument("--shifted-high", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {
        "baseline_governed": args.baseline_governed,
        "baseline_high": args.baseline_high,
        "shifted_governed": args.shifted_governed,
        "shifted_high": args.shifted_high,
    }
    raw = {name: _load(path) for name, path in paths.items()}
    cases = [
        _case(raw["baseline_governed"], raw["baseline_high"], ordering="BASELINE_LIKE"),
        _case(
            raw["shifted_governed"],
            raw["shifted_high"],
            ordering="SHIFTED_SHADOW_LIKE",
        ),
    ]
    accepted = (
        (1_432_370, "3fb1df08c27e063869f8922f71f2634b11c907fa3f8385325835d3f2769403bb"),
        (1_432_641, "f5d4df2085e46bd4d7084e278c157f1ac6ca1a0f3d145226da43d9af968dcda8"),
    )
    for case, (generated, decision_sha) in zip(cases, accepted, strict=True):
        if (
            case["complete_generated_policy_candidates"] != generated
            or case["complete_cumulative_legal_actions"] != 1_432_370
            or case["decision_semantic_sha256"] != decision_sha
            or not case["governed_high_decision_semantics_equal"]
        ):
            raise ValueError("L8 D7 exact capacity or decision oracle differs")
    value: dict[str, object] = {
        "schema_version": "current-team-strength-l8-capacity-oracle-v1",
        "classification": "OFFLINE_REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "immutable_parent": "f4585eee4a3ea492b6a535f33fa13183734ab2ac",
        "private_provider_requests": {"fpl": 0, "odds": 0},
        "policy": {
            "schema_version": "multi-gameweek-search-policy-v2",
            "generated_cap": 2_097_152,
            "retained_pareto_cap": 786_432,
            "legal_action_cap": 2_097_152,
            "high_reference_cap": 10_000_000,
        },
        "input_probe_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
        },
        "cases": cases,
    }
    value["semantic_sha256"] = canonical_sha256(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"semantic_sha256": value["semantic_sha256"], "cases": len(cases)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
