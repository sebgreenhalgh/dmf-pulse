"""Typer commands for strict configuration validation and display."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml  # type: ignore[import-untyped]

from dmf_pulse.config import ConfigError, EnvironmentName, canonical_config, load_config

CONFIG_INVALID_EXIT = 10

config_app = typer.Typer(help="Validate and display strict application configuration.")


def _parse_environment(value: str) -> EnvironmentName:
    try:
        return EnvironmentName(value.casefold())
    except ValueError as exc:
        supported = ", ".join(item.value for item in EnvironmentName)
        raise ConfigError(
            "CONFIG_ENVIRONMENT_INVALID",
            f"environment must be one of: {supported}",
        ) from exc


def _render_error(error: ConfigError) -> None:
    typer.echo(json.dumps(error.as_error_object(), sort_keys=True), err=True)


@config_app.command("validate")
def validate_command(
    environment: Annotated[str, typer.Option("--environment", help="Environment name.")],
    config_root: Annotated[Path, typer.Option("--config-root", help="Configuration root.")],
) -> None:
    """Validate the deterministic base/environment configuration overlays."""

    try:
        parsed_environment = _parse_environment(environment)
        load_config(environment=parsed_environment, config_root=config_root)
    except ConfigError as exc:
        _render_error(exc)
        raise typer.Exit(CONFIG_INVALID_EXIT) from exc
    typer.echo(f"Configuration valid (environment={parsed_environment.value}).")


@config_app.command("show")
def show_command(
    environment: Annotated[str, typer.Option("--environment", help="Environment name.")],
    config_root: Annotated[Path, typer.Option("--config-root", help="Configuration root.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit canonical JSON.")] = False,
) -> None:
    """Show deterministic configuration with defense-in-depth redaction."""

    try:
        parsed_environment = _parse_environment(environment)
        config = load_config(environment=parsed_environment, config_root=config_root)
    except ConfigError as exc:
        _render_error(exc)
        raise typer.Exit(CONFIG_INVALID_EXIT) from exc
    output = canonical_config(config)
    if as_json:
        typer.echo(json.dumps(output, indent=2, sort_keys=True))
    else:
        typer.echo(yaml.safe_dump(output, sort_keys=True).rstrip())
