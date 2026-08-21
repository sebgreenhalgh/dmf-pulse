"""Build synthetic-only Stage-8 market-dominance diagnostics for GW1 review."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dmf_pulse.football_events._decimal import canonical_json_sha256
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.football_events.support_prior import (
    calibrate_openfootball_support_prior,
    diagnose_market_dominance,
    validate_candidate_artifact,
)

AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _constraint(
    *,
    constraint_id: str,
    event: ScoreEvent,
    family: MarketFamily,
    target: str,
    line: str | None = None,
) -> MarketConstraint:
    body: dict[str, object] = {
        "confidence_grade": "B",
        "constraint_id": constraint_id,
        "event": event,
        "family": family,
        "target_probability": Decimal(target),
        "uncertainty": Decimal("0.050000000000"),
        "usable_at": AS_OF,
        "weight": Decimal("0.750000000000"),
    }
    if line is not None:
        body["line"] = Decimal(line)
    return MarketConstraint.model_validate(body)


def _synthetic_constraints() -> tuple[
    MarketConstraintSet, MarketConstraintSet, MarketConstraintSet
]:
    h2h = MarketConstraintSet.model_validate(
        {
            "as_of": AS_OF,
            "constraints": (
                _constraint(
                    constraint_id="synthetic-home",
                    event=ScoreEvent.HOME_WIN,
                    family=MarketFamily.ONE_X_TWO,
                    target="0.460000000000",
                ),
                _constraint(
                    constraint_id="synthetic-draw",
                    event=ScoreEvent.DRAW,
                    family=MarketFamily.ONE_X_TWO,
                    target="0.280000000000",
                ),
                _constraint(
                    constraint_id="synthetic-away",
                    event=ScoreEvent.AWAY_WIN,
                    family=MarketFamily.ONE_X_TWO,
                    target="0.260000000000",
                ),
            ),
        }
    )
    totals = (
        _constraint(
            constraint_id="synthetic-over-2.5",
            event=ScoreEvent.TOTAL_OVER,
            family=MarketFamily.TOTALS,
            target="0.600000000000",
            line="2.5",
        ),
        _constraint(
            constraint_id="synthetic-under-2.5",
            event=ScoreEvent.TOTAL_UNDER,
            family=MarketFamily.TOTALS,
            target="0.400000000000",
            line="2.5",
        ),
    )
    complete = MarketConstraintSet.model_validate(
        {"as_of": AS_OF, "constraints": (*h2h.constraints, *totals)}
    )
    no_market = MarketConstraintSet.model_validate({"as_of": AS_OF, "constraints": ()})
    return complete, h2h, no_market


def _write_content_addressed(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        raise FileExistsError(f"refusing to overwrite different diagnostics: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidate-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = json.loads(args.candidate_artifact.read_text(encoding="utf-8"))
        validate_candidate_artifact(artifact)
        calibration = calibrate_openfootball_support_prior(args.source_root)
        if calibration.dataset_sha256 != artifact["dataset_sha256"]:
            raise ValueError("candidate artifact dataset hash does not match local pinned source")
        complete, h2h_only, no_market = _synthetic_constraints()
        report: dict[str, Any] = {
            "candidate_artifact_sha256": artifact["artifact_sha256"],
            "diagnostic_input": "SYNTHETIC_STAGE8_H2H_AND_TOTALS_V1",
            "report": diagnose_market_dominance(
                calibration,
                complete_constraints=complete,
                h2h_only_constraints=h2h_only,
                no_market_constraints=no_market,
                policy=load_score_baseline_policy(),
            ),
            "schema_version": "gw1-support-prior-market-diagnostics-v1",
        }
        report["result_sha256"] = canonical_json_sha256(report)
        content = (
            json.dumps(report, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        _write_content_addressed(args.output, content)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"GW1 support-prior diagnostics blocked: {exc}", file=sys.stderr)
        return 2
    print(report["result_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
