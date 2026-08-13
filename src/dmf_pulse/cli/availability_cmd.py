"""Offline TEST/REPLAY CLI for the MIN-007G availability pipeline."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Annotated, Any, NoReturn

import typer
from sqlalchemy import Engine

from dmf_pulse.availability.dataset import semantic_dataset_hash
from dmf_pulse.availability.models import format_utc, parse_utc
from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_model_evaluation,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.availability.pipeline import (
    ModelEvaluationPublication,
    evaluate_minutes_baseline,
    fit_projection_artifact,
    predict_minutes_baseline,
)
from dmf_pulse.availability.registry import (
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
)
from dmf_pulse.availability.resources import availability_resource_json
from dmf_pulse.availability.role_model import FROZEN_POLICY_SHA256
from dmf_pulse.database.engine import (
    create_database_engine,
    resolve_test_database_url,
    session_factory,
)
from dmf_pulse.database.models import DatabaseSettings
from dmf_pulse.ingestion.errors import IngestionError

availability_app = typer.Typer(help="Run the deterministic TEST/REPLAY availability pipeline.")
dataset_app = typer.Typer(help="Build synthetic availability datasets.")
availability_app.add_typer(dataset_app, name="dataset")
BLOCKED_EXIT = 42
POLICY_SEED = "MIN-007-COHERENCE-V1"


def _fixtures() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    history = availability_resource_json("MIN-007/canonical_history.json")
    policy = availability_resource_json("MIN-007G/minutes_baseline_policy.json")
    evaluation = availability_resource_json("MIN-007G/evaluation_dataset.json")
    return history, policy, evaluation


def _mapping_plan() -> dict[str, Any]:
    """Load the wheel-contained TEST/REPLAY fixture authority."""

    plan = availability_resource_json("MIN-007/external_mapping_plan.json")
    if (
        plan.get("schema_version") != "min007-synthetic-mapping-plan-v1"
        or plan.get("provider_key") != "synthetic_availability"
        or plan.get("season_code") != "2026/27"
        or plan.get("environment_scope") != ["TEST", "REPLAY"]
    ):
        raise ValueError("synthetic mapping plan is invalid")
    return plan


def _resolve_fixture(
    plan: Mapping[str, Any], *, external_id: int, team_side: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixtures = plan.get("target_fixtures")
    teams = plan.get("teams")
    if not isinstance(fixtures, list) or not isinstance(teams, list):
        raise ValueError("synthetic mapping plan is incomplete")
    fixture = next(
        (
            item
            for item in fixtures
            if isinstance(item, Mapping) and item.get("external_id") == str(external_id)
        ),
        None,
    )
    if not isinstance(fixture, Mapping):
        raise ValueError("fixture external ID is not in the TEST mapping plan")
    side_key = {"HOME": "home_team_external_id", "AWAY": "away_team_external_id"}.get(team_side)
    if side_key is None:
        raise ValueError("team side is not supported by the synthetic mapping plan")
    external_team_id = fixture.get(side_key)
    team = next(
        (
            item
            for item in teams
            if isinstance(item, Mapping) and item.get("external_id") == external_team_id
        ),
        None,
    )
    if not isinstance(team, Mapping):
        raise ValueError("mapped team identity is unavailable")
    return dict(fixture), dict(team)


def _requested_as_of(value: str, *, training_cutoff: str, kickoff: str) -> str:
    """Validate and canonically render the strict requested prediction cutoff."""

    try:
        requested = parse_utc(value, field_name="as_of")
        cutoff = parse_utc(training_cutoff, field_name="training_cutoff")
        fixture_kickoff = parse_utc(kickoff, field_name="fixture kickoff")
    except ValueError as exc:
        _reject(str(exc))
    if not cutoff <= requested < fixture_kickoff:
        _reject("--as-of must satisfy training_cutoff <= as_of < mapped fixture kickoff")
    return format_utc(requested)


def _training() -> dict[str, Any]:
    return availability_resource_json("MIN-007/training_dataset.json")


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


def _reject(message: str) -> NoReturn:
    """Emit availability diagnostics on stderr without contaminating stdout."""

    error = IngestionError("USAGE_INVALID", message)
    typer.echo(json.dumps(error.as_error_object(), sort_keys=True), err=True)
    raise typer.Exit(error.exit_code)


def _guard_environment() -> None:
    environment = os.environ.get("DMF_ENVIRONMENT", "").upper()
    if environment not in {"TEST", "REPLAY"}:
        _reject("MIN-007G synthetic fixtures require DMF_ENVIRONMENT TEST or REPLAY")


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
    _, policy, _ = _fixtures()
    training = _training()
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
    _, policy, _ = _fixtures()
    training = _training()
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
    training = _training()
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
                register_model_evaluation(
                    session,
                    model_id,
                    ModelEvaluationPublication(
                        evaluation=result,
                        model_version_semantic_sha256=model_version_semantic_sha256(model),
                        model_artifact_sha256=artifact.artifact_sha256,
                        model_family=artifact.model_family,
                    ),
                )
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
    history, policy, _ = _fixtures()
    training = _training()
    if not isinstance(seed, str) or seed != policy.get("seed", POLICY_SEED):
        _reject("seed must exactly match the loaded MIN-007 coherence policy")
    try:
        plan = _mapping_plan()
        if fixture_external_provider != plan["provider_key"]:
            _reject("fixture provider is not supported by the synthetic mapping plan")
        if season_code != plan["season_code"]:
            _reject("season is not supported by the synthetic mapping plan")
        fixture, team = _resolve_fixture(plan, external_id=fixture_external_id, team_side=team_side)
        cutoff = str(training["training_cutoff"])
        requested_as_of = _requested_as_of(
            as_of, training_cutoff=cutoff, kickoff=str(fixture["kickoff"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        _reject(str(exc))
    scenario = fixture.get("scenario")
    if not isinstance(scenario, str) or not scenario:
        _reject("mapped fixture scenario is invalid")
    try:
        context = availability_resource_json(f"MIN-007G/contexts/{scenario}.json")
    except (OSError, ValueError):
        _reject("mapped fixture has no packaged context")
    if (
        context.get("fixture_id") != fixture.get("fixture_id")
        or context.get("team_id") != team.get("team_id")
        or context.get("team_key") != team.get("team_key")
    ):
        _reject("mapped fixture context identity is inconsistent")
    context["as_of"] = requested_as_of
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
                    cutoff,
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
                    role_marginals=result.core_role_marginals,
                    minute_pmfs=result.core_minute_pmfs,
                    scenarios=result.core_scenarios,
                    hard_eligibility=result.core_hard_eligibility,
                    final_projection=result.projection,
                )
        finally:
            engine.dispose()
    _emit(result)


__all__ = ["availability_app"]
