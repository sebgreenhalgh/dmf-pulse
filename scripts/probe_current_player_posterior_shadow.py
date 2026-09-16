"""Operator-only transient R9B shadow observation. Never runs a recommendation.

Not executed during R9B engineering acceptance. Existing FPL authority is required;
this script does not grant rights or activate the shadow model.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Literal, Never

from pydantic import Field

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
from dmf_pulse.ingestion.models import FrozenModel, RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles, require_rights
from dmf_pulse.private_v1.automatic_inputs import _player_uuid, _team_uuid

DIAGNOSTIC_SCHEMA_VERSION: Final = "r9c-shadow-probe-diagnostics-v1"


class ShadowProbeFailureReason(StrEnum):
    RIGHTS_CONFIRMATION_FAILED = "RIGHTS_CONFIRMATION_FAILED"
    RIGHTS_CAPABILITY_FAILED = "RIGHTS_CAPABILITY_FAILED"
    CUTOFF_WINDOW_FAILED = "CUTOFF_WINDOW_FAILED"
    FPL_ACQUISITION_FAILED = "FPL_ACQUISITION_FAILED"
    R9A_HISTORY_BUILD_FAILED = "R9A_HISTORY_BUILD_FAILED"
    STALE_PRIOR_POLICY_BUILD_FAILED = "STALE_PRIOR_POLICY_BUILD_FAILED"
    CURRENT_PRIOR_BINDING_FAILED = "CURRENT_PRIOR_BINDING_FAILED"
    HISTORICAL_RESOURCE_LOAD_FAILED = "HISTORICAL_RESOURCE_LOAD_FAILED"
    R9B_SHADOW_COMPILE_FAILED = "R9B_SHADOW_COMPILE_FAILED"
    SAFE_SUMMARY_FAILED = "SAFE_SUMMARY_FAILED"
    UNEXPECTED_INTERNAL_FAILURE = "UNEXPECTED_INTERNAL_FAILURE"


class ShadowProbeFailureStage(StrEnum):
    VALIDATE_RUNTIME_INPUT = "VALIDATE_RUNTIME_INPUT"
    VALIDATE_RIGHTS_REFERENCE = "VALIDATE_RIGHTS_REFERENCE"
    VALIDATE_RIGHTS_CAPABILITIES = "VALIDATE_RIGHTS_CAPABILITIES"
    ACQUIRE_FPL_SNAPSHOT = "ACQUIRE_FPL_SNAPSHOT"
    BUILD_R9A_HISTORY = "BUILD_R9A_HISTORY"
    BUILD_STALE_PRIOR_POLICY = "BUILD_STALE_PRIOR_POLICY"
    BUILD_CURRENT_PRIOR_BINDING = "BUILD_CURRENT_PRIOR_BINDING"
    LOAD_HISTORICAL_RATE_RESOURCE = "LOAD_HISTORICAL_RATE_RESOURCE"
    COMPILE_R9B_SHADOW = "COMPILE_R9B_SHADOW"
    BUILD_SAFE_SUMMARY = "BUILD_SAFE_SUMMARY"
    FINAL_CUTOFF_CHECK = "FINAL_CUTOFF_CHECK"
    INTERNAL = "INTERNAL"


class ShadowProbeBlockedResult(FrozenModel):
    """Closed, aggregate-only result. It deliberately has no error-details field."""

    diagnostic_schema_version: Literal["r9c-shadow-probe-diagnostics-v1"]
    status: Literal["BLOCKED"]
    reason_code: ShadowProbeFailureReason
    failure_stage: ShadowProbeFailureStage
    fpl_acquisition_requests: int = Field(ge=0)
    odds_requests: Literal[0] = 0
    stage7_11_invocations: Literal[0] = 0
    persistence_performed: Literal[False] = False
    model_training_performed: Literal[False] = False
    model_input_status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    retry_performed: Literal[False] = False

    def public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def _blocked(
    reason_code: ShadowProbeFailureReason,
    failure_stage: ShadowProbeFailureStage,
    direct: DirectFplClient | None,
) -> dict[str, object]:
    """Convert a known boundary failure without examining or serialising it."""
    request_count = 0 if direct is None else direct.request_count
    return ShadowProbeBlockedResult(
        diagnostic_schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        status="BLOCKED",
        reason_code=reason_code,
        failure_stage=failure_stage,
        fpl_acquisition_requests=request_count,
    ).public_dict()


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
    """One attempt only; failure payloads never inspect or disclose exceptions."""
    direct: DirectFplClient | None = None
    try:
        approved = clock()
        if (
            approved.tzinfo is None
            or approved.utcoffset() is None
            or type(entry_id) is not int
            or entry_id <= 0
        ):
            return _blocked(
                ShadowProbeFailureReason.RIGHTS_CONFIRMATION_FAILED,
                ShadowProbeFailureStage.VALIDATE_RUNTIME_INPUT,
                direct,
            )
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.RIGHTS_CONFIRMATION_FAILED,
            ShadowProbeFailureStage.VALIDATE_RUNTIME_INPUT,
            direct,
        )
    try:
        profile = load_rights_profiles()[DIRECT_FPL_PROFILE_ID]
        if not confirmed or reference != profile.human_approval_id:
            return _blocked(
                ShadowProbeFailureReason.RIGHTS_CONFIRMATION_FAILED,
                ShadowProbeFailureStage.VALIDATE_RIGHTS_REFERENCE,
                direct,
            )
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.RIGHTS_CONFIRMATION_FAILED,
            ShadowProbeFailureStage.VALIDATE_RIGHTS_REFERENCE,
            direct,
        )
    try:
        for capability in (
            RightsCapability.AUTOMATED_ACCESS,
            RightsCapability.TRANSIENT_PROCESSING,
            RightsCapability.PRIVATE_INTERNAL_USE,
        ):
            require_rights(profile, capability, checked_at=approved)
        cutoff = approved + timedelta(minutes=5)
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.RIGHTS_CAPABILITY_FAILED,
            ShadowProbeFailureStage.VALIDATE_RIGHTS_CAPABILITIES,
            direct,
        )

    try:

        def observed_now() -> datetime:
            now = clock()
            if now.tzinfo is None or now.utcoffset() is None or not approved <= now <= cutoff:
                raise ValueError("observation outside cutoff window")
            return now

        observed_now()
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.CUTOFF_WINDOW_FAILED,
            ShadowProbeFailureStage.VALIDATE_RUNTIME_INPUT,
            direct,
        )
    try:
        # Existing client independently enforces the approved-profile and denied-storage gates.
        direct = DirectFplClient(DirectFplRunAttestation(attested_at=approved))
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.UNEXPECTED_INTERNAL_FAILURE,
            ShadowProbeFailureStage.INTERNAL,
            direct,
        )
    try:
        snapshot = acquire_direct_fpl_snapshot(
            direct, entry_id=entry_id, captured_at=cutoff, clock=observed_now
        )
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.FPL_ACQUISITION_FAILED,
            ShadowProbeFailureStage.ACQUIRE_FPL_SNAPSHOT,
            direct,
        )
    try:
        observed_now()  # Includes the final event-live response, not just bootstrap receipt.
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.CUTOFF_WINDOW_FAILED,
            ShadowProbeFailureStage.FINAL_CUTOFF_CHECK,
            direct,
        )
    try:
        fpl = snapshot.fpl_input
        player_ids = {
            p.provider_element_id: _player_uuid(p.identity.canonical_lookup_sha256)
            for p in fpl.players
        }
        history = build_current_player_history_evidence(snapshot, canonical_player_ids=player_ids)
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.R9A_HISTORY_BUILD_FAILED,
            ShadowProbeFailureStage.BUILD_R9A_HISTORY,
            direct,
        )
    try:
        prior = load_packaged_player_prior()
        policy = build_automatic_current_gw_stale_prior_policy(
            prior,
            fpl,
            current_official_fpl_element_ids=tuple(sorted(player_ids)),
            declared_at=fpl.provenance.information_cutoff,
        )
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.STALE_PRIOR_POLICY_BUILD_FAILED,
            ShadowProbeFailureStage.BUILD_STALE_PRIOR_POLICY,
            direct,
        )
    try:
        binding = build_current_gw_player_prior_binding(
            prior,
            fpl,
            policy,
            canonical_player_ids_by_source_id={
                key: str(value) for key, value in player_ids.items()
            },
            canonical_team_ids_by_source_id={
                t.provider_team_id: str(_team_uuid(t.identity.canonical_lookup_sha256))
                for t in fpl.teams
            },
        )
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.CURRENT_PRIOR_BINDING_FAILED,
            ShadowProbeFailureStage.BUILD_CURRENT_PRIOR_BINDING,
            direct,
        )
    try:
        historical = load_historical_rate_resource()
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.HISTORICAL_RESOURCE_LOAD_FAILED,
            ShadowProbeFailureStage.LOAD_HISTORICAL_RATE_RESOURCE,
            direct,
        )
    try:
        shadow = compile_current_player_shadow(
            history=history,
            current_fpl=fpl,
            binding=binding,
            policy=policy,
            prior=prior,
            historical=historical,
        )
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.R9B_SHADOW_COMPILE_FAILED,
            ShadowProbeFailureStage.COMPILE_R9B_SHADOW,
            direct,
        )
    try:
        result = safe_shadow_summary(shadow, history) | {
            "status": "SHADOW_OBSERVATION_ONLY",
            "stage7_11_invocations": 0,
            "fpl_acquisition_requests": snapshot.request_count,
            "fpl_endpoint_classes": snapshot.endpoint_classes,
            "odds_requests": 0,
            "active_recommendation_path_changed": False,
        }
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.SAFE_SUMMARY_FAILED,
            ShadowProbeFailureStage.BUILD_SAFE_SUMMARY,
            direct,
        )
    try:
        observed_now()
    except Exception:
        return _blocked(
            ShadowProbeFailureReason.CUTOFF_WINDOW_FAILED,
            ShadowProbeFailureStage.FINAL_CUTOFF_CHECK,
            direct,
        )
    return result


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
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
