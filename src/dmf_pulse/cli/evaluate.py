"""Stage-12 evaluation CLI using the canonical application service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel, ValidationError

from dmf_pulse.evaluation.artifacts import canonical_json_bytes
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.service import EvaluationService, load_json

evaluate_app = typer.Typer(add_completion=False, no_args_is_help=True)


def _emit(value: BaseModel | tuple[Any, ...]) -> None:
    payload: object
    if isinstance(value, tuple):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    else:
        payload = value.model_dump(mode="json")
    typer.echo(canonical_json_bytes(payload).decode("utf-8"), nl=False)


def _load(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except ValueError as exc:
        raise EvaluationError(
            "EVALUATION_INPUT_INVALID",
            "evaluation input JSON is unavailable or malformed",
        ) from exc


def _fail(exc: Exception) -> None:
    if isinstance(exc, EvaluationError):
        payload = exc.as_error_object()
    elif isinstance(exc, ValidationError):
        payload = {
            "error": {
                "code": "EVALUATION_INPUT_INVALID",
                "message": "evaluation input violates the Stage-12 contract",
                "blocking": True,
            }
        }
    else:
        payload = {
            "error": {"code": "EVALUATION_EXECUTION_INVALID", "message": str(exc), "blocking": True}
        }
    typer.echo(json.dumps(payload, sort_keys=True))
    raise typer.Exit(2)


@evaluate_app.command("build-folds")
def build_folds(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Build immutable nested walk-forward folds."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        _emit(EvaluationService().build_folds(_load(input_path)))
    except (
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


@evaluate_app.command("benchmark")
def benchmark(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run selected B0-B5 benchmark contracts."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        _emit(EvaluationService().benchmark(_load(input_path)))
    except (
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


@evaluate_app.command("projections")
def projections(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Score point projections separately from decision outcomes."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        _emit(EvaluationService().projections(_load(input_path)))
    except (
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


@evaluate_app.command("policy")
def policy(
    input_path: Annotated[Path, typer.Option("--input")],
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Replay a stateful forecast-first policy over deterministic deadlines."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        _emit(EvaluationService().policy(_load(input_path), artifact_root=artifact_root))
    except (
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


@evaluate_app.command("leakage")
def leakage(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run first-class blocking temporal leakage assurance."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        report = EvaluationService().leakage(_load(input_path))
        _emit(report)
        if report.status == "BLOCKED":
            raise typer.Exit(3)
    except typer.Exit:
        raise
    except (
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


@evaluate_app.command("report")
def report(
    input_path: Annotated[Path, typer.Option("--input")],
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Build separated forecast/distribution/decision/operational scorecards."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    try:
        _emit(EvaluationService().report(_load(input_path), artifact_root=artifact_root))
    except (
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)
