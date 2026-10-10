"""Offline pre-result protocol inspection, retention and schedule planning."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.evaluation.team_strength_protocol import (
    initial_campaign_ledger,
    load_protocol,
    plan_cohort,
    protocol_summary,
)
from dmf_pulse.evaluation.team_strength_protocol_store import (
    load_campaign,
    persist_protocol_evidence,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistry,
    ParsedSnapshot,
    authenticate,
)

protocol_app = typer.Typer(help="Inspect and retain the frozen public P02+ protocol offline.")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, sort_keys=True, allow_nan=False))


@protocol_app.command("show")
def show() -> None:
    """Authenticate the pinned protocol and accepted runtime methodology."""
    try:
        _emit(protocol_summary(load_protocol()))
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from None


@protocol_app.command("retain")
def retain(root: Annotated[Path, typer.Option("--retained-artifact-root")]) -> None:
    """Retain protocol and existing pilot metadata; never create a forecast."""
    try:
        protocol = load_protocol()
        ledger = initial_campaign_ledger()
        _emit(
            {
                "protocol_path": str(persist_protocol_evidence(protocol, artifact_root=root)),
                "ledger_path": str(persist_protocol_evidence(ledger, artifact_root=root)),
                "protocol_sha256": protocol.semantic_sha256,
                "ledger_sha256": ledger.semantic_sha256,
                "production_activation": False,
            }
        )
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from None


@protocol_app.command("campaign-show")
def campaign_show(
    ledger: Annotated[Path, typer.Option("--ledger", exists=True)],
    expected: Annotated[str, typer.Option("--ledger-sha256")],
) -> None:
    try:
        _emit(load_campaign(ledger, expected_sha256=expected).model_dump(mode="json"))
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from None


@protocol_app.command("plan")
def plan(
    ledger: Annotated[Path, typer.Option("--ledger", exists=True)],
    expected: Annotated[str, typer.Option("--ledger-sha256")],
    schedule: Annotated[Path, typer.Option("--schedule", exists=True)],
    schedule_sha256: Annotated[str, typer.Option("--schedule-sha256")],
    registry: Annotated[Path, typer.Option("--fixture-registry", exists=True)],
    registry_sha256: Annotated[str, typer.Option("--fixture-registry-sha256")],
) -> None:
    """Plan from supplied public evidence using actual UTC; no acquisition or freeze."""
    try:
        value = plan_cohort(
            ledger=load_campaign(ledger, expected_sha256=expected),
            schedule=authenticate(
                ParsedSnapshot.model_validate_json(schedule.read_bytes()), schedule_sha256
            ),
            registry=authenticate(
                FixtureRegistry.model_validate_json(registry.read_bytes()), registry_sha256
            ),
            as_of=datetime.now(UTC),
        )
        _emit(
            {
                "plan": value.model_dump(mode="json"),
                "source_freshness_reassessed": False,
                "forecast_created": False,
                "production_activation": False,
            }
        )
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from None
