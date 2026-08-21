"""Synthetic-only builders for GW1-PLY-001 tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.player_evidence.models import (
    CaptureAccessMode,
    CurrentPlayer,
    CurrentPlayerCatalogue,
    EvidenceSourceLevel,
    HistorySensitivityWorld,
    PlayerHistoryRightsApproval,
    PriceWorld,
    RetentionMode,
    RolePooledPrior,
    SyntheticReplayRequest,
    candidate_eb_parameters,
    candidate_price_policy,
)
from tests.support.factories import base_participants, zero_bps_rates

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
SHA = "a" * 64


def catalogue() -> CurrentPlayerCatalogue:
    players = tuple(
        sorted(
            (
                CurrentPlayer(
                    player_id=UUID(item.player_id),
                    source_player_id=index,
                    team_id=UUID(item.team_id),
                    position=item.position,
                    current_price_tenths=50 + index,
                )
                for index, item in enumerate(base_participants(), start=1)
            ),
            key=lambda item: str(item.player_id),
        )
    )
    return CurrentPlayerCatalogue(source_catalogue_semantic_sha256=SHA, players=players)


def generic_prior() -> RolePooledPrior:
    return RolePooledPrior(
        shrinkage_group_id="synthetic-league-generic",
        source_level=EvidenceSourceLevel.LEAGUE_GENERIC,
        fallback_reason="SYNTHETIC_ROLE_PRIOR_FOR_OFFLINE_TESTS",
        prior_version="SYNTHETIC-ROLE-PRIOR-V1",
        source_reference="synthetic://GW1-PLY-001/role-prior",
        goal_rate_per90=0.10,
        assist_rate_per90=0.08,
        yellow_rate_per90=0.12,
        red_rate_per90=0.01,
        save_rate_per90=2.0,
        goal_role_adjustment=1.0,
        assist_role_adjustment=1.0,
        penalty_weight=0.10,
        own_goal_weight=0.01,
        saves_inside_box_fraction=0.70,
        clearances_per90=2.0,
        blocks_per90=1.0,
        interceptions_per90=1.0,
        tackles_per90=1.0,
        ball_recoveries_per90=2.0,
        bps_auxiliary=zero_bps_rates(),
    )


def eb_parameters():
    return candidate_eb_parameters(HistorySensitivityWorld.CENTRAL_TEMPORARY)


def price_policy():
    return candidate_price_policy(world=PriceWorld.PRICE_OFF)


def replay(*, histories=()) -> SyntheticReplayRequest:
    return SyntheticReplayRequest(
        catalogue=catalogue(),
        histories=histories,
        role_priors=(generic_prior(),),
        information_cutoff=NOW,
        source_observed_at=NOW.replace(hour=10),
        usable_at=NOW.replace(hour=11),
        produced_at=NOW.replace(minute=30),
        schema_fingerprint=SHA,
        eb_parameters=eb_parameters(),
        price_policy=price_policy(),
    )


def approval(
    *, schema_fingerprint: str, source_hash_permitted: bool = False
) -> PlayerHistoryRightsApproval:
    values = {
        "status": "HUMAN_ACCEPTED",
        "scope": "PRIVATE_2026_27_GW1_ONLY",
        "rights_profile_id": "TEST_ONLY_PLAYER_HISTORY_RIGHTS",
        "source_url_template": "https://fantasy.premierleague.com/api/element-summary/{current_element_id}/",
        "allowed_node": "history_past",
        "access_mode": CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT,
        "raw_retention": "FORBIDDEN",
        "derived_retention": RetentionMode.POSTERIOR_ONLY,
        "redistribution": "NONE",
        "repeat_collection": "REQUIRES_NEW_APPROVAL",
        "source_hash_permitted": source_hash_permitted,
        "terms_fingerprint": "b" * 64,
        "history_past_schema_fingerprint": schema_fingerprint,
        "approved_by": "synthetic-test-only",
        "approved_at": NOW,
    }
    provisional = PlayerHistoryRightsApproval.model_construct(
        **values,
        approval_sha256="0" * 64,
    )
    return PlayerHistoryRightsApproval(
        **values,
        approval_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"approval_sha256"})
        ),
    )
