"""Safe offline operator commands for GW1 player evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputRequest, CurrentFplInputService
from dmf_pulse.player_evidence.approvals import (
    SECOND_RETRY_APPROVAL_SHA256,
    load_player_history_rights_approval,
    validate_second_retry_capture_authorization,
)
from dmf_pulse.player_evidence.catalogue import build_current_player_history_catalogue
from dmf_pulse.player_evidence.diagnostic_approval import (
    DIAGNOSTIC_APPROVAL_SHA256,
    load_zero_minute_diagnostic_approval,
)
from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.history import (
    ApprovedCaptureRequest,
    UrllibHistoryTransport,
    bind_posterior_to_deletion_manifest,
    capture_approved_history,
    future_capture_endpoint,
    validate_capture_request,
)
from dmf_pulse.player_evidence.models import (
    CaptureAccessMode,
    CurrentPlayerCatalogue,
    HistorySensitivityWorld,
    PlayerHistoryRightsApproval,
    PriceWorld,
    RetentionMode,
    SyntheticReplayRequest,
    candidate_price_policy,
)
from dmf_pulse.player_evidence.profiles import build_allocation_candidate
from dmf_pulse.player_evidence.role_priors import (
    candidate_eb_parameters_from_role_prior,
    load_role_prior_candidate,
    role_priors_from_candidate,
)
from dmf_pulse.player_evidence.zero_minute_diagnostic import (
    ApprovedZeroMinuteDiagnosticRequest,
    OneShotUrllibDiagnosticTransport,
    execute_zero_minute_diagnostic,
    resolve_zero_minute_diagnostic_target,
    validate_zero_minute_diagnostic_request,
)

player_evidence_app = typer.Typer(help="Build offline-first GW1 player-evidence candidates.")

_GW1_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
_ACCEPTED_ROLE_PRIOR_SHA256 = "007e4d400d8f72eccc50541a9e9b385042bd3eb5d724b0b1d76e7cc69f42afb8"


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


def _parse_utc(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestionError("TEMPORAL_INVALID", f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _validate_new_output_paths(
    *,
    outputs: tuple[Path, ...],
    inputs: tuple[Path, ...],
) -> None:
    resolved_outputs = tuple(path.resolve() for path in outputs)
    resolved_inputs = {path.resolve() for path in inputs}
    if len(resolved_outputs) != len(set(resolved_outputs)):
        raise IngestionError("OUTPUT_UNAVAILABLE", "derived artifact output paths must be distinct")
    if any(path in resolved_inputs for path in resolved_outputs):
        raise IngestionError("OUTPUT_UNAVAILABLE", "derived output must not overwrite an input")
    if any(path.exists() for path in resolved_outputs):
        raise IngestionError("OUTPUT_UNAVAILABLE", "derived artifact output already exists")


def _write_derived(path: Path, value: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pretty_json(value), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise IngestionError(
            "OUTPUT_UNAVAILABLE", "derived artifact output is unavailable"
        ) from exc


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
        if expected_approval_sha256 != SECOND_RETRY_APPROVAL_SHA256:
            raise IngestionError(
                "RIGHTS_APPROVAL_HASH_MISMATCH",
                "live history capture requires the second retry approval hash",
            )
        approval_value = load_player_history_rights_approval(
            approval, expected_approval_sha256=expected_approval_sha256
        )
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
    except (IngestionError, ValidationError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else (
                IngestionError("HISTORY_MODEL_VALIDATION_FAILED", "history model validation failed")
                if isinstance(exc, ValidationError)
                else IngestionError("TEMPORAL_INVALID", "information cutoff is invalid")
            )
        )
        _emit(error.as_error_object())
        raise typer.Exit(2) from None


@player_evidence_app.command("capture-current-history")
def capture_current_history_command(
    approval: Annotated[
        Path | None, typer.Option("--approval", exists=True, dir_okay=False, readable=True)
    ] = None,
    expected_approval_sha256: Annotated[
        str | None, typer.Option("--expected-approval-sha256")
    ] = None,
    bootstrap: Annotated[
        Path | None, typer.Option("--bootstrap", exists=True, dir_okay=False, readable=True)
    ] = None,
    fixtures: Annotated[
        Path | None, typer.Option("--fixtures", exists=True, dir_okay=False, readable=True)
    ] = None,
    captured_at: Annotated[str | None, typer.Option("--captured-at")] = None,
    information_cutoff: Annotated[str | None, typer.Option("--information-cutoff")] = None,
    terms_fingerprint: Annotated[str | None, typer.Option("--terms-fingerprint")] = None,
    maximum_player_count: Annotated[int | None, typer.Option("--maximum-player-count")] = None,
    retention_mode: Annotated[
        RetentionMode, typer.Option("--retention-mode")
    ] = RetentionMode.POSTERIOR_ONLY,
    role_prior: Annotated[
        Path | None, typer.Option("--role-prior", exists=True, dir_okay=False, readable=True)
    ] = None,
    central_posterior_output: Annotated[
        Path | None, typer.Option("--central-posterior-output", dir_okay=False)
    ] = None,
    low_posterior_output: Annotated[
        Path | None, typer.Option("--low-posterior-output", dir_okay=False)
    ] = None,
    high_posterior_output: Annotated[
        Path | None, typer.Option("--high-posterior-output", dir_okay=False)
    ] = None,
    allocation_output: Annotated[
        Path | None, typer.Option("--allocation-output", dir_okay=False)
    ] = None,
    deletion_manifest_output: Annotated[
        Path | None, typer.Option("--deletion-manifest-output", dir_okay=False)
    ] = None,
    execute_network: Annotated[bool, typer.Option("--execute-network")] = False,
) -> None:
    """Capture approved current history through one transient Stage-7 identity bridge.

    This command deliberately has no current-catalogue output option.  It reads
    a fresh operator-supplied manual FPL pair into memory, binds exact Stage-7
    surrogate UUIDs, serially captures history only after every approval gate,
    and writes only the allowed posterior/candidate/deletion artifacts.
    """

    try:
        required = (
            approval,
            expected_approval_sha256,
            bootstrap,
            fixtures,
            captured_at,
            information_cutoff,
            terms_fingerprint,
            maximum_player_count,
            role_prior,
            central_posterior_output,
            low_posterior_output,
            high_posterior_output,
            allocation_output,
            deletion_manifest_output,
        )
        if any(value is None for value in required):
            raise IngestionError(
                "RIGHTS_APPROVAL_REQUIRED",
                "accepted rights approval and governed manual inputs are required",
            )
        assert approval is not None
        assert expected_approval_sha256 is not None
        assert bootstrap is not None
        assert fixtures is not None
        assert captured_at is not None
        assert information_cutoff is not None
        assert terms_fingerprint is not None
        assert maximum_player_count is not None
        assert role_prior is not None
        assert central_posterior_output is not None
        assert low_posterior_output is not None
        assert high_posterior_output is not None
        assert allocation_output is not None
        assert deletion_manifest_output is not None
        cutoff = _parse_utc(information_cutoff, label="information cutoff")
        if cutoff != _GW1_CUTOFF:
            raise IngestionError(
                "TEMPORAL_INVALID", "information cutoff is not the approved GW1 cutoff"
            )
        _validate_new_output_paths(
            outputs=(
                central_posterior_output,
                low_posterior_output,
                high_posterior_output,
                allocation_output,
                deletion_manifest_output,
            ),
            inputs=(approval, bootstrap, fixtures, role_prior),
        )
        rights_approval = load_player_history_rights_approval(
            approval, expected_approval_sha256=expected_approval_sha256
        )
        role_prior_candidate = load_role_prior_candidate(role_prior)
        if role_prior_candidate.artifact_sha256 != _ACCEPTED_ROLE_PRIOR_SHA256:
            raise IngestionError(
                "ARTIFACT_HASH_MISMATCH", "role-prior artifact is not accepted for GW1"
            )
        bundle = CurrentFplInputService().compile(
            CurrentFplInputRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                competition_key="PL",
                season_code="2026/27",
                captured_at=_parse_utc(captured_at, label="captured_at"),
                information_cutoff=cutoff,
                rights_profile_id="fpl_official_private_manual_v1",
                gameweek=1,
            )
        )
        if bundle.target_event.deadline_at != cutoff:
            raise IngestionError(
                "DEADLINE_MISMATCH", "current GW1 deadline does not match the cutoff"
            )
        catalogue = build_current_player_history_catalogue(bundle)
        validate_second_retry_capture_authorization(
            rights_approval,
            expected_approval_sha256=expected_approval_sha256,
            catalogue_semantic_sha256=catalogue.semantic_sha256 or "",
        )
        request = ApprovedCaptureRequest(
            approval=rights_approval,
            expected_approval_sha256=expected_approval_sha256,
            catalogue=catalogue,
            information_cutoff=cutoff,
            maximum_player_count=maximum_player_count,
            terms_fingerprint=terms_fingerprint,
            retention_mode=retention_mode,
            minimum_interval_seconds=1.0,
        )
        validate_capture_request(request)
        if not execute_network:
            raise IngestionError(
                "NETWORK_EXECUTION_DISABLED",
                "add --execute-network after reviewing the fresh input summary",
            )
        capture = capture_approved_history(
            request,
            transport=UrllibHistoryTransport(),
            clock=lambda: datetime.now(UTC),
        )
        produced_at = datetime.now(UTC)
        if produced_at > cutoff:
            raise IngestionError(
                "POST_CUTOFF", "posterior compilation is after the information cutoff"
            )
        observed_at = min(capture.source_observed_at.values(), default=produced_at)
        role_priors = role_priors_from_candidate(role_prior_candidate)
        central = compile_posterior_artifact(
            catalogue=catalogue,
            histories=capture.evidence,
            role_priors=role_priors,
            tactical_roles={},
            parameters=candidate_eb_parameters_from_role_prior(
                role_prior_candidate, world=HistorySensitivityWorld.CENTRAL_TEMPORARY
            ),
            information_cutoff=cutoff,
            source_observed_at=observed_at,
            usable_at=produced_at,
            produced_at=produced_at,
            source_locator=rights_approval.source_url_template,
            schema_fingerprint=capture.schema_fingerprint,
            rights_profile_id=rights_approval.rights_profile_id,
            source_hashes=capture.source_hashes,
            source_observed_ats=capture.source_observed_at,
        )
        low = compile_posterior_artifact(
            catalogue=catalogue,
            histories=capture.evidence,
            role_priors=role_priors,
            tactical_roles={},
            parameters=candidate_eb_parameters_from_role_prior(
                role_prior_candidate, world=HistorySensitivityWorld.LOW_SHRINKAGE
            ),
            information_cutoff=cutoff,
            source_observed_at=observed_at,
            usable_at=produced_at,
            produced_at=produced_at,
            source_locator=rights_approval.source_url_template,
            schema_fingerprint=capture.schema_fingerprint,
            rights_profile_id=rights_approval.rights_profile_id,
            source_hashes=capture.source_hashes,
            source_observed_ats=capture.source_observed_at,
        )
        high = compile_posterior_artifact(
            catalogue=catalogue,
            histories=capture.evidence,
            role_priors=role_priors,
            tactical_roles={},
            parameters=candidate_eb_parameters_from_role_prior(
                role_prior_candidate, world=HistorySensitivityWorld.HIGH_SHRINKAGE
            ),
            information_cutoff=cutoff,
            source_observed_at=observed_at,
            usable_at=produced_at,
            produced_at=produced_at,
            source_locator=rights_approval.source_url_template,
            schema_fingerprint=capture.schema_fingerprint,
            rights_profile_id=rights_approval.rights_profile_id,
            source_hashes=capture.source_hashes,
            source_observed_ats=capture.source_observed_at,
        )
        allocation = build_allocation_candidate(
            catalogue=catalogue,
            posterior=central,
            role_priors=role_priors,
            tactical_roles={},
            information_cutoff=cutoff,
            price_policy=candidate_price_policy(PriceWorld.PRICE_OFF),
            degraded_player_allocation=False,
        )
        deletion_manifest = bind_posterior_to_deletion_manifest(
            capture.deletion_manifest, posterior_artifact_sha256=central.artifact_sha256
        )
        history_by_player = {row.player_id: row for row in capture.evidence}
        lineage_by_player = {row.player_id: row for row in allocation.lineage}
        history_count = sum(bool(row.seasons) for row in capture.evidence)
        individual_goal_count = sum(
            row.posterior_effective_minutes > 0.0 for row in central.players
        )
        individual_assist_count = individual_goal_count
        established_goalkeeper_save_count = sum(
            bool(history_by_player[row.player_id].seasons) and row.position.value == "GK"
            for row in catalogue.players
        )
        generic_fallback_count = sum(
            lineage_by_player[row.player_id].goal_source_level.value == "LEAGUE_GENERIC"
            for row in catalogue.players
        )
        role_or_position_fallback_count = sum(
            lineage_by_player[row.player_id].goal_source_level.value != "INDIVIDUAL"
            for row in catalogue.players
        )
        _write_derived(central_posterior_output, central)
        _write_derived(low_posterior_output, low)
        _write_derived(high_posterior_output, high)
        _write_derived(allocation_output, allocation)
        _write_derived(deletion_manifest_output, deletion_manifest)
        summary = {
            "actual_history_request_count": len(capture.evidence),
            "allocation_artifact_sha256": allocation.artifact_sha256,
            "capture_failure_count": 0,
            "catalogue_semantic_sha256": catalogue.semantic_sha256,
            "current_catalogue_persisted": False,
            "current_player_count": len(catalogue.players),
            "current_player_identity_mode": catalogue.identity_mode.value,
            "current_team_count": len(bundle.teams),
            "deletion_manifest_sha256": canonical_sha256(deletion_manifest.model_dump(mode="json")),
            "defensive_contribution_model_completeness": "PARTIAL",
            "established_goalkeeper_individual_save_posterior_count": established_goalkeeper_save_count,
            "generic_fallback_count": generic_fallback_count,
            "history_schema_failure_count": 0,
            "history_source_hash_commitment_sha256": canonical_sha256(
                {
                    str(player_id): source_hash
                    for player_id, source_hash in capture.source_hashes.items()
                }
            ),
            "information_cutoff": cutoff.isoformat().replace("+00:00", "Z"),
            "individual_assist_posterior_count": individual_assist_count,
            "individual_goal_posterior_count": individual_goal_count,
            "no_fpl_history_count": len(capture.evidence) - history_count,
            "player_ids_match_stage7": True,
            "position_counts": bundle.safe_summary().position_counts,
            "post_cutoff_failure_count": 0,
            "raw_fpl_history_persisted": False,
            "real_odds_provider_call": "NOT_PERFORMED",
            "role_or_position_fallback_count": role_or_position_fallback_count,
            "schema_version": "gw1-current-player-history-capture-command-v1",
            "source_bootstrap_semantic_sha256": bundle.provenance.bootstrap_semantic_sha256,
            "source_bundle_semantic_sha256": bundle.semantic_sha256,
            "stage7_minutes_separate_from_player_event_priors": True,
            "successful_history_observed_at_max": max(capture.source_observed_at.values())
            .isoformat()
            .replace("+00:00", "Z"),
            "successful_history_observed_at_min": min(capture.source_observed_at.values())
            .isoformat()
            .replace("+00:00", "Z"),
            "successful_history_count": len(capture.evidence),
            "team_ids_match_stage7": True,
            "unresolved_current_player_mappings": 0,
        }
        del bundle
        del catalogue
        del capture
        _emit(summary)
    except (IngestionError, ValidationError, OSError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else (
                IngestionError("HISTORY_MODEL_VALIDATION_FAILED", "history model validation failed")
                if isinstance(exc, ValidationError)
                else IngestionError(
                    "CAPTURE_INPUT_INVALID", "current history capture input is invalid"
                )
            )
        )
        _emit(error.as_error_object())
        raise typer.Exit(2) from None


@player_evidence_app.command("diagnose-zero-minute-history")
def diagnose_zero_minute_history_command(
    approval: Annotated[
        Path | None, typer.Option("--approval", exists=True, dir_okay=False, readable=True)
    ] = None,
    expected_approval_sha256: Annotated[
        str | None, typer.Option("--expected-approval-sha256")
    ] = None,
    bootstrap: Annotated[
        Path | None, typer.Option("--bootstrap", exists=True, dir_okay=False, readable=True)
    ] = None,
    fixtures: Annotated[
        Path | None, typer.Option("--fixtures", exists=True, dir_okay=False, readable=True)
    ] = None,
    captured_at: Annotated[str | None, typer.Option("--captured-at")] = None,
    information_cutoff: Annotated[str | None, typer.Option("--information-cutoff")] = None,
    terms_fingerprint: Annotated[str | None, typer.Option("--terms-fingerprint")] = None,
    execute_network: Annotated[bool, typer.Option("--execute-network")] = False,
) -> None:
    """Diagnose one hash-bound history row without invoking the bulk capture path."""

    try:
        required = (
            approval,
            expected_approval_sha256,
            bootstrap,
            fixtures,
            captured_at,
            information_cutoff,
            terms_fingerprint,
        )
        if any(value is None for value in required):
            raise IngestionError(
                "DIAGNOSTIC_APPROVAL_REQUIRED",
                "the exact single-row diagnostic approval and manual inputs are required",
            )
        assert approval is not None
        assert expected_approval_sha256 is not None
        assert bootstrap is not None
        assert fixtures is not None
        assert captured_at is not None
        assert information_cutoff is not None
        assert terms_fingerprint is not None
        if expected_approval_sha256 != DIAGNOSTIC_APPROVAL_SHA256:
            raise IngestionError(
                "DIAGNOSTIC_APPROVAL_HASH_MISMATCH",
                "the single-row diagnostic requires its exact approval hash",
            )
        diagnostic_approval = load_zero_minute_diagnostic_approval(
            approval, expected_approval_sha256=expected_approval_sha256
        )
        cutoff = _parse_utc(information_cutoff, label="information cutoff")
        bundle = CurrentFplInputService().compile(
            CurrentFplInputRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                competition_key="PL",
                season_code="2026/27",
                captured_at=_parse_utc(captured_at, label="captured_at"),
                information_cutoff=cutoff,
                rights_profile_id="fpl_official_private_manual_v1",
                gameweek=1,
            )
        )
        if bundle.target_event.deadline_at != cutoff:
            raise IngestionError(
                "DEADLINE_MISMATCH", "current GW1 deadline does not match the cutoff"
            )
        catalogue = build_current_player_history_catalogue(bundle)
        target = resolve_zero_minute_diagnostic_target(catalogue)
        request = ApprovedZeroMinuteDiagnosticRequest(
            approval=diagnostic_approval,
            target=target,
            catalogue=catalogue,
            information_cutoff=cutoff,
            terms_fingerprint=terms_fingerprint,
        )
        validate_zero_minute_diagnostic_request(request)
        if not execute_network:
            raise IngestionError(
                "NETWORK_EXECUTION_DISABLED",
                "add --execute-network only after exact-SHA Ubuntu validation",
                details={
                    "catalogue_semantic_sha256": catalogue.semantic_sha256,
                    "current_fpl_catalogue_persisted": False,
                    "diagnostic_request_count": 0,
                    "raw_fpl_history_persisted": False,
                    "target_identity_sha256": target.identity_sha256,
                    "target_ordinal": target.ordinal,
                    "target_position": target.position,
                },
            )
        result = execute_zero_minute_diagnostic(
            request,
            transport=OneShotUrllibDiagnosticTransport(),
            clock=lambda: datetime.now(UTC),
        )
        safe = result.safe_dict()
        safe.update(
            {
                "catalogue_semantic_sha256": catalogue.semantic_sha256 or "",
                "diagnostic_approval_sha256": diagnostic_approval.approval_sha256,
                "schema_version": "gw1-zero-minute-history-diagnostic-result-v1",
                "target_identity_sha256": target.identity_sha256,
                "target_ordinal": target.ordinal,
                "target_position": target.position,
            }
        )
        del bundle
        del catalogue
        del target
        _emit(safe)
    except (IngestionError, ValidationError, OSError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, IngestionError)
            else IngestionError(
                "DIAGNOSTIC_INPUT_INVALID", "zero-minute diagnostic input is invalid"
            )
        )
        _emit(error.as_error_object())
        raise typer.Exit(2) from None


__all__ = ["player_evidence_app"]
