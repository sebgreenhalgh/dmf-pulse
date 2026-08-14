import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.service import (
    DerivedOutputPolicy,
    ScoreDistributionError,
    ScoreDistributionRequest,
    ScoreDistributionResult,
    ScoreDistributionService,
    ScoreGridPolicy,
    ScorePriorRequest,
    ScoreProjectionPolicy,
    explain_market_fit,
    load_joint_score_distribution,
    load_score_distribution_request,
    persist_joint_score_distribution,
)


def _stage7_request_fields(fixture_id: UUID, as_of: datetime) -> dict[str, object]:
    source_as_of = as_of.replace(minute=max(0, as_of.minute - 10))
    home_team_id = UUID("20000000-0000-7000-8000-000000000001")
    away_team_id = UUID("20000000-0000-7000-8000-000000000002")

    def identity(side: str, team_id: UUID) -> dict[str, object]:
        fixture_text = str(fixture_id)
        return {
            "schema_version": "team-minutes-projection-v1",
            "fixture_id": fixture_text,
            "team_id": str(team_id),
            "as_of": source_as_of.isoformat().replace("+00:00", "Z"),
            "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
            "dataset_sha256": hashlib.sha256(b"GCS-008 Stage-7 dataset").hexdigest(),
            "model_artifact_sha256": hashlib.sha256(b"GCS-008 Stage-7 model").hexdigest(),
            "sample_count": 256,
            "scenario_set_sha256": hashlib.sha256(
                f"{fixture_text}:{side}:scenarios".encode()
            ).hexdigest(),
            "result_sha256": hashlib.sha256(
                f"{fixture_text}:{side}:team-minutes-projection-v1".encode()
            ).hexdigest(),
        }

    return {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "minutes_context": {
            "schema_version": "stage7-minutes-context-v1",
            "home": identity("home", home_team_id),
            "away": identity("away", away_team_id),
        },
    }


pytestmark = pytest.mark.unit
FIXTURES = Path("fixtures/events/score/GCS-008")


def test_cancelled_fixture_is_blocked() -> None:
    request = load_score_distribution_request(FIXTURES / "postponed_fixture.json").model_copy(
        update={"fixture_status": "CANCELLED"}
    )
    result = ScoreDistributionService().project(request)
    assert result.status == "BLOCKED"
    assert result.error_code == "FIXTURE_CANCELLED"


def test_abandoned_fixture_is_blocked_with_specific_error() -> None:
    request = load_score_distribution_request(FIXTURES / "postponed_fixture.json").model_copy(
        update={"fixture_status": "ABANDONED"}
    )
    result = ScoreDistributionService().project(request)
    assert result.status == "BLOCKED"
    assert result.error_code == "FIXTURE_ABANDONED"


def test_prior_rate_above_policy_range_is_rejected() -> None:
    request = ScoreDistributionRequest.model_validate(
        {
            "schema_version": "score-distribution-request-v1",
            "fixture_id": UUID("10000000-0000-7000-8000-000000000890"),
            "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
            **_stage7_request_fields(
                UUID("10000000-0000-7000-8000-000000000890"),
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            ),
            "prior": ScorePriorRequest.model_validate(
                {"home_goal_rate": Decimal("9"), "away_goal_rate": Decimal("1")}
            ),
        }
    )
    with pytest.raises(ScoreDistributionError) as raised:
        ScoreDistributionService().project(request)
    assert raised.value.code == "PRIOR_RATE_OUT_OF_RANGE"
    assert raised.value.as_error_object()["error"]["code"] == "PRIOR_RATE_OUT_OF_RANGE"


