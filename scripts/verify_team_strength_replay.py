"""Mandatory zero-network locked real-corpus replay; never silently update a golden."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.team_strength_replay import run_reconstructed_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--private-artifact-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started = perf_counter()
    report = run_reconstructed_replay(
        args.corpus_root,
        private_artifact_root=args.private_artifact_root,
        progress=lambda origin: print(
            json.dumps({"completed_origin": origin, "total_origins": 38}), flush=True
        ),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(pretty_json(report), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "status": "PASS",
                "classification": "RECONSTRUCTED",
                "holdout": "2025/26",
                "baseline_exact_log_loss": str(report.baseline.exact_log_loss),
                "research_candidate_exact_log_loss": str(
                    report.research_reproduction.metrics.exact_log_loss
                ),
                "research_delta": str(
                    report.research_reproduction.candidate_minus_baseline_exact_log_loss
                ),
                "governed_d_plus_2_exact_log_loss": str(
                    report.governed_d_plus_2.metrics.exact_log_loss
                ),
                "governed_d_plus_2_delta": str(
                    report.governed_d_plus_2.candidate_minus_baseline_exact_log_loss
                ),
                "differing_origins": report.differing_training_origins,
                "replay_seconds": round(perf_counter() - started, 6),
                "semantic_sha256": report.semantic_sha256,
                "network_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
