from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.manual_override import build_manual_minutes_override
from dmf_pulse.football_events.minutes_context import (
    Stage7MinutesContext,
    validate_stage7_context,
)
from tests.unit.availability.manual_override_test_support import (
    AWAY_TEAM_ID,
    FIXTURE_ID,
    HOME_TEAM_ID,
    valid_manual_input,
)

pytestmark = pytest.mark.unit


def _context_body() -> dict[str, object]:
    bundle = build_manual_minutes_override(valid_manual_input())
    return Stage7MinutesContext.from_projections(bundle.home, bundle.away).public_dict()


def test_valid_manual_projections_build_and_validate_stage7_context() -> None:
    bundle = build_manual_minutes_override(valid_manual_input())
    context = Stage7MinutesContext.from_projections(bundle.home, bundle.away)
    assert context.home.model_family == "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"
    assert context.away.model_family == "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"
    validate_stage7_context(
        context,
        fixture_id=UUID(FIXTURE_ID),
        home_team_id=UUID(HOME_TEAM_ID),
        away_team_id=UUID(AWAY_TEAM_ID),
        information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
    )


def test_manual_context_pair_rejects_fixture_team_and_asof_mismatch() -> None:
    body = _context_body()
    body["away"]["fixture_id"] = "10000000-0000-7000-8000-000000000999"
    with pytest.raises(ValidationError, match="share fixture_id"):
        Stage7MinutesContext.model_validate(body)

    body = _context_body()
    body["away"]["team_id"] = HOME_TEAM_ID
    with pytest.raises(ValidationError, match="distinct teams"):
        Stage7MinutesContext.model_validate(body)

    body = _context_body()
    body["away"]["as_of"] = "2026-08-20T11:49:59Z"
    with pytest.raises(ValidationError, match="share one as_of"):
        Stage7MinutesContext.model_validate(body)


def test_manual_context_preserves_cutoff_side_and_hash_gates() -> None:
    context = Stage7MinutesContext.model_validate(_context_body())
    with pytest.raises(ValueError, match="POST_CUTOFF_MINUTES"):
        validate_stage7_context(
            context,
            fixture_id=UUID(FIXTURE_ID),
            home_team_id=UUID(HOME_TEAM_ID),
            away_team_id=UUID(AWAY_TEAM_ID),
            information_cutoff=datetime(2026, 8, 20, 11, 49, 59, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="home team_id"):
        validate_stage7_context(
            context,
            fixture_id=UUID(FIXTURE_ID),
            home_team_id=UUID("20000000-0000-7000-8000-000000000099"),
            away_team_id=UUID(AWAY_TEAM_ID),
            information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="away team_id"):
        validate_stage7_context(
            context,
            fixture_id=UUID(FIXTURE_ID),
            home_team_id=UUID(HOME_TEAM_ID),
            away_team_id=UUID("20000000-0000-7000-8000-000000000099"),
            information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
        )

    body = _context_body()
    body["home"]["result_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        Stage7MinutesContext.model_validate(body)


def test_arbitrary_stage7_model_family_remains_rejected() -> None:
    body = _context_body()
    body["home"]["model_family"] = "ARBITRARY_MANUAL_STRING"
    with pytest.raises(ValidationError):
        Stage7MinutesContext.model_validate(body)
