from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from dmf_pulse.availability.manual_override import (
    ManualFixtureMinutesInput,
    ManualScenarioPlayer,
    build_manual_minutes_override,
)
from dmf_pulse.football_events.minutes_context import Stage7MinutesContext
from dmf_pulse.football_events.service import ScoreDistributionRequest, ScoreDistributionService
from dmf_pulse.fpl_points.models import (
    EventAllocationConfig,
    FixtureProjectionResult,
    FixtureSimulationRequest,
    PenaltyOutcome,
    PlayerAllocationProfile,
    PlayerPosition,
    ProjectionMode,
    SimulationStatus,
)
from dmf_pulse.fpl_points.player_prior import (
    GovernedPlayerPrior,
    bind_fixture_allocation_profiles,
    build_player_prior_identity_binding,
    load_packaged_player_prior,
)
from dmf_pulse.fpl_points.service import FplPointsService
from dmf_pulse.fpl_points.upstream import build_participation_scenario
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from tests.support.factories import make_request, mc_policy, reference_engine
from tests.unit.availability.manual_override_test_support import (
    AWAY_TEAM_ID,
    FIXTURE_ID,
    HOME_TEAM_ID,
    valid_manual_input_dict,
)

pytestmark = pytest.mark.integration

_CUTOFF_TEXT = "2026-08-21T17:30:00Z"
_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
_DONOR_TEAM_BY_SOURCE_ID = {
    1: "700d3302-6bde-54bd-b411-83a38845da5a",
    2: "c15dfbe5-4e5f-5a88-ac3e-5a011a641e04",
}
_CURRENT_TEAM_BY_SOURCE_ID = {1: HOME_TEAM_ID, 2: AWAY_TEAM_ID}
_ELEMENT_TYPE_BY_POSITION = {
    "GK": 1,
    "DEF": 2,
    "MID": 3,
    "FWD": 4,
}


def _manual_input_at_prior_cutoff() -> ManualFixtureMinutesInput:
    payload = valid_manual_input_dict()
    payload.update(
        as_of="2026-08-21T17:20:00Z",
        information_cutoff=_CUTOFF_TEXT,
    )
    provenance = payload["provenance"]
    assert isinstance(provenance, dict)
    provenance.update(
        source_timestamp="2026-08-21T16:00:00Z",
        entered_at="2026-08-21T16:30:00Z",
        usable_at="2026-08-21T17:00:00Z",
        expires_at="2026-08-21T18:30:00Z",
    )
    return ManualFixtureMinutesInput.model_validate(payload)


def _profiles_for_roster(
    prior: GovernedPlayerPrior,
    *,
    source_team_id: int,
    roster: tuple[ManualScenarioPlayer, ...],
) -> dict[str, PlayerAllocationProfile]:
    candidates = tuple(
        profile
        for profile in prior.artifact.profiles
        if profile.team_id == _DONOR_TEAM_BY_SOURCE_ID[source_team_id]
    )
    goalkeepers = tuple(
        sorted(
            (profile for profile in candidates if profile.goalkeeper_saves_per90 > 0.0),
            key=lambda profile: profile.player_id,
        )
    )
    outfield = tuple(profile for profile in candidates if profile.goalkeeper_saves_per90 == 0.0)
    penalty_takers = tuple(
        sorted(
            (profile for profile in outfield if profile.penalty_taker_share > 0.0),
            key=lambda profile: profile.player_id,
        )
    )
    goalkeeper_rows = tuple(row for row in roster if row.position == "GK")
    penalty_rows = tuple(
        row
        for row in roster
        if row.position != "GK" and row.role == "START" and row.official_minutes == 90
    )
    assert len(goalkeepers) == len(goalkeeper_rows) == 3
    assert len(penalty_takers) == 2
    assert len(penalty_rows) >= len(penalty_takers)

    assigned: dict[str, PlayerAllocationProfile] = dict(
        zip((row.player_id for row in goalkeeper_rows), goalkeepers, strict=True)
    )
    for row, profile in zip(penalty_rows, penalty_takers, strict=False):
        assigned[row.player_id] = profile
    used = {profile.player_id for profile in assigned.values()}
    remaining = iter(
        sorted(
            (profile for profile in outfield if profile.player_id not in used),
            key=lambda p: p.player_id,
        )
    )
    for row in roster:
        if row.player_id not in assigned:
            assigned[row.player_id] = next(remaining)
    assert len(assigned) == len(roster) == 23
    return assigned


