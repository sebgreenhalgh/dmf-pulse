"""Mandatory offline real-corpus model acceptance and safe aggregate report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.football_events.team_strength_model import fit_team_strength
from dmf_pulse.football_events.team_strength_store import persist_team_strength
from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_reconstructed_corpus
from dmf_pulse.ingestion.openfootball.team_strength_data import build_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--private-artifact-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    fixtures, sources = load_reconstructed_corpus(args.corpus_root)
    dataset = build_dataset(
        sources=sources,
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
        information_cutoff=max(source.lineage.usable_at for source in sources),
        training_cutoff=datetime(2026, 6, 1, tzinfo=UTC),
        forecast_season="2025/26",
        mode="RECONSTRUCTED",
    )
    start = perf_counter()
    artifact = fit_team_strength(dataset)
    elapsed = perf_counter() - start
    if elapsed > 60:
        raise ValueError("historical fit exceeds the 60 second acceptance ceiling")
    repeated = fit_team_strength(dataset)
    if repeated.model.semantic_sha256 != artifact.model.semantic_sha256:
        raise ValueError("deterministic semantic model reproduction failed")
    persist_team_strength(artifact, artifact_root=args.private_artifact_root)
    model = artifact.model
    result = {
        "status": "PASS",
        "classification": "RECONSTRUCTED",
        "shadow_only": True,
        "training_cutoff": model.training_cutoff.isoformat(),
        "information_cutoff": model.information_cutoff.isoformat(),
        "model_family": model.model_family,
        "eligible_matches": model.match_count,
        "team_count": len(model.effects),
        "half_life_days": 365,
        "attack_prior_matches": 12,
        "defence_prior_matches": 12,
        "mu": str(model.mu),
        "home_effect": str(model.global_home_effect),
        "attack_range": [
            str(min(row.attack for row in model.effects)),
            str(max(row.attack for row in model.effects)),
        ],
        "defence_range": [
            str(min(row.defence for row in model.effects)),
            str(max(row.defence for row in model.effects)),
        ],
        "cohort_attack_centre": str(model.entrant_cohort.attack_centre),
        "cohort_defence_centre": str(model.entrant_cohort.defence_centre),
        "cohort_entrant_seasons": len(model.entrant_cohort.contributors),
        "penalty_mean": "UNWEIGHTED",
        "kappa_attack": str(model.kappa_attack),
        "kappa_defence": str(model.kappa_defence),
        "weighted_observation_count": str(model.weighted_observation_count),
        "numerics": model.numerics.model_dump(mode="json"),
        "parameter_covariance": model.uncertainty.classification,
        "covariance_elements": len(model.uncertainty.covariance),
        "model_semantic_sha256": model.semantic_sha256,
        "execution_envelope_sha256": artifact.semantic_sha256,
        "dataset_semantic_sha256": dataset.semantic_sha256,
        "fit_seconds": round(elapsed, 6),
        "performance_environment": "Windows CPU, Python 3.13.9, locked uv environment; no NumPy/SciPy",
        "semantic_reproduction": "PASS",
        "network_calls": 0,
        "limitations": list(model.limitations),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(pretty_json(result), encoding="utf-8", newline="\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
