"""Checkpoint-1.2 contracts for governed current official-FPL input."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.rules.models import FPLPosition

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 18, 12, tzinfo=UTC)
RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def _source(repository_root: Path, name: str) -> object:
    return json.loads(
        (repository_root / "fixtures/fpl/FPL-004/happy_path" / name).read_text(encoding="utf-8")
    )


def _write_pair(
    tmp_path: Path,
    bootstrap: object,
    fixtures: object,
    *,
    indent: int | None = None,
    sort_keys: bool = True,
) -> tuple[Path, Path]:
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_text(
        json.dumps(bootstrap, indent=indent, sort_keys=sort_keys), encoding="utf-8"
    )
    fixtures_path.write_text(
        json.dumps(fixtures, indent=indent, sort_keys=sort_keys), encoding="utf-8"
    )
    return bootstrap_path, fixtures_path


def _request(
    bootstrap_path: Path,
    fixtures_path: Path,
    **updates: Any,
) -> CurrentFplInputRequest:
    values: dict[str, object] = {
        "bootstrap_path": bootstrap_path,
        "fixtures_path": fixtures_path,
        "competition_key": "PL",
        "season_code": "2026/27",
        "captured_at": CAPTURED,
        "information_cutoff": CUTOFF,
        "rights_profile_id": "fpl_official_private_manual_v1",
        "gameweek": 1,
    }
    values.update(updates)
    return CurrentFplInputRequest.model_validate(values)


def _compile(
    request: CurrentFplInputRequest,
    *,
    received_at: datetime = RECEIVED,
):
    return CurrentFplInputService(clock=lambda: received_at).compile(request)


def _assert_error(request: CurrentFplInputRequest, code: str, *, received_at: datetime = RECEIVED):
    with pytest.raises(IngestionError) as raised:
        _compile(request, received_at=received_at)
    assert raised.value.code == code
    return raised.value


def test_valid_pair_exposes_complete_transient_current_input_contract(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    assert isinstance(fixtures, list)
    elements = bootstrap["elements"]
    assert isinstance(elements, list)
    first = elements[0]
    assert isinstance(first, dict)
    first["status"] = "d"
    first["chance_of_playing_next_round"] = 75
    first["chance_of_playing_this_round"] = 50
    first["news"] = "Minor doubt"
    first["news_added"] = "2026-08-18T10:00:00Z"
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)

    bundle = _compile(_request(bootstrap_path, fixtures_path))

    assert bundle.provider == "official_fpl"
    assert bundle.competition_key == "PL"
    assert bundle.season_code == "2026/27"
    assert bundle.target_gameweek == 1
    assert bundle.target_event.provider_event_id == 1
    assert bundle.target_event.deadline_at == CUTOFF
    assert len(bundle.teams) == 2
    assert len(bundle.players) == 4
    assert len(bundle.fixtures) == 1
    assert {position.canonical_position for position in bundle.positions} == set(FPLPosition)
    assert bundle.players[0].position is FPLPosition.GK
    assert bundle.players[0].current_price_tenths == 55
    assert bundle.players[0].status == "d"
    assert bundle.players[0].chance_of_playing_next_round == 75
    assert bundle.players[0].chance_of_playing_this_round == 50
    assert bundle.players[0].news == "Minor doubt"
    assert bundle.players[0].news_added == datetime(2026, 8, 18, 10, tzinfo=UTC)
    assert bundle.players[0].team_identity == bundle.teams[0].identity
    assert bundle.fixtures[0].event_identity == bundle.target_event.identity
    assert bundle.fixtures[0].home_team_identity == bundle.teams[0].identity
    assert bundle.fixtures[0].away_team_identity == bundle.teams[1].identity
    assert bundle.provenance.captured_at == CAPTURED
    assert bundle.provenance.received_at == RECEIVED
    assert bundle.provenance.information_cutoff == CUTOFF
    assert bundle.provenance.usable_at == RECEIVED
    assert bundle.provenance.transport_called is False
    assert bundle.rights.automated_access == "DENY"
    assert bundle.rights.raw_storage == "DENY"
    assert bundle.rights.derived_storage == "DENY"
    assert bundle.rights.database_accessed is False
    assert bundle.rights.raw_storage_performed is False
    assert bundle.rights.derived_storage_performed is False
    assert bundle.rights.operator_delete_required is True
    decisions = {decision.capability: decision.decision for decision in bundle.rights.decisions}
    assert decisions == {
        "automated_access": "DENY",
        "derived_storage": "DENY",
        "manual_import": "ALLOW",
        "private_internal_use": "ALLOW",
        "raw_storage": "DENY",
        "transient_processing": "ALLOW",
    }
    assert bundle.game_settings["squad_squadplay"] == 11
    assert len(bundle.semantic_sha256) == 64

    summary = bundle.safe_summary().model_dump(mode="json")
    rendered = json.dumps(summary, sort_keys=True)
    assert summary["player_count"] == 4
    assert summary["position_counts"] == {"DEF": 1, "FWD": 1, "GK": 1, "MID": 1}
    assert summary["status_counts"] == {"a": 3, "d": 1}
    assert summary["current_price_tenths_min"] == 50
    assert summary["current_price_tenths_max"] == 80
    assert summary["next_action"] == "CHECKPOINT 1.3 — LIVE THE ODDS API INPUT FOUNDATION"
    assert "A. Keeper" not in rendered
    assert "Minor doubt" not in rendered
    assert str(bootstrap_path) not in rendered
    assert str(fixtures_path) not in rendered


def test_compile_handles_decimal_game_setting_from_official_payload(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    game_settings = bootstrap["game_settings"]
    assert isinstance(game_settings, dict)
    # The official current payload carries this as a JSON number.  Its strict
    # parser intentionally reads JSON floats as Decimal to avoid float drift.
    game_settings["transfers_sell_on_fee"] = 0.5
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)

    bundle = _compile(_request(bootstrap_path, fixtures_path))

    assert bundle.game_settings["transfers_sell_on_fee"] == Decimal("0.5")
    assert len(bundle.game_settings_semantic_sha256) == 64


def test_position_mapping_uses_target_payload_labels_not_historical_numeric_ids(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    element_types = bootstrap["element_types"]
    elements = bootstrap["elements"]
    assert isinstance(element_types, list)
    assert isinstance(elements, list)
    replacement = {1: 41, 2: 17, 3: 88, 4: 5}
    for definition in element_types:
        assert isinstance(definition, dict)
        definition["id"] = replacement[int(definition["id"])]
    for player in elements:
        assert isinstance(player, dict)
        player["element_type"] = replacement[int(player["element_type"])]
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)

    bundle = _compile(_request(bootstrap_path, fixtures_path))

    assert {player.position for player in bundle.players} == set(FPLPosition)
    assert {position.provider_element_type_id for position in bundle.positions} == set(
        replacement.values()
    )


def test_semantically_equivalent_json_has_same_bundle_identity(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    left_paths = _write_pair(left, bootstrap, fixtures, indent=None, sort_keys=True)
    right_paths = _write_pair(right, bootstrap, fixtures, indent=2, sort_keys=False)

    left_bundle = _compile(_request(*left_paths), received_at=RECEIVED)
    right_bundle = _compile(_request(*right_paths), received_at=RECEIVED + timedelta(minutes=1))

    assert left_bundle.provenance.bootstrap_payload_sha256 != (
        right_bundle.provenance.bootstrap_payload_sha256
    )
    assert left_bundle.provenance.fixtures_payload_sha256 != (
        right_bundle.provenance.fixtures_payload_sha256
    )
    assert left_bundle.provenance.bootstrap_semantic_sha256 == (
        right_bundle.provenance.bootstrap_semantic_sha256
    )
    assert left_bundle.provenance.fixtures_semantic_sha256 == (
        right_bundle.provenance.fixtures_semantic_sha256
    )
    assert left_bundle.semantic_sha256 == right_bundle.semantic_sha256
    assert left_bundle.players[0].identity == right_bundle.players[0].identity


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("empty_teams", "VALIDATION_FAILED"),
        ("empty_players", "VALIDATION_FAILED"),
        ("duplicate_team", "VALIDATION_FAILED"),
        ("duplicate_player", "VALIDATION_FAILED"),
        ("unknown_player_team", "VALIDATION_FAILED"),
        ("unknown_position", "VALIDATION_FAILED"),
        ("zero_price", "VALIDATION_FAILED"),
        ("duplicate_fixture", "VALIDATION_FAILED"),
        ("unknown_fixture_team", "MAPPING_CONFLICT"),
        ("same_fixture_team", "VALIDATION_FAILED"),
        ("unknown_fixture_event", "MAPPING_CONFLICT"),
        ("missing_target_fixture", "VALIDATION_FAILED"),
        ("missing_target_kickoff", "VALIDATION_FAILED"),
        ("kickoff_before_deadline", "VALIDATION_FAILED"),
        ("incomplete_positions", "VALIDATION_FAILED"),
        ("duplicate_position_label", "VALIDATION_FAILED"),
        ("inconsistent_event_flags", "VALIDATION_FAILED"),
    ],
)
def test_structural_and_cross_resource_failures_are_explicit(
    repository_root: Path,
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    assert isinstance(fixtures, list)
    teams = bootstrap["teams"]
    elements = bootstrap["elements"]
    positions = bootstrap["element_types"]
    events = bootstrap["events"]
    assert isinstance(teams, list)
    assert isinstance(elements, list)
    assert isinstance(positions, list)
    assert isinstance(events, list)
    fixture = fixtures[0]
    assert isinstance(fixture, dict)

    if mutation == "empty_teams":
        bootstrap["teams"] = []
    elif mutation == "empty_players":
        bootstrap["elements"] = []
    elif mutation == "duplicate_team":
        teams.append(deepcopy(teams[0]))
    elif mutation == "duplicate_player":
        elements.append(deepcopy(elements[0]))
    elif mutation == "unknown_player_team":
        assert isinstance(elements[0], dict)
        elements[0]["team"] = 999
    elif mutation == "unknown_position":
        assert isinstance(elements[0], dict)
        elements[0]["element_type"] = 999
    elif mutation == "zero_price":
        assert isinstance(elements[0], dict)
        elements[0]["now_cost"] = 0
    elif mutation == "duplicate_fixture":
        fixtures.append(deepcopy(fixture))
    elif mutation == "unknown_fixture_team":
        fixture["team_h"] = 999
    elif mutation == "same_fixture_team":
        fixture["team_a"] = fixture["team_h"]
    elif mutation == "unknown_fixture_event":
        fixture["event"] = 999
    elif mutation == "missing_target_fixture":
        fixture["event"] = 2
    elif mutation == "missing_target_kickoff":
        fixture["kickoff_time"] = None
    elif mutation == "kickoff_before_deadline":
        fixture["kickoff_time"] = "2026-08-21T17:00:00Z"
    elif mutation == "incomplete_positions":
        positions.pop()
    elif mutation == "duplicate_position_label":
        assert isinstance(positions[0], dict)
        assert isinstance(positions[1], dict)
        positions[1]["singular_name_short"] = positions[0]["singular_name_short"]
    elif mutation == "inconsistent_event_flags":
        assert isinstance(events[1], dict)
        events[1]["is_current"] = True
    else:  # pragma: no cover - parameter contract
        raise AssertionError(mutation)

    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)
    _assert_error(_request(bootstrap_path, fixtures_path), code)


@pytest.mark.parametrize(
    ("resource", "body"),
    [("bootstrap", "{"), ("fixtures", "{")],
)
def test_malformed_json_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    resource: str,
    body: str,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)
    target = bootstrap_path if resource == "bootstrap" else fixtures_path
    target.write_text(body, encoding="utf-8")

    _assert_error(_request(bootstrap_path, fixtures_path), "MALFORMED_JSON")


def test_invalid_timestamp_types_and_values_fail_in_parser(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    events = bootstrap["events"]
    assert isinstance(events, list)
    assert isinstance(events[0], dict)
    events[0]["deadline_time"] = "not-a-timestamp"
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)
    _assert_error(_request(bootstrap_path, fixtures_path), "VALIDATION_FAILED")

    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(fixtures, list)
    assert isinstance(fixtures[0], dict)
    fixtures[0]["kickoff_time"] = "not-a-timestamp"
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)
    _assert_error(_request(bootstrap_path, fixtures_path), "VALIDATION_FAILED")


@pytest.mark.parametrize(
    ("request_updates", "received_at", "code"),
    [
        ({"captured_at": CUTOFF + timedelta(seconds=1)}, RECEIVED, "POST_CUTOFF"),
        (
            {"captured_at": CUTOFF, "information_cutoff": CUTOFF - timedelta(seconds=1)},
            RECEIVED,
            "POST_CUTOFF",
        ),
        ({}, CUTOFF + timedelta(seconds=1), "POST_CUTOFF"),
        ({"information_cutoff": CUTOFF + timedelta(seconds=1)}, RECEIVED, "POST_CUTOFF"),
    ],
)
def test_temporal_integrity_rejects_future_or_post_cutoff_inputs(
    repository_root: Path,
    tmp_path: Path,
    request_updates: dict[str, object],
    received_at: datetime,
    code: str,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    _assert_error(_request(*paths, **request_updates), code, received_at=received_at)


def test_request_rejects_naive_capture_or_cutoff_timestamps(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    for field in ("captured_at", "information_cutoff"):
        values: dict[str, object] = {
            "bootstrap_path": paths[0],
            "fixtures_path": paths[1],
            "competition_key": "PL",
            "season_code": "2026/27",
            "captured_at": CAPTURED,
            "information_cutoff": CUTOFF,
            "rights_profile_id": "fpl_official_private_manual_v1",
            "gameweek": 1,
        }
        values[field] = datetime(2026, 8, 18, 12)
        with pytest.raises(ValueError, match="timezone-aware"):
            CurrentFplInputRequest.model_validate(values)


def test_post_cutoff_availability_evidence_is_rejected(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    elements = bootstrap["elements"]
    assert isinstance(elements, list)
    assert isinstance(elements[0], dict)
    elements[0]["news_added"] = "2026-08-21T17:31:00Z"
    paths = _write_pair(tmp_path, bootstrap, fixtures)

    _assert_error(_request(*paths), "POST_CUTOFF")


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"competition_key": "UCL"}, "VALIDATION_FAILED"),
        ({"season_code": "2025/26"}, "VALIDATION_FAILED"),
        ({"rights_profile_id": "synthetic_test_v1"}, "RIGHTS_BLOCKED"),
    ],
)
def test_metadata_and_rights_mismatches_fail_closed(
    repository_root: Path,
    tmp_path: Path,
    updates: dict[str, object],
    code: str,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    _assert_error(_request(*paths, **updates), code)


def test_symlink_input_is_not_followed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    fixtures = repository_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json"
    link = tmp_path / "bootstrap-link.json"
    try:
        link.symlink_to(bootstrap)
    except OSError:
        pytest.fail("test environment must support symlinks")

    _assert_error(_request(link, fixtures), "SOURCE_UNAVAILABLE")
