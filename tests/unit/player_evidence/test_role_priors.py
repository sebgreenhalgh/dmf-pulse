"""Synthetic, offline assurance for the GW1-PLY-002 aggregate role-prior path."""

from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.models import HistorySensitivityWorld
from dmf_pulse.player_evidence.profiles import build_allocation_candidate
from dmf_pulse.player_evidence.role_priors import (
    MappingQuality,
    WyscoutInputPaths,
    WyscoutSourceFile,
    WyscoutSourceGovernance,
    build_role_prior_candidate,
    candidate_eb_parameters_from_role_prior,
    load_role_prior_candidate,
    load_verified_wyscout_source,
    map_wyscout_broad_role,
    reconstruct_regulation_minutes,
    role_priors_from_candidate,
    verify_role_prior_candidate,
)
from tests.unit.player_evidence.support import NOW, catalogue, price_policy


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _players() -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for player_id in range(1, 25):
        if player_id in {1, 12}:
            role = "Goalkeeper"
        elif player_id == 23:
            role = "Forward"
        elif player_id % 3 == 0:
            role = "Midfielder"
        else:
            role = "Defender"
        values.append({"wyId": player_id, "role": {"name": role}})
    return values


def _match() -> dict[str, object]:
    home_xi = [{"playerId": player_id} for player_id in range(1, 12)]
    away_xi = [{"playerId": player_id} for player_id in range(12, 23)]
    return {
        "wyId": 101,
        "duration": "Regular",
        "teamsData": {
            "home": {
                "formation": {
                    "lineup": home_xi,
                    "substitutions": [{"playerIn": 23, "playerOut": 2, "minute": 75}],
                }
            },
            "away": {"formation": {"lineup": away_xi, "substitutions": "null"}},
        },
    }


def _event(
    *,
    player_id: int,
    name: str,
    sub_name: str,
    tags: tuple[int, ...],
    period: str = "1H",
    seconds: float = 30.0,
) -> dict[str, object]:
    return {
        "eventName": name,
        "eventSec": seconds,
        "matchId": 101,
        "matchPeriod": period,
        "playerId": player_id,
        "subEventName": sub_name,
        "tags": [{"id": value} for value in tags],
    }


def _events() -> list[dict[str, object]]:
    return [
        _event(player_id=23, name="Shot", sub_name="Shot", tags=(101, 1205)),
        _event(player_id=23, name="Free Kick", sub_name="Penalty", tags=(101, 1205)),
        _event(player_id=3, name="Pass", sub_name="Simple pass", tags=(301, 302, 1801)),
        _event(player_id=3, name="Pass", sub_name="Cross", tags=(1801,)),
        _event(player_id=3, name="Others on the ball", sub_name="Clearance", tags=(1401,)),
        _event(player_id=3, name="Duel", sub_name="Ground defending duel", tags=(703,)),
        _event(player_id=3, name="Duel", sub_name="Ground attacking duel", tags=(703,)),
        _event(player_id=3, name="Foul", sub_name="Foul", tags=(1702,)),
        _event(player_id=3, name="Offside", sub_name="", tags=()),
        _event(player_id=3, name="Shot", sub_name="Shot", tags=(1210,)),
        _event(player_id=3, name="Shot", sub_name="Shot", tags=(1201,)),
        _event(player_id=1, name="Save attempt", sub_name="Reflexes", tags=(1801,)),
        _event(player_id=3, name="Others on the ball", sub_name="Touch", tags=(102,)),
        _event(
            player_id=1,
            name="Foul",
            sub_name="Foul",
            tags=(1701,),
            period="2H",
            seconds=900.0,
        ),
    ]


