import json
from pathlib import Path

import pytest

from dmf_pulse.football_events.service import (
    ScoreDistributionService,
    load_joint_score_distribution,
    load_score_distribution_request,
    persist_joint_score_distribution,
)

pytestmark = pytest.mark.unit
FIXTURES = Path("fixtures/events/score/GCS-008")


def test_no_market_returns_visible_prior_only_low_confidence() -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "market_missing.json")
    )
    assert result.status == "PROJECTED"
    assert result.distribution is not None
    assert result.distribution.diagnostics.projection_status == "PRIOR_ONLY"
    assert result.distribution.confidence_grade == "D"
    assert "NO_MARKET_CONSTRAINTS" in result.distribution.confidence_reasons


def test_postponed_fixture_is_blocked_without_distribution() -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "postponed_fixture.json")
    )
    assert result.status == "BLOCKED"
    assert result.error_code == "FIXTURE_POSTPONED"
    assert result.distribution is None


def test_stage6_consensus_integrates_without_parallel_market_identity() -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "stage6_consensus_fixture.json")
    )
    assert result.distribution is not None
    assert result.distribution.source_market_sha256 == "c" * 64
    assert tuple(item.source_result_sha256 for item in result.distribution.market_residuals) == (
        "c" * 64,
        "c" * 64,
        "c" * 64,
    )


def test_content_addressed_artifact_is_idempotent_and_replayable(tmp_path: Path) -> None:
    result = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURES / "balanced_fixture.json")
    )
    assert result.distribution is not None
    first = persist_joint_score_distribution(result.distribution, artifact_root=tmp_path)
    second = persist_joint_score_distribution(result.distribution, artifact_root=tmp_path)
    assert first == second
    assert load_joint_score_distribution(first) == result.distribution
    assert json.loads(first.read_text(encoding="utf-8"))["result_sha256"] == (
        result.distribution.result_sha256
    )


def test_market_change_invalidates_artifact_identity(tmp_path: Path) -> None:
    first_request = load_score_distribution_request(FIXTURES / "balanced_fixture.json")
    second_request = load_score_distribution_request(FIXTURES / "strong_home_favourite.json")
    first_result = ScoreDistributionService().project(first_request)
    second_result = ScoreDistributionService().project(second_request)
    assert first_result.distribution is not None
    assert second_result.distribution is not None
    first_path = persist_joint_score_distribution(first_result.distribution, artifact_root=tmp_path)
    second_path = persist_joint_score_distribution(
        second_result.distribution, artifact_root=tmp_path
    )
    assert first_result.input_signature_sha256 != second_result.input_signature_sha256
    assert first_path != second_path
