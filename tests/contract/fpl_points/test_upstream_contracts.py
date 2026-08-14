from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dmf_pulse.availability import MinutesPredictionResult, TeamMinutesProjection
from dmf_pulse.availability.projection import canonical_sha256
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import FixtureSimulationRequest
from dmf_pulse.fpl_points.service import FplPointsService
from dmf_pulse.fpl_points.upstream import (
    adapt_stage8_score_distribution,
    build_participation_scenario,
    scoreline_cells,
)
from tests.support.factories import (
    AWAY_TEAM_ID,
    FIXTURE_ID,
    HOME_TEAM_ID,
    make_request,
    mc_policy,
    reference_engine,
)

ROOT = Path(__file__).resolve().parents[3]
STAGE8 = ROOT / "fixtures/events/score/GCS-008/balanced_fixture.expected.json"


def _team_projection(
    team_id: str, player_prefix: int, *, fixture_id: str = FIXTURE_ID
) -> TeamMinutesProjection:
    players: list[dict[str, object]] = []
    for index in range(1, 12):
        pmf = ["0.000000000000"] * 91
        pmf[90] = "1.000000000000"
        player: dict[str, object] = {
            "player_id": f"{player_prefix:08d}-0000-7000-8000-{index:012d}",
            "position": "GK" if index == 1 else "DEF",
            "p_start": "1.000000000000",
            "p_bench": "0.000000000000",
            "p_out_of_squad": "0.000000000000",
            "p_appearance": "1.000000000000",
            "p_zero_minutes": "0.000000000000",
            "p_60_plus": "1.000000000000",
            "expected_minutes": "90.000000",
            "minute_pmf": pmf,
            "confidence_grade": "B",
            "confidence_reasons": ["BASELINE_MODEL_CAP_B"],
        }
        player["projection_sha256"] = canonical_sha256(player)
        players.append(player)
    body: dict[str, object] = {
        "schema_version": "team-minutes-projection-v1",
        "fixture_id": fixture_id,
        "team_id": team_id,
        "as_of": "2026-08-20T11:50:00Z",
        "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        "dataset_sha256": "3" * 64,
        "model_artifact_sha256": "4" * 64,
        "sample_count": 256,
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "players": players,
        "scenario_set_sha256": "5" * 64,
        "sum_p_start": "11.000000000000",
        "sum_p_bench": "0.000000000000",
        "sum_p_out": "0.000000000000",
    }
    body["result_sha256"] = canonical_sha256(body)
    return TeamMinutesProjection.model_validate(body)


def _rows(
    home: TeamMinutesProjection, away: TeamMinutesProjection
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "player_id": player.player_id,
            "team_id": projection.team_id,
            "position": player.position,
            "official_minutes": 90,
            "entry_minute": 0,
            "exit_minute": 90,
            "starter": True,
        }
        for projection in (home, away)
        for player in projection.players
    )


def test_final_stage8_public_contract_adapter_is_exact() -> None:
    payload = json.loads(STAGE8.read_text(encoding="utf-8"))
    adapted = adapt_stage8_score_distribution(payload)
    cells = scoreline_cells(adapted)
    assert adapted.result_sha256 == payload["result_sha256"]
    assert cells[0].probability == "0.074443732068"
    assert sum(int(cell.probability.replace(".", "")) for cell in cells) == 10**12
    assert adapt_stage8_score_distribution(adapted) is adapted
    dumpable = SimpleNamespace(model_dump=lambda mode: adapted.model_dump(mode=mode))
    assert adapt_stage8_score_distribution(dumpable) == adapted


def test_stage8_rejects_aliases_binary_floats_and_hash_tampering() -> None:
    payload = json.loads(STAGE8.read_text(encoding="utf-8"))
    payload["matrix"] = payload.pop("probabilities")
    with pytest.raises(FplPointsError) as exc:
        adapt_stage8_score_distribution(payload)
    assert exc.value.code == "STAGE8_CONTRACT_INVALID"

    with pytest.raises(FplPointsError) as exc:
        adapt_stage8_score_distribution(object())
    assert exc.value.code == "STAGE8_CONTRACT_INVALID"

    payload = json.loads(STAGE8.read_text(encoding="utf-8"))
    payload["probabilities"][0][0] = 0.1
    with pytest.raises(FplPointsError) as exc:
        adapt_stage8_score_distribution(payload)
    assert exc.value.code == "STAGE8_CONTRACT_INVALID"


