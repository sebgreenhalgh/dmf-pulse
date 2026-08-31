"""Private operator CLI for CURRENT-AVAILABILITY-001B."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError

from dmf_pulse.availability.manual_override import (
    MANUAL_MODEL_FAMILY,
    ManualOverrideError,
    build_manual_minutes_override,
    load_manual_fixture_minutes,
    manual_transient_policy_artifact,
)
from dmf_pulse.availability.projection import canonical_sha256
from dmf_pulse.football_events.minutes_context import Stage7MinutesContext

PRIVATE_OUTPUT_MARKER = "dmf-private-transient"


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject(code: str, message: str) -> NoReturn:
    typer.echo(json.dumps({"error": {"code": code, "message": message}}, sort_keys=True), err=True)
    raise typer.Exit(2)


def _private_output_root(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if PRIVATE_OUTPUT_MARKER not in {part.lower() for part in resolved.parts}:
        raise ManualOverrideError(
            "PRIVATE_OUTPUT_REQUIRED",
            f"--output-dir must be within a directory named {PRIVATE_OUTPUT_MARKER}",
        )
    candidate = path
    while candidate != candidate.parent:
        if candidate.exists() and candidate.is_symlink():
            raise ManualOverrideError(
                "PRIVATE_OUTPUT_UNSAFE", "private output path must not traverse a symlink"
            )
        candidate = candidate.parent
    if path.exists() and not path.is_dir():
        raise ManualOverrideError(
            "PRIVATE_OUTPUT_UNSAFE", "private output path must be a directory"
        )
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ManualOverrideError(
            "PRIVATE_OUTPUT_UNSAFE", "private output path must not be a symlink"
        )
    return path.resolve(strict=True)


def _preflight_immutable(root: Path, documents: Mapping[str, bytes]) -> None:
    for name, body in documents.items():
        target = root / name
        if target.exists() and (
            target.is_symlink() or not target.is_file() or target.read_bytes() != body
        ):
            raise ManualOverrideError(
                "PRIVATE_OUTPUT_CONFLICT", "an existing transient artifact has different bytes"
            )


def _write_immutable(root: Path, name: str, body: bytes) -> None:
    target = root / name
    if target.exists():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != body:
            raise ManualOverrideError(
                "PRIVATE_OUTPUT_CONFLICT", "an existing transient artifact has different bytes"
            )
        return
    created = False
    try:
        with target.open("xb") as handle:
            created = True
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if created and target.is_file() and not target.is_symlink():
            target.unlink()
        raise


def _documents(input_value: Any, bundle: Any) -> dict[str, bytes]:
    context = Stage7MinutesContext.from_projections(bundle.home, bundle.away)
    documents = {
        "away-team-minutes-projection.json": _json_bytes(bundle.away.model_dump(mode="json")),
        "home-team-minutes-projection.json": _json_bytes(bundle.home.model_dump(mode="json")),
        "manual-input.canonical.json": _json_bytes(input_value.model_dump(mode="json")),
        "stage7-minutes-context.json": _json_bytes(context.public_dict()),
    }
    manifest_body: dict[str, object] = {
        "artifacts": {
            name: {"bytes": len(body), "sha256": _sha256(body)}
            for name, body in sorted(documents.items())
        },
        "classification": "PRIVATE_TRANSIENT",
        "dataset_sha256": bundle.dataset_sha256,
        "fixture_id": bundle.fixture_id,
        "manual_bundle_sha256": bundle.semantic_sha256,
        "model_derived": False,
        "model_family": MANUAL_MODEL_FAMILY,
        "persistence_class": "TRANSIENT_PRIVATE",
        "production_suitable": False,
        "provenance": input_value.provenance.model_dump(mode="json"),
        "provenance_sha256": bundle.provenance_sha256,
        "schema_version": "private-manual-transient-manifest-v1",
        "stage7_minutes_context_sha256": context.semantic_sha256,
        "team_result_sha256": {
            "away": bundle.away.result_sha256,
            "home": bundle.home.result_sha256,
        },
        "transformation_policy": manual_transient_policy_artifact(),
        "transformation_policy_sha256": bundle.transformation_policy_sha256,
    }
    manifest_body["semantic_sha256"] = canonical_sha256(manifest_body)
    documents["manual-override-manifest.json"] = _json_bytes(manifest_body)
    return documents


def manual_override_command(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Strict private-manual-transient-minutes-v1 JSON input.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            file_okay=True,
            dir_okay=True,
            help="Output below an explicitly named dmf-private-transient directory.",
        ),
    ],
) -> None:
    """Materialize one private, transient, non-model-derived Stage-7 fixture context."""

    try:
        input_value = load_manual_fixture_minutes(input_path)
        bundle = build_manual_minutes_override(input_value)
        root = _private_output_root(output_dir)
        documents = _documents(input_value, bundle)
        _preflight_immutable(root, documents)
        for name, body in sorted(documents.items()):
            _write_immutable(root, name, body)
    except ManualOverrideError as exc:
        _reject(exc.code, exc.message)
    except ValidationError:
        _reject("MANUAL_OVERRIDE_INVALID", "manual override output failed validation")
    except (OSError, ValueError, ArithmeticError):
        _reject("MANUAL_OVERRIDE_FAILED", "manual override could not be materialized safely")
    typer.echo(
        json.dumps(
            {
                "artifact_names": sorted(documents),
                "classification": "PRIVATE_TRANSIENT",
                "dataset_sha256": bundle.dataset_sha256,
                "fixture_id": bundle.fixture_id,
                "model_derived": False,
                "model_family": MANUAL_MODEL_FAMILY,
                "production_suitable": False,
                "schema_version": "private-manual-transient-command-v1",
                "status": "PROJECTED",
            },
            sort_keys=True,
        )
    )


__all__ = ["manual_override_command"]
