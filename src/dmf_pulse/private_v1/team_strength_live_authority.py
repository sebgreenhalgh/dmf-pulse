"""Consumed L1/L2 purposes; no current live authority, acquisition or credentials.

Legacy function/exception names remain stable; there is no runtime reset/selector.
"""

from datetime import datetime

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.models import RightsProfile

L1_APPROVAL = "DMF-CTS-001P-LIVE-RIGHTS-2026-09-22"
L1_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L1#ONE-SHOT-2026-09-22"
# D1's newest human safe record reports consumption. No operator switch may reset
# this ledger; another live purpose/reference requires a separate reviewed ticket.
L2_APPROVAL = "DMF-CTS-001P-L2-LIVE-RIGHTS-2026-09-22"
L2_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L2#ONE-SHOT-2026-09-22"
# Legacy aliases are retained for offline replay/tests only. They do not denote a
# current authority: validation rejects both historical approvals before rights or
# credentials can be consulted.
APPROVAL = L2_APPROVAL
ATTESTATION = L2_ATTESTATION
CONSUMED_APPROVALS = frozenset({L1_APPROVAL, L2_APPROVAL})
FPL_PROFILE = "fpl_official_private_operator_initiated_read_v1"
ODDS_PROFILE = "the_odds_api_private_analytics_v1"
FPL_PROFILE_SHA = "f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095"
ODDS_PROFILE_SHA = "bc5dfa98500459bc50c00e4cd44a30e64e0df04957f383ec8107947ac5350faf"


class ConsumedL1ApprovalError(ValueError):
    """A historical approval cannot authorize another private provider attempt."""


def profile_sha(profile: RightsProfile) -> str:
    return canonical_sha256(
        {
            key: value.isoformat()
            if isinstance(value, datetime)
            else dict(value)
            if key == "capabilities"
            else value
            for key, value in profile
        }
    )


def validate_l1_authority(*, approval: str, attestation: str, checked_at: datetime) -> None:
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("live authority clock must be aware")
    if approval in CONSUMED_APPROVALS:
        raise ConsumedL1ApprovalError("prior live approval consumed; fresh decision required")
    # D2 is offline-only and creates no L3 purpose. Unknown pairs fail before any
    # rights loader (and therefore before any credential/provider boundary).
    del attestation
    raise ValueError("no current live one-shot authority")
