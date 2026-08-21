"""Safe offline operator commands for GW1 player evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.history import (
    ApprovedCaptureRequest,
    UrllibHistoryTransport,
    capture_approved_history,
    future_capture_endpoint,
    validate_capture_request,
)
from dmf_pulse.player_evidence.models import (
    CaptureAccessMode,
    CurrentPlayerCatalogue,
    PlayerHistoryRightsApproval,
    RetentionMode,
    SyntheticReplayRequest,
)
from dmf_pulse.player_evidence.profiles import build_allocation_candidate

player_evidence_app = typer.Typer(help="Build offline-first GW1 player-evidence candidates.")


def _emit(value: dict[str, Any]) -> None:
    typer.echo(json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True))


def _load(
    path: Path,
    model: type[SyntheticReplayRequest]
    | type[CurrentPlayerCatalogue]
    | type[PlayerHistoryRightsApproval],
) -> Any:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise IngestionError("REPLAY_INPUT_INVALID", "operator input is invalid") from exc


def _replay(path: Path, *, degraded: bool) -> tuple[Any, Any]:
    replay = _load(path, SyntheticReplayRequest)
    roles = {row.player_id: row.tactical_role for row in replay.tactical_roles}
    posterior = compile_posterior_artifact(
        catalogue=replay.catalogue,
        histories=() if degraded else replay.histories,
        role_priors=replay.role_priors,
        tactical_roles=roles,
        parameters=replay.eb_parameters,
        information_cutoff=replay.information_cutoff,
        source_observed_at=replay.source_observed_at,
        usable_at=replay.usable_at,
        produced_at=replay.produced_at,
        source_locator="synthetic://GW1-PLY-001/replay",
        schema_fingerprint=replay.schema_fingerprint,
        rights_profile_id="SYNTHETIC_REPLAY_ONLY",
    )
    allocation = build_allocation_candidate(
        catalogue=replay.catalogue,
        posterior=posterior,
        role_priors=replay.role_priors,
        tactical_roles=roles,
        information_cutoff=replay.information_cutoff,
        price_policy=replay.price_policy,
        degraded_player_allocation=degraded,
    )
    return posterior, allocation


def _safe_replay_summary(posterior: Any, allocation: Any) -> dict[str, Any]:
    return {
        "allocation_artifact_sha256": allocation.artifact_sha256,
        "approval_present": False,
        "degraded_player_allocation": allocation.degraded_player_allocation,
        "fallback_count": sum(
            row.goal_source_level.value != "INDIVIDUAL" for row in allocation.lineage
        ),
        "player_count": len(allocation.profiles),
        "posterior_artifact_sha256": posterior.artifact_sha256,
        "raw_persistence": False,
        "rights_mode": "SYNTHETIC_REPLAY_ONLY",
        "schema_version": "gw1-player-evidence-command-v1",
    }


@player_evidence_app.command("rights-status")
def rights_status_command() -> None:
    """Show the required, still-absent human rights decision without networking."""

    _emit(
        {
            "approval_present": False,
            "allowed_node": "history_past",
            "future_source_url_template": future_capture_endpoint(),
            "next_state": "READY_FOR_PLAYER_HISTORY_RIGHTS_APPROVAL_AND_CAPTURE",
            "raw_persistence": False,
            "required_access_mode": CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT.value,
            "required_retention_mode": RetentionMode.POSTERIOR_ONLY.value,
            "schema_version": "gw1-player-evidence-rights-status-v1",
        }
    )


@player_evidence_app.command("synthetic-dry-run")
def synthetic_dry_run_command(
    replay: Annotated[Path, typer.Option("--replay", exists=True, dir_okay=False, readable=True)],
) -> None:
    """Compile a synthetic/replay posterior and Stage-9 profile candidate in memory."""

    try:
        posterior, allocation = _replay(replay, degraded=False)
        _emit(_safe_replay_summary(posterior, allocation))
    except IngestionError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None


@player_evidence_app.command("posterior-compile")
def posterior_compile_command(
    replay: Annotated[Path, typer.Option("--replay", exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
) -> None:
    """Write only a synthetic posterior artifact—never its synthetic input rows."""

    try:
        posterior, allocation = _replay(replay, degraded=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(pretty_json(posterior), encoding="utf-8", newline="\n")
        summary = _safe_replay_summary(posterior, allocation)
        summary["posterior_artifact_path"] = str(output)
        _emit(summary)
    except (OSError, IngestionError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else IngestionError("OUTPUT_UNAVAILABLE", "posterior output is unavailable")
        )
        _emit(error.as_error_object())
        raise typer.Exit(2) from None


@player_evidence_app.command("emergency-degraded")
def emergency_degraded_command(
    replay: Annotated[Path, typer.Option("--replay", exists=True, dir_okay=False, readable=True)],
) -> None:
    """Build a complete no-history allocation fallback from role/position priors."""

    try:
        posterior, allocation = _replay(replay, degraded=True)
        _emit(_safe_replay_summary(posterior, allocation))
    except IngestionError as exc:
        _emit(exc.as_error_object())
        raise typer.Exit(2) from None


@player_evidence_app.command("capture-history")
def capture_history_command(
    approval: Annotated[
        Path | None, typer.Option("--approval", exists=True, dir_okay=False, readable=True)
    ] = None,
    expected_approval_sha256: Annotated[
        str | None, typer.Option("--expected-approval-sha256")
    ] = None,
    catalogue: Annotated[
        Path | None, typer.Option("--catalogue", exists=True, dir_okay=False, readable=True)
    ] = None,
    information_cutoff: Annotated[str | None, typer.Option("--information-cutoff")] = None,
    maximum_player_count: Annotated[int | None, typer.Option("--maximum-player-count")] = None,
    terms_fingerprint: Annotated[str | None, typer.Option("--terms-fingerprint")] = None,
    retention_mode: Annotated[
        RetentionMode, typer.Option("--retention-mode")
    ] = RetentionMode.POSTERIOR_ONLY,
    execute_network: Annotated[bool, typer.Option("--execute-network")] = False,
) -> None:
    """Future serial capture, locked until a matching human approval is supplied."""

    try:
        if (
            approval is None
            or expected_approval_sha256 is None
            or catalogue is None
            or information_cutoff is None
            or maximum_player_count is None
            or terms_fingerprint is None
        ):
            raise IngestionError(
                "RIGHTS_APPROVAL_REQUIRED", "explicit human rights approval is required"
            )
        approval_value = _load(approval, PlayerHistoryRightsApproval)
        catalogue_value = _load(catalogue, CurrentPlayerCatalogue)
        cutoff = datetime.fromisoformat(information_cutoff.replace("Z", "+00:00"))
        request = ApprovedCaptureRequest(
            approval=approval_value,
            expected_approval_sha256=expected_approval_sha256,
            catalogue=catalogue_value,
            information_cutoff=cutoff,
            maximum_player_count=maximum_player_count,
            terms_fingerprint=terms_fingerprint,
            retention_mode=retention_mode,
        )
        validate_capture_request(request)
        if not execute_network:
            raise IngestionError(
                "NETWORK_EXECUTION_DISABLED", "add --execute-network after approval review"
            )
        result = capture_approved_history(
            request,
            transport=UrllibHistoryTransport(),
            clock=lambda: datetime.now(UTC),
        )
        _emit(
            {
                "approval_present": True,
                "deletion_status": result.deletion_manifest.deletion_outcome,
                "expected_count": maximum_player_count,
                "fallback_count": sum(not item.seasons for item in result.evidence),
                "posterior_artifact_sha256": result.deletion_manifest.posterior_artifact_sha256,
                "raw_persistence": False,
                "requested_count": maximum_player_count,
                "rights_mode": approval_value.access_mode.value,
                "schema_version": "gw1-player-history-capture-command-v1",
                "success_count": len(result.evidence),
            }
        )
    except (IngestionError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else IngestionError("TEMPORAL_INVALID", "information cutoff is invalid")
        )
        _emit(error.as_error_object())
        raise typer.Exit(2) from None


__all__ = ["player_evidence_app"]
