"""Stage-14 chip CLI backed exclusively by the shared application service."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dmf_pulse.chips.artifacts import (
    Stage14DecisionArtifact,
    load_decision_artifact,
    seal_decision_artifact,
    verify_decision_artifact,
)
from dmf_pulse.chips.definitions import CompiledChipBundle, semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import ChipInventory, build_chip_inventory
from dmf_pulse.chips.replay import (
    ChipReplayRequest,
    replay_chip_policy,
)
from dmf_pulse.chips.service import (
    evaluate_chip_opportunities,
    optimise_chip_schedule,
    validate_compiled_chip_bundle,
    validate_installed_chip_capability,
)
from dmf_pulse.chips.service_models import ChipDecisionSet, ChipServiceRequest
from dmf_pulse.evaluation.artifacts import canonical_json_bytes

chips_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Evaluate, schedule, replay, and validate finite-inventory FPL chip policy.",
)


class _InventoryBuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chip_bundle: CompiledChipBundle
    current_gameweek: int = Field(gt=0)


def _emit(value: BaseModel | tuple[Any, ...] | dict[str, Any] | list[Any]) -> None:
    if isinstance(value, BaseModel):
        payload: BaseModel | dict[str, Any] | list[Any] = value.model_dump(mode="json")
    elif isinstance(value, tuple):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    else:
        payload = value
    typer.echo(canonical_json_bytes(payload).decode("utf-8"), nl=False)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChipError(
            "CHIP_INPUT_INVALID",
            "chip input JSON is unavailable or malformed",
            path=str(path),
        ) from exc
    if not isinstance(value, dict):
        raise ChipError("CHIP_INPUT_INVALID", "chip input JSON must be an object")
    return value


def _request(path: Path) -> ChipServiceRequest:
    return ChipServiceRequest.model_validate(_load(path))


def _decision_set(path: Path) -> ChipDecisionSet:
    return evaluate_chip_opportunities(_request(path))


def _fail(exc: Exception) -> None:
    if isinstance(exc, ChipError):
        payload = exc.as_error_object()
    elif isinstance(exc, ValidationError):
        payload = {
            "error": {
                "code": "CHIP_INPUT_INVALID",
                "message": "chip input violates the Stage-14 contract",
                "details": {"validation_errors": len(exc.errors())},
            }
        }
    else:
        payload = {
            "error": {
                "code": "CHIP_EXECUTION_INVALID",
                "message": str(exc),
                "details": {},
            }
        }
    typer.echo(json.dumps(payload, sort_keys=True))
    raise typer.Exit(2)


def _execute(operation: Callable[[], BaseModel | tuple[Any, ...] | dict[str, Any]]) -> None:
    try:
        _emit(operation())
    except (
        ChipError,
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OSError,
    ) as exc:
        _fail(exc)


def _json_only(output: str) -> None:
    if output != "json":
        raise typer.BadParameter("--output must be json")


@chips_app.command("validate-rules")
def validate_rules(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Validate compiled chip rules, definitions, activation state, and hashes."""

    _json_only(output)
    _execute(
        lambda: validate_compiled_chip_bundle(CompiledChipBundle.model_validate(_load(input_path)))
    )


