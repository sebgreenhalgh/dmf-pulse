"""CURRENT-FPL-STATE-001A manual transient current-FPL contracts."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import current as current_module
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.rules.models import FPLPosition

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 18, 12, tzinfo=UTC)
RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
GW1_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
GW2_CAPTURED = datetime(2026, 8, 24, 12, tzinfo=UTC)
GW2_RECEIVED = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)
GW2_CUTOFF = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)


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
    tmp_path.mkdir(parents=True, exist_ok=True)
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
        "target_gameweek": 1,
        "captured_at": CAPTURED,
        "information_cutoff": GW1_CUTOFF,
        "rights_profile_id": "fpl_official_private_manual_v1",
    }
    values.update(updates)
    return CurrentFplInputRequest.model_validate(values)


def _compile(
    request: CurrentFplInputRequest,
    *,
    received_at: datetime = RECEIVED,
):
    return CurrentFplInputService(clock=lambda: received_at).compile(request)


def _compile_with_times(
    request: CurrentFplInputRequest, received_at: datetime, usable_at: datetime
):
    values = iter((received_at, usable_at))
    return CurrentFplInputService(clock=lambda: next(values)).compile(request)


def _assert_error(
    request: CurrentFplInputRequest,
    code: str,
    *,
    received_at: datetime = RECEIVED,
) -> IngestionError:
    with pytest.raises(IngestionError) as raised:
        _compile(request, received_at=received_at)
    assert raised.value.code == code
    return raised.value


def _add_gw2_fixture(fixtures: list[object]) -> None:
    fixture = deepcopy(fixtures[0])
    assert isinstance(fixture, dict)
    fixture.update(
        {
            "id": 102,
            "code": 900102,
            "event": 2,
            "kickoff_time": "2026-08-29T14:00:00Z",
            "team_h": 2,
            "team_a": 1,
        }
    )
    fixtures.append(fixture)


def test_valid_pair_exposes_complete_private_contract_and_safe_summary(
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
    first.update(
        {
            "status": "d",
            "chance_of_playing_next_round": 75,
            "chance_of_playing_this_round": 50,
            "news": "PRIVATE-INJURY-TEXT",
            "news_added": "2026-08-18T10:00:00Z",
        }
    )
    bootstrap_path, fixtures_path = _write_pair(tmp_path, bootstrap, fixtures)

    bundle = _compile(_request(bootstrap_path, fixtures_path))

    assert bundle.provider == "official_fpl"
    assert bundle.competition_key == "PL"
    assert bundle.season_code == "2026/27"
    assert bundle.target_gameweek == 1
    assert bundle.target_event.provider_event_id == 1
    assert bundle.target_event.deadline_at == GW1_CUTOFF
    assert len(bundle.teams) == 2
    assert len(bundle.players) == 4
    assert len(bundle.events) == 2
    assert len(bundle.fixtures) == 1
    assert {position.canonical_position for position in bundle.positions} == set(FPLPosition)
    assert bundle.players[0].position is FPLPosition.GK
    assert bundle.players[0].current_price_tenths == 55
    assert bundle.players[0].status == "d"
    assert bundle.players[0].chance_of_playing_next_round == 75
    assert bundle.players[0].chance_of_playing_this_round == 50
    assert bundle.players[0].news == "PRIVATE-INJURY-TEXT"
    assert bundle.players[0].news_added == datetime(2026, 8, 18, 10, tzinfo=UTC)
    assert bundle.players[0].team_identity == bundle.teams[0].identity
    assert bundle.fixtures[0].event_identity == bundle.target_event.identity
    assert bundle.fixtures[0].home_team_identity == bundle.teams[0].identity
    assert bundle.fixtures[0].away_team_identity == bundle.teams[1].identity
    assert json.loads(bundle.game_settings.canonical_json)["squad_squadplay"] == 11
    assert len(bundle.game_settings.semantic_sha256) == 64

    provenance = bundle.provenance
    assert provenance.captured_at == CAPTURED
    assert provenance.received_at == RECEIVED
    assert provenance.information_cutoff == GW1_CUTOFF
    assert provenance.usable_at == RECEIVED
    assert provenance.input_bundle_semantic_sha256 == bundle.semantic_sha256
    assert provenance.transport_called is False
    assert provenance.database_accessed is False
    assert provenance.raw_storage_performed is False
    assert provenance.derived_storage_performed is False

    rights = bundle.rights
    assert rights.automated_access == "DENY"
    assert rights.raw_storage == "DENY"
    assert rights.derived_storage_profile_value == "UNKNOWN"
    assert rights.derived_storage == "DENY"
    assert rights.database_accessed is False
    assert rights.raw_storage_performed is False
    assert rights.derived_storage_performed is False
    assert rights.operator_delete_required is True
    assert {(item.capability, item.decision) for item in rights.decisions} == {
        ("automated_access", "DENY"),
        ("derived_storage", "DENY"),
        ("manual_import", "ALLOW"),
        ("private_internal_use", "ALLOW"),
        ("raw_storage", "DENY"),
        ("transient_processing", "ALLOW"),
    }

    summary = bundle.safe_summary().model_dump(mode="json")
    rendered = json.dumps(summary, sort_keys=True)
    assert summary["player_count"] == 4
    assert summary["team_count"] == 2
    assert summary["position_definition_count"] == 4
    assert summary["position_counts"] == {"DEF": 1, "FWD": 1, "GK": 1, "MID": 1}
    assert summary["status_counts"] == {"a": 3, "d": 1}
    assert summary["current_price_tenths_min"] == 50
    assert summary["current_price_tenths_max"] == 80
    assert summary["operator_delete_required"] is True
    assert summary["transport_called"] is False
    for secret in (
        "Alice",
        "A. Keeper",
        "PRIVATE-INJURY-TEXT",
        str(bootstrap_path),
        str(fixtures_path),
    ):
        assert secret not in rendered


def test_target_gameweek_is_generalized_for_current_and_next_events(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    assert isinstance(fixtures, list)
    _add_gw2_fixture(fixtures)
    paths = _write_pair(tmp_path, bootstrap, fixtures)

    next_bundle = _compile(
        _request(
            *paths,
            target_gameweek=2,
            captured_at=GW2_CAPTURED,
            information_cutoff=GW2_CUTOFF,
        ),
        received_at=GW2_RECEIVED,
    )
    assert next_bundle.target_gameweek == 2
    assert next_bundle.target_event.is_next is True
    assert next_bundle.safe_summary().target_gameweek_fixture_count == 1

    events = bootstrap["events"]
    assert isinstance(events, list)
    assert isinstance(events[0], dict)
    assert isinstance(events[1], dict)
    events[0].update({"is_current": False, "is_previous": True, "finished": True})
    events[1].update({"is_current": True, "is_next": False})
    current_paths = _write_pair(tmp_path / "current", bootstrap, fixtures)
    current_bundle = _compile(
        _request(
            *current_paths,
            target_gameweek=2,
            captured_at=GW2_CAPTURED,
            information_cutoff=GW2_CUTOFF,
        ),
        received_at=GW2_RECEIVED,
    )
    assert current_bundle.target_gameweek == 2
    assert current_bundle.target_event.is_current is True


@pytest.mark.parametrize(
    ("state", "case"),
    [
        (
            {
                "finished": True,
                "is_previous": False,
                "is_current": True,
                "is_next": False,
            },
            "finished_true",
        ),
        (
            {
                "finished": None,
                "is_previous": False,
                "is_current": True,
                "is_next": False,
            },
            "finished_null",
        ),
        (
            {
                "finished": False,
                "is_previous": True,
                "is_current": True,
                "is_next": False,
            },
            "previous_current",
        ),
        (
            {
                "finished": False,
                "is_previous": True,
                "is_current": False,
                "is_next": True,
            },
            "previous_next",
        ),
        (
            {
                "finished": False,
                "is_previous": False,
                "is_current": True,
                "is_next": True,
            },
            "current_next",
        ),
        (
            {
                "finished": False,
                "is_previous": None,
                "is_current": True,
                "is_next": False,
            },
            "previous_null",
        ),
        (
            {
                "finished": False,
                "is_previous": False,
                "is_current": None,
                "is_next": True,
            },
            "current_null",
        ),
        (
            {
                "finished": False,
                "is_previous": False,
                "is_current": True,
                "is_next": None,
            },
            "next_null",
        ),
        (
            {
                "finished": False,
                "is_previous": False,
                "is_current": False,
                "is_next": False,
            },
            "neither_current_nor_next",
        ),
    ],
)
def test_target_event_state_must_be_explicit_and_consistent(
    repository_root: Path,
    tmp_path: Path,
    state: dict[str, bool | None],
    case: str,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    events = bootstrap["events"]
    assert isinstance(events, list)
    target = events[0]
    assert isinstance(target, dict)
    target.update(state)
    paths = _write_pair(tmp_path / case, bootstrap, fixtures)

    _assert_error(_request(*paths), "VALIDATION_FAILED")


@pytest.mark.parametrize("case", ["two_current", "two_next", "previous_current", "current_next"])
def test_global_event_state_contradictions_fail_closed(
    repository_root: Path,
    tmp_path: Path,
    case: str,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    events = bootstrap["events"]
    assert isinstance(events, list)
    first = events[0]
    second = events[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    if case == "two_current":
        second["is_current"] = True
    elif case == "two_next":
        first["is_next"] = True
    elif case == "previous_current":
        first.update({"is_previous": True, "is_current": True, "is_next": False})
    elif case == "current_next":
        second.update({"is_previous": False, "is_current": True, "is_next": True})
    else:  # pragma: no cover - parameter contract
        raise AssertionError(case)
    paths = _write_pair(tmp_path / case, bootstrap, fixtures)

    _assert_error(_request(*paths), "VALIDATION_FAILED")


def test_position_mapping_uses_payload_labels_not_historical_numeric_ids(
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
    paths = _write_pair(tmp_path, bootstrap, fixtures)

    bundle = _compile(_request(*paths))

    assert {player.position for player in bundle.players} == set(FPLPosition)
    assert {position.provider_element_type_id for position in bundle.positions} == set(
        replacement.values()
    )


def test_semantic_and_safe_summary_hashes_are_deterministic(
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

    left_bundle = _compile(_request(*left_paths))
    right_bundle = _compile(_request(*right_paths))

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
    left_summary = left_bundle.safe_summary().model_dump(
        exclude={"bootstrap_payload_sha256", "fixtures_payload_sha256"}
    )
    right_summary = right_bundle.safe_summary().model_dump(
        exclude={"bootstrap_payload_sha256", "fixtures_payload_sha256"}
    )
    assert left_summary == right_summary
    assert left_bundle.players[0].identity == right_bundle.players[0].identity


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("empty_teams", "VALIDATION_FAILED"),
        ("empty_players", "VALIDATION_FAILED"),
        ("duplicate_team", "VALIDATION_FAILED"),
        ("duplicate_player", "VALIDATION_FAILED"),
        ("duplicate_event", "VALIDATION_FAILED"),
        ("unknown_player_team", "VALIDATION_FAILED"),
        ("unknown_position", "VALIDATION_FAILED"),
        ("zero_price", "VALIDATION_FAILED"),
        ("duplicate_fixture", "VALIDATION_FAILED"),
        ("unknown_fixture_team", "MAPPING_CONFLICT"),
        ("same_fixture_team", "VALIDATION_FAILED"),
        ("unknown_fixture_event", "MAPPING_CONFLICT"),
        ("missing_target_fixture", "VALIDATION_FAILED"),
        ("missing_target_kickoff", "VALIDATION_FAILED"),
        ("kickoff_at_deadline", "VALIDATION_FAILED"),
        ("incomplete_positions", "VALIDATION_FAILED"),
        ("duplicate_position_label", "VALIDATION_FAILED"),
        ("inconsistent_event_flags", "VALIDATION_FAILED"),
        ("target_current_and_next", "VALIDATION_FAILED"),
        ("finished_target", "VALIDATION_FAILED"),
        ("missing_game_settings", "VALIDATION_FAILED"),
        ("empty_fixtures", "VALIDATION_FAILED"),
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
    elif mutation == "duplicate_event":
        events.append(deepcopy(events[0]))
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
    elif mutation == "kickoff_at_deadline":
        fixture["kickoff_time"] = "2026-08-21T17:30:00Z"
    elif mutation == "incomplete_positions":
        positions.pop()
    elif mutation == "duplicate_position_label":
        assert isinstance(positions[0], dict)
        assert isinstance(positions[1], dict)
        positions[1]["singular_name_short"] = positions[0]["singular_name_short"]
    elif mutation == "inconsistent_event_flags":
        assert isinstance(events[1], dict)
        events[1]["is_current"] = True
    elif mutation == "target_current_and_next":
        assert isinstance(events[0], dict)
        events[0]["is_next"] = True
    elif mutation == "finished_target":
        assert isinstance(events[0], dict)
        events[0]["finished"] = True
    elif mutation == "missing_game_settings":
        bootstrap["game_settings"] = {}
    elif mutation == "empty_fixtures":
        fixtures.clear()
    else:  # pragma: no cover - parameter contract
        raise AssertionError(mutation)

    paths = _write_pair(tmp_path, bootstrap, fixtures)
    _assert_error(_request(*paths), code)


@pytest.mark.parametrize(
    ("resource", "body", "code"),
    [
        ("bootstrap", "{", "MALFORMED_JSON"),
        ("fixtures", "{", "MALFORMED_JSON"),
        ("bootstrap", "[]", "VALIDATION_FAILED"),
        ("fixtures", "{}", "VALIDATION_FAILED"),
    ],
)
def test_malformed_or_wrong_resource_json_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    resource: str,
    body: str,
    code: str,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    target = paths[0] if resource == "bootstrap" else paths[1]
    target.write_text(body, encoding="utf-8")
    _assert_error(_request(*paths), code)


@pytest.mark.parametrize(
    ("request_updates", "received_at", "code"),
    [
        ({"captured_at": GW1_CUTOFF + timedelta(seconds=1)}, RECEIVED, "POST_CUTOFF"),
        (
            {
                "captured_at": GW1_CUTOFF,
                "information_cutoff": GW1_CUTOFF - timedelta(seconds=1),
            },
            RECEIVED,
            "POST_CUTOFF",
        ),
        ({}, GW1_CUTOFF + timedelta(seconds=1), "POST_CUTOFF"),
        (
            {"information_cutoff": GW1_CUTOFF + timedelta(seconds=1)},
            RECEIVED,
            "POST_CUTOFF",
        ),
        ({"captured_at": RECEIVED + timedelta(seconds=1)}, RECEIVED, "VALIDATION_FAILED"),
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


def test_usable_at_after_cutoff_or_backwards_clock_fails_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    request = _request(*paths)
    with pytest.raises(IngestionError, match="usable post-cutoff") as post_cutoff:
        _compile_with_times(request, RECEIVED, GW1_CUTOFF + timedelta(seconds=1))
    assert post_cutoff.value.code == "POST_CUTOFF"

    with pytest.raises(IngestionError, match="moved backwards") as backwards:
        _compile_with_times(request, RECEIVED, RECEIVED - timedelta(seconds=1))
    assert backwards.value.code == "INTERNAL_INVARIANT"


def test_request_and_clock_reject_naive_timestamps(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    for field in ("captured_at", "information_cutoff"):
        values = _request(*paths).model_dump()
        values[field] = datetime(2026, 8, 18, 12)
        with pytest.raises(ValidationError, match="timezone-aware"):
            CurrentFplInputRequest.model_validate(values)

    with pytest.raises(IngestionError, match="clock must be timezone-aware") as raised:
        CurrentFplInputService(clock=lambda: datetime(2026, 8, 18, 12)).compile(_request(*paths))
    assert raised.value.code == "INTERNAL_INVARIANT"


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
        ({"target_gameweek": 38}, "VALIDATION_FAILED"),
    ],
)
def test_metadata_target_and_rights_mismatches_fail_closed(
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


def test_profile_that_enables_automated_access_is_rejected_before_files(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    profiles = load_rights_profiles()
    official = profiles["fpl_official_private_manual_v1"]
    capabilities = dict(official.capabilities)
    capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.ALLOW
    enabled = official.model_copy(update={"capabilities": capabilities})
    monkeypatch.setattr(
        current_module,
        "load_rights_profiles",
        lambda: {"fpl_official_private_manual_v1": enabled},
    )

    _assert_error(_request(*paths), "RIGHTS_BLOCKED")


def test_duplicate_unavailable_directory_and_symlink_inputs_fail_safely(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    fixtures = repository_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json"
    _assert_error(_request(bootstrap, bootstrap), "USAGE_INVALID")
    _assert_error(_request(tmp_path / "absent-private.json", fixtures), "SOURCE_UNAVAILABLE")
    _assert_error(_request(tmp_path, fixtures), "SOURCE_UNAVAILABLE")

    if os.name == "nt":
        monkeypatch.setattr(current_module.stat, "S_ISLNK", lambda _mode: True)
        with pytest.raises(IngestionError) as exc_info:
            current_module._safe_read(bootstrap)
        error = exc_info.value
        assert error.code == "SOURCE_UNAVAILABLE"
    else:
        link = tmp_path / "bootstrap-link.json"
        link.symlink_to(bootstrap)
        error = _assert_error(_request(link, fixtures), "SOURCE_UNAVAILABLE")
        assert str(link) not in error.message
    assert str(bootstrap) not in error.message


def test_resolved_and_hard_link_aliases_are_rejected_by_opened_identity(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    resolved_alias = bootstrap.parent / ".." / "happy_path" / "bootstrap.json"
    _assert_error(_request(bootstrap, resolved_alias), "USAGE_INVALID")

    hard_link = tmp_path / "bootstrap-hard-link.json"
    try:
        os.link(bootstrap, hard_link)
    except OSError as exc:
        pytest.skip(f"hard links are unavailable on this test host: {exc}")
    _assert_error(_request(bootstrap, hard_link), "USAGE_INVALID")


def test_descriptor_substitution_is_rejected_and_descriptor_is_closed(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    attacker = tmp_path / "attacker.json"
    attacker.write_bytes(b'"PRIVATE-ATTACKER-BYTES"')
    real_open = os.open
    real_fstat = os.fstat
    substituted_descriptors: list[int] = []

    def substituted_open(
        path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777
    ) -> int:
        del path
        descriptor = real_open(attacker, flags, mode)
        substituted_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(current_module.os, "open", substituted_open)

    with pytest.raises(IngestionError) as exc_info:
        current_module._safe_read(bootstrap)

    assert exc_info.value.code == "SOURCE_UNAVAILABLE"
    assert "PRIVATE-ATTACKER-BYTES" not in exc_info.value.message
    assert substituted_descriptors
    with pytest.raises(OSError):
        real_fstat(substituted_descriptors[0])


def test_opened_descriptor_must_be_regular_and_is_closed_on_failure(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    real_open = os.open
    real_fstat = os.fstat
    opened_descriptors: list[int] = []

    def observing_open(path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(path, flags, mode)
        opened_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(current_module.os, "open", observing_open)
    monkeypatch.setattr(current_module.os, "fstat", lambda _descriptor: tmp_path.stat())

    with pytest.raises(IngestionError) as exc_info:
        current_module._safe_read(bootstrap)

    assert exc_info.value.code == "SOURCE_UNAVAILABLE"
    assert opened_descriptors
    with pytest.raises(OSError):
        real_fstat(opened_descriptors[0])


def test_post_open_path_identity_mismatch_is_rejected(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    attacker = tmp_path / "replacement.json"
    attacker.write_bytes(b'"PRIVATE-REPLACEMENT-BYTES"')
    real_lstat = os.lstat
    calls = 0

    def substituted_lstat(path: str | bytes | os.PathLike[str]) -> os.stat_result:
        nonlocal calls
        calls += 1
        return real_lstat(path if calls == 1 else attacker)

    monkeypatch.setattr(current_module.os, "lstat", substituted_lstat)

    with pytest.raises(IngestionError) as exc_info:
        current_module._safe_read(bootstrap)

    assert calls == 2
    assert exc_info.value.code == "SOURCE_UNAVAILABLE"
    assert "PRIVATE-REPLACEMENT-BYTES" not in exc_info.value.message


def test_secure_open_uses_nofollow_when_available(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    real_open = os.open
    observed_flags: list[int] = []

    def observing_open(path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        observed_flags.append(flags)
        return real_open(path, flags, mode)

    monkeypatch.setattr(current_module.os, "open", observing_open)

    assert current_module._safe_read(bootstrap)
    assert observed_flags
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        assert observed_flags[0] & nofollow


@pytest.mark.parametrize("oversized_resource", ["bootstrap", "fixtures"])
def test_oversized_file_is_rejected_without_reading_beyond_bound(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    oversized_resource: str,
) -> None:
    bootstrap = repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    fixtures = repository_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json"
    oversized = tmp_path / f"{oversized_resource}.json"
    oversized.write_bytes(b"x" * 17)
    if oversized_resource == "bootstrap":
        bootstrap = oversized
    else:
        fixtures = oversized
    config = current_module.load_provider_config()
    monkeypatch.setattr(
        current_module,
        "load_provider_config",
        lambda: config.model_copy(update={"max_response_bytes": 16}),
    )
    _assert_error(_request(bootstrap, fixtures), "PAYLOAD_TOO_LARGE")


def test_schema_drift_is_reported_without_unknown_values(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap = _source(repository_root, "bootstrap.json")
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    bootstrap["provider_private_extension"] = "DO-NOT-DISCLOSE"
    paths = _write_pair(tmp_path, bootstrap, fixtures)

    bundle = _compile(_request(*paths))
    summary = bundle.safe_summary()

    assert summary.status == "VALID_WITH_WARNINGS"
    assert summary.data_quality_status == "PASS_WITH_WARNINGS"
    assert summary.data_quality_warning_count >= 1
    assert "DO-NOT-DISCLOSE" not in summary.model_dump_json()


def test_bundle_contracts_are_immutable(repository_root: Path, tmp_path: Path) -> None:
    paths = _write_pair(
        tmp_path,
        _source(repository_root, "bootstrap.json"),
        _source(repository_root, "fixtures.json"),
    )
    bundle = _compile(_request(*paths))

    with pytest.raises(ValidationError):
        bundle.target_gameweek = 2
    with pytest.raises(ValidationError):
        bundle.players[0].status = "u"