def _current_fpl_and_player_map(
    repository_root: Path,
    tmp_path: Path,
    prior: GovernedPlayerPrior,
    manual_input: ManualFixtureMinutesInput,
) -> tuple[CurrentFplInputBundle, dict[int, str]]:
    lineage_by_profile = {lineage.player_id: lineage for lineage in prior.artifact.lineage}
    assignments: dict[int, tuple[str, str]] = {}
    for source_team_id, team in ((1, manual_input.home), (2, manual_input.away)):
        roster = team.scenarios[0].players
        for row_player_id, profile in _profiles_for_roster(
            prior, source_team_id=source_team_id, roster=roster
        ).items():
            source_player_id = lineage_by_profile[profile.player_id].source_player_id
            assignments[source_player_id] = (
                row_player_id,
                next(row.position for row in roster if row.player_id == row_player_id),
            )

    fixture_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = json.loads((fixture_root / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures = json.loads((fixture_root / "fixtures.json").read_text(encoding="utf-8"))
    templates = {int(item["element_type"]): item for item in bootstrap["elements"]}
    current_players: list[dict[str, Any]] = []
    source_team_by_profile = {
        profile.player_id: source_team_id
        for source_team_id, donor_team_id in _DONOR_TEAM_BY_SOURCE_ID.items()
        for profile in prior.artifact.profiles
        if profile.team_id == donor_team_id
    }
    profile_by_source_id = {
        lineage.source_player_id: lineage.player_id for lineage in prior.artifact.lineage
    }
    for offset, (source_player_id, (_player_id, position)) in enumerate(
        sorted(assignments.items()), start=1
    ):
        element_type = _ELEMENT_TYPE_BY_POSITION[position]
        player = deepcopy(templates[element_type])
        player.update(
            id=source_player_id,
            code=800000 + offset,
            team=source_team_by_profile[profile_by_source_id[source_player_id]],
            element_type=element_type,
            first_name=f"Current{offset}",
            second_name=f"Prior{offset}",
            web_name=f"CP{offset}",
            status="a",
            chance_of_playing_this_round=None,
            chance_of_playing_next_round=None,
            news="",
            news_added=None,
        )
        current_players.append(player)
    bootstrap["elements"] = current_players
    bootstrap_path = tmp_path / "current-player-bootstrap.json"
    fixtures_path = tmp_path / "current-player-fixtures.json"
    bootstrap_path.write_text(json.dumps(bootstrap, sort_keys=True), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures, sort_keys=True), encoding="utf-8")
    clock = iter(
        (
            datetime(2026, 8, 21, 17, 10, tzinfo=UTC),
            datetime(2026, 8, 21, 17, 11, tzinfo=UTC),
        )
    )
    bundle = CurrentFplInputService(clock=lambda: next(clock)).compile(
        CurrentFplInputRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixtures_path,
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=1,
            captured_at=datetime(2026, 8, 21, 17, 0, tzinfo=UTC),
            information_cutoff=_CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
        )
    )
    return bundle, {source_id: value[0] for source_id, value in assignments.items()}


def _participation_rows(manual_input: ManualFixtureMinutesInput) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for team in (manual_input.home, manual_input.away):
        for player in team.scenarios[0].players:
            row: dict[str, object] = {
                "player_id": player.player_id,
                "team_id": team.team_id,
                "position": player.position,
                "official_minutes": player.official_minutes,
                "hard_ineligible": False,
                "starter": player.role == "START",
            }
            if player.official_minutes > 0:
                row["entry_minute"] = 0 if player.role == "START" else 90 - player.official_minutes
                row["exit_minute"] = player.official_minutes if player.role == "START" else 90
            rows.append(row)
    return tuple(rows)


