"""Offline private-fixture adapter authentication and cold-cache CPU benchmark."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from time import perf_counter

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.football_events.team_strength_adapter import (
    _validated_artifact_json,
    authenticate_fixture_bundle,
    fixture_prior_bundle,
    fixture_rate_uncertainty,
)
from dmf_pulse.football_events.team_strength_store import load_team_strength
from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_fixture_registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--private-artifact-root", type=Path, required=True)
    parser.add_argument("--model-summary", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads(args.model_summary.read_bytes())
    state_hash = metadata["model_semantic_sha256"]
    envelope_hash = metadata["execution_envelope_sha256"]
    # Only validated digest strings can select content-addressed filenames.
    if any(
        len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
        for value in (state_hash, envelope_hash)
    ):
        raise ValueError("invalid model summary identity")
    artifact = load_team_strength(
        args.private_artifact_root / "team-strength-shadow" / state_hash / f"{envelope_hash}.json",
        expected_artifact_sha256=envelope_hash,
    )
    fixtures = load_fixture_registry(args.corpus_root)
    if fixtures.semantic_sha256 != artifact.model.fixture_registry_sha256:
        raise ValueError("fixture registry differs from model")
    matches = tuple(
        row for row in fixtures.fixtures if row.season == artifact.model.forecast_season
    )[:30]
    as_of = artifact.usable_at + timedelta(microseconds=1)
    _validated_artifact_json.cache_clear()
    start = perf_counter()
    bundles = tuple(
        fixture_prior_bundle(
            artifact=artifact, fixture=match, as_of=as_of, expected_artifact_sha256=envelope_hash
        )
        for match in matches
    )
    elapsed = perf_counter() - start
    if len(bundles) != 30 or elapsed >= 0.1:
        raise ValueError("30 cold-cache fixture requests exceeded 100ms or were incomplete")
    for bundle in bundles:
        authenticate_fixture_bundle(
            bundle, artifact=artifact, expected_artifact_sha256=envelope_hash
        )
    diagnostic = fixture_rate_uncertainty(
        artifact=artifact, fixture=matches[0], as_of=as_of, expected_artifact_sha256=envelope_hash
    )
    result = {
        "status": "PASS",
        "model_semantic_sha256": state_hash,
        "fixture_count": 30,
        "cold_cache_inference_milliseconds": round(elapsed * 1000, 6),
        "benchmark_scope": "30 full adapter calls including cold artifact authentication; excludes loading/network/Stage8",
        "bundle_sha256s": [bundle.semantic_sha256 for bundle in bundles],
        "all_rates_in_open_zero_closed_eight": True,
        "rounding": "SIX_PLACE_ROUND_HALF_EVEN",
        "uncertainty_classification": diagnostic.classification,
        "parameter_mixture_active": False,
        "score_prior_request_changed": False,
        "network_calls": 0,
        "shadow_only": True,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(pretty_json(result), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "bundle_sha256s"}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
