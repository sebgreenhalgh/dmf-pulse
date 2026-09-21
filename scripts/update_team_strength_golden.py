"""Explicit reviewed golden update only; ordinary tests never call this script."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.team_strength_replay import (
    TeamStrengthReplayReportV1,
    verify_research_reproduction,
)
from dmf_pulse.ingestion.openfootball.team_strength_corpus import FIXTURE_REGISTRY_SHA256
from dmf_pulse.ingestion.openfootball.team_strength_governance import load_historical_team_identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-report", type=Path, required=True)
    parser.add_argument("--confirm-fixed-policy-golden-update", action="store_true", required=True)
    args = parser.parse_args()
    report = TeamStrengthReplayReportV1.model_validate_json(args.replay_report.read_bytes())
    verify_research_reproduction(report)
    expected = {
        row.path: (row.commit_sha, row.content_sha256)
        for row in load_historical_team_identity().source_snapshots
        if row.season_code <= "2025/26"
    }
    actual = {row.path: (row.commit, row.content_sha256) for row in report.source_resources}
    if expected != actual or report.fixture_registry_sha256 != FIXTURE_REGISTRY_SHA256:
        raise ValueError("golden source identities differ from the approved retained corpus")
    destination = (
        Path(__file__).resolve().parents[1]
        / "src/dmf_pulse/evaluation/resources/team_strength_golden.json"
    )
    destination.write_text(pretty_json(report), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "status": "GOLDEN_WRITTEN_REQUIRES_DIFF_REVIEW",
                "semantic_sha256": report.semantic_sha256,
                "note": "Trusted loader identity is never updated automatically",
            }
        )
    )


if __name__ == "__main__":
    main()
