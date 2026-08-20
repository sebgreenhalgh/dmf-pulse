"""Checkpoint-2.3 current football-event distribution acceptance."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability import CurrentAvailabilityBundle, build_current_availability
from dmf_pulse.football_events import assert_score_coherence
from dmf_pulse.football_events.service import ScorePriorRequest
from dmf_pulse.fpl_points.current import (
    CurrentFixtureEventPrior,
    CurrentFootballEventApproval,
    CurrentFootballEventBundle,
    CurrentFootballEventPriorArtifact,
    build_current_football_event_review,
    build_current_football_events,
)
from dmf_pulse.fpl_points.models import (
    BpsAuxiliaryRates,
    BpsCompletenessMode,
    EventAllocationConfig,
    FixtureSimulationRequest,
    PlayerAllocationProfile,
    ProjectionMode,
)
from dmf_pulse.ingestion.errors import IngestionError
from tests.unit.availability.test_current_availability import (
    CUTOFF,
    KICKOFF,
    REVIEWER,
    _market_source,
)
from tests.unit.availability.test_current_availability import (
    _approval as availability_approval,
)

pytestmark = pytest.mark.unit

EVENT_APPROVED = datetime(2026, 8, 20, 12, 4, tzinfo=UTC)
PRIOR_INFORMATION_CUTOFF = datetime(2026, 8, 20, 12, 2, tzinfo=UTC)


def _availability(repository_root: Path, tmp_path: Path) -> CurrentAvailabilityBundle:
    market = _market_source(repository_root, tmp_path)
    return build_current_availability(market, availability_approval(market))


@pytest.fixture(scope="module")
def current_source(
    repository_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> CurrentAvailabilityBundle:
    return _availability(repository_root, tmp_path_factory.mktemp("gw1-current-events"))


def _bps() -> BpsAuxiliaryRates:
    return BpsAuxiliaryRates(
        big_chances_created_per90=0.1,
        big_chances_missed_per90=0.1,
        errors_leading_attempt_per90=0.01,
        errors_leading_goal_per90=0.01,
        fouls_conceded_per90=1.0,
        fouls_won_per90=1.0,
        goal_line_clearances_per90=0.01,
        key_passes_per90=1.0,
        offsides_per90=0.2,
        pass_attempts_per90=30.0,
        pass_completion_probability=0.8,
        recoveries_per90=4.0,
        shots_off_target_per90=0.5,
        shots_on_target_non_goal_per90=0.5,
        successful_dribbles_per90=0.5,
        successful_open_play_crosses_per90=0.2,
        times_tackled_per90=0.5,
    )


def _config(*, source_tag: str = "TEMP-EVT-002") -> EventAllocationConfig:
    return EventAllocationConfig.model_validate(
        {
            "model_version_id": "accepted-current-event-allocation-v1",
            "source_tag": source_tag,
            "bps_completeness_mode": BpsCompletenessMode.EVENT_LINKED_PLUS_AUXILIARY_BASELINE,
            "auxiliary_source_tag": "TEMP-PTS-001",
            "match_minutes": 90.0,
            "goal_time_lower": 0.01,
            "goal_time_upper": 89.99,
            "penalty_goal_probability": 0.08,
            "set_piece_goal_probability": 0.18,
            "direct_free_kick_goal_probability": 0.02,
            "own_goal_probability": 0.02,
            "assistable_probability": 0.72,
            "ambiguous_assist_probability": 0.1,
            "ambiguous_assist_eligible_probability": 0.5,
            "extra_penalty_attempt_probability": 0.03,
            "extra_penalty_save_probability": 0.2,
        }
    )


def _profile(player_id: str, team_id: str, *, count: int, position: str) -> PlayerAllocationProfile:
    return PlayerAllocationProfile(
        player_id=player_id,
        team_id=team_id,
        goal_share=1.0 / count,
        assist_share=1.0 / count,
        penalty_taker_share=1.0 / count,
        own_goal_share=1.0 / count,
        goalkeeper_saves_per90=3.0 if position == "GK" else 0.0,
        saves_inside_box_fraction=0.7,
        yellow_cards_per90=0.1,
        red_cards_per90=0.01,
        clearances_per90=1.0,
        blocks_per90=0.5,
        interceptions_per90=0.8,
        tackles_per90=1.5,
        ball_recoveries_per90=4.0,
        bps_auxiliary=_bps(),
    )


def _artifact(
    source: CurrentAvailabilityBundle,
    *,
    home_rate: Decimal = Decimal("1.400000"),
    away_rate: Decimal = Decimal("1.100000"),
    information_cutoff: datetime = PRIOR_INFORMATION_CUTOFF,
    expires_at: datetime = KICKOFF + timedelta(days=1),
    source_tag: str = "TEMP-EVT-002",
) -> CurrentFootballEventPriorArtifact:
    review = build_current_football_event_review(source)
    projection_by_fixture_team = {
        (row.official_fpl_fixture_id, str(row.transient_team_id)): row.posterior_projection
        for row in source.team_projections
    }
    fixtures: list[CurrentFixtureEventPrior] = []
    for row in review.fixtures:
        profiles: list[PlayerAllocationProfile] = []
        for team_id in (row.transient_home_team_id, row.transient_away_team_id):
            projection = projection_by_fixture_team[(row.official_fpl_fixture_id, str(team_id))]
            count = len(projection.players)
            profiles.extend(
                _profile(
                    player.player_id,
                    str(team_id),
                    count=count,
                    position=player.position,
                )
                for player in projection.players
            )
        fixtures.append(
            CurrentFixtureEventPrior(
                official_fpl_fixture_id=row.official_fpl_fixture_id,
                transient_fixture_id=row.transient_fixture_id,
                transient_home_team_id=row.transient_home_team_id,
                transient_away_team_id=row.transient_away_team_id,
                score_prior=ScorePriorRequest(
                    home_goal_rate=home_rate,
                    away_goal_rate=away_rate,
                ),
                allocation_profiles=tuple(sorted(profiles, key=lambda item: item.player_id)),
            )
        )
    values: dict[str, Any] = {
        "source_model_key": "accepted-test-current-team-strength",
        "source_model_version": "v1",
        "source_dataset_sha256": "1" * 64,
        "source_policy_sha256": "2" * 64,
        "evidence_locator": "test://accepted-current-event-prior",
        "acceptance_reference": "test://independent-acceptance/current-event-prior",
        "accepted_by": "Independent Test Reviewer",
        "information_cutoff": information_cutoff,
        "produced_at": information_cutoff + timedelta(seconds=10),
        "accepted_at": information_cutoff + timedelta(seconds=20),
        "expires_at": expires_at,
        "allocation_config": _config(source_tag=source_tag),
        "fixtures": tuple(fixtures),
    }
    provisional = CurrentFootballEventPriorArtifact.model_construct(
        **values, artifact_sha256="0" * 64
    )
    return CurrentFootballEventPriorArtifact(
        **values,
        artifact_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"artifact_sha256"})
        ),
    )


def _event_approval(
    source: CurrentAvailabilityBundle,
    *,
    artifact: CurrentFootballEventPriorArtifact | None = None,
    approved_at: datetime = EVENT_APPROVED,
) -> CurrentFootballEventApproval:
    review = build_current_football_event_review(source)
    selected = artifact or _artifact(source)
    return CurrentFootballEventApproval(
        reviewer=REVIEWER,
        approved_at=approved_at,
        reviewed_all_fixtures=True,
        accepted_model_artifact_confirmed=True,
        template_sha256=review.template_sha256,
        confirmed_template_sha256=review.template_sha256,
        prior_artifact=selected,
        confirmed_prior_artifact_sha256=selected.artifact_sha256,
    )


@pytest.fixture(scope="module")
def accepted_event_result(current_source: CurrentAvailabilityBundle) -> CurrentFootballEventBundle:
    return build_current_football_events(current_source, _event_approval(current_source))


def test_accepted_prior_builds_coherent_stage8_and_exact_stage9_handoff(
    current_source: CurrentAvailabilityBundle,
    accepted_event_result: CurrentFootballEventBundle,
) -> None:
    review = build_current_football_event_review(current_source)
    result = accepted_event_result
    summary = result.safe_summary()

    assert review.status == "ACCEPTED_PRIOR_ARTIFACT_REQUIRED"
    assert len(result.fixtures) == 1
    fixture = result.fixtures[0]
    assert fixture.score_distribution.source_market_sha256 is not None
    assert len(fixture.participation_scenarios) == 256
    assert len(fixture.allocation_profiles) == 44
    assert fixture.event_allocation_status == "STAGE9_REQUEST_READY_NOT_EXECUTED"
    stage9_request = FixtureSimulationRequest(
        schema_version="fpl-points-fixture-request-v1",
        gameweek_id=str(fixture.gameweek_id),
        projection_mode=ProjectionMode.TEST,
        as_of_utc=fixture.score_distribution.as_of,
        information_cutoff_utc=fixture.score_distribution.information_cutoff,
        root_seed=1,
        scenario_count=256,
        fixture_readiness=fixture.fixture_readiness,
        score_distribution=fixture.score_distribution,
        participation_scenarios=fixture.participation_scenarios,
        allocation_profiles=fixture.allocation_profiles,
        allocation_config=fixture.allocation_config,
        expected_ruleset_id="test-only-checkpoint-2.3-handoff",
        expected_ruleset_version="test-only",
        expected_ruleset_hash="0" * 64,
    )
    assert stage9_request.score_distribution.result_sha256 == (
        fixture.score_distribution.result_sha256
    )
    assert all(
        sum(player.starter for player in scenario.participants if player.team_id == team_id) == 11
        for scenario in fixture.participation_scenarios
        for team_id in (str(fixture.transient_home_team_id), str(fixture.transient_away_team_id))
    )
    assert all(len(scenario.participants) == 44 for scenario in fixture.participation_scenarios)
    assert_score_coherence(fixture.score_distribution)
    assert summary.status == "READY_FOR_STAGE9_WITH_MATERIAL_LIMITATIONS"
    assert summary.production_status == "NON_PRODUCTION"
    assert summary.production_calibration_claim is False
    assert summary.participation_scenario_count == 256
    assert summary.next_checkpoint == "2.4_FPL_POINTS_DISTRIBUTIONS"
    assert CurrentFootballEventBundle.model_validate_json(result.model_dump_json()) == result


def test_stage8_is_bound_to_reviewed_market_minutes_and_prior(
    current_source: CurrentAvailabilityBundle,
    accepted_event_result: CurrentFootballEventBundle,
) -> None:
    artifact = _artifact(current_source)
    result = accepted_event_result
    fixture = result.fixtures[0]
    prior = artifact.fixtures[0]
    home = next(
        row
        for row in current_source.team_projections
        if row.transient_team_id == prior.transient_home_team_id
    )
    away = next(
        row
        for row in current_source.team_projections
        if row.transient_team_id == prior.transient_away_team_id
    )

    assert fixture.score_distribution.prior_home_goal_rate == "1.400000"
    assert fixture.score_distribution.prior_away_goal_rate == "1.100000"
    assert fixture.score_distribution.source_home_minutes_sha256 == (
        home.posterior_projection.result_sha256
    )
    assert fixture.score_distribution.source_away_minutes_sha256 == (
        away.posterior_projection.result_sha256
    )
    assert fixture.source_prior_artifact_sha256 == artifact.artifact_sha256


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("fixture", "identity or validity window"),
        ("players", "identity or validity window"),
        ("teams", "identity or validity window"),
        ("expiry", "identity or validity window"),
        ("cutoff", "information exceeds"),
    ],
)
def test_prior_identity_coverage_and_time_attacks_fail_closed(
    current_source: CurrentAvailabilityBundle,
    mutation: str,
    message: str,
) -> None:
    artifact = _artifact(current_source)
    fixture = artifact.fixtures[0]
    values = artifact.model_dump(mode="python", exclude={"artifact_sha256"})
    values["allocation_config"] = artifact.allocation_config
    values["fixtures"] = artifact.fixtures
    if mutation == "fixture":
        values["fixtures"] = (
            fixture.model_copy(update={"transient_fixture_id": fixture.transient_home_team_id}),
        )
    elif mutation == "players":
        values["fixtures"] = (
            fixture.model_copy(update={"allocation_profiles": fixture.allocation_profiles[:-1]}),
        )
    elif mutation == "teams":
        first = fixture.allocation_profiles[0]
        swapped_team = (
            str(fixture.transient_away_team_id)
            if first.team_id == str(fixture.transient_home_team_id)
            else str(fixture.transient_home_team_id)
        )
        values["fixtures"] = (
            fixture.model_copy(
                update={
                    "allocation_profiles": (
                        first.model_copy(update={"team_id": swapped_team}),
                        *fixture.allocation_profiles[1:],
                    )
                }
            ),
        )
    elif mutation == "expiry":
        values["expires_at"] = KICKOFF - timedelta(seconds=1)
    else:
        values["information_cutoff"] = EVENT_APPROVED + timedelta(seconds=1)
        values["produced_at"] = EVENT_APPROVED + timedelta(seconds=2)
        values["accepted_at"] = EVENT_APPROVED + timedelta(seconds=3)
    provisional = CurrentFootballEventPriorArtifact.model_construct(
        **values, artifact_sha256="0" * 64
    )
    mutated = CurrentFootballEventPriorArtifact(
        **values,
        artifact_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"artifact_sha256"})
        ),
    )

    with pytest.raises(IngestionError, match=message):
        build_current_football_events(
            current_source, _event_approval(current_source, artifact=mutated)
        )


def test_synthetic_event_configuration_is_not_eligible_for_current_run(
    current_source: CurrentAvailabilityBundle,
) -> None:
    with pytest.raises(ValidationError, match="current football-event prior artifact"):
        _artifact(current_source, source_tag="TEST_SYNTHETIC")


def test_accepted_prior_outside_stage8_validated_rate_boundary_fails_closed(
    current_source: CurrentAvailabilityBundle,
) -> None:
    artifact = _artifact(current_source, home_rate=Decimal("99.000000"))

    with pytest.raises(IngestionError, match="outside the Stage-8 validated boundary") as exc:
        build_current_football_events(
            current_source, _event_approval(current_source, artifact=artifact)
        )

    assert exc.value.details["error_code"] == "PRIOR_RATE_OUT_OF_RANGE"


def test_post_cutoff_approval_and_unconfirmed_hashes_fail_closed(
    current_source: CurrentAvailabilityBundle,
) -> None:
    with pytest.raises(IngestionError, match="outside the usable window"):
        build_current_football_events(
            current_source,
            _event_approval(current_source, approved_at=CUTOFF + timedelta(seconds=1)),
        )

    approval = _event_approval(current_source)
    hostile = approval.model_copy(update={"confirmed_prior_artifact_sha256": "f" * 64})
    with pytest.raises(IngestionError, match="not bound to current inputs"):
        build_current_football_events(current_source, hostile)


def test_serialized_stage7_path_or_stage8_output_tampering_is_rejected(
    current_source: CurrentAvailabilityBundle,
    accepted_event_result: CurrentFootballEventBundle,
) -> None:
    source_payload = current_source.model_dump(mode="json")
    source_payload["team_projections"][0]["posterior_lineup_scenarios"][0]["scenario_sha256"] = (
        "f" * 64
    )
    with pytest.raises(ValidationError, match="lineage is inconsistent"):
        CurrentAvailabilityBundle.model_validate_json(json.dumps(source_payload))

    payload = deepcopy(accepted_event_result.model_dump(mode="json"))
    payload["fixtures"][0]["score_distribution"]["expected_home_goals"] = "9.000000"
    with pytest.raises(ValidationError):
        CurrentFootballEventBundle.model_validate(payload)


def test_review_and_safe_summary_do_not_disclose_names_or_prices(
    current_source: CurrentAvailabilityBundle,
    accepted_event_result: CurrentFootballEventBundle,
) -> None:
    review = build_current_football_event_review(current_source)
    summary = accepted_event_result.safe_summary()
    rendered = review.model_dump_json() + summary.model_dump_json()

    assert "Player1001" not in rendered
    assert "decimal_price" not in rendered
    assert "bookmaker" not in rendered.lower()
