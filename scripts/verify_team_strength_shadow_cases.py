"""Explicit offline evidence run of the five locked real-pipeline 001P cases.

This never updates test expectations. Generated one-draw scenarios demonstrate
decision/control behavior, not live calibration or prospective model value.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dmf_pulse.private_v1.team_strength_comparison import (  # noqa: E402
    TeamStrengthComparisonRun,
    run_team_strength_shadow_comparison,
    safe_team_strength_summary,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import (  # noqa: E402
    prepare_team_strength_shadow,
)
from tests.unit.private_v1.team_strength_case_support import (  # noqa: E402
    CASES,
    assert_case,
    case_prepared,
)
from tests.unit.private_v1.team_strength_shadow_support import (  # noqa: E402
    synthetic_model_prepared,
    synthetic_strength,
)


def blocked(*args, **kwargs):
    raise AssertionError("001P acceptance evidence must remain offline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    socket.getaddrinfo = blocked
    socket.create_connection = blocked
    socket.socket.connect = blocked
    reports = []
    with tempfile.TemporaryDirectory(prefix="dmf-001p-fixed-cases-") as temporary:
        started = perf_counter()
        prepared = synthetic_model_prepared(ROOT, Path(temporary))
        preparation_ms = Decimal(str((perf_counter() - started) * 1000))
        for case in CASES:
            frozen = case_prepared(prepared, case)
            dataset, artifact = synthetic_strength(case.source_variant)
            preparation = prepare_team_strength_shadow(
                frozen.rolling_execution,
                artifact=artifact,
                expected_artifact_sha256=artifact.semantic_sha256,
                fixture_registry=dataset.fixture_registry,
            )
            result = run_team_strength_shadow_comparison(
                frozen, preparation, preparation_ms=preparation_ms
            )
            assert isinstance(result, TeamStrengthComparisonRun)
            assert_case(case, result.comparison)
            reports.append(
                {
                    "case": case.name,
                    "source_variant": case.source_variant,
                    "root_seed": case.seed,
                    "candidate_screen_enabled": case.screen,
                    "summary": safe_team_strength_summary(result),
                    "fixture_proof": [
                        row.model_dump(mode="json") for row in result.comparison.fixtures
                    ],
                    "world_proof": [
                        row.model_dump(mode="json") for row in result.comparison.worlds
                    ],
                }
            )
            print(json.dumps({"case": case.name, "status": "PASS"}), flush=True)
    report = {
        "status": "PASS",
        "classification": "SYNTHETIC_RECONSTRUCTED_OFFLINE",
        "limitations": "ONE_DRAW_CONTROL_AND_DECISION_CASES_NOT_LIVE_CALIBRATION",
        "expectations_updated": False,
        "provider_calls": 0,
        "private_live_data_persisted": False,
        "production_activation": False,
        "cases": reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
