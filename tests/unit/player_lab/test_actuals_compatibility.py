"""Documented conventions stay distinct from observed schema and source rights."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from uuid import uuid4

import pytest

from dmf_pulse.player_lab.actuals import ActualsError, FinalityContext
from dmf_pulse.player_lab.compatibility import (
    actuals_compatibility_proposal,
    check_offline_compatibility,
    future_cohort_proposal,
)

pytestmark = pytest.mark.unit


def fixture():
    root = files("dmf_pulse.player_lab.resources")
    return (
        root.joinpath("actuals-gw2.json").read_bytes(),
        FinalityContext.model_validate_json(root.joinpath("context-gw2.json").read_bytes()),
    )


def test_textual_rules_proposal_cannot_confer_schema_observation_or_rights():
    proposal = actuals_compatibility_proposal()
    assert len(proposal.official_identifiers) == 13
    assert proposal.observed_live_schema is False
    assert proposal.acquisition_authorized is False
    assert proposal.real_retention_authorized is False
    assert proposal.finality_policy == "FPL_2026_27_NEXT_DAY_0900_LONDON_V1"
    body, context = fixture()
    result = check_offline_compatibility(body, context)
    assert result.expected_players == result.matched_players == 4
    assert result.observed_live_schema is result.retention_authorized is False
    assert result.proposal_sha256 == proposal.semantic_sha256


@pytest.mark.parametrize(
    "attack", ["sparse", "new_field", "identifier", "boolean", "duplicate", "interim"]
)
def test_sparse_unknown_and_interim_data_cannot_be_accepted_as_zero(attack):
    body, context = fixture()
    payload = json.loads(body)
    if attack == "sparse":
        payload["elements"][0]["explain"][0]["stats"].pop()
    elif attack == "new_field":
        payload["elements"][0]["stats"]["new_live_stat"] = 0
    elif attack == "identifier":
        payload["elements"][0]["explain"][0]["stats"][0]["identifier"] = "started"
    elif attack == "boolean":
        payload["elements"][0]["stats"]["minutes"] = True
    elif attack == "duplicate":
        payload["elements"].append(payload["elements"][0])
    else:
        context = context.model_copy(update={"event_data_checked": False})
    with pytest.raises(ActualsError):
        check_offline_compatibility(json.dumps(payload).encode(), context)


def test_blank_and_double_gameweeks_are_explicit_and_do_not_verify_live_encoding():
    body, context = fixture()
    payload = json.loads(body)
    for player in payload["elements"]:
        player["stats"] = dict.fromkeys(player["stats"], 0)
        player["explain"] = []
    players = tuple(
        item.model_copy(
            update={
                "key": item.key.model_copy(update={"fixture_ids": ()}),
                "official_fixture_ids": (),
            }
        )
        for item in context.players
    )
    blank = context.model_copy(update={"players": players})
    assert check_offline_compatibility(json.dumps(payload).encode(), blank).matched_players == 4
    payload = json.loads(body)
    second_fixture = uuid4()
    for player in payload["elements"]:
        second = deepcopy(player["explain"][0])
        second["fixture"] = 201
        player["explain"].append(second)
        player["stats"] = {key: value * 2 for key, value in player["stats"].items()}
    players = tuple(
        item.model_copy(
            update={
                "key": item.key.model_copy(
                    update={
                        "fixture_ids": tuple(
                            sorted((*item.key.fixture_ids, second_fixture), key=str)
                        )
                    }
                ),
                "official_fixture_ids": (200, 201),
            }
        )
        for item in context.players
    )
    doubled = context.model_copy(
        update={
            "players": players,
            "fixture_mapping": {**context.fixture_mapping, 201: second_fixture},
        }
    )
    result = check_offline_compatibility(json.dumps(payload).encode(), doubled)
    assert result.matched_players == 4 and result.observed_live_schema is False
    # Two fixtures do not imply a start, nor a Gameweek60-plus probability.
    assert "independent observed-start" in " ".join(
        actuals_compatibility_proposal().unresolved_live_schema
    )


def test_transferred_player_retains_canonical_identity_and_exact_fixture_membership():
    body, context = fixture()
    payload = json.loads(body)
    replacement = uuid4()
    for player in payload["elements"]:
        player["explain"][0]["fixture"] = 300
    players = tuple(
        item.model_copy(
            update={
                "key": item.key.model_copy(update={"fixture_ids": (replacement,)}),
                "official_fixture_ids": (300,),
            }
        )
        for item in context.players
    )
    transferred = context.model_copy(
        update={"players": players, "fixture_mapping": {300: replacement}}
    )
    assert tuple(item.key.player_id for item in transferred.players) == tuple(
        item.key.player_id for item in context.players
    )
    assert (
        check_offline_compatibility(json.dumps(payload).encode(), transferred).matched_players == 4
    )
    with pytest.raises(ActualsError, match="FIXTURE_MISMATCH"):
        check_offline_compatibility(body, transferred)


def test_next_day_lock_uses_london_calendar_across_dst_change():
    body, context = fixture()
    # UK switches to GMT on25October2026: next-day09:00local is09:00UTC.
    retrieved = datetime(2026, 10, 25, 10, tzinfo=UTC)
    source = context.source.model_copy(update={"observed_at": retrieved, "usable_at": retrieved})
    changed = context.model_copy(
        update={
            "last_final_whistle_at": datetime(2026, 10, 24, 20, tzinfo=UTC),
            "points_lock_at": datetime(2026, 10, 25, 9, tzinfo=UTC),
            "retrieved_at": retrieved,
            "usable_at": retrieved,
            "source": source,
        }
    )
    assert check_offline_compatibility(body, changed).matched_players == 4
    with pytest.raises(ActualsError):
        check_offline_compatibility(
            body,
            changed.model_copy(update={"points_lock_at": datetime(2026, 10, 25, 8, tzinfo=UTC)}),
        )


def test_future_candidate_expires_and_never_authorizes_freeze():
    future = future_cohort_proposal(assessed_at=datetime(2026, 10, 29, 18, tzinfo=UTC))
    assert future.candidate_gameweek == 9
    assert future.candidate_deadline_at == datetime(2026, 10, 31, 11, tzinfo=UTC)
    assert future.status == "FUTURE_CANDIDATE_REQUIRES_APPROVAL"
    assert future.direct_open_status == "ACCESS_ERROR"
    assert future.evidence_kind == "OFFICIAL_PUBLIC_HTML_SEARCH_INDEX"
    assert future.execution_authorized is future.freeze_attempted is False
    assert future.real_cohort_size == 0
    expired = future_cohort_proposal(assessed_at=future.candidate_deadline_at)
    assert expired.status == "EXPIRED_NEXT_DEADLINE_UNRESOLVED"
    with pytest.raises(ValueError):
        future_cohort_proposal(assessed_at=datetime(2026, 10, 29))