def _write_source(tmp_path: Path) -> tuple[WyscoutInputPaths, WyscoutSourceGovernance]:
    members: dict[str, tuple[Path, list[dict[str, object]]]] = {
        "players.json": (tmp_path / "players.json", _players()),
        "matches_England.json": (tmp_path / "matches_England.json", [_match()]),
        "events_England.json": (tmp_path / "events_England.json", _events()),
    }
    for path, payload in members.values():
        path.write_text(json.dumps(payload), encoding="utf-8")
    paths = WyscoutInputPaths(
        players=members["players.json"][0],
        matches=members["matches_England.json"][0],
        events=members["events_England.json"][0],
    )
    source_files = (
        WyscoutSourceFile(
            item_id=1,
            item_version=1,
            file_id=1,
            file_name="events.zip",
            download_url="https://example.invalid/events",
            supplied_md5="a" * 32,
            download_sha256="b" * 64,
            used_member="events_England.json",
            member_sha256=_sha(paths.events),
        ),
        WyscoutSourceFile(
            item_id=2,
            item_version=1,
            file_id=2,
            file_name="matches.zip",
            download_url="https://example.invalid/matches",
            supplied_md5="c" * 32,
            download_sha256="d" * 64,
            used_member="matches_England.json",
            member_sha256=_sha(paths.matches),
        ),
        WyscoutSourceFile(
            item_id=3,
            item_version=1,
            file_id=3,
            file_name="players.json",
            download_url="https://example.invalid/players",
            supplied_md5="e" * 32,
            download_sha256="f" * 64,
            used_member="players.json",
            member_sha256=_sha(paths.players),
        ),
    )
    return paths, WyscoutSourceGovernance(
        dataset_owner="Pappalardo / Wyscout Soccer Match Event Dataset",
        paper="Synthetic Wyscout schema fixture",
        figshare_collection="https://figshare.com/collections/Soccer_match_event_dataset/4415000/2",
        figshare_collection_version=5,
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Synthetic test fixture preserving the required attribution shape.",
        retrieved_at=NOW,
        files=source_files,
    )


def _candidate(tmp_path: Path):
    paths, source = _write_source(tmp_path)
    return build_role_prior_candidate(
        paths=paths,
        source=source,
        transformation_code_commit="a" * 40,
    )


@pytest.mark.unit
def test_verified_source_rejects_member_hash_mismatch(tmp_path: Path) -> None:
    paths, source = _write_source(tmp_path)
    paths.events.write_text("[]", encoding="utf-8")
    with pytest.raises(IngestionError) as error:
        load_verified_wyscout_source(paths=paths, source=source)
    assert error.value.code == "SOURCE_HASH_MISMATCH"


@pytest.mark.unit
def test_source_schema_rejects_current_fpl_shaped_material(tmp_path: Path) -> None:
    paths, source = _write_source(tmp_path)
    players = _players()
    players[0]["fantasy"] = "forbidden"
    paths.players.write_text(json.dumps(players), encoding="utf-8")
    altered_source = source.model_copy(
        update={
            "files": tuple(
                item.model_copy(update={"member_sha256": _sha(paths.players)})
                if item.used_member == "players.json"
                else item
                for item in source.files
            )
        }
    )
    with pytest.raises(IngestionError) as error:
        load_verified_wyscout_source(paths=paths, source=altered_source)
    assert error.value.code == "CURRENT_FPL_MATERIAL_FORBIDDEN"


@pytest.mark.unit
def test_role_mapping_is_limited_to_published_broad_taxonomy() -> None:
    assert map_wyscout_broad_role("Goalkeeper").value == "GK"
    assert map_wyscout_broad_role("Defender").value == "DEF"
    assert map_wyscout_broad_role("Midfielder").value == "MID"
    assert map_wyscout_broad_role("Forward").value == "FWD"
    with pytest.raises(IngestionError) as error:
        map_wyscout_broad_role("Centre Back")
    assert error.value.code == "ROLE_TAXONOMY_UNSUPPORTED"


@pytest.mark.unit
def test_minute_reconstruction_uses_xi_substitution_and_dismissal() -> None:
    minutes, excluded = reconstruct_regulation_minutes(matches=[_match()], events=_events())
    assert excluded == 0
    assert minutes[1] == 60.0
    assert minutes[2] == 75.0
    assert minutes[23] == 15.0
    assert minutes[12] == 90.0
    assert sum(minutes.values()) == 22 * 90.0 - 30.0