@chips_app.command("inventory")
def inventory(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Build or validate a rules-bound finite chip-token inventory."""

    _json_only(output)

    def operation() -> ChipInventory:
        payload = _load(input_path)
        if "chip_bundle" in payload:
            request = _InventoryBuildInput.model_validate(payload)
            validate_compiled_chip_bundle(request.chip_bundle)
            return build_chip_inventory(
                request.chip_bundle,
                current_gameweek=request.current_gameweek,
            )
        value = ChipInventory.model_validate(payload)
        expected = semantic_sha256(value.model_dump(mode="json", exclude={"inventory_hash"}))
        if value.inventory_hash != expected:
            raise ChipError(
                "CHIP_INVENTORY_HASH_MISMATCH",
                "chip inventory hash does not match",
            )
        return value

    _execute(operation)


@chips_app.command("captain")
def captain(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Return the validated joint captain/vice decision bound to the chip request."""

    _json_only(output)

    def operation() -> BaseModel:
        value = _decision_set(input_path)
        if value.captain_vice is None:
            raise ChipError(
                "CHIP_CAPTAIN_EVIDENCE_MISSING",
                "service request does not contain a frozen captain/vice evaluation",
            )
        return value.captain_vice

    _execute(operation)


def _chip_value(path: Path, chip_key: str, field_name: str) -> BaseModel:
    value = _decision_set(path)
    domain = getattr(value, field_name)
    if isinstance(domain, BaseModel):
        return domain
    candidates = tuple(item for item in value.opportunities if item.chip_key == chip_key)
    if not candidates:
        raise ChipError(
            "CHIP_OPPORTUNITY_MISSING",
            "service request does not contain the requested current chip opportunity",
            chip_key=chip_key,
        )
    return max(
        candidates,
        key=lambda item: (item.net_policy_value, item.opportunity_id),
    )


@chips_app.command("triple-captain-value")
def triple_captain_value(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Evaluate Triple Captain through the shared current/future comparison."""

    _json_only(output)
    _execute(lambda: _chip_value(input_path, "TRIPLE_CAPTAIN", "triple_captain"))


@chips_app.command("bench-boost-value")
def bench_boost_value(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Evaluate Bench Boost including ordinary autosub overlap and policy cost."""

    _json_only(output)
    _execute(lambda: _chip_value(input_path, "BENCH_BOOST", "bench_boost"))


@chips_app.command("free-hit-value")
def free_hit_value(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Evaluate Free Hit against the permanent-state normal policy comparator."""

    _json_only(output)
    _execute(lambda: _chip_value(input_path, "FREE_HIT", "free_hit"))


@chips_app.command("wildcard-now-vs-later")
def wildcard_now_vs_later(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Evaluate immediate Wildcard versus retained/delayed policy routes."""

    _json_only(output)
    _execute(lambda: _chip_value(input_path, "WILDCARD", "wildcard"))


@chips_app.command("opportunity")
def opportunity(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Return comparable current chip opportunities with decomposed policy value."""

    _json_only(output)
    _execute(lambda: _decision_set(input_path).opportunities)


@chips_app.command("compare")
def compare(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Compare NO CHIP, use-now, hold/delay, and finite-inventory schedules."""

    _json_only(output)
    _execute(lambda: _decision_set(input_path))


@chips_app.command("schedule")
def schedule(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Optimise the finite-inventory schedule; only its root action is executable."""

    _json_only(output)
    _execute(lambda: optimise_chip_schedule(_request(input_path)))


@chips_app.command("explain")
def explain(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Emit structured reasons and alternatives from the deterministic service output."""

    _json_only(output)

    def operation() -> dict[str, Any]:
        value = _decision_set(input_path)
        return {
            "decision": value.decision.model_dump(mode="json"),
            "opportunities": [item.model_dump(mode="json") for item in value.opportunities],
            "alternatives": [
                item.model_dump(mode="json") for item in value.schedule_policy.alternatives
            ],
            "lineage": value.lineage.model_dump(mode="json"),
        }

    _execute(operation)


@chips_app.command("backtest")
def backtest(
    input_path: Annotated[Path, typer.Option("--input")],
    artifact_root: Annotated[Path | None, typer.Option("--artifact-root")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run deadline-safe sequential replay with root-only execution and re-solving."""

    _json_only(output)
    _execute(
        lambda: replay_chip_policy(
            ChipReplayRequest.model_validate(_load(input_path)),
            artifact_root=artifact_root,
        )
    )


@chips_app.command("validate")
def validate(
    input_path: Annotated[Path | None, typer.Option("--input")] = None,
    artifact: Annotated[Path | None, typer.Option("--artifact")] = None,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Validate installed capability, a service request, or a sealed artifact."""

    _json_only(output)
    if input_path is not None and artifact is not None:
        raise typer.BadParameter("use only one of --input or --artifact")

    def operation() -> BaseModel | dict[str, Any]:
        if artifact is not None:
            return load_decision_artifact(artifact)
        if input_path is None:
            return validate_installed_chip_capability()
        payload = _load(input_path)
        if payload.get("schema_version") == "stage14-chip-decision-v1":
            value = Stage14DecisionArtifact.model_validate(payload)
            verify_decision_artifact(value)
            return value
        request = ChipServiceRequest.model_validate(payload)
        value = seal_decision_artifact(request)
        return {
            "status": "VALID",
            "service_request_hash": request.service_request_hash,
            "decision_set_hash": value.decision_set.decision_set_hash,
            "artifact_hash": value.artifact_hash,
        }

    _execute(operation)


__all__ = ["chips_app"]