def _allocation_config() -> EventAllocationConfig:
    resource = resources.files("dmf_pulse.fpl_points.resources").joinpath(
        "event_allocation_baseline.yaml"
    )
    payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    return EventAllocationConfig.model_validate(
        {
            "model_version_id": payload["model_version_id"],
            "source_tag": payload["source_tag"],
            "bps_completeness_mode": payload["bps_completeness_mode"],
            "auxiliary_source_tag": payload["auxiliary_source_tag"],
            **payload["parameters"],
        }
    )


def _assert_event_timing_and_links(result: FixtureProjectionResult) -> None:
    for scenario in result.scenarios:
        event = scenario.event_scenario
        players = {player.player_id: player for player in event.players}
        assert len(event.goals) == event.home_goals + event.away_goals
        assert (
            sum(goal.scoring_team_id == event.home_team_id for goal in event.goals)
            == event.home_goals
        )
        assert (
            sum(goal.scoring_team_id == event.away_team_id for goal in event.goals)
            == event.away_goals
        )
        goals_by_id = {goal.goal_id: goal for goal in event.goals}
        penalties_by_id = {penalty.penalty_id: penalty for penalty in event.penalties}
        for goal in event.goals:
            if goal.scorer_player_id is not None:
                assert goal.scorer_player_id != goal.assister_player_id
            for player_id in (
                goal.scorer_player_id,
                goal.assister_player_id,
                goal.own_goal_player_id,
            ):
                if player_id is not None:
                    interval = players[player_id].on_pitch_interval
                    assert interval is not None
                    assert interval.contains(goal.minute)
        for penalty in event.penalties:
            taker_interval = players[penalty.taker_player_id].on_pitch_interval
            assert taker_interval is not None
            assert taker_interval.contains(penalty.minute)
            if penalty.outcome is PenaltyOutcome.GOAL:
                assert penalty.goal_id in goals_by_id
                assert goals_by_id[penalty.goal_id].mechanism.value == "PENALTY"
            else:
                assert penalty.goal_id is None
        for save in event.goalkeeper_saves:
            goalkeeper = players[save.goalkeeper_player_id]
            shooter = players[save.shooter_player_id]
            assert goalkeeper.position is PlayerPosition.GK
            assert goalkeeper.on_pitch_interval is not None
            assert shooter.on_pitch_interval is not None
            assert goalkeeper.on_pitch_interval.contains(save.minute)
            assert shooter.on_pitch_interval.contains(save.minute)
            if save.penalty_id is not None:
                assert penalties_by_id[save.penalty_id].outcome is PenaltyOutcome.SAVED


