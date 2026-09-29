"""Consumed L1-L6 history and the exact current L7 one-shot authority.

Legacy function/exception names remain stable; there is no runtime reset/selector.
"""

from datetime import datetime

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.openfootball.team_strength_data import require_team_strength_rights
from dmf_pulse.ingestion.rights import load_rights_profiles as load_fpl_rights

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
L6_APPROVAL = "DMF-CTS-001P-L6-LIVE-RIGHTS-2026-09-28"
L6_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L6#ONE-SHOT-2026-09-28"
L7_APPROVAL = "DMF-CTS-001P-L7-LIVE-RIGHTS-2026-09-29"
L7_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L7#ONE-SHOT-2026-09-29"
APPROVAL = L7_APPROVAL
ATTESTATION = L7_ATTESTATION
CURRENT_APPROVAL = L7_APPROVAL
CURRENT_ATTESTATION = L7_ATTESTATION
CONSUMED_APPROVALS = frozenset(
    {L1_APPROVAL, L2_APPROVAL, L3_APPROVAL, L4_APPROVAL, L5_APPROVAL, L6_APPROVAL}
)
FPL_PROFILE = "fpl_official_private_operator_initiated_read_v1"
ODDS_PROFILE = "the_odds_api_private_analytics_v1"
FPL_PROFILE_SHA = "f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095"
ODDS_PROFILE_SHA = "b0ef596d8438649a369a84687211207b6de632a23c3fb2ced5daf757e2690f3e"


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
    if approval != CURRENT_APPROVAL or attestation != CURRENT_ATTESTATION:
        raise ValueError("current team-strength live authority mismatch")
    fpl = load_fpl_rights()[FPL_PROFILE]
    odds = load_odds_rights()[ODDS_PROFILE]
    if profile_sha(fpl) != FPL_PROFILE_SHA or profile_sha(odds) != ODDS_PROFILE_SHA:
        raise ValueError("L7 exact provider purpose or capability authority differs")
    if any(row.approved_at is None or row.approved_at > checked_at for row in (fpl, odds)):
        raise ValueError("L7 provider approval is unavailable at cutoff")
    require_team_strength_rights()
