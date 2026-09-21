from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_COMMIT_SHA,
    APPROVED_PROFILE_ID,
    TEAM_STRENGTH_APPROVED_PROFILE_ID,
    load_provider_config,
    load_rights_profiles,
    provider_config_sha256,
    rights_config_sha256,
)


@pytest.mark.contract
def test_approved_provider_snapshot_is_exact() -> None:
    config = load_provider_config()

    assert config.commit_sha == APPROVED_COMMIT_SHA
    assert tuple(season.season_code for season in config.seasons) == (
        "2023/24",
        "2024/25",
        "2025/26",
    )
    assert sum(season.expected_matches for season in config.seasons) == 1140
    assert sum(season.home_goals for season in config.seasons) == 1839
    assert sum(season.away_goals for season in config.seasons) == 1567
    assert config.expected_home_goal_rate == Decimal("1.613158")
    assert config.expected_away_goal_rate == Decimal("1.374561")
    assert config.licence.blob_sha1 == "670154e3538863b2d9891fd5483160fbdfc89164"
    assert len(provider_config_sha256()) == 64


@pytest.mark.contract
def test_human_approved_rights_profile_is_exact_and_private() -> None:
    profile = load_rights_profiles()[APPROVED_PROFILE_ID]

    assert profile.approved_by == "Sebastian Greenhalgh"
    assert profile.human_approval_id == (
        "CURRENT-SCORE-PRIOR-001A#openfootball_football_json_score_prior_v1"
    )
    assert profile.capabilities[RightsCapability.AUTOMATED_ACCESS] is CapabilityValue.ALLOW
    assert profile.capabilities[RightsCapability.MODEL_TRAINING] is CapabilityValue.ALLOW
    assert profile.capabilities[RightsCapability.PUBLIC_DISPLAY] is CapabilityValue.DENY
    assert profile.capabilities[RightsCapability.REDISTRIBUTION] is CapabilityValue.DENY
    assert profile.retention_seconds is None
    assert profile.unresolved_rights == ()
    assert len(rights_config_sha256()) == 64


@pytest.mark.contract
def test_team_strength_rights_profile_is_purpose_bound_and_private() -> None:
    profiles = load_rights_profiles()
    profile = profiles[TEAM_STRENGTH_APPROVED_PROFILE_ID]

    assert set(profiles) == {APPROVED_PROFILE_ID, TEAM_STRENGTH_APPROVED_PROFILE_ID}
    assert profile.approved_by == "Sebastian Greenhalgh"
    assert profile.human_approval_id == (
        "CURRENT-TEAM-STRENGTH-001A#openfootball_football_json_team_strength_v1"
    )
    assert profile.profile_version == "1.0.0"
    assert profile.approved_purpose == (
        "Private internal Premier League team-strength estimation and private internal "
        "fixture-specific score-prior generation for DMF Pulse."
    )
    allowed = {
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.RAW_STORAGE,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.CACHE,
        RightsCapability.BACKUP,
        RightsCapability.MODEL_TRAINING,
        RightsCapability.PRIVATE_INTERNAL_USE,
        RightsCapability.MANUAL_IMPORT,
    }
    assert all(profile.capabilities[item] is CapabilityValue.ALLOW for item in allowed)
    assert profile.capabilities[RightsCapability.PUBLIC_DISPLAY] is CapabilityValue.DENY
    assert profile.capabilities[RightsCapability.REDISTRIBUTION] is CapabilityValue.DENY
    assert profile.retention_seconds is None
    assert profile.retention_reason is not None
    for required_provenance in (
        "source commit",
        "source path",
        "content hashes",
        "licence identity",
        "retrieval time",
        "usable_at provenance",
    ):
        assert required_provenance in profile.retention_reason
    assert profile.geography_scope == "private UK analytical use"
    assert profile.unresolved_rights == ()


@pytest.mark.security
def test_mutable_or_unapproved_resource_path_is_refused() -> None:
    config = load_provider_config()

    with pytest.raises(IngestionError, match="allowlisted"):
        config.raw_path("master/en.1.json")
