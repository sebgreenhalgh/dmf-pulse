"""Reviewed one-attempt P01 public fallback execution; no model-building path."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json, sha256_file
from dmf_pulse.evaluation.p01_fallback import fallback_scorecard, score_p01_fallback
from dmf_pulse.evaluation.p01_fallback_context import authenticate_p01, load_context
from dmf_pulse.evaluation.p01_fallback_store import persist_fallback
from dmf_pulse.ingestion.p01_fallback_acquisition import acquire_p01_once


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.artifact_root.resolve()
    context = load_context()
    before = sha256_file(args.forecast)
    # This authenticates the immutable forecast before any transport; acquisition
    # independently repeats the check immediately before its one-attempt marker.
    forecast = authenticate_p01(args.forecast)
    started = datetime.now(UTC)
    try:
        labels = acquire_p01_once(
            forecast_path=args.forecast,
            review_path=args.review,
            expected_review_sha256=args.review_sha256,
            implementation_root=Path(__file__).resolve().parents[1],
            artifact_root=root,
        )
    except (ValueError, OSError) as exc:
        after = authenticate_p01(args.forecast)
        known = {
            "P01_OPENLIGADB_OUTCOMES_INCOMPLETE",
            "P01_D_PLUS_2_NOT_COMPLETE",
            "OPENLIGADB_RIGHTS_IDENTITY_MISMATCH",
            "P01_SOURCE_POLICY_LOCKED_ONE_ATTEMPT_CONSUMED",
        }
        status = str(exc) if str(exc) in known else "P01_OUTCOME_ADMISSION_FAILED_CLOSED"
        stopped = {
            "schema_version": "public-team-strength-p01-a02-stopped-execution-v1",
            "status": status,
            "context_sha256": context.semantic_sha256,
            "independent_review_sha256": args.review_sha256,
            "started_at": started.isoformat(),
            "stopped_at": datetime.now(UTC).isoformat(),
            "forecast_sha256_before": forecast.semantic_sha256,
            "forecast_sha256_after": after.semantic_sha256,
            "forecast_byte_sha256_before": before,
            "forecast_byte_sha256_after": sha256_file(args.forecast),
            "scoring_performed": False,
            "production_active": False,
            "no_retry_or_source_switch": True,
        }
        write_handoff(stopped, root=root)
        return 2
    score = score_p01_fallback(forecast, outcomes=labels, as_of=datetime.now(UTC))
    score_path = persist_fallback(score, artifact_root=root)
    report = fallback_scorecard(score, outcomes=labels)
    report_path = persist_fallback(report, artifact_root=root)
    after = authenticate_p01(args.forecast)
    handoff = {
        "schema_version": "public-team-strength-p01-a02-execution-handoff-v1",
        "context_sha256": context.semantic_sha256,
        "provenance": "PUBLIC_FALLBACK_OUTCOME_SOURCE",
        "classification": "DESCRIPTIVE_P01_PILOT",
        "independent_review_sha256": args.review_sha256,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "forecast_semantic_sha256_before": forecast.semantic_sha256,
        "forecast_semantic_sha256_after": after.semantic_sha256,
        "forecast_byte_sha256_before": before,
        "forecast_byte_sha256_after": sha256_file(args.forecast),
        "outcome_artifact_sha256": labels.semantic_sha256,
        "score_sha256": score.semantic_sha256,
        "scorecard_sha256": report.semantic_sha256,
        "score_path": str(score_path),
        "scorecard_path": str(report_path),
        "one_attempt_marker_byte_sha256": sha256_file(root / "OPENLIGADB-P01-ONE-ATTEMPT.json"),
        "fixture_count": len(labels.outcomes),
        "private_provider_access_performed": False,
        "official_premier_league_used": False,
        "production_active": False,
        "promotion_performed": False,
        "tuning_performed": False,
        "reconciliation_status": "OPENFOOTBALL_RECONCILIATION_PENDING",
    }
    write_handoff(handoff, root=root)
    return 0


def write_handoff(handoff: dict[str, object], *, root: Path) -> None:
    handoff["semantic_sha256"] = canonical_sha256(handoff)
    destination = root / "execution-handoffs" / f"{handoff['semantic_sha256']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(pretty_json(handoff))
    print(pretty_json(handoff), end="")


if __name__ == "__main__":
    sys.exit(main())