def test_stage7_path_adapter_uses_accepted_team_and_player_identities() -> None:
    home = _team_projection(HOME_TEAM_ID, 40000000)
    away = _team_projection(AWAY_TEAM_ID, 50000000)
    rows = _rows(home, away)
    scenario = build_participation_scenario(
        scenario_id="path-1",
        probability=1.0,
        fixture_id=FIXTURE_ID,
        gameweek_id="GW-1",
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        participant_rows=rows,
        home_projection=home,
        away_projection=away,
        information_cutoff_utc="2026-08-20T12:00:00Z",
    )
    assert len(scenario.participants) == 22
    assert scenario.stage7_minutes_context.home.result_sha256 == home.result_sha256
    assert scenario.stage7_player_projection_sha256s == {
        player.player_id: player.projection_sha256 for player in (*home.players, *away.players)
    }

    projected_home = MinutesPredictionResult(
        status="PROJECTED",
        fixture_id=home.fixture_id,
        team_id=home.team_id,
        as_of=home.as_of,
        projection=home,
        error_code=None,
    )
    mapped_away = MinutesPredictionResult(
        status="PROJECTED",
        fixture_id=away.fixture_id,
        team_id=away.team_id,
        as_of=away.as_of,
        projection=away,
        error_code=None,
    ).model_dump(mode="python")
    wrapped = build_participation_scenario(
        scenario_id="path-2",
        probability=1.0,
        fixture_id=FIXTURE_ID,
        gameweek_id="GW-1",
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        participant_rows=(SimpleNamespace(**row) for row in rows),
        home_projection=projected_home,
        away_projection=mapped_away,
        information_cutoff_utc="2026-08-20T12:00:00Z",
    )
    assert len(wrapped.participants) == 22


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda rows: rows[0].pop("player_id"), "UPSTREAM_FIELD_MISSING"),
        (lambda rows: rows[0].update(position="INVALID"), "STAGE7_POSITION_INVALID"),
        (lambda rows: rows[0].pop("entry_minute"), "STAGE7_INTERVAL_MISSING"),
        (lambda rows: rows[0].update(starter=1), "STAGE7_BOOLEAN_INVALID"),
        (lambda rows: rows[0].update(team_id=AWAY_TEAM_ID), "STAGE7_PLAYER_TEAM_MISMATCH"),
        (lambda rows: rows[0].update(position="DEF"), "STAGE7_PLAYER_POSITION_MISMATCH"),
        (lambda rows: rows[0].update(official_minutes=91), "STAGE7_MINUTES_INVALID"),
        (
            lambda rows: rows[0].update(official_minutes=89, entry_minute=0, exit_minute=89),
            "STAGE7_MINUTE_PMF_ZERO",
        ),
        (lambda rows: rows[0].update(exit_minute=89), "STAGE7_INTERVAL_INVALID"),
    ],
)
def test_stage7_path_adapter_rejects_bad_explicit_rows(mutation, code: str) -> None:
    home = _team_projection(HOME_TEAM_ID, 40000000)
    away = _team_projection(AWAY_TEAM_ID, 50000000)
    rows = [dict(row) for row in _rows(home, away)]
    mutation(rows)
    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(
            scenario_id="bad-path",
            probability=1.0,
            fixture_id=FIXTURE_ID,
            gameweek_id="GW-1",
            home_team_id=HOME_TEAM_ID,
            away_team_id=AWAY_TEAM_ID,
            participant_rows=rows,
            home_projection=home,
            away_projection=away,
            information_cutoff_utc="2026-08-20T12:00:00Z",
        )
    assert exc.value.code == code


def test_stage7_path_adapter_rejects_blocked_mismatched_and_colliding_projections() -> None:
    home = _team_projection(HOME_TEAM_ID, 40000000)
    away = _team_projection(AWAY_TEAM_ID, 50000000)
    blocked = MinutesPredictionResult(
        status="BLOCKED",
        fixture_id=home.fixture_id,
        team_id=home.team_id,
        as_of=home.as_of,
        projection=None,
        error_code="MINUTES_BLOCKED",
    )
    base = {
        "scenario_id": "bad-projection",
        "probability": 1.0,
        "fixture_id": FIXTURE_ID,
        "gameweek_id": "GW-1",
        "home_team_id": HOME_TEAM_ID,
        "away_team_id": AWAY_TEAM_ID,
        "participant_rows": _rows(home, away),
        "home_projection": home,
        "away_projection": away,
        "information_cutoff_utc": "2026-08-20T12:00:00Z",
    }
    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(**{**base, "home_projection": blocked})
    assert exc.value.code == "STAGE7_PROJECTION_BLOCKED"

    other_fixture = "10000000-0000-7000-8000-000000000999"
    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(
            **{
                **base,
                "home_projection": _team_projection(
                    HOME_TEAM_ID, 40000000, fixture_id=other_fixture
                ),
            }
        )
    assert exc.value.code == "STAGE7_FIXTURE_MISMATCH"

    wrong_team = "20000000-0000-7000-8000-000000000099"
    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(
            **{**base, "home_projection": _team_projection(wrong_team, 40000000)}
        )
    assert exc.value.code == "STAGE7_TEAM_MISMATCH"

    colliding_away = _team_projection(AWAY_TEAM_ID, 40000000)
    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(
            **{
                **base,
                "participant_rows": _rows(home, colliding_away),
                "away_projection": colliding_away,
            }
        )
    assert exc.value.code == "STAGE7_PLAYER_ID_COLLISION"

    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(**{**base, "home_projection": {"not": "a projection"}})
    assert exc.value.code == "STAGE7_CONTRACT_INVALID"

    with pytest.raises(FplPointsError) as exc:
        build_participation_scenario(**{**base, "participant_rows": base["participant_rows"][:-1]})
    assert exc.value.code == "STAGE7_PARTICIPATION_INVALID"


def test_cutoff_fails_at_request_boundary_and_ruleset_mismatch_blocks_service() -> None:
    request = make_request()
    payload = request.model_dump(mode="python")
    payload["information_cutoff_utc"] = "2026-08-20T13:00:00Z"
    with pytest.raises(ValidationError, match="Stage-8 cutoff"):
        FixtureSimulationRequest.model_validate(payload)

    payload = request.model_dump(mode="python")
    payload["expected_ruleset_hash"] = "9" * 64
    mismatched = FixtureSimulationRequest.model_validate(payload)
    result = FplPointsService(reference_engine(), mc_policy()).project(mismatched)
    assert result.error_code == "RULESET_REQUEST_MISMATCH"
