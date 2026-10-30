"""One current recommendation through the enrolled dashboard worker and ledger."""

from __future__ import annotations

from typing import Annotated, Literal, cast

import typer

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.operation.console import run_enrolled_current

_ACTIONS = {
    "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED": "Enroll a reviewed refresh approval; run dmf operation status.",
    "PRODUCTION_APPROVAL_NOT_ENROLLED": "Install the reviewed enrollment wheel; run dmf operation status.",
    "CREDENTIAL_UNAVAILABLE": "Configure the required credentials with dmf credentials; check dmf credentials status.",
    "CREDENTIAL_NOT_CONFIGURED": "Configure the required credentials with dmf credentials; check dmf credentials status.",
    "CREDENTIAL_EXPIRED": "Replace the expired FPL token with dmf credentials set-fpl-token --replace --expires-at <actual-expiry>.",
    "CREDENTIAL_CORRUPT": "Explicitly replace the invalid entry through dmf credentials.",
    "CREDENTIAL_BACKEND_UNAVAILABLE": "Use the correct Windows user session and check Windows Credential Manager.",
    "FPL_AUTH_REQUIRED": "Obtain an authorized current FPL token and replace it through dmf credentials.",
    "AUTHORIZATION_REVOKED": "Obtain a new reviewed approval; this approval was revoked.",
    "AUTHORIZATION_EXPIRED": "Obtain a new reviewed approval and current official deadline evidence.",
    "REFRESH_GRANT_EXPIRED": "Obtain a new reviewed approval and current official deadline evidence.",
    "ACQUISITION_CUTOFF_PASSED": "The acquisition window closed; obtain a new reviewed scope.",
    "ONE_SHOT_CONSUMED": "This attempt is spent; a fresh explicit authorization is required.",
    "QUOTA_EXHAUSTED": "Qualify remaining account credits and obtain an approved budget before retrying.",
    "DAILY_BUDGET_EXHAUSTED": "The approved daily request budget is spent.",
    "MONTHLY_BUDGET_EXHAUSTED": "The approved monthly credit budget is spent.",
    "SOURCE_REQUEST_BUDGET_EXHAUSTED": "The approved source attempt budget is spent.",
    "USAGE_LEDGER_UNAVAILABLE": "Recover the existing canonical control ledger with dmf operation recover-control.",
    "USAGE_LEDGER_IDENTITY_MISMATCH": "Recover the expected canonical ledger; do not initialize a replacement.",
    "IMPLEMENTATION_IDENTITY_CHANGED": "Install the exact reviewed wheel and its matching enrollment.",
    "AUTHORIZATION_SCOPE_MISMATCH": "Use the exact approved manager and source scope.",
    "AUTHORIZATION_HORIZON_NOT_APPROVED": "Use an approved one- or three-GW horizon.",
    "AUTHORIZATION_DEADLINE_SCOPE_MISMATCH": "Qualify the exact official deadline in the installed approval.",
    "RUN_TIMEOUT": "The worker timed out; inspect control usage before any authorized retry.",
    "QUALIFIED_QUOTA_EVIDENCE_STALE": "Qualify fresh dated remaining-credit evidence; no live quota probe is authorized.",
    "AUTHORIZATION_DEADLINE_INVALID": "Replace invalid or expired official deadline evidence in a reviewed approval.",
    "USAGE_LEDGER_SCHEMA_NOT_READY": "Install and run the accepted canonical control migration before recovery.",
    "SOURCE_PROFILE_CHANGED": "Review the changed provider terms/profile and enroll its exact current hash.",
    "OFFICIAL_DEADLINE_SCOPE_MISMATCH": "Use the exact target Gameweek and qualified official deadline.",
    "ACQUISITION_CLOSED": "The acquisition phase is closed; use a fresh reviewed attempt if needed.",
    "ACQUISITION_WINDOW_EXCEEDED": "Reduce acquisition to the reviewed time window or obtain a new approval.",
    "AUTHORIZATION_CLOCK_INVALID": "Correct the local UTC clock before retrying an authorized operation.",
    "AUTHORIZATION_CLOCK_REGRESSED": "Correct the local UTC clock and recover the existing control ledger.",
    "CONTROL_DATABASE_REFERENCE_INVALID": "Configure the accepted private control database reference.",
    "MANAGER_SCOPE_INVALID": "Use the exact manager entry approved for this refresh.",
    "OPERATOR_CONTROL_CONTEXT_REQUIRED": "Complete canonical control setup and reviewed enrollment with dmf operation.",
    "OWNED_SOURCE_INJECTION_REQUIRED": "Use owned injected sources for this synthetic acceptance run.",
    "PRIVATE_CONTROL_DATABASE_REQUIRED": "Use the canonical private control database for a real refresh.",
    "PRODUCTION_CONTROL_STORE_NOT_ACCEPTED": "Use the accepted PostgreSQL control ledger and installed enrollment.",
    "REFRESH_GRANT_ALREADY_CLAIMED": "This grant was already claimed; audit usage before a fresh authorized attempt.",
    "REFRESH_GRANT_INVALID": "Recover the canonical ledger and exact reviewed enrollment; do not edit a grant.",
    "REFRESH_GRANT_NOT_CLAIMED": "Launch through the enrolled worker; a copied grant cannot authorize acquisition.",
    "SOURCE_CLASSIFICATION_MISMATCH": "Keep real and owned synthetic source enrollments separate.",
    "SOURCE_PROFILE_NOT_AVAILABLE": "Install the exact reviewed provider profile before refresh.",
    "SOURCE_ROUTE_NOT_AUTHORIZED": "Use only the source routes in the installed approval.",
    "SOURCE_SCOPE_INVALID": "Qualify the exact source scope and purpose before enrollment.",
    "TRUSTED_APPROVAL_REGISTRY_INVALID": "Reinstall the reviewed wheel; arbitrary approval JSON is not accepted.",
    "USAGE_LEDGER_ACCOUNT_MISMATCH": "Recover the existing ledger for the exact approved quota account.",
    "USAGE_LEDGER_BACKEND_INVALID": "Use the canonical PostgreSQL ledger backend for private current refresh.",
    "USAGE_LEDGER_CAPACITY_REACHED": "Review and maintain the existing ledger without resetting spent usage.",
    "USAGE_LEDGER_CONFIGURATION_INVALID": "Correct the canonical control database configuration.",
    "USAGE_LEDGER_IDENTITY_INVALID": "Recover the expected canonical ledger identity; do not invent a replacement.",
    "USAGE_LEDGER_INITIALIZATION_FAILED": "Inspect canonical control initialization before repeating explicit setup.",
    "USAGE_LEDGER_INVALID": "Recover and audit the existing ledger; do not reset its usage history.",
    "USAGE_LEDGER_REQUIRED": "Complete explicit canonical control setup with dmf operation.",
    "USAGE_LEDGER_TRANSACTION_REQUIRED": "Use the accepted transactional control database adapter.",
    "WORKER_CLEANUP_FAILED": "Close the session and resolve worker cleanup before any new refresh.",
    "WORKER_RESULT_BINDING_INVALID": "Discard this result and inspect the exact installed worker/enrollment identity.",
}


