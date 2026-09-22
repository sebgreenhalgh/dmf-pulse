"""Exact one-shot L1 purpose authority; no acquisition or credential access."""

from datetime import datetime

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.openfootball.team_strength_data import require_team_strength_rights
from dmf_pulse.ingestion.rights import load_rights_profiles as load_fpl_rights

APPROVAL = "DMF-CTS-001P-LIVE-RIGHTS-2026-09-22"
ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L1#ONE-SHOT-2026-09-22"
# D1's newest human safe record reports consumption. No operator switch may reset
# this ledger; another live purpose/reference requires a separate reviewed ticket.
CONSUMED_APPROVALS = frozenset({APPROVAL})
FPL_PROFILE = "fpl_official_private_operator_initiated_read_v1"
ODDS_PROFILE = "the_odds_api_private_analytics_v1"
FPL_PROFILE_SHA = "f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095"
ODDS_PROFILE_SHA = "be1b0c045fbba995e8f518f95c9f814e92ec61745acde4b481e97ae5b9f1be0e"


class ConsumedL1ApprovalError(ValueError):
    """The historical approval cannot authorize another private provider attempt."""


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
        raise ValueError("L1 authority clock must be aware")
    if approval != APPROVAL or attestation != ATTESTATION:
        raise ValueError("L1 one-shot authority differs")
    if approval in CONSUMED_APPROVALS:
        raise ConsumedL1ApprovalError("prior L1 approval consumed; fresh decision required")
    fpl = load_fpl_rights()[FPL_PROFILE]
    odds = load_odds_rights()[ODDS_PROFILE]
    if profile_sha(fpl) != FPL_PROFILE_SHA or profile_sha(odds) != ODDS_PROFILE_SHA:
        raise ValueError("L1 exact provider purpose or capability authority differs")
    if any(row.approved_at is None or row.approved_at > checked_at for row in (fpl, odds)):
        raise ValueError("L1 provider approval is unavailable at cutoff")
    require_team_strength_rights()
