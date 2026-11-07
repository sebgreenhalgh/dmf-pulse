"""Owned match-time membership cases; no real player history or source rights."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from tests.unit.scripts.script_support import load_script

mq = load_script("model_quality_membership")
AT = datetime(2026, 9, 1, 12, tzinfo=UTC)


def owned_batch():
    evidence = mq.EvidenceTime(evidence_sha256="a" * 64, observed_at=AT, usable_at=AT)
    key = dict(season="2026/27", gameweek=7, player_id=UUID(int=7))
    fixtures = tuple(
        mq.Fixture(
            season="2026/27",
            gameweek=7,
            fixture_id=UUID(int=i),
            home_team_id=team,
            away_team_id=team + 2,
            status="FINISHED",
            evidence=evidence,
        )
        for i, team in ((11, 1), (12, 2))
    )
    return mq.OwnedHistoryBatch(
        cutoff=AT,
        aggregates=(mq.Aggregate(**key, minutes=60, starts=1),),
        membership=(mq.MembershipWindow(**key, fixture_ids=(UUID(int=11),), evidence=evidence),),
        fixtures=fixtures,
        participation=(
            mq.Participation(
                **key, fixture_id=UUID(int=11), team_id=1, minutes=60, starts=1, evidence=evidence
            ),
        ),
    )


def test_transferred_player_is_bound_to_exact_historical_fixture_and_team():
    result = mq.resolve_history(owned_batch())
    assert len(result.accepted) == result.accepted_aggregate_count == 1
    assert result.accepted[0].fixture_id == UUID(int=11)
    assert result.accepted[0].team_id == 1
    assert result.accepted[0].minutes == 60
    assert not result.excluded


def test_same_owned_inputs_expose_current_team_assignment_in_accepted_champion():
    from dmf_pulse.private_v1.automatic_inputs import _current_history, _fixture_uuid

    batch = owned_batch()
    fixtures = tuple(
        NS(
            event_identity=NS(external_id_text="7"),
            home_team_identity=NS(external_id_text=str(team)),
            away_team_identity=NS(external_id_text=str(team + 2)),
            identity=NS(canonical_lookup_sha256=letter * 64),
            provider_fixture_id=i,
        )
        for i, team, letter in ((11, 1, "a"), (12, 2, "b"))
    )
    snapshot = NS(
        captured_at=AT,
        fpl_input=NS(
            players=(
                NS(
                    provider_element_id=7,
                    team_identity=NS(external_id_text="2"),
                    position=NS(value="MID"),
                ),
            ),
            events=(NS(provider_event_id=7, deadline_at=AT - timedelta(days=1)),),
            fixtures=fixtures,
        ),
        live_by_gameweek={7: NS(elements=(NS(id=7, stats=NS(minutes=60, starts=1)),))},
    )
    identities = NS(
        players=(NS(official_fpl_element_id=7, canonical_player_id=UUID(int=7)),),
        teams=tuple(NS(official_fpl_team_id=i, canonical_team_id=UUID(int=i)) for i in range(1, 5)),
    )
    old, warnings = _current_history(snapshot, identities)
    actual_fixture_ids = (_fixture_uuid("a" * 64), _fixture_uuid("b" * 64))
    matched = batch.model_copy(
        update={
            "fixtures": tuple(
                row.model_copy(update={"fixture_id": fid})
                for row, fid in zip(batch.fixtures, actual_fixture_ids, strict=True)
            ),
            "membership": (
                batch.membership[0].model_copy(update={"fixture_ids": actual_fixture_ids[:1]}),
            ),
            "participation": (
                batch.participation[0].model_copy(update={"fixture_id": actual_fixture_ids[0]}),
            ),
        }
    )
    safe = mq.resolve_history(matched)
    assert old["rows"][0]["fixture_id"] == str(actual_fixture_ids[1])
    assert safe.accepted[0].fixture_id == actual_fixture_ids[0]
    assert old["rows"][0]["minutes_label"] == safe.accepted[0].minutes == 60
    assert "CURRENT_TEAM_ASSOCIATION_USED_FOR_RETRIEVED_HISTORY" in warnings


@given(st.integers(0, 90), st.integers(0, 90), st.booleans())
def test_double_requires_exact_per_fixture_values_and_is_order_invariant(first, second, reverse):
    batch = owned_batch()
    a = batch.participation[0].model_copy(update={"minutes": first})
    b = a.model_copy(update={"fixture_id": UUID(int=12), "team_id": 2, "minutes": second})
    double = batch.model_copy(
        update={
            "aggregates": (
                batch.aggregates[0].model_copy(update={"minutes": first + second, "starts": 2}),
            ),
            "membership": (
                batch.membership[0].model_copy(
                    update={"fixture_ids": (UUID(int=11), UUID(int=12))}
                ),
            ),
            "participation": (b, a) if reverse else (a, b),
            "fixtures": tuple(reversed(batch.fixtures)) if reverse else batch.fixtures,
        }
    )
    result = mq.resolve_history(double)
    assert [row.minutes for row in result.accepted] == [first, second]
    assert result.accepted_aggregate_count == 1 and not result.excluded
    missing = mq.resolve_history(double.model_copy(update={"participation": (a,)}))
    assert not missing.accepted and len(missing.excluded) == 1


def test_evidenced_blank_is_distinct_from_missing_and_generates_no_zero_row():
    batch = owned_batch()
    blank = batch.model_copy(
        update={
            "aggregates": (batch.aggregates[0].model_copy(update={"minutes": 0, "starts": 0}),),
            "membership": (batch.membership[0].model_copy(update={"fixture_ids": ()}),),
            "participation": (),
        }
    )
    result = mq.resolve_history(blank)
    assert len(result.known_blank) == 1 and not result.accepted and not result.excluded
    missing = mq.resolve_history(blank.model_copy(update={"membership": ()}))
    assert missing.excluded[0].reason == "MISSING_MEMBERSHIP" and not missing.known_blank


@pytest.mark.parametrize(
    "case",
    [
        "postponed",
        "scheduled",
        "rearranged_gw",
        "wrong_team",
        "late_membership",
        "late_participation",
        "ambiguous_window",
        "duplicate_fixture",
        "duplicate_fact",
        "extra_fact",
        "aggregate_mismatch",
    ],
)
def test_ambiguous_incomplete_or_temporally_invalid_history_is_excluded(case):
    batch = owned_batch()
    if case in {"postponed", "scheduled"}:
        batch = batch.model_copy(
            update={"fixtures": (batch.fixtures[0].model_copy(update={"status": case.upper()}),)}
        )
    elif case == "rearranged_gw":
        batch = batch.model_copy(
            update={"fixtures": (batch.fixtures[0].model_copy(update={"gameweek": 8}),)}
        )
    elif case == "wrong_team":
        batch = batch.model_copy(
            update={"participation": (batch.participation[0].model_copy(update={"team_id": 2}),)}
        )
    elif case.startswith("late_"):
        key = "membership" if case.endswith("membership") else "participation"
        row = getattr(batch, key)[0]
        batch = batch.model_copy(
            update={
                key: (
                    row.model_copy(
                        update={
                            "evidence": row.evidence.model_copy(
                                update={"usable_at": AT + timedelta(seconds=1)}
                            )
                        }
                    ),
                )
            }
        )
    elif case == "ambiguous_window":
        batch = batch.model_copy(update={"membership": batch.membership * 2})
    elif case == "duplicate_fixture":
        batch = batch.model_copy(update={"fixtures": (*batch.fixtures, batch.fixtures[0])})
    elif case == "duplicate_fact":
        batch = batch.model_copy(update={"participation": batch.participation * 2})
    elif case == "extra_fact":
        batch = batch.model_copy(
            update={
                "participation": (
                    *batch.participation,
                    batch.participation[0].model_copy(update={"fixture_id": UUID(int=12)}),
                )
            }
        )
    else:
        batch = batch.model_copy(
            update={"aggregates": (batch.aggregates[0].model_copy(update={"minutes": 61}),)}
        )
    result = mq.resolve_history(batch)
    assert not result.accepted and len(result.excluded) == 1 and not result.known_blank
    assert (
        result.input_aggregate_count
        == len(result.excluded) + len(result.known_blank) + result.accepted_aggregate_count
    )


def test_explicit_zero_minute_start_is_preserved_without_imputation():
    batch = owned_batch()
    result = mq.resolve_history(
        batch.model_copy(
            update={
                "aggregates": (batch.aggregates[0].model_copy(update={"minutes": 0}),),
                "participation": (batch.participation[0].model_copy(update={"minutes": 0}),),
            }
        )
    )
    assert result.accepted[0].starts == 1 and result.accepted[0].minutes == 0


def test_naive_times_real_mode_and_current_club_fields_are_refused():
    batch = owned_batch()
    for changes in (
        {"cutoff": AT.replace(tzinfo=None)},
        {"dataset_mode": "PROSPECTIVE_REAL"},
        {"current_team_id": 2},
    ):
        with pytest.raises(ValidationError):
            mq.OwnedHistoryBatch.model_validate({**batch.model_dump(), **changes})
    with pytest.raises(ValidationError):
        mq.Participation.model_validate({**batch.participation[0].model_dump(), "starts": True})
