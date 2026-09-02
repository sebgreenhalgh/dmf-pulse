"""Official current penalty-order extraction remains transient, strict and ordinal."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct_payloads import (
    CurrentPenaltyHierarchy,
    CurrentPenaltyHierarchyTeamStatus,
    _target_gameweek,
    build_current_penalty_hierarchy,
    current_penalty_hierarchy_sha256,
)
from dmf_pulse.ingestion.fpl.parser import BootstrapPayload, FplResource, parse_fpl_payload
from tests.unit.ingestion.current_manager_test_support import _synthetic_bootstrap

CUTOFF = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def _extract(repository_root, mutate=None) -> CurrentPenaltyHierarchy:
    payload = deepcopy(_synthetic_bootstrap(repository_root))
    if mutate is not None:
        mutate(payload)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    parsed = parse_fpl_payload(FplResource.BOOTSTRAP, body)
    assert isinstance(parsed.payload, BootstrapPayload)
    return build_current_penalty_hierarchy(
        parsed.payload,
        observed_at=CUTOFF,
        information_cutoff=CUTOFF,
        source_bootstrap_payload_sha256=parsed.payload_sha256,
    )


def _complete(payload) -> None:
    next_order: dict[int, int] = {}
    for player in payload["elements"]:
        order = next_order.get(player["team"], 0) + 1
        next_order[player["team"]] = order
        player["penalties_order"] = order
        player["penalties_text"] = f"Published order {order}"


def test_complete_current_hierarchy_is_canonical_hash_bound_and_round_trips(
    repository_root,
) -> None:
    result = _extract(repository_root, _complete)

    assert result.source_class == "OFFICIAL_FPL_BOOTSTRAP_PROVIDER_PUBLISHED"
    assert len(result.entries) == 19
    assert len(result.teams) == len({item.official_fpl_team_id for item in result.teams})
    assert {item.status for item in result.teams} == {
        CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER
    }
    assert result.semantic_sha256 == current_penalty_hierarchy_sha256(result)
    assert tuple(result.entries) == tuple(
        sorted(
            result.entries,
            key=lambda item: (
                item.official_fpl_team_id,
                item.penalties_order,
                item.official_fpl_element_id,
            ),
        )
    )
    assert CurrentPenaltyHierarchy.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("missing_value", (None, 0))
def test_absent_null_and_zero_role_are_ignored(repository_root, missing_value) -> None:
    def mutate(payload) -> None:
        _complete(payload)
        player = payload["elements"][0]
        if missing_value is None:
            player.pop("penalties_order")
        else:
            player["penalties_order"] = missing_value

    result = _extract(repository_root, mutate)
    assert len(result.entries) == 18


@pytest.mark.parametrize("invalid", (True, "1", 1.0, -1, [], {}))
def test_unsupported_or_negative_penalty_order_fails_closed(repository_root, invalid) -> None:
    def mutate(payload) -> None:
        _complete(payload)
        payload["elements"][0]["penalties_order"] = invalid

    with pytest.raises(IngestionError, match="penalty hierarchy"):
        _extract(repository_root, mutate)


def test_duplicate_team_order_marks_only_that_team_ambiguous_and_remains_hash_bound(
    repository_root,
) -> None:
    def mutate(payload) -> None:
        _complete(payload)
        same_team = [item for item in payload["elements"] if item["team"] == 1]
        same_team[1]["penalties_order"] = 1

    result = _extract(repository_root, mutate)

    statuses = {item.official_fpl_team_id: item.status for item in result.teams}
    assert statuses[1] is CurrentPenaltyHierarchyTeamStatus.AMBIGUOUS_DUPLICATE_ORDER
    assert all(
        status is CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER
        for team_id, status in statuses.items()
        if team_id != 1
    )
    duplicate_rows = tuple(
        item
        for item in result.entries
        if item.official_fpl_team_id == 1 and item.penalties_order == 1
    )
    assert len(duplicate_rows) == 2
    assert result.semantic_sha256 == current_penalty_hierarchy_sha256(result)
    assert "CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS" in result.warnings


@pytest.mark.parametrize("orders", ((1, 3), (2, 3, 4)))
def test_noncontiguous_unique_team_order_is_usable_and_not_renumbered(
    repository_root, orders
) -> None:
    def mutate(payload) -> None:
        for player in payload["elements"]:
            player["penalties_order"] = 0
        same_team = [item for item in payload["elements"] if item["team"] == 1]
        for row, order in zip(same_team[: len(orders)], orders, strict=True):
            row["penalties_order"] = order

    result = _extract(repository_root, mutate)

    assert (
        tuple(item.penalties_order for item in result.entries if item.official_fpl_team_id == 1)
        == orders
    )
    statuses = {item.official_fpl_team_id: item.status for item in result.teams}
    assert statuses[1] is CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER
    assert set(statuses.values()) == {
        CurrentPenaltyHierarchyTeamStatus.USABLE_UNIQUE_ORDER,
        CurrentPenaltyHierarchyTeamStatus.NO_PUBLISHED_ORDER,
    }


def test_team_status_records_cover_catalogue_when_no_rows_are_published(repository_root) -> None:
    def mutate(payload) -> None:
        seen: set[int] = set()
        for player in payload["elements"]:
            if player["team"] != 1 and player["team"] not in seen:
                player["penalties_order"] = 1
                seen.add(player["team"])

    result = _extract(repository_root, mutate)

    catalogue = {item.official_fpl_team_id for item in result.teams}
    assert catalogue == {item.official_fpl_team_id for item in _extract(repository_root).teams}
    assert len(result.entries) == len(catalogue) - 1
    statuses = {item.official_fpl_team_id: item.status for item in result.teams}
    assert statuses[1] is CurrentPenaltyHierarchyTeamStatus.NO_PUBLISHED_ORDER
    assert "CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE" in result.warnings


def test_hierarchy_contract_rejects_naive_post_cutoff_and_wrong_hash(repository_root) -> None:
    valid = _extract(repository_root, _complete)
    payload = valid.model_dump(mode="python")

    with pytest.raises(ValueError, match="time must be aware"):
        CurrentPenaltyHierarchy.model_validate(
            {**payload, "observed_at": valid.observed_at.replace(tzinfo=None)}
        )
    with pytest.raises(ValueError, match="post-cutoff"):
        CurrentPenaltyHierarchy.model_validate(
            {**payload, "observed_at": valid.information_cutoff.replace(year=2027)}
        )
    with pytest.raises(ValueError, match="semantic hash"):
        CurrentPenaltyHierarchy.model_validate({**payload, "semantic_sha256": "f" * 64})


def test_target_gameweek_resolution_fails_closed_on_conflicting_provider_state(
    repository_root,
) -> None:
    def parsed(mutator) -> BootstrapPayload:
        payload = deepcopy(_synthetic_bootstrap(repository_root))
        mutator(payload)
        result = parse_fpl_payload(FplResource.BOOTSTRAP, json.dumps(payload).encode())
        assert isinstance(result.payload, BootstrapPayload)
        return result.payload

    def conflicting_next(payload) -> None:
        payload["events"][0]["is_next"] = True
        payload["events"][1]["is_next"] = True

    with pytest.raises(IngestionError, match="flags conflict"):
        _target_gameweek(parsed(conflicting_next), captured_at=CUTOFF)

    def ambiguous(payload) -> None:
        for event in payload["events"]:
            event["is_next"] = False
            event["finished"] = True

    with pytest.raises(IngestionError, match="ambiguous"):
        _target_gameweek(parsed(ambiguous), captured_at=CUTOFF)

    def deadline_passed(payload) -> None:
        payload["events"][1]["is_next"] = True
        payload["events"][1]["deadline_time"] = "2026-01-01T00:00:00Z"

    with pytest.raises(IngestionError, match="deadline has passed"):
        _target_gameweek(parsed(deadline_passed), captured_at=CUTOFF)

    def current_conflict(payload) -> None:
        payload["events"][0]["is_current"] = False
        payload["events"][1]["is_current"] = True
        payload["events"][1]["is_next"] = True

    with pytest.raises(IngestionError, match="current and next"):
        _target_gameweek(parsed(current_conflict), captured_at=CUTOFF)
