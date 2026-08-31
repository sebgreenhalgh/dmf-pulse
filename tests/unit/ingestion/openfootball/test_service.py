from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfileStatus
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    OpenFootballProviderConfig,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)

from .conftest import FakeTransport, ticking_clock

_START = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
_CUTOFF = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def _service(
    config: OpenFootballProviderConfig,
    transport: FakeTransport,
    *,
    profiles: object | None = None,
    clock: object | None = None,
) -> CurrentScorePriorService:
    selected_profiles = load_rights_profiles() if profiles is None else profiles
    selected_clock = ticking_clock(_START) if clock is None else clock
    return CurrentScorePriorService(
        provider_config=config,
        rights_profiles=selected_profiles,  # type: ignore[arg-type]
        transport=transport,
        clock=selected_clock,  # type: ignore[arg-type]
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    )


@pytest.mark.unit
def test_build_emits_exact_weak_league_prior_with_full_lineage(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    transport = FakeTransport(bodies)

    result = _service(config, transport).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=_CUTOFF,
            rights_profile_id=APPROVED_PROFILE_ID,
        )
    )

    assert result.sample_size == 1140
    assert result.home_goal_total == 1839
    assert result.away_goal_total == 1567
    assert result.score_prior_request.home_goal_rate == Decimal("1.613158")
    assert result.score_prior_request.away_goal_rate == Decimal("1.374561")
    assert result.classification == "WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR"
    assert result.provenance.source_mode == "RECONSTRUCTED"
    assert result.provenance.transport_call_count == 4
    assert result.provenance.usable_at <= result.provenance.information_cutoff
    assert result.market_evidence_used is False
    assert result.current_team_strength_claim is False
    assert result.production_active is False
    assert len(result.semantic_sha256) == 64
    assert len(transport.requests) == 4
    assert all(request.host == "raw.githubusercontent.com" for request in transport.requests)
    assert all(config.commit_sha in request.path for request in transport.requests)


@pytest.mark.security
def test_unapproved_rights_profile_blocks_before_transport(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    transport = FakeTransport(bodies)
    approved = load_rights_profiles()[APPROVED_PROFILE_ID]
    blocked = approved.model_copy(update={"status": RightsProfileStatus.DRAFT})

    with pytest.raises(IngestionError) as caught:
        _service(config, transport, profiles={APPROVED_PROFILE_ID: blocked}).build(
            CurrentScorePriorBuildRequest(
                information_cutoff=_CUTOFF,
                rights_profile_id=APPROVED_PROFILE_ID,
            )
        )

    assert caught.value.code == "RIGHTS_BLOCKED"
    assert caught.value.details["transport_call_count"] == 0
    assert transport.requests == []


@pytest.mark.security
def test_cutoff_before_acquisition_blocks_before_transport(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    transport = FakeTransport(bodies)

    with pytest.raises(IngestionError) as caught:
        _service(config, transport).build(
            CurrentScorePriorBuildRequest(
                information_cutoff=datetime(2026, 8, 30, 8, 59, tzinfo=UTC),
                rights_profile_id=APPROVED_PROFILE_ID,
            )
        )

    assert caught.value.code == "POST_CUTOFF"
    assert caught.value.details["transport_call_count"] == 0
    assert transport.requests == []


@pytest.mark.security
def test_tampered_resource_is_rejected_with_exact_call_count(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, original = approved_snapshot
    bodies = dict(original)
    bodies[config.seasons[0].path] += b" "
    transport = FakeTransport(bodies)

    with pytest.raises(IngestionError) as caught:
        _service(config, transport).build(
            CurrentScorePriorBuildRequest(
                information_cutoff=_CUTOFF,
                rights_profile_id=APPROVED_PROFILE_ID,
            )
        )

    assert caught.value.code == "VALIDATION_FAILED"
    assert caught.value.details["transport_call_count"] == 2
    assert len(transport.requests) == 2


@pytest.mark.unit
def test_same_validated_inputs_and_clock_produce_same_semantic_identity(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    request = CurrentScorePriorBuildRequest(
        information_cutoff=_CUTOFF,
        rights_profile_id=APPROVED_PROFILE_ID,
    )

    left = _service(config, FakeTransport(bodies)).build(request)
    right = _service(config, FakeTransport(bodies)).build(request)

    assert left == right
    assert left.semantic_sha256 == right.semantic_sha256