def test_governed_current_player_prior_runs_real_manual_stage7_to_stage9_path(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    prior = load_packaged_player_prior()
    manual_input = _manual_input_at_prior_cutoff()
    minutes = build_manual_minutes_override(manual_input)
    context = Stage7MinutesContext.from_projections(minutes.home, minutes.away)
    stage8_payload = json.loads(
        (repository_root / "fixtures/events/score/GCS-008/balanced_fixture.json").read_text(
            encoding="utf-8"
        )
    )
    stage8_payload["as_of"] = _CUTOFF_TEXT
    stage8_payload["minutes_context"] = context.public_dict()
    stage8_result = ScoreDistributionService().project(
        ScoreDistributionRequest.model_validate_json(json.dumps(stage8_payload))
    )
    assert stage8_result.status == "PROJECTED"
    assert stage8_result.distribution is not None
    distribution = stage8_result.distribution

    current_fpl, player_map = _current_fpl_and_player_map(
        repository_root, tmp_path, prior, manual_input
    )
    binding = build_player_prior_identity_binding(
        prior,
        current_fpl,
        canonical_player_ids_by_source_id=player_map,
        canonical_team_ids_by_source_id=_CURRENT_TEAM_BY_SOURCE_ID,
    )
    participation = build_participation_scenario(
        scenario_id="MANUAL-SCENARIO-01",
        probability=1.0,
        fixture_id=FIXTURE_ID,
        gameweek_id="GW-1",
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        participant_rows=_participation_rows(manual_input),
        home_projection=minutes.home,
        away_projection=minutes.away,
        information_cutoff_utc=_CUTOFF_TEXT,
    )
    profiles, prior_identity = bind_fixture_allocation_profiles(prior, binding, (participation,))
    engine = reference_engine()
    request = FixtureSimulationRequest(
        schema_version="fpl-points-fixture-request-v1",
        gameweek_id="GW-1",
        projection_mode=ProjectionMode.TEST,
        as_of_utc=_CUTOFF_TEXT,
        information_cutoff_utc=_CUTOFF_TEXT,
        root_seed=20260821,
        scenario_count=32,
        score_distribution=distribution,
        participation_scenarios=(participation,),
        allocation_profiles=profiles,
        player_prior_identity=prior_identity,
        allocation_config=_allocation_config(),
        expected_ruleset_id=engine.identity.ruleset_id,
        expected_ruleset_version=engine.identity.ruleset_version,
        expected_ruleset_hash=engine.identity.ruleset_hash,
    )
    service = FplPointsService(engine, mc_policy())
    result = service.project(request)

    assert result.status is SimulationStatus.SUCCESS
    assert result == service.project(request)
    assert result.result_sha256 is not None
    assert result.upstream_stage8_sha256 == distribution.result_sha256
    assert context.home.model_family == "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"
    assert all(
        scenario.stage7_minutes_context.semantic_sha256 == context.semantic_sha256
        for scenario in result.scenarios
    )
    assert prior_identity.artifact_sha256 in result.source_bundle_ids
    assert prior_identity.historical_acceptance_sha256 in result.source_bundle_ids
    assert prior_identity.current_fpl_bundle_sha256 == current_fpl.semantic_sha256
    assert prior_identity.current_fpl_bundle_sha256 in result.source_bundle_ids
    assert prior_identity.current_identity_binding_sha256 in result.source_bundle_ids
    assert prior_identity.production_activation is False
    assert "DONOR_PRIVATE_ACCEPTANCE_IS_NOT_PORT_ACCEPTANCE" in result.warnings
    assert "NOT_PRODUCTION_ACTIVE" in result.warnings
    assert any(scenario.event_scenario.penalties for scenario in result.scenarios)
    assert any(scenario.event_scenario.goalkeeper_saves for scenario in result.scenarios)
    _assert_event_timing_and_links(result)

    production_payload = request.model_dump(mode="python")
    production_payload["projection_mode"] = ProjectionMode.PRODUCTION
    with pytest.raises(
        ValueError, match="private GW1 donor prior cannot activate production projection"
    ):
        FixtureSimulationRequest.model_validate(production_payload)

    assert result.joint_matrix is not None
    matrix = result.joint_matrix
    assert sum(matrix.weights) == pytest.approx(1.0)
    assert matrix.points == tuple(
        tuple(scenario.players[player_id].total for player_id in matrix.player_ids)
        for scenario in result.scenarios
    )
    assert (
        len(
            {
                tuple(scenario.players[player_id].total for player_id in matrix.player_ids)
                for scenario in result.scenarios
            }
        )
        > 1
    )
    for player_id, summary in result.player_summaries.items():
        player_index = matrix.player_ids.index(player_id)
        recomputed: defaultdict[int, float] = defaultdict(float)
        for weight, points in zip(matrix.weights, matrix.points, strict=True):
            recomputed[points[player_index]] += weight
        assert summary.pmf == pytest.approx(dict(sorted(recomputed.items())))
    assert all(
        score.total
        == sum(
            getattr(score, component)
            for component in (
                "appearance",
                "goals",
                "assists",
                "clean_sheet",
                "saves",
                "penalty_saves",
                "defensive_contributions",
                "goals_conceded",
                "penalty_misses",
                "yellow_cards",
                "red_cards",
                "own_goals",
                "bonus",
            )
        )
        for scenario in result.scenarios
        for score in scenario.players.values()
    )


def test_existing_empirical_stage7_family_remains_supported() -> None:
    request = make_request(scenario_count=8)
    result = FplPointsService(reference_engine(), mc_policy()).project(request)
    assert result.status is SimulationStatus.SUCCESS
    assert all(
        scenario.stage7_minutes_context.home.model_family
        == "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
        for scenario in result.scenarios
    )
