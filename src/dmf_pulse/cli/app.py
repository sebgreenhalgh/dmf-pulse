"""Top-level Typer application."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from typer._click.exceptions import Abort, Exit, UsageError

from dmf_pulse import __version__
from dmf_pulse.cli.availability_cmd import availability_app
from dmf_pulse.cli.config_cmd import config_app
from dmf_pulse.cli.data_model_cmd import data_model_app
from dmf_pulse.cli.doctor import build_doctor_report
from dmf_pulse.cli.evaluate import evaluate_app
from dmf_pulse.cli.events import events_app
from dmf_pulse.cli.evidence_cmd import evidence_app
from dmf_pulse.cli.fpl_points import fpl_points_app
from dmf_pulse.cli.ingest_cmd import ingest_app
from dmf_pulse.cli.market_cmd import market_app
from dmf_pulse.cli.optimise import optimise_app
from dmf_pulse.cli.prices import prices_app
from dmf_pulse.cli.review_pack_cmd import review_pack_app
from dmf_pulse.cli.rules_cmd import rules_app
from dmf_pulse.cli.specs_cmd import specs_app
from dmf_pulse.ingestion.errors import IngestionError

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="DMF Pulse governed foundation commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(config_app, name="config")
app.add_typer(availability_app, name="availability")
app.add_typer(data_model_app, name="data-model")
app.add_typer(evidence_app, name="evidence")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(events_app, name="events")
app.add_typer(fpl_points_app, name="fpl-points")
app.add_typer(ingest_app, name="ingest")
app.add_typer(market_app, name="market")
app.add_typer(review_pack_app, name="review-pack")
app.add_typer(rules_app, name="rules")
app.add_typer(optimise_app, name="optimise")
app.add_typer(prices_app, name="prices")
app.add_typer(specs_app, name="specs")

DOCTOR_BLOCKING_EXIT = 40


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"dmf {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed DMF Pulse version and exit.",
        ),
    ] = False,
) -> None:
    """Dispatch DMF Pulse commands."""


@app.command("doctor")
def doctor_command(
    as_json: Annotated[bool, typer.Option("--json", help="Emit the stable JSON contract.")] = False,
) -> None:
    """Run offline system and configuration diagnostics."""

    report = build_doctor_report()
    if as_json:
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        typer.echo(f"DMF Pulse {report.package_version}: {report.status}")
        typer.echo(
            f"Python {report.python.version} (requires {report.python.required_minor}): "
            f"{'compatible' if report.python.compatible else 'incompatible'}"
        )
        typer.echo(f"Configuration: {report.config.status} ({report.config.source})")
        typer.echo(f"Artifact root: {report.artifact_root.status}")
        typer.echo(f"NVIDIA: {report.nvidia.status} (optional, nonblocking)")
    if report.status == "BLOCKING":
        raise typer.Exit(DOCTOR_BLOCKING_EXIT)


def main() -> None:
    """Run the installed console application."""

    try:
        result = app(prog_name="dmf", standalone_mode=False)
    except Exit as exc:
        raise SystemExit(exc.exit_code) from None
    except (UsageError, Abort):
        error = IngestionError("USAGE_INVALID", "command arguments are invalid")
        typer.echo(json.dumps(error.as_error_object(), sort_keys=True))
        raise SystemExit(error.exit_code) from None
    if isinstance(result, int) and result:
        raise SystemExit(result)