@pytest.mark.unit
def test_candidate_is_deterministic_aggregate_only_and_marks_sparse_position_fallback(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    repeated = _candidate(tmp_path)
    assert candidate.artifact_sha256 == repeated.artifact_sha256
    assert verify_role_prior_candidate(candidate) is candidate
    payload = json.dumps(candidate.model_dump(mode="json"), sort_keys=True)
    assert "playerId" not in payload
    assert "source_player_id" not in payload
    assert "fantasy.premierleague.com" not in payload
    fwd_goal = next(
        cell
        for cell in candidate.cells
        if cell.shrinkage_group_id == "wyscout-epl-2017-18-fpl-fwd"
        and cell.field == "goal_rate_per90"
    )
    generic_goal = next(
        cell
        for cell in candidate.cells
        if cell.shrinkage_group_id == "wyscout-epl-2017-18-league-generic"
        and cell.field == "goal_rate_per90"
    )
    assert not fwd_goal.minimum_support_met
    assert fwd_goal.prior_mean == generic_goal.prior_mean
    assert fwd_goal.fallback_level == "LEAGUE_GENERIC"


@pytest.mark.unit
def test_goal_penalty_assist_gk_and_unsupported_field_handling(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    generic = {
        cell.field: cell
        for cell in candidate.cells
        if cell.shrinkage_group_id == "wyscout-epl-2017-18-league-generic"
    }
    assert generic["goal_rate_per90"].event_count == 1
    assert generic["goal_rate_per90"].raw_pooled_rate is not None
    assert generic["assist_rate_per90"].event_count == 1
    assert generic["save_rate_per90"].event_count == 1
    assert generic["pass_completion_probability"].event_count == 2
    assert generic["pass_completion_probability"].prior_variance is not None
    assert (
        generic["saves_inside_box_fraction"].mapping_quality is MappingQuality.UNSUPPORTED_BY_SOURCE
    )
    assert generic["blocks_per90"].prior_mean == 0.0
    assert candidate.calibration.excluded_non_goalkeeper_save_events == 0


@pytest.mark.unit
def test_candidate_compiler_input_preserves_existing_stage7_boundary(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    priors = role_priors_from_candidate(candidate)
    assert priors == candidate.role_priors
    parameters = candidate_eb_parameters_from_role_prior(
        candidate, world=HistorySensitivityWorld.CENTRAL_TEMPORARY
    )
    assert parameters.goal_kappa_full_match_equivalents == 10.0
    cutoff = NOW + timedelta(days=1)
    posterior = compile_posterior_artifact(
        catalogue=catalogue(),
        histories=(),
        role_priors=candidate,
        tactical_roles={},
        parameters=parameters,
        information_cutoff=cutoff,
        source_observed_at=NOW,
        usable_at=NOW,
        produced_at=cutoff,
        source_locator="synthetic://role-prior-candidate",
        schema_fingerprint="a" * 64,
        rights_profile_id="SYNTHETIC_ONLY",
    )
    allocation = build_allocation_candidate(
        catalogue=catalogue(),
        posterior=posterior,
        role_priors=priors,
        tactical_roles={},
        information_cutoff=cutoff,
        price_policy=price_policy(),
        degraded_player_allocation=True,
    )
    assert allocation.degraded_player_allocation
    assert "STAGE7_MINUTES_NOT_EMBEDDED_IN_PERSISTENT_SHARES" in allocation.limitations
    assert all(profile.goal_share >= 0.0 for profile in allocation.profiles)


@pytest.mark.unit
def test_candidate_hash_tamper_is_rejected(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    tampered = candidate.model_copy(update={"artifact_sha256": "0" * 64})
    with pytest.raises(IngestionError) as error:
        verify_role_prior_candidate(tampered)
    assert error.value.code == "ARTIFACT_HASH_MISMATCH"


@pytest.mark.unit
def test_serialized_candidate_loads_with_strict_json_contract(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    path = tmp_path / "candidate.json"
    path.write_text(candidate.model_dump_json(), encoding="utf-8")
    assert load_role_prior_candidate(path) == candidate
