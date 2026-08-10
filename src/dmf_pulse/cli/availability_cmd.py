"""Offline TEST/REPLAY CLI for the MIN-007G availability pipeline."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import Engine

from dmf_pulse.availability.dataset import semantic_dataset_hash
from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_model_evaluation,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.availability.pipeline import (
    evaluate_minutes_baseline,
    fit_projection_artifact,
    predict_minutes_baseline,
)
from dmf_pulse.availability.registry import (
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
)
from dmf_pulse.availability.role_model import FROZEN_POLICY_SHA256
from dmf_pulse.database.engine import (
    create_database_engine,
    resolve_test_database_url,
    session_factory,
)
from dmf_pulse.database.models import DatabaseSettings

availability_app = typer.Typer(help="Run the deterministic TEST/REPLAY availability pipeline.")
dataset_app = typer.Typer(help="Build synthetic availability datasets.")
availability_app.add_typer(dataset_app, name="dataset")
BLOCKED_EXIT = 42


def _root() -> Path:
    # Source-tree execution is the canonical repository command boundary.  The
    # package remains import-safe because fixture reads occur only inside commands.
    return Path(__file__).resolve().parents[3]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"fixture {path.name} must contain an object")
    return value


def _fixtures() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _root()
    history = _read_json(root / "fixtures/availability/MIN-007/canonical_history.json")
    policy = _read_json(root / "fixtures/availability/MIN-007G/minutes_baseline_policy.json")
    evaluation = _read_json(root / "fixtures/availability/MIN-007G/evaluation_dataset.json")
    return history, policy, evaluation


def _training(history: Mapping[str, Any]) -> dict[str, Any]:
    root = _root()
    path = root / "fixtures/availability/MIN-007/training_dataset.json"
    return _read_json(path)


def _dataset_payload(
    dataset_key: str,
    competition_code: str,
    season_code: str,
    cutoff: str,
    training: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "minutes-dataset-version-v1",
        "dataset_key": dataset_key,
        "competition_code": competition_code,
        "season_code": season_code,
        "training_cutoff": cutoff,
        "dataset_sha256": semantic_dataset_hash(training),
        "policy_sha256": FROZEN_POLICY_SHA256,
        "training_example_count": len(training.get("rows", ())),
    }


def _database() -> tuple[Engine, Any] | None:
    if os.environ.get("DMF_ENVIRONMENT", "").upper() != "TEST":
        return None
    try:
        url = resolve_test_database_url(environment="TEST")
    except Exception:
        return None
    engine = create_database_engine(
        url,
        DatabaseSettings(
            url_secret_ref="env:DMF_TEST_DATABASE_URL",
            connect_timeout_seconds=5,
            application_name="dmf-pulse-min007g",
        ),
    )
    return engine, session_factory(engine)


def _emit(value: object) -> None:
    data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    typer.echo(json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True))


def _guard_environment() -> None:
    environment = os.environ.get("DMF_ENVIRONMENT", "").upper()
    if environment not in {"TEST", "REPLAY"}:
        raise typer.BadParameter(
            "MIN-007G synthetic fixtures require DMF_ENVIRONMENT TEST or REPLAY"
        )


@dataset_app.command("build")
def dataset_build_command(
    dataset_key: Annotated[str, typer.Option("--dataset-key")],
    competition_code: Annotated[str, typer.Option("--competition-code")],
    season_code: Annotated[str, typer.Option("--season-code")],
    training_cutoff: Annotated[str, typer.Option("--training-cutoff")],
    output: Annotated[str, typer.Option("--output")] = "human",
) -> None:
    """Build and register the frozen synthetic TRAIN dataset."""

    _guard_environment()
    history, policy, _ = _fixtures()
    training = _training(history)
    payload = _dataset_payload(
        dataset_key, competition_code, season_code, training_cutoff, training, policy
    )
    runtime = _database()
    if runtime is not None:
        engine, factory = runtime
        try:
            with factory.begin() as session:
                register_dataset_version(
                    session, payload, training_examples=training.get("rows", ())
                )
        finally:
            engine.dispose()
    _emit(payload)


@availability_app.command("fit")
def fit_command(
    dataset_key: Annotated[str, typer.Option("--dataset-key")],
    model_key: Annotated[str, typer.Option("--model-key")],
    output: Annotated[str, typer.Option("--output")] = "human",
) -> None:
    """Fit and register the frozen compatibility model artifact."""

    _guard_environment()
    history, policy, _ = _fixtures()
    training = _training(history)
    artifact = fit_projection_artifact(training, policy=policy)
    payload = {
        "schema_version": "minutes-dataset-version-v1",
        "dataset_key": dataset_key,
        "competition_code": "SYNTH_EPL",
        "season_code": "2026/27",
        "training_cutoff": "2026-06-08T17:00:00Z",
        "dataset_sha256": artifact.dataset_sha256,
        "policy_sha256": policy.get(
            "policy_sha256", "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994"
        ),
        "training_example_count": artifact.training_example_count,
    }
    model = {
        "schema_version": "minutes-model-version-v1",
        "model_key": model_key,
        "dataset_version_sha256": dataset_version_semantic_sha256(payload),
        "role_artifact_sha256": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
        "minute_artifact_sha256": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
        "policy_sha256": payload["policy_sha256"],
        "model_family": artifact.model_family,
        "code_identity": "MIN-007G",
    }
    runtime = _database()
    if runtime is not None:
        engine, factory = runtime
        try:
            with factory.begin() as session:
                register_dataset_version(
                    session, payload, training_examples=training.get("rows", ())
                )
                register_model_version(session, model, artifact=artifact.model_dump(mode="json"))
        finally:
            engine.dispose()
    _emit(artifact)


@availability_app.command("evaluate")
def evaluate_command(
    model_key: Annotated[str, typer.Option("--model-key")],
    evaluation_key: Annotated[str, typer.Option("--evaluation-key")],
    output: Annotated[str, typer.Option("--output")] = "human",
) -> None:
    """Evaluate the frozen 92-row synthetic EVAL dataset."""

    _guard_environment()
    history, policy, evaluation = _fixtures()
    training = _training(history)
    artifact = fit_projection_artifact(training, policy=policy)
    result = evaluate_minutes_baseline(history, artifact, evaluation, policy=policy)
    runtime = _database()
    if runtime is not None:
        engine, factory = runtime
        try:
            with factory.begin() as session:
                dataset = _dataset_payload(
                    "min007-synthetic-train-v1",
                    "SYNTH_EPL",
                    "2026/27",
                    "2026-06-08T17:00:00Z",
                    training,
                    policy,
                )
                register_dataset_version(
                    session, dataset, training_examples=training.get("rows", ())
                )
                model = {
                    "schema_version": "minutes-model-version-v1",
                    "model_key": model_key,
                    "dataset_version_sha256": dataset_version_semantic_sha256(dataset),
                    "role_artifact_sha256": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
                    "minute_artifact_sha256": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
                    "policy_sha256": dataset["policy_sha256"],
                    "model_family": artifact.model_family,
                    "code_identity": "MIN-007G",
                }
                model_id = register_model_version(
                    session, model, artifact=artifact.model_dump(mode="json")
                )
                register_model_evaluation(session, model_id, result.model_dump(mode="json"))
        finally:
            engine.dispose()
    _emit(result)


@availability_app.command("predict")
def predict_command(
    fixture_external_provider: Annotated[str, typer.Option("--fixture-external-provider")],
    fixture_external_id: Annotated[int, typer.Option("--fixture-external-id")],
    season_code: Annotated[str, typer.Option("--season-code")],
    team_side: Annotated[str, typer.Option("--team-side")],
    as_of: Annotated[str, typer.Option("--as-of")],
    model_key: Annotated[str, typer.Option("--model-key")],
    seed: Annotated[str, typer.Option("--seed")],
    output: Annotated[str, typer.Option("--output")] = "human",
) -> None:
    """Predict one mapped synthetic fixture without any provider access."""

    _guard_environment()
    if (
        fixture_external_provider != "synthetic_availability"
        or team_side != "HOME"
        or season_code != "2026/27"
    ):
        raise typer.BadParameter("only the frozen synthetic HOME fixture mapping is supported")
    name = {701: "stable_xi", 709: "insufficient_eligible_squad"}.get(fixture_external_id)
    if name is None:
        raise typer.BadParameter("fixture external ID is not in the TEST mapping plan")
    history, policy, _ = _fixtures()
    context = _read_json(_root() / f"fixtures/availability/MIN-007G/contexts/{name}.json")
    training = _training(history)
    artifact = fit_projection_artifact(training, policy=policy)
    result = predict_minutes_baseline(history, artifact, context=context, policy=policy)
    if result.status == "BLOCKED":
        _emit(result)
        raise typer.Exit(BLOCKED_EXIT)
    runtime = _database()
    if runtime is not None and result.projection is not None:
        engine, factory = runtime
        try:
            with factory.begin() as session:
                dataset = _dataset_payload(
                    "min007-synthetic-train-v1",
                    "SYNTH_EPL",
                    "2026/27",
                    "2026-06-08T17:00:00Z",
                    training,
                    policy,
                )
                dataset_id = register_dataset_version(
                    session, dataset, training_examples=training.get("rows", ())
                )
                del dataset_id
                model = {
                    "schema_version": "minutes-model-version-v1",
                    "model_key": model_key,
                    "dataset_version_sha256": dataset_version_semantic_sha256(dataset),
                    "role_artifact_sha256": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
                    "minute_artifact_sha256": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
                    "policy_sha256": dataset["policy_sha256"],
                    "model_family": artifact.model_family,
                    "code_identity": "MIN-007G",
                }
                model_hash = model_version_semantic_sha256(model)
                prediction = {
                    "schema_version": "minutes-prediction-signature-v1",
                    "fixture_id": result.fixture_id,
                    "team_id": result.team_id,
                    "as_of": result.as_of,
                    "model_version_sha256": model_hash,
                    "dataset_version_sha256": dataset_version_semantic_sha256(dataset),
                    "policy_sha256": dataset["policy_sha256"],
                    "manager_context": {"manager_regime_id": context["manager_regime_id"]},
                    "manager_regime_id": context["manager_regime_id"],
                    "seed": seed,
                    "sample_count": result.projection.sample_count,
                    "bench_size": result.projection.bench_size,
                    "bench_goalkeeper_slots": result.projection.bench_goalkeeper_slots,
                    "code_identity": "MIN-007G",
                }
                model_id = register_model_version(
                    session, model, artifact=artifact.model_dump(mode="json")
                )
                del model_id
                register_prediction_bundle(
                    session,
                    prediction,
                    role_marginals=(),
                    minute_pmfs=(),
                    scenarios=(),
                    hard_eligibility=(),
                    final_projection=result.projection,
                )
        finally:
            engine.dispose()
    _emit(result)


__all__ = ["availability_app"]