def test_request_rejects_parallel_generic_and_stage6_evidence() -> None:
    constraint = MarketConstraint.model_validate(
        {
            "constraint_id": "home",
            "family": MarketFamily.ONE_X_TWO,
            "event": ScoreEvent.HOME_WIN,
            "target_probability": Decimal("0.5"),
            "uncertainty": Decimal("0.02"),
            "usable_at": datetime(2026, 8, 20, 11, tzinfo=UTC),
        }
    )
    with pytest.raises(ValidationError, match="either constraints"):
        ScoreDistributionRequest.model_validate(
            {
                "schema_version": "score-distribution-request-v1",
                "fixture_id": UUID("10000000-0000-7000-8000-000000000891"),
                "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
                **_stage7_request_fields(
                    UUID("10000000-0000-7000-8000-000000000891"),
                    datetime(2026, 8, 20, 12, tzinfo=UTC),
                ),
                "prior": ScorePriorRequest.model_validate(
                    {"home_goal_rate": Decimal("1"), "away_goal_rate": Decimal("1")}
                ),
                "constraints": (constraint,),
                "market_consensus": json.loads(
                    Path("fixtures/events/score/GCS-008/stage6_consensus_fixture.json").read_text(
                        encoding="utf-8"
                    )
                )["market_consensus"],
            }
        )


def test_policy_models_reject_invalid_boundaries() -> None:
    with pytest.raises(ValidationError):
        ScoreGridPolicy.model_validate(
            {
                "minimum_max_goals": 10,
                "maximum_max_goals": 5,
                "tail_tolerance": Decimal("0.001"),
                "hard_tail_limit": Decimal("0.01"),
            }
        )
    with pytest.raises(ValidationError):
        ScoreProjectionPolicy.model_validate(
            {
                "max_iterations": 1,
                "gradient_tolerance": Decimal("0.001"),
                "line_search_min_step": Decimal(1),
                "market_uncertainty_floor": Decimal("0.01"),
                "allow_prior_fallback": True,
                "maximum_prior_goal_rate": Decimal(8),
            }
        )
    with pytest.raises(ValidationError):
        DerivedOutputPolicy.model_validate(
            {"total_goal_lines": ["2.5", "1.5"], "top_scoreline_count": 5}
        )


def test_unreadable_and_invalid_files_fail_with_typed_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ScoreDistributionError) as request_error:
        load_score_distribution_request(missing)
    assert request_error.value.code == "REQUEST_UNREADABLE"
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ScoreDistributionError) as invalid_request:
        load_score_distribution_request(bad)
    assert invalid_request.value.code == "REQUEST_INVALID"
    with pytest.raises(ScoreDistributionError) as invalid_artifact:
        load_joint_score_distribution(bad)
    assert invalid_artifact.value.code == "ARTIFACT_INVALID"


def test_artifact_identity_conflict_fails_closed(tmp_path: Path) -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "balanced_fixture.json")
    )
    assert result.distribution is not None
    path = persist_joint_score_distribution(result.distribution, artifact_root=tmp_path)
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ScoreDistributionError) as raised:
        persist_joint_score_distribution(result.distribution, artifact_root=tmp_path)
    assert raised.value.code == "ARTIFACT_IDENTITY_CONFLICT"


def test_market_fit_explanation_is_derived_from_distribution() -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "balanced_fixture.json")
    )
    assert result.distribution is not None
    explanation = explain_market_fit(result.distribution)
    assert explanation["result_sha256"] == result.distribution.result_sha256
    assert explanation["diagnostics"]["constraint_count"] == 4
    assert explanation["source_minutes_context_sha256"] == (
        result.distribution.source_minutes_context_sha256
    )
    assert explanation["source_home_minutes_sha256"] == (
        result.distribution.source_home_minutes_sha256
    )
    assert explanation["source_away_minutes_sha256"] == (
        result.distribution.source_away_minutes_sha256
    )
    assert explanation["source_minutes_as_of"] == result.distribution.source_minutes_as_of


def test_outer_result_identity_must_match_nested_distribution() -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "balanced_fixture.json")
    )
    payload = result.model_dump(mode="json")
    payload["fixture_id"] = "10000000-0000-7000-8000-000000009999"
    with pytest.raises(ValidationError, match="fixture identities"):
        ScoreDistributionResult.model_validate(payload)
    payload = result.model_dump(mode="json")
    payload["as_of"] = "2026-08-20T11:59:59Z"
    with pytest.raises(ValidationError, match="as_of values"):
        ScoreDistributionResult.model_validate(payload)


