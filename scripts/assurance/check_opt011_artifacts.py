"""Static artifact, fixture and dependency assurance for OPT-011."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_CASES = {
    "simple_one_ft",
    "roll_ft",
    "rational_hit",
    "retained_selling_profit",
    "price_fall",
    "repurchase_resets_cohort",
    "funding_transfer_bundle",
    "price_change_blocks_later_route",
    "injury_revealed_after_current_decision",
    "postponed_reassigned_fixture",
    "horizon_reversal",
    "futures_identical_until_revelation",
    "clairvoyance_trap",
    "terminal_value_reversal",
    "tied_plans",
    "malformed_scenario_probabilities_tree",
    "illegal_manager_state",
    "infeasible_future_state",
    "resource_limit_incumbent",
    "no_materially_distinct_alternative",
}


def main() -> int:
    root = Path.cwd()
    config_pairs = (
        (
            root / "config/optimisation/multi_gameweek.yaml",
            root / "src/dmf_pulse/optimisation/resources/multi_gameweek.yaml",
        ),
        (
            root / "config/optimisation/multi_gameweek_terminal.yaml",
            root / "src/dmf_pulse/optimisation/resources/multi_gameweek_terminal.yaml",
        ),
    )
    byte_identical = all(left.read_bytes() == right.read_bytes() for left, right in config_pairs)
    fixture_root = root / "fixtures/optimisation/multi_gameweek/adversarial"
    actual_cases = {path.stem for path in fixture_root.glob("*.json")} - {"expected_summaries"}
    summaries = json.loads((fixture_root / "expected_summaries.json").read_text(encoding="utf-8"))
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in sorted((root / "src/dmf_pulse/optimisation").glob("multi_gameweek*.py"))
    )
    forbidden_runtime_solver_tokens = tuple(
        token
        for token in ("import pyomo", "import highspy", "import pulp", "import scipy")
        if token in source_text.lower()
    )
    production_fail_closed = "MULTI_GAMEWEEK_PRODUCTION_BACKEND_UNAVAILABLE" in source_text
    report = {
        "schema_version": "opt-011-artifact-assurance-v1",
        "config_resources_byte_identical": byte_identical,
        "expected_fixture_cases": sorted(EXPECTED_CASES),
        "actual_fixture_cases": sorted(actual_cases),
        "fixture_case_set_exact": actual_cases == EXPECTED_CASES,
        "frozen_summary_case_set_exact": set(summaries) == EXPECTED_CASES,
        "forbidden_runtime_solver_tokens": list(forbidden_runtime_solver_tokens),
        "production_fail_closed": production_fail_closed,
    }
    report["ok"] = all(
        (
            byte_identical,
            actual_cases == EXPECTED_CASES,
            set(summaries) == EXPECTED_CASES,
            not forbidden_runtime_solver_tokens,
            production_fail_closed,
        )
    )
    output = root / "evidence/tickets/OPT-011/artifact_assurance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
