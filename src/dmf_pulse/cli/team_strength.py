"""Explicit offline public-core research surfaces; no private recommendation hook."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from dmf_pulse.evaluation.team_strength_replay import run_reconstructed_replay
from dmf_pulse.football_events.team_strength_model import fit_team_strength
from dmf_pulse.football_events.team_strength_numerics import StrengthFitError
from dmf_pulse.football_events.team_strength_store import persist_team_strength
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_reconstructed_corpus
from dmf_pulse.ingestion.openfootball.team_strength_data import build_dataset

team_strength_app = typer.Typer(
    help="Offline reconstructed team-strength research; shadow only, never ordinary recommendations."
)


def _emit(operation: Callable[[], dict[str, Any]]) -> None:
    try:
        result = operation()
    except StrengthFitError as exc:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "SHADOW_FIT_FAILED",
                        "message": "Shadow numerical fit failed; no current prior is activated",
                    }
                }
            )
        )
        raise typer.Exit(2) from exc
    except (ValueError, OSError, IngestionError) as exc:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "SHADOW_EVIDENCE_INVALID",
                        "message": "Shadow source, policy or output request is invalid",
                    }
                }
            )
        )
        raise typer.Exit(2) from exc
    except Exception as exc:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "SHADOW_OPERATION_FAILED",
                        "message": "Shadow operation failed safely",
                    }
                }
            )
        )
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, allow_nan=False, sort_keys=True))


@team_strength_app.command("fit-reconstructed")
def fit_reconstructed(
    corpus_root: Annotated[
        Path,
        typer.Option("--corpus-root", help="Explicit private retained immutable corpus directory."),
    ],
    private_artifact_root: Annotated[
        Path,
        typer.Option(
            "--private-artifact-root", help="Explicit private immutable model output directory."
        ),
    ],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Fit the fixed historical corpus through 2025/26; not a current/live refit."""

    def operation() -> dict[str, Any]:
        if output != "json":
            raise ValueError("only safe JSON summaries are supported")
        fixtures, sources = load_reconstructed_corpus(corpus_root)
        dataset = build_dataset(
            sources=sources,
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
            information_cutoff=max(source.lineage.usable_at for source in sources),
            training_cutoff=datetime(2026, 6, 1, tzinfo=UTC),
            forecast_season="2025/26",
            mode="RECONSTRUCTED",
        )
        artifact = fit_team_strength(dataset)
        persist_team_strength(artifact, artifact_root=private_artifact_root)
        model = artifact.model
        return {
            "status": model.status,
            "dataset_mode": model.dataset_mode,
            "source_commit": sources[0].lineage.resource.commit,
            "eligible_matches": model.match_count,
            "fitted_teams": len(model.effects),
            "freshness_at_information_cutoff": model.freshness,
            "information_cutoff": model.information_cutoff.isoformat(),
            "training_cutoff": model.training_cutoff.isoformat(),
            "fitted_at": artifact.fitted_at.isoformat(),
            "usable_at": artifact.usable_at.isoformat(),
            "model_family": model.model_family,
            "convergence": model.numerics.convergence,
            "iterations": model.numerics.iterations,
            "gradient_infinity": str(model.numerics.gradient_infinity),
            "mu": str(model.mu),
            "global_home_effect": str(model.global_home_effect),
            "attack_range": [
                str(min(row.attack for row in model.effects)),
                str(max(row.attack for row in model.effects)),
            ],
            "defence_range": [
                str(min(row.defence for row in model.effects)),
                str(max(row.defence for row in model.effects)),
            ],
            "model_semantic_sha256": model.semantic_sha256,
            "execution_envelope_sha256": artifact.semantic_sha256,
            "dataset_semantic_sha256": dataset.semantic_sha256,
            "rights_profile": model.sources[0].rights_profile_id,
            "identity_registry_sha256": model.identity_registry_sha256,
            "parameter_covariance": model.uncertainty.classification,
            "limitations": model.limitations,
            "production_active": False,
            "current_live_refit_claimed": False,
        }

    _emit(operation)


@team_strength_app.command("replay")
def replay_command(
    corpus_root: Annotated[
        Path,
        typer.Option("--corpus-root", help="Explicit private retained immutable corpus directory."),
    ],
    private_artifact_root: Annotated[
        Path,
        typer.Option(
            "--private-artifact-root", help="Private output for the 38 governed model artifacts."
        ),
    ],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Reproduce fixed 2025/26 OOT evidence; no policy search or live-data access."""

    def operation() -> dict[str, Any]:
        if output != "json":
            raise ValueError("only safe JSON summaries are supported")
        report = run_reconstructed_replay(corpus_root, private_artifact_root=private_artifact_root)
        return {
            "status": "SHADOW_NOT_MODEL_INPUT",
            "classification": report.classification,
            "holdout": report.holdout,
            "fixtures": 380,
            "forecast_origins": 38,
            "baseline_seasons": report.baseline_seasons,
            "baseline": report.baseline.model_dump(mode="json"),
            "research_reproduction": report.research_reproduction.metrics.model_dump(mode="json"),
            "research_delta": str(
                report.research_reproduction.candidate_minus_baseline_exact_log_loss
            ),
            "governed_d_plus_2": report.governed_d_plus_2.metrics.model_dump(mode="json"),
            "governed_delta": str(report.governed_d_plus_2.candidate_minus_baseline_exact_log_loss),
            "differing_training_origins": report.differing_training_origins,
            "replay_semantic_sha256": report.semantic_sha256,
            "production_active": False,
            "historical_live_availability_claimed": False,
            "current_2026_27_used_for_selection": False,
            "parameter_mixture_active": False,
            "uncertainty_ticket_required": "CURRENT-TEAM-STRENGTH-001U",
        }

    _emit(operation)
