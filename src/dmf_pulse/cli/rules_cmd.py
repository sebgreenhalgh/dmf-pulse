"""Typer surface for versioned rules compilation, lifecycle, and scoring."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ValidationError

from dmf_pulse.rules.aggregation import score_gameweek
from dmf_pulse.rules.canonical import pretty_rules_json
from dmf_pulse.rules.compiler import (
    compile_ruleset,
    load_compiled_ruleset,
    resolve_ruleset,
    validate_ruleset_directory,
    write_compiled_ruleset,
)
from dmf_pulse.rules.diff import diff_rulesets
from dmf_pulse.rules.errors import RulesError, RulesValidationError
from dmf_pulse.rules.lifecycle import activate_ruleset
from dmf_pulse.rules.models import (
    ApprovalRecord,
    CompiledRuleset,
    FixtureScenario,
    GameweekScenario,
)
from dmf_pulse.rules.scoring import score_fixture

rules_app = typer.Typer(help="Validate, compile, compare, score, and activate governed rulesets.")


def _read_model[T: BaseModel](path: Path, model: type[T]) -> T:
    try:
        raw = path.read_bytes()
        if len(raw) > 10 * 1024 * 1024:
            raise RulesValidationError("RULESET_INPUT_TOO_LARGE", "rules input exceeds 10 MiB")
        return model.model_validate_json(raw)
    except RulesError:
        raise
    except (OSError, ValidationError, ValueError) as exc:
        raise RulesValidationError(
            "RULESET_INPUT_INVALID", "rules input is unavailable or invalid"
        ) from exc


def _run[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except RulesError as exc:
        typer.echo(json.dumps(exc.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:  # pragma: no cover - final safety boundary
        error = RulesError("RULESET_INTERNAL_ERROR", "rules command failed safely")
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True), err=True)
        raise typer.Exit(1) from exc


def _emit(value: BaseModel | Mapping[str, object], *, as_json: bool, human: str) -> None:
    if as_json:
        data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        typer.echo(json.dumps(data, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(human)


@rules_app.command("validate")
def validate_command(
    source_dir: Path,
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    report = _run(lambda: validate_ruleset_directory(source_dir))
    _emit(
        report,
        as_json=as_json,
        human=f"Ruleset {report.ruleset_id} {report.ruleset_version}: valid ({report.status.value}).",
    )


@rules_app.command("compile")
def compile_command(
    source_dir: Path,
    output: Annotated[Path, typer.Option("--output", help="Canonical compiled JSON output.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    def operation() -> CompiledRuleset:
        compiled = compile_ruleset(source_dir)
        write_compiled_ruleset(compiled, output)
        return compiled

    compiled = _run(operation)
    summary = {
        "output": output.as_posix(),
        "production_eligible": compiled.production_eligible,
        "ruleset_hash": compiled.ruleset_hash,
        "ruleset_id": compiled.ruleset_id,
        "ruleset_version": compiled.ruleset_version,
        "status": compiled.status.value,
    }
    _emit(
        summary,
        as_json=as_json,
        human=f"Compiled {compiled.ruleset_id} at {compiled.ruleset_hash}.",
    )


@rules_app.command("hash")
def hash_command(
    compiled_file: Path,
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    compiled = _run(lambda: load_compiled_ruleset(compiled_file))
    value = {"ruleset_hash": compiled.ruleset_hash, "ruleset_id": compiled.ruleset_id}
    _emit(value, as_json=as_json, human=compiled.ruleset_hash)


@rules_app.command("show")
def show_command(
    ruleset: Path,
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    compiled = _run(lambda: resolve_ruleset(ruleset))
    value = {
        "production_eligible": compiled.production_eligible,
        "rule_families": sorted(compiled.rules),
        "ruleset_hash": compiled.ruleset_hash,
        "ruleset_id": compiled.ruleset_id,
        "ruleset_version": compiled.ruleset_version,
        "status": compiled.status.value,
        "unknown_blockers": list(compiled.unknown_blockers),
    }
    _emit(value, as_json=as_json, human=pretty_rules_json(value).rstrip())


@rules_app.command("diff")
def diff_command(
    left: Path,
    right: Path,
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    difference = _run(lambda: diff_rulesets(left, right))
    _emit(
        difference,
        as_json=as_json,
        human=f"{len(difference.changes)} rule change(s) between {difference.left_id} and {difference.right_id}.",
    )


@rules_app.command("score-fixture")
def score_fixture_command(
    ruleset: Path,
    scenario: Path,
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    result = _run(
        lambda: score_fixture(resolve_ruleset(ruleset), _read_model(scenario, FixtureScenario))
    )
    _emit(result, as_json=as_json, human=pretty_rules_json(result.model_dump(mode="json")).rstrip())


@rules_app.command("score-gameweek")
def score_gameweek_command(
    ruleset: Path,
    scenario: Path,
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    result = _run(
        lambda: score_gameweek(resolve_ruleset(ruleset), _read_model(scenario, GameweekScenario))
    )
    _emit(result, as_json=as_json, human=pretty_rules_json(result.model_dump(mode="json")).rstrip())


@rules_app.command("activate")
def activate_command(
    ruleset: Path,
    approval: Annotated[Path, typer.Option("--approval", help="Exact approval record JSON.")],
    registry: Annotated[
        Path, typer.Option("--registry", help="Immutable active-artifact registry.")
    ] = Path("artifacts/rules/active"),
    as_json: Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")] = False,
) -> None:
    receipt = _run(
        lambda: activate_ruleset(
            resolve_ruleset(ruleset),
            _read_model(approval, ApprovalRecord),
            registry,
        )
    )
    _emit(
        receipt, as_json=as_json, human=f"Activated {receipt.ruleset_id} {receipt.ruleset_version}."
    )
