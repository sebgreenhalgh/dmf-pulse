from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from dmf_pulse.football_events.service import ScorePriorRequest
from dmf_pulse.ingestion.openfootball import service as score_prior_service
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorResult,
    CurrentScorePriorSummary,
)


@pytest.mark.contract
def test_approved_rates_bind_to_existing_stage8_orientation_contract() -> None:
    prior = ScorePriorRequest.model_validate_json(
        '{"away_goal_rate":"1.374561","home_goal_rate":"1.613158",'
        '"model_family":"INDEPENDENT_POISSON_V1"}'
    )

    assert prior.home_goal_rate == Decimal("1.613158")
    assert prior.away_goal_rate == Decimal("1.374561")
    assert prior.public_dict() == {
        "away_goal_rate": "1.374561",
        "home_goal_rate": "1.613158",
        "model_family": "INDEPENDENT_POISSON_V1",
    }


@pytest.mark.contract
def test_public_result_and_summary_freeze_non_claim_boundaries() -> None:
    result_schema = CurrentScorePriorResult.model_json_schema()
    summary_schema = CurrentScorePriorSummary.model_json_schema()

    for schema in (result_schema, summary_schema):
        serialized = str(schema)
        assert "WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR" in serialized
        assert "production_active" in serialized
        assert "market_evidence_used" in serialized
        assert "current_team_strength_claim" in serialized
    assert "ScorePriorRequest" in result_schema["$defs"]


@pytest.mark.contract
def test_score_prior_implementation_has_no_current_market_dependency() -> None:
    source = inspect.getsource(score_prior_service)

    assert "dmf_pulse.markets" not in source
    assert "market_consensus" not in source
    assert '"market_evidence_used": False' in source
