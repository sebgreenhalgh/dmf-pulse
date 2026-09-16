"""Explicit offline collector: only repository-generated synthetic inputs are accepted."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="Explicit synthetic aggregate report path"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from compare_r9b_decisions import compare_decisions
    from compare_r9b_stage9 import compare_stage9

    from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
    from dmf_pulse.fpl_points.current_player_shadow_diagnostics import safe_shadow_summary
    from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
    from dmf_pulse.rules.compiler import compile_ruleset
    from tests.support.factories import reference_engine
    from tests.unit.fpl_points.current_shadow_support import (
        synthetic_decision_inputs,
        synthetic_inputs,
        synthetic_stage9_request,
    )

    inputs = synthetic_inputs(root, count=659)
    compile_current_player_shadow(**inputs)  # Warm-up: excluded from timing.
    samples = []
    for _ in range(3):
        started = perf_counter()
        shadow = compile_current_player_shadow(**inputs)
        samples.append(perf_counter() - started)
    summary = safe_shadow_summary(shadow, inputs["history"])
    fixture_inputs = synthetic_inputs(root, count=120)
    fixture_shadow = compile_current_player_shadow(**fixture_inputs)
    request = synthetic_stage9_request(fixture_shadow, scenario_count=256)
    paired = compare_stage9(
        request,
        fixture_shadow.worlds[0],
        reference_engine(),
        frozen_squad=tuple(p.player_id for p in request.allocation_profiles[:15]),
    )
    requests, squads = synthetic_decision_inputs(fixture_shadow, scenario_count=16)
    rules = compile_ruleset(root / "config/rules/fpl-2026-27")
    decision = compare_decisions(
        requests,
        fixture_shadow.worlds[0],
        AcceptedRulesAdapter(rules),
        rules,
        squads,
    )
    report = {
        "classification": "REPOSITORY_OWNED_SYNTHETIC_ONLY_NOT_A_LIVE_OBSERVATION",
        "compiler_seconds": {
            "samples": samples,
            "median": median(samples),
            "warmup_excluded": True,
            "resource_loaded_before_timing": True,
        },
        "summary": summary,
        "stage9_paired_ablation": paired,
        "stage10_decision_sensitivity": decision,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(args.output),
                "compiler_median_seconds": median(samples),
                "current_players": summary["current_player_count"],
                "individual": summary["individual_prior_count"],
                "fallback": summary["fallback_prior_count"],
                "stage9": paired["variants"],
                "decision": decision,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
