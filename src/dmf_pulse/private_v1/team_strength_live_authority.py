"""Consumed L1/L2/L3/L4/L5 history with no current live authority.

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
L3_APPROVAL = "DMF-CTS-001P-L3-LIVE-RIGHTS-2026-09-23"
L3_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L3#ONE-SHOT-2026-09-23"
L4_APPROVAL = "DMF-CTS-001P-L4-LIVE-RIGHTS-2026-09-24"
L4_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L4#ONE-SHOT-2026-09-24"
L5_APPROVAL = "DMF-CTS-001P-L5-LIVE-RIGHTS-2026-09-27"
L5_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L5#ONE-SHOT-2026-09-27"
APPROVAL = L5_APPROVAL
ATTESTATION = L5_ATTESTATION
CURRENT_APPROVAL: None = None
CURRENT_ATTESTATION: None = None
CONSUMED_APPROVALS = frozenset({L1_APPROVAL, L2_APPROVAL, L3_APPROVAL, L4_APPROVAL, L5_APPROVAL})
FPL_PROFILE = "fpl_official_private_operator_initiated_read_v1"
ODDS_PROFILE = "the_odds_api_private_analytics_v1"
FPL_PROFILE_SHA = "f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095"
ODDS_PROFILE_SHA = "34280931d9874c5921791776973acade047df4d588f25a5046a8f842f2dbe388"


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
    raise ValueError("no current team-strength live authority exists")
