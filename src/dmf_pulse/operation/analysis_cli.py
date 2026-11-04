"""Read-only local SQL/export commands; never load operational credentials."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from dmf_pulse.operation.analysis_paths import warehouse_path
from dmf_pulse.operation.analysis_store import AnalysisStore

analysis_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@analysis_app.command("query")
def query(
    sql: Annotated[str, typer.Argument(help="One read-only SQL statement.")],
    database: Annotated[Path | None, typer.Option("--database")] = None,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    """Query saved derived results without starting the dashboard or pipeline."""
    try:
        rows = AnalysisStore(database or warehouse_path()).query(sql)
    except (OSError, ValueError, sqlite3.Error):
        typer.echo("ANALYSIS_READ_ONLY_QUERY_FAILED", err=True)
        raise typer.Exit(2) from None
    if as_csv:
        output = io.StringIO(newline="")
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        typer.echo(output.getvalue(), nl=False)
    else:
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@analysis_app.command("export")
def export(
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    database: Annotated[Path | None, typer.Option("--database")] = None,
) -> None:
    """Print a private derived JSON snapshot; never upload or modify it."""
    try:
        typer.echo(AnalysisStore(database or warehouse_path()).export_json(run_id))
    except (OSError, ValueError, sqlite3.Error):
        typer.echo("ANALYSIS_READ_ONLY_EXPORT_FAILED", err=True)
        raise typer.Exit(2) from None
