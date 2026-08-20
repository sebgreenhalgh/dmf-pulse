"""Operator-only, transient GW1 decision command backed by shared services."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import TypeAdapter, ValidationError

from dmf_pulse.availability.current import (
    CurrentAvailabilityApproval,
    CurrentAvailabilityReviewTemplate,
    CurrentPlayerAvailabilityDecision,
)
from dmf_pulse.cli.ingest_cmd import collect_session1_approval
from dmf_pulse.fpl_points.current import (
    CurrentFootballEventApproval,
    CurrentFootballEventPriorArtifact,
    CurrentFootballEventReviewTemplate,
)
from dmf_pulse.fpl_points.current_points import (
    TARGET_MC_POLICY_FILE_SHA256,
    TARGET_RULESET_FILE_SHA256,
    TARGET_RULESET_HASH,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import parse_rfc3339_timestamp
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.session1 import (
    Session1CurrentInputRequest,
    Session1CurrentInputService,
)
from dmf_pulse.optimisation.current_initial_squad import (
    TARGET_GW1_INITIAL_SQUAD_CAPABILITY_HASH,
)
from dmf_pulse.orchestration.gw1 import run_gw1_decision_pipeline
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset, write_compiled_ruleset
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import RuleCapability

gw1_app = typer.Typer(help="Run the private, transient GW1 decision pipeline.")
_DECISIONS = TypeAdapter(tuple[CurrentPlayerAvailabilityDecision, ...])


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True)


def _failure(error: IngestionError) -> NoReturn:
    typer.echo(_json(error.as_error_object()))
    raise typer.Exit(error.exit_code)


def _timestamp(value: str, *, option: str) -> datetime:
    try:
        return parse_rfc3339_timestamp(value).astimezone(UTC)
    except ValueError as exc:
        raise IngestionError("USAGE_INVALID", f"{option} must be RFC3339 UTC") from exc


def _read_event_prior(path: Path) -> CurrentFootballEventPriorArtifact:
    try:
        payload = path.read_bytes()
        if len(payload) > 10 * 1024 * 1024:
            raise ValueError("event prior is too large")
        return CurrentFootballEventPriorArtifact.model_validate_json(payload)
    except (OSError, ValueError, ValidationError) as exc:
        raise IngestionError(
            "QUALITY_BLOCKED", "accepted football-event prior is unavailable or invalid"
        ) from exc


def _availability_provider(
    *, reviewer: str, clock: Callable[[], datetime]
) -> Callable[[CurrentAvailabilityReviewTemplate], CurrentAvailabilityApproval]:
    def collect(template: CurrentAvailabilityReviewTemplate) -> CurrentAvailabilityApproval:
        typer.echo("PRIVATE TRANSIENT AVAILABILITY REVIEW - do not redirect or persist.", err=True)
        typer.echo(_json(template), err=True)
        raw = typer.prompt(
            "Paste the reviewed availability decision JSON array (use [] only when no rows require a decision)",
            type=str,
            err=True,
        )
        confirmed = typer.prompt(
            "Type the complete availability template SHA-256", type=str, err=True
        )
        try:
            decisions = _DECISIONS.validate_json(raw)
            return CurrentAvailabilityApproval(
                reviewer=reviewer,
                approved_at=clock(),
                template_sha256=template.template_sha256,
                confirmed_template_sha256=confirmed,
                reviewed_all_players=True,
                decisions=decisions,
            )
        except ValidationError as exc:
            raise IngestionError(
                "MAPPING_CONFLICT", "availability approval is invalid or incomplete"
            ) from exc

    return collect


def _event_provider(
    *,
    reviewer: str,
    prior: CurrentFootballEventPriorArtifact,
    clock: Callable[[], datetime],
) -> Callable[[CurrentFootballEventReviewTemplate], CurrentFootballEventApproval]:
    def collect(template: CurrentFootballEventReviewTemplate) -> CurrentFootballEventApproval:
        typer.echo("PRIVATE TRANSIENT EVENT REVIEW - do not redirect or persist.", err=True)
        typer.echo(_json(template), err=True)
        confirmed_template = typer.prompt(
            "Type the complete football-event template SHA-256", type=str, err=True
        )
        confirmed_prior = typer.prompt(
            "Type the complete accepted event-prior artifact SHA-256", type=str, err=True
        )
        return CurrentFootballEventApproval(
            reviewer=reviewer,
            approved_at=clock(),
            reviewed_all_fixtures=True,
            accepted_model_artifact_confirmed=True,
            template_sha256=template.template_sha256,
            confirmed_template_sha256=confirmed_template,
            prior_artifact=prior,
            confirmed_prior_artifact_sha256=confirmed_prior,
        )

    return collect


@gw1_app.command("run")
def gw1_run_command(
    bootstrap: Annotated[Path, typer.Option("--bootstrap")],
    fixtures: Annotated[Path, typer.Option("--fixtures")],
    captured_at: Annotated[str, typer.Option("--captured-at")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    reviewer: Annotated[str, typer.Option("--reviewer")],
    event_prior: Annotated[Path, typer.Option("--event-prior")],
    code_commit: Annotated[str, typer.Option("--code-commit")],
    database_url_ref: Annotated[str, typer.Option("--database-url-ref")] = DATABASE_REF,
    rules_source: Annotated[Path, typer.Option("--rules-source")] = Path(
        "config/rules/fpl-2026-27"
    ),
    mc_policy: Annotated[Path, typer.Option("--mc-policy")] = Path(
        "config/models/fpl_points_simulation.yaml"
    ),
    prospective_root: Annotated[Path, typer.Option("--prospective-root")] = Path(
        "artifacts/prospective"
    ),
    root_seed: Annotated[int, typer.Option("--root-seed", min=0)] = 2026270001,
    scenario_count: Annotated[int, typer.Option("--scenario-count", min=1)] = 1000,
    output: Annotated[str, typer.Option("--output")] = "json",
) -> None:
    """Run the reviewed current-data path; detailed output is stdout-only and transient."""

    try:
        if (
            output != "json"
            or not reviewer.strip()
            or re.fullmatch(r"[0-9a-f]{40}", code_commit) is None
        ):
            raise IngestionError("USAGE_INVALID", "GW1 operator options are invalid")
        prior = _read_event_prior(event_prior)
        with tempfile.TemporaryDirectory(prefix="dmf-gw1-rules-") as directory:
            ruleset_path = Path(directory) / "fpl-2026-27.json"
            compiled = compile_ruleset(rules_source)
            write_compiled_ruleset(compiled, ruleset_path)
            capability = compile_capability_artifact(compiled, RuleCapability.GW1_INITIAL_SQUAD)
            try:
                mc_policy_file_sha256 = hashlib.sha256(mc_policy.read_bytes()).hexdigest()
            except OSError as exc:
                raise IngestionError(
                    "QUALITY_BLOCKED", "accepted Monte Carlo policy is unavailable"
                ) from exc
            if (
                compiled.ruleset_hash != TARGET_RULESET_HASH
                or hashlib.sha256(ruleset_path.read_bytes()).hexdigest()
                != TARGET_RULESET_FILE_SHA256
                or capability.capability_hash != TARGET_GW1_INITIAL_SQUAD_CAPABILITY_HASH
                or not capability.source_backed
                or not capability.production_eligible
                or capability.blockers
                or mc_policy_file_sha256 != TARGET_MC_POLICY_FILE_SHA256
            ):
                raise IngestionError(
                    "QUALITY_BLOCKED",
                    "rules or Monte Carlo policy differs from accepted GW1 authority",
                )
            request = Session1CurrentInputRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                captured_at=_timestamp(captured_at, option="--captured-at"),
                information_cutoff=_timestamp(information_cutoff, option="--information-cutoff"),
                database_url_ref=database_url_ref,
            )
            service = Session1CurrentInputService()
            prepared = service.prepare(request)
            session1 = service.complete(
                prepared, collect_session1_approval(prepared, reviewer=reviewer)
            )
            result = run_gw1_decision_pipeline(
                session1,
                availability_approval_provider=_availability_provider(
                    reviewer=reviewer, clock=lambda: datetime.now(UTC)
                ),
                event_approval_provider=_event_provider(
                    reviewer=reviewer,
                    prior=prior,
                    clock=lambda: datetime.now(UTC),
                ),
                ruleset_path=ruleset_path,
                mc_policy_path=mc_policy,
                root_seed=root_seed,
                scenario_count=scenario_count,
                code_commit=code_commit,
                receipt_clock=lambda: datetime.now(UTC),
                prospective_artifact_root=prospective_root,
            )
        typer.echo("PRIVATE TRANSIENT DECISION OUTPUT - do not redirect or persist.", err=True)
        typer.echo(
            _json(
                {
                    "decision": result.decision.model_dump(mode="json"),
                    "prospective_receipt": (
                        result.prospective_receipt.model_dump(mode="json")
                        if result.prospective_receipt
                        else None
                    ),
                    "prospective_receipt_path": (
                        str(result.prospective_receipt_path)
                        if result.prospective_receipt_path
                        else None
                    ),
                    "safe_summary": result.summary.model_dump(mode="json"),
                }
            )
        )
        if result.decision.status == "BLOCKED":
            raise typer.Exit(30)
    except typer.Exit:
        raise
    except IngestionError as exc:
        _failure(exc)
    except RulesError as exc:
        _failure(IngestionError("QUALITY_BLOCKED", exc.message))
    except Exception as exc:  # pragma: no cover - final secret-safe boundary
        error = IngestionError("INTERNAL_INVARIANT", "GW1 command failed safely")
        typer.echo(_json(error.as_error_object()))
        raise typer.Exit(error.exit_code) from exc


__all__ = ["gw1_app", "gw1_run_command"]
