"""Fail-closed contracts for the official entry duplicate-summary remediation."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct_payloads import (
    CURRENT_FPL_ENTRY_DUPLICATE_SUMMARY_FIELDS_OBSERVED,
    CURRENT_FPL_ENTRY_EVENT_RANK_AMBIGUOUS_DISCARDED,
    CURRENT_FPL_ENTRY_OVERALL_RANK_AMBIGUOUS_UNAVAILABLE,
    CURRENT_FPL_ENTRY_OVERALL_RANK_RECONCILED_FROM_HISTORY_V1,
    DirectEntryOverallRankStatus,
    parse_direct_entry,
    parse_direct_history,
    resolve_direct_entry,
)

pytestmark = pytest.mark.unit


def _history(*, event: int = 4, points: int = 100, rank: int | None = 200) -> object:
    rank_text = "null" if rank is None else str(rank)
    return parse_direct_history(
        (
            '{"current":[{"event":'
            f'{event},"points":10,"total_points":{points},"overall_rank":{rank_text},'
            '"bank":0,"value":1000,"event_transfers":0,"event_transfers_cost":0}]}'
        ).encode()
    )


def test_observed_live_shape_is_reconciled_without_first_or_last_wins(
    repository_root: Path,
) -> None:
    body = (
        repository_root
        / "fixtures/fpl/PRIVATE-V1-ONE-COMMAND-001N-R3/entry_duplicate_summary_synthetic.json"
    ).read_bytes()

    result = resolve_direct_entry(body, history=_history(), target_gameweek=5)

    assert result.entry.summary_overall_points == 100
    assert result.entry.summary_overall_rank == 200
    assert result.quality.overall_rank_status is DirectEntryOverallRankStatus.HISTORY_RECONCILED
    assert CURRENT_FPL_ENTRY_DUPLICATE_SUMMARY_FIELDS_OBSERVED in result.quality.warnings
    assert CURRENT_FPL_ENTRY_EVENT_RANK_AMBIGUOUS_DISCARDED in result.quality.warnings
    assert CURRENT_FPL_ENTRY_OVERALL_RANK_RECONCILED_FROM_HISTORY_V1 in result.quality.warnings


def test_normal_and_identical_rank_duplicate_entries_are_unambiguous() -> None:
    normal = resolve_direct_entry(
        b'{"id":42,"started_event":1,"summary_overall_points":100,"summary_overall_rank":200}'
    )
    duplicate = resolve_direct_entry(
        b'{"id":42,"started_event":1,"summary_overall_rank":200,"summary_overall_rank":200}'
    )

    assert normal.entry.summary_overall_rank == 200
    assert normal.quality.duplicate_summary_fields == ()
    assert duplicate.entry.summary_overall_rank == 200
    assert (
        duplicate.quality.overall_rank_status is DirectEntryOverallRankStatus.DUPLICATE_UNAMBIGUOUS
    )


@pytest.mark.parametrize(
    ("history", "target_gameweek"),
    [
        (_history(rank=300), 5),
        (_history(points=99), 5),
        (_history(event=3), 5),
        (_history(rank=None), 5),
        (None, None),
    ],
)
def test_conflicting_rank_without_one_coherent_history_match_is_unavailable(
    history: object, target_gameweek: int | None
) -> None:
    result = resolve_direct_entry(
        b'{"id":42,"started_event":1,"summary_overall_points":100,'
        b'"summary_overall_rank":100,"summary_overall_rank":200}',
        history=history,  # type: ignore[arg-type]
        target_gameweek=target_gameweek,
    )

    assert result.entry.summary_overall_rank is None
    assert result.quality.overall_rank_status is DirectEntryOverallRankStatus.AMBIGUOUS_UNAVAILABLE
    assert CURRENT_FPL_ENTRY_OVERALL_RANK_AMBIGUOUS_UNAVAILABLE in result.quality.warnings
    with pytest.raises(IngestionError, match="overall rank is unavailable"):
        result.require_known_overall_rank()


@pytest.mark.parametrize(
    "body",
    [
        b'{"id":42,"id":42,"started_event":1}',
        b'{"id":42,"started_event":1,"started_event":1}',
        b'{"id":42,"started_event":1,"summary_overall_points":1,"summary_overall_points":2}',
        b'{"id":42,"started_event":1,"summary_event_points":1,"summary_event_points":2}',
        b'{"id":42,"started_event":1,"unknown":1,"unknown":1}',
        b'{"id":42,"started_event":1,"nested":{"a":1,"a":2}}',
        b'{"id":NaN,"started_event":1}',
        b'{"id":"42","started_event":1}',
    ],
)
def test_entry_duplicate_exceptions_remain_fail_closed(body: bytes) -> None:
    with pytest.raises(IngestionError, match="entry failed schema validation"):
        parse_direct_entry(body)
