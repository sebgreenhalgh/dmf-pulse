"""Exact accepted Stage-8 parity, identity completeness and inactive boundaries."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionService,
    load_score_baseline_policy,
    load_score_distribution_request,
)
from dmf_pulse.private_v1.models import PrivateFixtureScorePrior, seal_fixture_score_prior
from dmf_pulse.private_v1.prior_only_candidate import (
    PriorOnlyCandidateInput,
    PriorOnlyFixture,
    PriorOnlyGameweekAssignment,
    project_prior_only_candidate,
)

pytestmark = pytest.mark.unit
FIXTURES = Path("fixtures/events/score/GCS-008")


def candidate(horizon=1):
    base = load_score_distribution_request(FIXTURES / "market_missing.json")
    rows = []
    for offset in range(horizon):
        # Preserve the accepted sealed Stage-7 identities for each new fixture.
        body = base.model_dump(mode="json")
        fixture_id = UUID(int=100 + offset)
        body["fixture_id"] = str(fixture_id)
        for side in ("home", "away"):
            body["minutes_context"][side]["fixture_id"] = str(fixture_id)
        request = ScoreDistributionRequest.model_validate_json(json.dumps(body))
        prior = seal_fixture_score_prior(
            PrivateFixtureScorePrior.model_construct(
                source_class="REPOSITORY_OWNED_SYNTHETIC",
                fixture_id=fixture_id,
                competition_id=UUID(int=1),
                home_team_id=request.home_team_id,
                away_team_id=request.away_team_id,
                as_of=request.as_of,
                score_prior_request=request.prior,
                current_bundle=None,
                semantic_sha256="0" * 64,
            )
        )
        rows.append(
            PriorOnlyFixture(
                official_fixture_id=100 + offset,
                official_fixture_lookup_sha256=f"{offset + 1:064x}",
                gameweek=5 + offset,
                home_official_team_id=1,
                away_official_team_id=2,
                kickoff_at=request.as_of + timedelta(days=offset + 1),
                prior=prior,
                request=request,
            )
        )
    return PriorOnlyCandidateInput(
        season_code="2026/27",
        target_gameweek=5,
        horizon=horizon,
        information_cutoff=base.as_of,
        expected_stage8_policy_sha256=load_score_baseline_policy().sha256,
        assignments=tuple(
            PriorOnlyGameweekAssignment(gameweek=5 + offset, official_fixture_ids=(100 + offset,))
            for offset in range(horizon)
        ),
        fixtures=tuple(rows),
    )


@pytest.mark.parametrize("horizon", [1, 3])
def test_exact_stage8_parity_and_explicit_inactive_report(horizon):
    value = candidate(horizon)
    report = project_prior_only_candidate(value)
    expected = tuple(
        ScoreDistributionService().project(row.request).model_dump(mode="json")
        for row in value.fixtures
    )
    assert tuple(row.model_dump(mode="json") for row in report.fixture_results) == expected
    assert report.private_workflow_status == "NOT_CONNECTED_TO_PRIVATE_WORKFLOW"
    assert report.status == "INACTIVE_OFFLINE_ONLY"
    assert report.mode == "GOVERNED_PRIOR_ONLY"
    assert report.input_sha256 == value.semantic_sha256
    assert all(row.distribution.confidence_grade == "D" for row in report.fixture_results)


def test_explicit_blank_gameweek_needs_no_invented_fixture():
    value = candidate().model_copy(
        update={
            "assignments": (PriorOnlyGameweekAssignment(gameweek=5, official_fixture_ids=()),),
            "fixtures": (),
        }
    )
    assert project_prior_only_candidate(value).fixture_results == ()


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "wrong_gameweek", "wrong_lookup", "policy", "active", "wrong_cutoff"],
)
def test_incomplete_identity_policy_or_activation_rejects(mutation):
    value = candidate(3)
    with pytest.raises(ValueError):
        if mutation == "missing":
            value.model_copy(update={"fixtures": value.fixtures[:-1]})
        elif mutation == "duplicate":
            value.model_copy(update={"fixtures": (*value.fixtures, value.fixtures[0])})
        elif mutation == "wrong_gameweek":
            value.model_copy(update={"target_gameweek": 6})
        elif mutation == "wrong_lookup":
            value.model_copy(
                update={
                    "fixtures": (
                        value.fixtures[0],
                        value.fixtures[1].model_copy(
                            update={
                                "official_fixture_lookup_sha256": value.fixtures[
                                    0
                                ].official_fixture_lookup_sha256
                            }
                        ),
                        value.fixtures[2],
                    )
                }
            )
        elif mutation == "policy":
            project_prior_only_candidate(
                value.model_copy(update={"expected_stage8_policy_sha256": "f" * 64})
            )
        elif mutation == "active":
            value.model_copy(update={"status": "ACTIVE"})
        else:
            value.model_copy(
                update={"information_cutoff": value.information_cutoff + timedelta(seconds=1)}
            )


def test_market_evidence_is_never_disguised_as_prior_only():
    row = candidate().fixtures[0]
    market_request = load_score_distribution_request(FIXTURES / "balanced_fixture.json")
    with pytest.raises(ValueError, match="market evidence"):
        row.model_copy(update={"request": market_request})
    with pytest.raises(ValueError, match="future scheduled"):
        row.model_copy(update={"kickoff_at": row.request.as_of})
    with pytest.raises(ValueError, match="teams must differ"):
        row.model_copy(update={"away_official_team_id": 1})
