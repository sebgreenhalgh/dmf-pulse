"""Stage-13 price prediction CLI backed by the canonical application service."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel, ValidationError

from dmf_pulse.evaluation.artifacts import canonical_json_bytes
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.service import load_json
from dmf_pulse.prices.configuration import load_price_config
from dmf_pulse.prices.errors import PriceError
from dmf_pulse.prices.service import PriceService

prices_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Build, validate, and evaluate governed Stage-13 price forecasts.",
)


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
    except (OSError, ValueError) as exc:
        raise PriceError(
            "PRICE_INPUT_INVALID",
            "price input JSON is unavailable or malformed",
        ) from exc


def _service(config: Path | None) -> PriceService:
    return PriceService(load_price_config(config))


def _fail(exc: Exception) -> None:
    if isinstance(exc, (PriceError, EvaluationError)):
        payload = exc.as_error_object()
    elif isinstance(exc, ValidationError):
        payload = {
            "error": {
                "blocking": True,
                "code": "PRICE_INPUT_INVALID",
                "message": "price input violates the Stage-13 contract",
            }
        }
    else:
        payload = {
            "error": {
                "blocking": True,
                "code": "PRICE_EXECUTION_INVALID",
                "message": str(exc),
            }
        }
    typer.echo(json.dumps(payload, sort_keys=True))
    raise typer.Exit(2)


def _execute(operation: Callable[[], BaseModel | tuple[Any, ...]]) -> None:
    try:
        _emit(operation())
    except (
        PriceError,
        EvaluationError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


@prices_app.command("build-update-cycles")
def build_update_cycles(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Build interval-censored update labels from immutable observations."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).build_update_cycles(_load(input_path)))


@prices_app.command("build-features")
def build_features(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Build cutoff-safe transfer-flow and recurrent features."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).build_features(_load(input_path)))


@prices_app.command("train-baseline")
def train_baseline(
    input_path: Annotated[Path, typer.Option("--input")],
    artifact_root: Annotated[Path | None, typer.Option("--artifact-root")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Fit the regularized competing-logit baseline chronologically."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(
        lambda: _service(config).train_baseline(_load(input_path), artifact_root=artifact_root)
    )


@prices_app.command("predict-next")
def predict_next(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Predict the next update and complete 24h/72h/7d price PMFs."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).predict(_load(input_path)))


@prices_app.command("simulate-path")
def simulate_path(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Simulate a bounded recurrent market-price path distribution."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).simulate(_load(input_path)))


@prices_app.command("selling-value")
def selling_value(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Map market price through Stage 11's accepted selling-value rule."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).selling_value(_load(input_path)))


@prices_app.command("price-scenarios")
def price_scenarios(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Expose exact bounded price branches to the Stage-11 optimiser."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).price_scenarios(_load(input_path)))


@prices_app.command("act-or-wait")
def act_or_wait(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Compare ACT and WAIT using complete utility and fail-closed activation."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).act_or_wait(_load(input_path)))


@prices_app.command("evaluate")
def evaluate(
    input_path: Annotated[Path, typer.Option("--input")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Score probabilistic price forecasts with Stage-12 metrics."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).evaluate(_load(input_path)))


@prices_app.command("validate")
def validate(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Validate configuration, model availability, and fail-closed status."""

    if output != "json":
        raise typer.BadParameter("--output must be json")
    _execute(lambda: _service(config).validate())
