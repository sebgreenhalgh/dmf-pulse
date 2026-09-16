"""Operator-only transient R9B shadow observation. Never runs a recommendation.

Not executed during R9B engineering acceptance. Existing FPL authority is required;
this script does not grant rights or activate the shadow model.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from dmf_pulse.fpl_points.current_player_posterior import load_historical_rate_resource
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.fpl_points.current_player_shadow_diagnostics import safe_shadow_summary
from dmf_pulse.fpl_points.player_prior import (
    build_automatic_current_gw_stale_prior_policy,
    build_current_gw_player_prior_binding,
    load_packaged_player_prior,
)
from dmf_pulse.ingestion.fpl.current_player_history import build_current_player_history_evidence
from dmf_pulse.ingestion.fpl.direct import (
    DIRECT_FPL_PROFILE_ID,
    DirectFplClient,
    DirectFplRunAttestation,
)
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot, acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles, require_rights
from dmf_pulse.private_v1.automatic_inputs import _player_uuid, _team_uuid


def observe_snapshot(snapshot: DirectFplSnapshot) -> dict[str, object]:
    """Offline-testable post-acquisition boundary: no calls, writes or optimisation."""
    fpl = snapshot.fpl_input
    prior = load_packaged_player_prior()
    player_ids = {
        p.provider_element_id: _player_uuid(p.identity.canonical_lookup_sha256) for p in fpl.players
    }
    history = build_current_player_history_evidence(snapshot, canonical_player_ids=player_ids)
    policy = build_automatic_current_gw_stale_prior_policy(
        prior,
        fpl,
        current_official_fpl_element_ids=tuple(sorted(player_ids)),
        declared_at=fpl.provenance.information_cutoff,
    )
    binding = build_current_gw_player_prior_binding(
        prior,
        fpl,
        policy,
        canonical_player_ids_by_source_id={key: str(value) for key, value in player_ids.items()},
        canonical_team_ids_by_source_id={
            t.provider_team_id: str(_team_uuid(t.identity.canonical_lookup_sha256))
            for t in fpl.teams
        },
    )
    shadow = compile_current_player_shadow(
        history=history,
        current_fpl=fpl,
        binding=binding,
        policy=policy,
        prior=prior,
        historical=load_historical_rate_resource(),
    )
    return safe_shadow_summary(shadow, history) | {
        "status": "SHADOW_OBSERVATION_ONLY",
        "stage7_11_invocations": 0,
        "fpl_acquisition_requests": snapshot.request_count,
        "fpl_endpoint_classes": snapshot.endpoint_classes,
        "odds_requests": 0,
        "active_recommendation_path_changed": False,
    }


def run_operator(
    entry_id: int,
    reference: str | None,
    confirmed: bool,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """No exception text, identifiers or credentials are disclosed on failure."""
    direct: DirectFplClient | None = None
    try:
        approved = clock()
        if (
            approved.tzinfo is None
            or approved.utcoffset() is None
            or type(entry_id) is not int
            or entry_id <= 0
        ):
            raise ValueError("invalid runtime input")
        profile = load_rights_profiles()[DIRECT_FPL_PROFILE_ID]
        if not confirmed or reference != profile.human_approval_id:
            raise ValueError("existing authority not confirmed")
        for capability in (
            RightsCapability.AUTOMATED_ACCESS,
            RightsCapability.TRANSIENT_PROCESSING,
            RightsCapability.PRIVATE_INTERNAL_USE,
        ):
            require_rights(profile, capability, checked_at=approved)
        cutoff = approved + timedelta(minutes=5)

        def observed_now() -> datetime:
            now = clock()
            if now.tzinfo is None or now.utcoffset() is None or not approved <= now <= cutoff:
                raise ValueError("observation outside cutoff window")
            return now

        # Existing client performs its independent approved-profile and denied-storage gates.
        direct = DirectFplClient(DirectFplRunAttestation(attested_at=approved))
        snapshot = acquire_direct_fpl_snapshot(
            direct, entry_id=entry_id, captured_at=cutoff, clock=observed_now
        )
        observed_now()  # Includes the final event-live response, not just bootstrap receipt.
        result = observe_snapshot(snapshot)
        observed_now()
        return result
    except Exception:
        return {
            "status": "BLOCKED",
            "reason": "RIGHTS_INPUT_OR_SHADOW_INTEGRITY_BLOCKED",
            "fpl_acquisition_requests": 0 if direct is None else direct.request_count,
            "odds_requests": 0,
            "stage7_11_invocations": 0,
            "persistence_performed": False,
            "model_training_performed": False,
            "model_input_status": "SHADOW_NOT_MODEL_INPUT",
        }


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "Invalid shadow probe arguments; use --help.\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--entry-id", type=int, required=True)
    parser.add_argument("--rights-approval-reference")
    parser.add_argument("--confirm-approved-scope", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    result = run_operator(
        args.entry_id, args.rights_approval_reference, args.confirm_approved_scope
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "SHADOW_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
