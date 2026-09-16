"""Explicit synthetic catalogue and event-live history. No provider execution or files."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dmf_pulse.fpl_points.current_player_posterior import load_historical_rate_resource
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.fpl_points.player_prior import (
    build_automatic_current_gw_stale_prior_policy,
    build_current_gw_player_prior_binding,
    load_packaged_player_prior,
)
from dmf_pulse.ingestion.fpl.current import CurrentFplDirectInputRequest, CurrentFplInputService
from dmf_pulse.ingestion.fpl.current_player_history import build_current_player_history_evidence
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot, parse_direct_event_live
from dmf_pulse.private_v1.automatic_inputs import _player_uuid, _team_uuid
from tests.unit.ingestion.current_manager_test_support import (
    _synthetic_bootstrap,
    _synthetic_fixtures,
)


def load_r9b_script(name):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[3] / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_inputs(
    repository_root: Path,
    *,
    count=20,
    gameweeks=4,
    changes=None,
    missing_rows=(),
    with_snapshot=False,
):
    bootstrap = _synthetic_bootstrap(repository_root)
    templates = {p["element_type"]: p for p in bootstrap["elements"]}
    # Existing governed position-level donors; numerical saves agree with GK structure.
    ids = (110, 120, 170, 176, 115, *range(10000, 10000 + count - 5))
    positions = (1, 2, 3, 4, 4, *(i % 4 + 1 for i in range(count - 5)))
    players = []
    event_rows = {gw: [] for gw in range(1, gameweeks + 1)}
    for index, (source_id, position) in enumerate(zip(ids, positions, strict=True)):
        player = deepcopy(templates[position])
        player.update(
            id=source_id,
            code=90000 + source_id,
            element_type=position,
            team=5 if source_id == 115 else index % 5 + 1,
            first_name="Synthetic",
            second_name=f"Shadow-{source_id}",
            web_name=f"SH{source_id}",
        )
        minutes_total = starts_total = 0
        for gw in event_rows:
            minutes = (0, 45, 90, 90, 90)[index % 5]
            stats = dict(
                minutes=minutes,
                starts=int(minutes > 0),
                goals_scored=int(minutes > 0 and index % 3 == 0),
                assists=int(minutes > 0 and index % 2 == 0),
                yellow_cards=int(index % 3 == 0),
                red_cards=int(index % 11 == 0),
                saves=3 if position == 1 and minutes else 0,
                own_goals=0,
                penalties_saved=0,
                penalties_missed=0,
                clearances_blocks_interceptions=4,
                tackles=2,
                recoveries=5,
                defensive_contribution=8,
                bonus=0,
                bps=-2 if not minutes else 14,
            )
            stats.update((changes or {}).get((source_id, gw), {}))
            minutes_total += stats.get("minutes") or 0
            starts_total += stats.get("starts") or 0
            if (source_id, gw) not in missing_rows:
                event_rows[gw].append(
                    dict(id=source_id, stats={k: v for k, v in stats.items() if v is not None})
                )
        player.update(minutes=minutes_total, starts=starts_total)
        players.append(player)
    bootstrap["elements"] = players
    cutoff = datetime(2026, 9, 16, 12, tzinfo=UTC)
    event_template = bootstrap["events"][0]
    bootstrap["events"] = []
    for gw in range(1, gameweeks + 2):
        event = deepcopy(event_template)
        event.update(
            id=gw,
            name=f"Synthetic GW {gw}",
            deadline_time=(
                cutoff + timedelta(days=3 if gw > gameweeks else gw - gameweeks - 1)
            ).isoformat(),
            finished=gw <= gameweeks,
            data_checked=gw <= gameweeks,
            is_previous=gw == gameweeks,
            is_current=False,
            is_next=gw == gameweeks + 1,
        )
        bootstrap["events"].append(event)
    fixtures = _synthetic_fixtures(repository_root)
    for fixture in fixtures:
        fixture.update(
            event=gameweeks + 1,
            kickoff_time=(cutoff + timedelta(days=4)).isoformat(),
            finished=False,
        )
    fpl = CurrentFplInputService(clock=lambda: cutoff).compile_direct(
        CurrentFplDirectInputRequest(
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=gameweeks + 1,
            captured_at=cutoff,
            information_cutoff=cutoff,
        ),
        bootstrap_body=json.dumps(bootstrap).encode(),
        fixtures_body=json.dumps(fixtures).encode(),
    )
    snapshot = DirectFplSnapshot.model_construct(
        fpl_input=fpl,
        target_gameweek=gameweeks + 1,
        request_count=7 + gameweeks,
        endpoint_classes=(
            "BOOTSTRAP",
            "FIXTURES",
            "ENTRY",
            "HISTORY",
            "TRANSFERS",
            "PICKS",
            "MY_TEAM",
            "EVENT_LIVE",
        ),
        live_by_gameweek={
            gw: parse_direct_event_live(json.dumps({"elements": rows}).encode())
            for gw, rows in event_rows.items()
        },
    )
    history = build_current_player_history_evidence(snapshot)
    prior = load_packaged_player_prior()
    policy = build_automatic_current_gw_stale_prior_policy(
        prior, fpl, current_official_fpl_element_ids=tuple(sorted(ids)), declared_at=cutoff
    )
    binding = build_current_gw_player_prior_binding(
        prior,
        fpl,
        policy,
        canonical_player_ids_by_source_id={
            p.provider_element_id: str(_player_uuid(p.identity.canonical_lookup_sha256))
            for p in fpl.players
        },
        canonical_team_ids_by_source_id={
            t.provider_team_id: str(_team_uuid(t.identity.canonical_lookup_sha256))
            for t in fpl.teams
        },
    )
    inputs = dict(
        history=history,
        current_fpl=fpl,
        binding=binding,
        policy=policy,
        prior=prior,
        historical=load_historical_rate_resource(),
    )
    return (inputs, snapshot) if with_snapshot else inputs


def synthetic_shadow(repository_root: Path, **kwargs):
    return compile_current_player_shadow(**synthetic_inputs(repository_root, **kwargs))


def synthetic_stage9_request(shadow, *, scenario_count=64, team_indexes=(0, 1), future_minutes=90):
    from uuid import UUID, uuid5

    from dmf_pulse.assurance.canonical import canonical_sha256
    from dmf_pulse.football_events.minutes_context import Stage7MinutesContext
    from dmf_pulse.fpl_points.models import (
        FixtureSimulationRequest,
        ParticipationScenario,
        ProjectionMode,
    )
    from tests.support.factories import (
        FIXTURE_ID,
        RULESET_HASH,
        RULESET_ID,
        RULESET_VERSION,
        _stage7_projection,
        allocation_config,
        participant,
        stage8_distribution,
    )

    world = shadow.worlds[0]
    entries = world.posterior.entries
    all_teams = sorted({e.binding.current_team_id for e in entries})
    teams = [all_teams[i] for i in team_indexes]
    fixture_id = str(uuid5(UUID(FIXTURE_ID), "|".join(teams)))
    chosen = []
    for team in teams:
        available = [e for e in entries if e.binding.current_team_id == team]
        for pos, number in (("GK", 1), ("DEF", 4), ("MID", 4), ("FWD", 2)):
            selected = [e for e in available if e.binding.position.value == pos][:number]
            assert len(selected) == number
            chosen.extend(selected)
    participants = tuple(
        participant(
            e.binding.current_player_id,
            e.binding.current_team_id,
            e.binding.position,
            minutes=future_minutes if i == 1 else 90,
            end=float(future_minutes if i == 1 else 90),
        )
        for i, e in enumerate(chosen)
    )
    cutoff = world.posterior.information_cutoff.isoformat().replace("+00:00", "Z")
    projections = tuple(
        _stage7_projection(
            fixture_id=fixture_id,
            team_id=team,
            cutoff=cutoff,
            players=tuple(p for p in participants if p.team_id == team),
        )
        for team in teams
    )
    context = Stage7MinutesContext.from_projections(*projections)
    template = stage8_distribution(
        fixture_id=fixture_id, home_team_id=teams[0], away_team_id=teams[1]
    )
    body = template.model_dump(mode="json")
    body.update(
        as_of=cutoff,
        information_cutoff=cutoff,
        source_minutes_as_of=cutoff,
        source_minutes_context=context.public_dict(),
        source_minutes_context_sha256=context.semantic_sha256,
        source_home_minutes_sha256=projections[0].result_sha256,
        source_away_minutes_sha256=projections[1].result_sha256,
    )
    body["result_sha256"] = canonical_sha256(
        {k: v for k, v in body.items() if k != "result_sha256"}
    )
    distribution = type(template).model_validate(body)
    participation = ParticipationScenario(
        scenario_id="synthetic-r9b-fixed-participation",
        fixture_id=fixture_id,
        gameweek_id="GW-5",
        home_team_id=teams[0],
        away_team_id=teams[1],
        probability=1.0,
        participant_universe_complete=True,
        participants=participants,
        stage7_minutes_context=context,
        stage7_player_projection_sha256s={
            p.player_id: p.projection_sha256
            for projection in projections
            for p in projection.players
        },
        stage7_home_projection=projections[0],
        stage7_away_projection=projections[1],
        information_cutoff_utc=cutoff,
    )
    ids = {p.player_id for p in participants}
    return FixtureSimulationRequest(
        schema_version="fpl-points-fixture-request-v1",
        gameweek_id="GW-5",
        projection_mode=ProjectionMode.TEST,
        as_of_utc=cutoff,
        information_cutoff_utc=cutoff,
        root_seed=12345,
        scenario_count=scenario_count,
        score_distribution=distribution,
        participation_scenarios=(participation,),
        allocation_profiles=tuple(p for p in world.stale_profiles if p.player_id in ids),
        allocation_config=allocation_config(),
        expected_ruleset_id=RULESET_ID,
        expected_ruleset_version=RULESET_VERSION,
        expected_ruleset_hash=RULESET_HASH,
    )


def synthetic_decision_inputs(shadow, *, scenario_count=32):
    from dmf_pulse.rules.compiler import compile_ruleset

    rules = compile_ruleset(Path(__file__).resolve().parents[3] / "config/rules/fpl-2026-27")
    requests = tuple(
        synthetic_stage9_request(shadow, scenario_count=scenario_count, team_indexes=pair)
        for pair in ((0, 1), (2, 3), (4, 0))
    )
    requests = tuple(
        type(r).model_validate(
            r.model_dump(mode="python")
            | {
                "expected_ruleset_id": rules.ruleset_id,
                "expected_ruleset_version": rules.ruleset_version,
                "expected_ruleset_hash": rules.ruleset_hash,
            }
        )
        for r in requests
    )
    universe = {p.player_id for request in requests for p in request.allocation_profiles}
    entries = [
        e for e in shadow.worlds[0].posterior.entries if e.binding.current_player_id in universe
    ]
    teams = sorted({e.binding.current_team_id for e in entries})
    selected = []
    for index, team in enumerate(teams):
        positions = ("GK", "DEF", "MID") if index < 2 else ("DEF", "MID", "FWD")
        for position in positions:
            selected.append(
                next(
                    e.binding.current_player_id
                    for e in entries
                    if e.binding.current_team_id == team and e.binding.position.value == position
                )
            )
    mids = [
        e.binding.current_player_id
        for e in entries
        if e.binding.current_team_id == teams[-1] and e.binding.position.value == "MID"
    ]
    first = tuple(sorted(selected))
    second = tuple(sorted(mids[1] if p == mids[0] else p for p in selected))
    return requests, (first, second)