def test_exact_score_market_expands_grid_with_safety_margin() -> None:
    request = ScoreDistributionRequest.model_validate(
        {
            "schema_version": "score-distribution-request-v1",
            "fixture_id": UUID("10000000-0000-7000-8000-000000000892"),
            "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
            **_stage7_request_fields(
                UUID("10000000-0000-7000-8000-000000000892"),
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            ),
            "prior": {"home_goal_rate": "1.0", "away_goal_rate": "1.0"},
            "constraints": (
                MarketConstraint.model_validate(
                    {
                        "constraint_id": "score-25-0",
                        "family": MarketFamily.CORRECT_SCORE,
                        "event": ScoreEvent.EXACT_SCORE,
                        "target_probability": Decimal("0.000001"),
                        "uncertainty": Decimal("0.500000"),
                        "weight": Decimal("0.010000"),
                        "usable_at": datetime(2026, 8, 20, 11, tzinfo=UTC),
                        "home_goals": 25,
                        "away_goals": 0,
                    }
                ),
            ),
        }
    )
    result = ScoreDistributionService().project(request)
    assert result.distribution is not None
    assert result.distribution.home_max >= 27
    assert result.distribution.away_max >= 27


def test_total_line_market_expands_grid_with_safety_margin() -> None:
    request = ScoreDistributionRequest.model_validate(
        {
            "schema_version": "score-distribution-request-v1",
            "fixture_id": UUID("10000000-0000-7000-8000-000000000893"),
            "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
            **_stage7_request_fields(
                UUID("10000000-0000-7000-8000-000000000893"),
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            ),
            "prior": {"home_goal_rate": "1.0", "away_goal_rate": "1.0"},
            "constraints": (
                MarketConstraint.model_validate(
                    {
                        "constraint_id": "over-12-5",
                        "family": MarketFamily.TOTALS,
                        "event": ScoreEvent.TOTAL_OVER,
                        "line": Decimal("12.5"),
                        "target_probability": Decimal("0.000001"),
                        "uncertainty": Decimal("0.500000"),
                        "weight": Decimal("0.010000"),
                        "usable_at": datetime(2026, 8, 20, 11, tzinfo=UTC),
                    }
                ),
            ),
        }
    )
    result = ScoreDistributionService().project(request)
    assert result.distribution is not None
    assert result.distribution.home_max >= 15
    assert result.distribution.away_max >= 15


def test_market_support_beyond_validated_grid_fails_closed() -> None:
    request = ScoreDistributionRequest.model_validate(
        {
            "schema_version": "score-distribution-request-v1",
            "fixture_id": UUID("10000000-0000-7000-8000-000000000894"),
            "as_of": datetime(2026, 8, 20, 12, tzinfo=UTC),
            **_stage7_request_fields(
                UUID("10000000-0000-7000-8000-000000000894"),
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            ),
            "prior": {"home_goal_rate": "1.0", "away_goal_rate": "1.0"},
            "constraints": (
                MarketConstraint.model_validate(
                    {
                        "constraint_id": "score-35-0",
                        "family": MarketFamily.CORRECT_SCORE,
                        "event": ScoreEvent.EXACT_SCORE,
                        "target_probability": Decimal("0.000001"),
                        "uncertainty": Decimal("0.500000"),
                        "weight": Decimal("0.010000"),
                        "usable_at": datetime(2026, 8, 20, 11, tzinfo=UTC),
                        "home_goals": 35,
                        "away_goals": 0,
                    }
                ),
            ),
        }
    )
    with pytest.raises(ScoreDistributionError) as raised:
        ScoreDistributionService().project(request)
    assert raised.value.code == "MARKET_SUPPORT_OUT_OF_RANGE"
