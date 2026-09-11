"""Operator-invoked R8A probe. No automatic output files or recommendation stages."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DIRECT_FPL_TOKEN_ENV,
    DirectFplClient,
    DirectFplRunAttestation,
)
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.client import OddsClient, OddsFetchFailure
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import EnvironmentOddsCredentialProvider
from dmf_pulse.ingestion.odds.horizon_probe import (
    PROFILE_ID,
    classify_horizon,
    horizon_window,
    verify_observation,
)
from dmf_pulse.ingestion.rights import require_rights

# Published-source date reported by supplied R8 research S23, not an approval.
REPORTED_TERMS_DATE = date(2026, 8, 31)
PENDING_REVIEW = "PRIVATE-V1-ONE-COMMAND-001N-R8A/RIGHTS-REVIEW-PENDING"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "Invalid probe arguments; use --help.\n")


def live_rights_blocker(
    profile: RightsProfile, reference: str | None, scope_confirmed: bool, now: datetime
) -> str | None:
    """A runtime flag cannot ratify terms or upgrade the checked-in rights profile."""
    try:
        reviewed_terms_date = date.fromisoformat(profile.terms_version.removeprefix("checked-"))
    except ValueError:
        return "CURRENT_TERMS_AND_APPLICABLE_ACCOUNT_REVIEW_PENDING"
    if (
        profile.rights_profile_id != PROFILE_ID
        or reviewed_terms_date < REPORTED_TERMS_DATE
        or profile.checked_at.date() < REPORTED_TERMS_DATE
        or profile.approved_at is None
        or profile.approved_at.date() < REPORTED_TERMS_DATE
        or "future approved" in profile.account_scope.casefold()
    ):
        return "CURRENT_TERMS_AND_APPLICABLE_ACCOUNT_REVIEW_PENDING"
    if not scope_confirmed or reference != profile.human_approval_id:
        return "EXISTING_PURPOSE_ACCOUNT_GEOGRAPHY_AUTHORITY_NOT_CONFIRMED"
    for capability in (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    ):
        try:
            require_rights(profile, capability, checked_at=now)
        except IngestionError:
            return "RIGHTS_BLOCKED"
    return None


def acquire_probe(
    *,
    entry_id: int,
    approved_at: datetime,
    direct_client: DirectFplClient,
    odds_client: OddsClient,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Reuse the accepted full FPL snapshot; make exactly one logical Odds request.

    Called only after the entrypoint's rights/operator gates. Injectable clients
    are for offline tests, not a new public-only FPL transport or target policy.
    """
    cutoff = (approved_at + timedelta(minutes=5)).replace(microsecond=0)

    def observed_now() -> datetime:
        value = clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise IngestionError("VALIDATION_FAILED", "probe clock must be aware")
        value = value.astimezone(UTC)
        if not approved_at <= value <= cutoff:
            raise IngestionError("POST_CUTOFF", "probe acquisition window exceeded")
        return value

    if (
        approved_at.tzinfo is None
        or approved_at.utcoffset() is None
        or isinstance(entry_id, bool)
        or entry_id <= 0
    ):
        raise IngestionError("VALIDATION_FAILED", "probe runtime input is invalid")
    started = observed_now()
    snapshot = acquire_direct_fpl_snapshot(
        direct_client, entry_id=entry_id, captured_at=cutoff, clock=observed_now
    )
    start, end = horizon_window(snapshot.fpl_input)
    observed_now()
    fetched = odds_client.fetch(commence_from=start, commence_to=end)
    assessed = observed_now()
    observation = classify_horizon(
        fetched, snapshot.fpl_input, assessed_at=assessed, usable_at=assessed
    )
    observation = replace(observation, usable_at=observed_now())
    verify_observation(observation, fetched, snapshot.fpl_input)
    observed_now()
    summary = observation.safe_summary()
    summary.update(
        {
            "probe_started_at": started.isoformat(),
            "fpl_transport_attempts": direct_client.request_count,
            "odds_logical_requests": 1,
            "openfootball_invocations": 0,
        }
    )
    return summary


def _failure(
    reason: str, *, status: str = "NOT_ATTEMPTED", fpl_attempts: int = 0, odds_attempts: int = 0
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "rights_review_reference": PENDING_REVIEW,
        "consensus": "NOT_EVALUATED",
        "stage8_acceptance": "NOT_EVALUATED",
        "fpl_transport_attempts": fpl_attempts,
        "odds_transport_attempts": odds_attempts,
        "model_stage_invocations": 0,
        "openfootball_invocations": 0,
        "persistence_performed": False,
    }


def run_operator(
    entry_id: int,
    reference: str | None,
    scope_confirmed: bool,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Do not expose exceptions, private entry values, environment or provider strings."""
    direct: DirectFplClient | None = None
    odds: OddsClient | None = None
    result: dict[str, object]
    try:
        approved = clock()
        profile = load_rights_profiles()[PROFILE_ID]
        blocker = live_rights_blocker(profile, reference, scope_confirmed, approved)
        if blocker is not None:
            return _failure(blocker)
        credential = EnvironmentOddsCredentialProvider()
        if not credential._configured():
            return _failure("ODDS_CREDENTIAL_UNAVAILABLE")
        if not os.environ.get(DIRECT_FPL_TOKEN_ENV, "").strip():
            return _failure("FPL_CREDENTIAL_UNAVAILABLE")
        direct = DirectFplClient(DirectFplRunAttestation(attested_at=approved))
        odds = OddsClient(profile, credential_provider=credential, clock=clock)
        result = acquire_probe(
            entry_id=entry_id,
            approved_at=approved,
            direct_client=direct,
            odds_client=odds,
            clock=clock,
        )
    except Exception as exc:
        # Safe fixed vocabulary only. Never stringify exceptions or their details.
        reason = "PROBE_FAILED"
        if isinstance(exc, IngestionError):
            if exc.code in {"CREDENTIAL_MISSING", "CREDENTIAL_INVALID", "CREDENTIAL_UNAVAILABLE"}:
                reason = "RUNTIME_CREDENTIAL_UNAVAILABLE"
            elif exc.code == "POST_CUTOFF":
                reason = "POST_CUTOFF"
            elif isinstance(exc, OddsFetchFailure):
                reason = "ODDS_ACQUISITION_FAILED"
            else:
                reason = "INPUT_OR_INTEGRITY_BLOCKED"
        result = _failure(
            reason,
            status="FAILED",
            fpl_attempts=0 if direct is None else direct.request_count,
            odds_attempts=0 if odds is None else odds.transport_call_count,
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--entry-id", type=int, required=True)
    parser.add_argument(
        "--rights-approval-reference", help="Existing human approval identifier; not a credential"
    )
    parser.add_argument(
        "--confirm-approved-scope",
        action="store_true",
        help="Confirm existing private-purpose/account/geography authority applies",
    )
    # Argument errors must not echo a private identifier or accidentally pasted token.
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    result = run_operator(
        args.entry_id, args.rights_approval_reference, args.confirm_approved_scope
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0 if result["status"] == "OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