def pulse_command(
    entry_id: Annotated[int, typer.Option("--entry-id", min=1, help="Private FPL entry ID.")],
    horizon_gameweeks: Annotated[
        int,
        typer.Option(
            "--horizon-gameweeks",
            help="Optimisation horizon: 1 (default) or explicit rolling 3-GW mode.",
        ),
    ] = 1,
    no_progress: Annotated[
        bool,
        typer.Option("--no-progress", help="Suppress human progress output on STDERR."),
    ] = False,
    refresh_approval: Annotated[
        str | None,
        typer.Option("--refresh-approval", help="Reviewed approval ID in the installed registry."),
    ] = None,
) -> None:
    """Publish one read-only current recommendation under an installed approval."""
    if horizon_gameweeks not in {1, 3}:
        typer.echo("--horizon-gameweeks must be exactly 1 or 3.", err=True)
        raise typer.Exit(2)
    if not refresh_approval:
        typer.echo("A reviewed refresh approval is required. Run dmf operation status.", err=True)
        raise typer.Exit(2)
    try:
        run_enrolled_current(
            authorization_id=refresh_approval,
            entry_id=entry_id,
            horizon=cast(Literal[1, 3], horizon_gameweeks),
            publish=lambda view: typer.echo(view.team.report),
            progress=None if no_progress else lambda value: typer.echo(value, err=True),
        )
    except AuthorizationError as error:
        # Fixed known diagnostics preserve the required operator action without
        # copying arbitrary worker/transport text into the console.
        code = error.code
        if type(code) is str and code in _ACTIONS:
            message = f"{code}: {_ACTIONS[code]}"
        else:
            message = (
                "Current refresh was blocked or expired. Run dmf operation status for readiness."
            )
        typer.echo(message, err=True)
        raise typer.Exit(2) from None


__all__ = ["pulse_command"]
