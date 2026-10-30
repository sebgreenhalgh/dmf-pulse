"""Explicit operator commands; passive status never looks up credentials or a DB."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from pydantic import ValidationError

from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.operation.control import (
    ControlRecoveryRequest,
    ControlSetupRequest,
    init_control,
    recover_control,
)
from dmf_pulse.operation.models import CredentialObservation, Metadata, OperationError, readiness
from dmf_pulse.operation.packages import PilotProposal, prepare_pilot, read_metadata, write_metadata

operation_app = typer.Typer(help="Prepare owner review and recover canonical control metadata.")


def _show(value: Metadata) -> None:
    typer.echo(
        json.dumps(
            {"payload": value.model_dump(mode="json"), "semantic_sha256": value.semantic_sha256},
            sort_keys=True,
            indent=2,
        )
    )


def _fail(error: Exception) -> None:
    code = (
        error.code
        if isinstance(error, (OperationError, AuthorizationError))
        else "OPERATOR_METADATA_INVALID"
    )
    typer.echo(code, err=True)
    raise typer.Exit(2) from None


@operation_app.command("status")
def status_command(
    check_credentials: Annotated[
        bool,
        typer.Option(
            help="Explicitly inspect native presence metadata; never validate with a provider."
        ),
    ] = False,
) -> None:
    """Display all eight independent stages; absent evidence stays NOT_CHECKED."""
    observations: tuple[CredentialObservation, ...] | None = None
    if check_credentials:
        from dmf_pulse.credentials.service import CredentialError, CredentialService

        service = CredentialService()
        rows = []
        for provider in ("odds", "fpl"):
            try:
                value = service.status(provider)
                rows.append(
                    CredentialObservation(
                        provider=provider, configured=value.configured, state=value.state
                    )
                )
            except CredentialError:
                rows.append(
                    CredentialObservation(provider=provider, configured=False, state="UNAVAILABLE")
                )
        observations = tuple(rows)
    _show(readiness(now=datetime.now(UTC), credentials=observations))


@operation_app.command("prepare-pilot")
def prepare_pilot_command(
    authorization_id: Annotated[
        str,
        typer.Option(
            help="Fresh ACCEL004-PILOT- identifier; historical consumed approvals are prohibited."
        ),
    ],
    output: Annotated[Path, typer.Option(help="New immutable metadata-only owner package.")],
    proposal: Annotated[
        Path | None,
        typer.Option(help="Optional authenticated redacted proposal; never a runtime approval."),
    ] = None,
) -> None:
    """Prepare one manual 1-GW, UK h2h+totals, one-GET/two-credit review draft."""
    try:
        draft = (
            PilotProposal(authorization_id=authorization_id)
            if proposal is None
            else read_metadata(proposal, PilotProposal)
        )
        if draft.authorization_id != authorization_id:
            raise OperationError("PILOT_IDENTITY_MISMATCH")
        package = prepare_pilot(draft, now=datetime.now(UTC))
        digest = write_metadata(output, package)
    except (OperationError, AuthorizationError, ValidationError) as error:
        _fail(error)
        return
    typer.echo(
        json.dumps(
            {
                "state": package.state,
                "blockers": package.blockers,
                "artifact_sha256": digest,
                "semantic_sha256": package.semantic_sha256,
                "runtime_authority": "NOT_GRANTED",
            },
            sort_keys=True,
        )
    )


@operation_app.command("init-control")
def init_control_command(
    request: Annotated[
        Path,
        typer.Option(
            help="Authenticated control-metadata setup request; no provider or quota values."
        ),
    ],
    output: Annotated[Path, typer.Option(help="New immutable control receipt.")],
) -> None:
    """Explicitly initialize/reopen the canonical account ledger; no grant is issued."""
    try:
        from dmf_pulse.dashboard.current import _control_connection

        setup = read_metadata(request, ControlSetupRequest)
        receipt = init_control(
            setup, lambda: _control_connection(setup.database_ref), now=datetime.now(UTC)
        )
        write_metadata(output, receipt)
    except (OperationError, AuthorizationError, ValidationError) as error:
        _fail(error)
        return
    _show(receipt)


@operation_app.command("prepare-control")
def prepare_control_command(
    account_ref: Annotated[
        str, typer.Option(help="Opaque canonical quota account identifier; never a credential.")
    ],
    operator_ref: Annotated[str, typer.Option(help="Opaque operator identifier.")],
    control_evidence: Annotated[
        str, typer.Option(help="SHA-256 of explicit control-metadata retention permission.")
    ],
    output: Annotated[
        Path,
        typer.Option(help="New immutable setup/recovery request; this command never connects."),
    ],
    approve_control_metadata: Annotated[
        bool, typer.Option(help="Explicit permission for control metadata only.")
    ] = False,
    ledger_id: Annotated[
        str | None,
        typer.Option(help="Existing expected ledger identity selects read-only recovery."),
    ] = None,
    owned_synthetic: Annotated[
        bool, typer.Option(help="Select the isolated synthetic test database identifier.")
    ] = False,
) -> None:
    """Prepare control-only administration; it grants no provider authority."""
    values = {
        "classification": "OWNED_SYNTHETIC" if owned_synthetic else "PRIVATE_CURRENT",
        "account_ref": account_ref,
        "operator_ref": operator_ref,
        "database_ref": "SYNTHETIC_TEST_DATABASE"
        if owned_synthetic
        else "OPERATOR_CONTROL_DATABASE",
        "control_metadata_retention_approved": approve_control_metadata,
        "control_permission_evidence_sha256": control_evidence,
    }
    try:
        request: Metadata = (
            ControlSetupRequest.model_validate(values)
            if ledger_id is None
            else ControlRecoveryRequest.model_validate({**values, "ledger_id": ledger_id})
        )
        digest = write_metadata(output, request)
    except (OperationError, ValidationError) as error:
        _fail(error)
        return
    typer.echo(
        json.dumps(
            {
                "artifact_sha256": digest,
                "semantic_sha256": request.semantic_sha256,
                "provider_authority": "NOT_GRANTED",
            },
            sort_keys=True,
        )
    )


@operation_app.command("recover-control")
def recover_control_command(
    request: Annotated[
        Path,
        typer.Option(
            help="Authenticated expected account/ledger identity; missing history blocks."
        ),
    ],
    output: Annotated[Path, typer.Option(help="New immutable read-only recovery receipt.")],
) -> None:
    """Reconnect and authenticate existing history without initializing or resetting it."""
    try:
        from dmf_pulse.dashboard.current import _control_connection

        recovery = read_metadata(request, ControlRecoveryRequest)
        receipt = recover_control(
            recovery, lambda: _control_connection(recovery.database_ref), now=datetime.now(UTC)
        )
        write_metadata(output, receipt)
    except (OperationError, AuthorizationError, ValidationError) as error:
        _fail(error)
        return
    _show(receipt)


@operation_app.command("validate-installed")
def validate_installed_command(
    refresh_approval: Annotated[
        str, typer.Option(help="Exact separately reviewed installed enrollment identifier.")
    ],
    entry_id: Annotated[int, typer.Option(min=1)],
    horizon: Annotated[int, typer.Option(min=1, max=3)] = 1,
) -> None:
    """Use shared current scope and locked budget checks without spending or credentials."""
    try:
        from dmf_pulse.operation.validation import validate_installed

        if horizon not in (1, 3):
            raise OperationError("AUTHORIZATION_HORIZON_NOT_APPROVED")
        result = validate_installed(
            authorization_id=refresh_approval,
            entry_id=entry_id,
            horizon=cast(Literal[1, 3], horizon),
        )
    except (OperationError, AuthorizationError, ValidationError) as error:
        _fail(error)
        return
    _show(result)
