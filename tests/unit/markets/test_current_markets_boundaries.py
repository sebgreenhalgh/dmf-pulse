"""Adversarial current-market source, cutoff, identity and readiness tests."""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

import dmf_pulse.markets.current as current_market_module
from dmf_pulse.ingestion.current_state import current_unified_state_semantic_sha256
from dmf_pulse.ingestion.models import RightsProfileStatus
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsBookmaker,
    CurrentOddsEvent,
    CurrentOddsQualityState,
)
from dmf_pulse.markets.current import (
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    CurrentMarketReadiness,
    bind_current_market_constraint_request,
    current_odds_rights_sha256,
    current_odds_temporal_sha256,
)

from .current_market_test_support import (
    build_from_context,
    build_market_context,
    identity_view,
    recompose,
    rehash_identity_view,
    rehash_odds,
    rehash_unified_source,
    replace_odds,
)


def _transform_event(
    context,
    event_index: int,
    transform: Callable[[CurrentOddsBookmaker], CurrentOddsBookmaker],
):
    events = list(context.odds_input.events)
    event = events[event_index]
    events[event_index] = event.model_copy(
        update={"bookmakers": tuple(transform(item) for item in event.bookmakers)}
    )
    return recompose(context, rehash_odds(context.odds_input, events=tuple(events)))


def _fixture_for_event(result, view, context, event_index: int):
    event_id = context.odds_input.events[event_index].provider_event_id
    mapping = next(
        item for item in context.identity_map.fixture_mappings if item.provider_event_id == event_id
    )
    fixture_id = view.fixture(mapping.official_fpl_fixture_id).canonical_fixture_id
    return next(item for item in result.fixtures if item.canonical_fixture_id == fixture_id)


def _changed_h2h_context(context):
    market = context.odds_input.events[0].bookmakers[0].markets[0]
    outcomes = tuple(
        item.model_copy(update={"decimal_price": Decimal("1.79")})
        if item.outcome == "HOME"
        else item
        for item in market.outcomes
    )
    return replace_odds(
        context,
        event_index=0,
        bookmaker_index=0,
        h2h_market=market.model_copy(update={"outcomes": outcomes}),
    )


def _one_operator_alias_view(view):
    first, second = view.operators
    return rehash_identity_view(
        view,
        operators=(
            first,
            second.model_copy(
                update={
                    "canonical_operator_id": first.canonical_operator_id,
                    "canonical_operator_key": first.canonical_operator_key,
                }
            ),
        ),
    )


def test_h2h_price_mutation_changes_every_bound_result_and_stale_request_fails(
    repository_root, tmp_path
) -> None:
    context, _view, request, result = build_market_context(repository_root, tmp_path)
    changed = _changed_h2h_context(context)
    changed_view, changed_request, changed_result = build_from_context(changed)

    assert changed.odds_input.market_semantic_sha256 != context.odds_input.market_semantic_sha256
    assert changed.bundle.semantic_sha256 != context.bundle.semantic_sha256
    assert changed_result.fixtures[0].h2h_consensus is not None
    assert result.fixtures[0].h2h_consensus is not None
    assert (
        changed_result.fixtures[0].h2h_consensus.result_sha256
        != result.fixtures[0].h2h_consensus.result_sha256
    )
    assert changed_result.fixtures[0].semantic_sha256 != result.fixtures[0].semantic_sha256
    assert changed_result.semantic_sha256 != result.semantic_sha256
    assert changed_request.current_unified_state_semantic_sha256 == changed.bundle.semantic_sha256

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            request,
            source=changed.bundle,
            identity_view=changed_view,
        )
    assert caught.value.code == "SOURCE_MISMATCH"

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().verify(
            result,
            changed_request,
            source=changed.bundle,
            identity_view=changed_view,
        )
    assert caught.value.code == "VERIFICATION_FAILED"


@pytest.mark.parametrize(
    "corruption",
    (
        "ONE_BOOK_SWAP",
        "ALL_BOOKS_SWAP",
        "HOME_NAME",
        "AWAY_NAME",
        "DRAW_NAME",
    ),
)
def test_cmr_ir_001_h2h_orientation_corruption_fails_closed(
    repository_root, tmp_path, corruption: str
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    selected = range(len(books)) if corruption == "ALL_BOOKS_SWAP" else range(1)
    for index in selected:
        market = books[index].markets[0]
        outcomes = []
        for outcome in market.outcomes:
            updates: dict[str, object] = {}
            if corruption in {"ONE_BOOK_SWAP", "ALL_BOOKS_SWAP"}:
                if outcome.outcome == "HOME":
                    updates["outcome"] = "AWAY"
                elif outcome.outcome == "AWAY":
                    updates["outcome"] = "HOME"
            elif corruption == "HOME_NAME" and outcome.outcome == "HOME":
                updates["provider_name"] = "synthetic wrong home"
            elif corruption == "AWAY_NAME" and outcome.outcome == "AWAY":
                updates["provider_name"] = "synthetic wrong away"
            elif corruption == "DRAW_NAME" and outcome.outcome == "DRAW":
                updates["provider_name"] = "synthetic not draw"
            outcomes.append(outcome.model_copy(update=updates))
        books[index] = books[index].model_copy(
            update={"markets": (market.model_copy(update={"outcomes": tuple(outcomes)}),)}
        )
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    changed_view = identity_view(changed)
    changed_request = bind_current_market_constraint_request(changed.bundle, changed_view)

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            changed_request,
            source=changed.bundle,
            identity_view=changed_view,
        )

    assert caught.value.code == "SOURCE_INVALID"
    serialized = json.dumps(caught.value.as_error_object(), sort_keys=True)
    assert event.provider_home_team not in serialized
    assert event.provider_away_team not in serialized


@pytest.mark.parametrize("mutation", ("REQUEST_STARTED", "RECEIPT", "USABLE"))
def test_cmr_ir_002_temporal_mutation_invalidates_stale_request_and_result_identity(
    repository_root, tmp_path, mutation: str
) -> None:
    context, _view, request, result = build_market_context(repository_root, tmp_path)
    temporal = context.odds_input.temporal
    if mutation == "REQUEST_STARTED":
        changed_temporal = temporal.model_copy(
            update={"request_started_at": temporal.request_started_at - timedelta(seconds=1)}
        )
    elif mutation == "RECEIPT":
        changed_temporal = temporal.model_copy(
            update={
                "received_at": temporal.received_at - timedelta(seconds=1),
                "captured_at": temporal.captured_at - timedelta(seconds=1),
            }
        )
    else:
        changed_temporal = temporal.model_copy(
            update={"usable_at": temporal.usable_at + timedelta(seconds=1)}
        )
    changed = recompose(
        context,
        context.odds_input.model_copy(update={"temporal": changed_temporal}),
    )
    changed_view = identity_view(changed)

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            request,
            source=changed.bundle,
            identity_view=changed_view,
        )
    assert caught.value.code == "SOURCE_MISMATCH"

    changed_request = bind_current_market_constraint_request(changed.bundle, changed_view)
    changed_result = CurrentMarketConstraintService().build(
        changed_request,
        source=changed.bundle,
        identity_view=changed_view,
    )
    assert changed_request.odds_temporal_sha256 != request.odds_temporal_sha256
    assert changed_result.lineage.odds_temporal_sha256 == (
        current_odds_temporal_sha256(changed.bundle)
    )
    assert changed_result.semantic_sha256 != result.semantic_sha256


def test_cmr_ir_002_temporal_digest_binds_complete_temporal_state(
    repository_root, tmp_path
) -> None:
    context, _view, request, result = build_market_context(repository_root, tmp_path)
    expected_fields = {
        "request_started_at",
        "received_at",
        "captured_at",
        "information_cutoff",
        "usable_at",
        "provider_response_generated_at",
        "provider_response_generated_at_state",
    }
    assert set(context.odds_input.temporal.model_dump(mode="json")) == expected_fields
    assert request.odds_temporal_sha256 == current_odds_temporal_sha256(context.bundle)
    assert result.lineage.odds_temporal_sha256 == request.odds_temporal_sha256


def test_totals_price_and_line_mutations_change_constraints(repository_root, tmp_path) -> None:
    context, _view, _request, result = build_market_context(repository_root, tmp_path)
    original = context.odds_input.events[0].bookmakers[0].totals_markets[1]
    price_outcomes = tuple(
        item.model_copy(update={"decimal_price": Decimal("1.88")})
        if item.outcome == "OVER"
        else item
        for item in original.outcomes
    )
    price_context = replace_odds(
        context,
        event_index=0,
        bookmaker_index=0,
        totals_markets=(
            context.odds_input.events[0].bookmakers[0].totals_markets[0],
            original.model_copy(update={"outcomes": price_outcomes}),
        ),
    )
    _price_view, _price_request, price_result = build_from_context(price_context)

    new_line = Decimal("3.5")
    line_market = original.model_copy(
        update={
            "line": new_line,
            "outcomes": tuple(
                item.model_copy(update={"point": new_line}) for item in original.outcomes
            ),
        }
    )
    line_context = replace_odds(
        context,
        event_index=0,
        bookmaker_index=0,
        totals_markets=(
            context.odds_input.events[0].bookmakers[0].totals_markets[0],
            line_market,
        ),
    )
    _line_view, _line_request, line_result = build_from_context(line_context)

    assert price_result.fixtures[0].totals_consensuses[1].result_sha256 != (
        result.fixtures[0].totals_consensuses[1].result_sha256
    )
    assert price_result.semantic_sha256 != result.semantic_sha256
    assert {item.line for item in line_result.fixtures[0].totals_consensuses} == {
        Decimal("1.5"),
        Decimal("2.5"),
        Decimal("3.5"),
    }
    assert line_result.fixtures[0].semantic_sha256 != result.fixtures[0].semantic_sha256


def test_missing_totals_degrades_only_the_affected_fixture(repository_root, tmp_path) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    changed = _transform_event(
        context,
        0,
        lambda bookmaker: bookmaker.model_copy(update={"totals_markets": ()}),
    )
    view, _request, result = build_from_context(changed)
    affected = _fixture_for_event(result, view, changed, 0)
    unaffected = _fixture_for_event(result, view, changed, 1)

    assert affected.readiness is CurrentMarketReadiness.H2H_ONLY_DEGRADED
    assert affected.h2h_consensus is not None
    assert not affected.totals_consensuses
    assert len(affected.constraint_set.constraints) == 3
    assert unaffected.readiness is CurrentMarketReadiness.MARKET_READY


def test_upstream_quality_exclusions_are_propagated_and_safely_summarized(
    repository_root, tmp_path
) -> None:
    context, _view, original_request, _result = build_market_context(repository_root, tmp_path)
    quality = CurrentOddsQualityState(
        status="WARNING",
        warnings=(
            "ADDITIVE_UNSUPPORTED_MARKET:btts",
            "PROVIDER_UNAVAILABLE",
            "SYNTHETIC_OTHER_WARNING",
            "TIMESTAMP_INCOHERENT",
            "TOTALS_INCOMPLETE",
        ),
        additive_unsupported_markets=("btts",),
    )
    changed = recompose(
        context,
        context.odds_input.model_copy(update={"quality": quality}),
    )
    changed_view, changed_request, result = build_from_context(changed)
    summary = result.safe_summary()
    serialized = json.dumps(summary.model_dump(mode="json"), sort_keys=True)

    assert result.source_quality_warnings == quality.warnings
    assert changed_request.odds_quality_sha256 != original_request.odds_quality_sha256
    assert {item.reason: item.count for item in result.source_exclusion_counts} == {
        "FUTURE_OBSERVATION": 1,
        "INCOMPLETE": 1,
        "QUALITY_BLOCKED": 1,
        "UNSUPPORTED": 1,
        "UNAVAILABLE": 1,
    }
    assert {item.reason: item.count for item in summary.exclusion_counts} == {
        "FUTURE_OBSERVATION": 1,
        "INCOMPLETE": 1,
        "QUALITY_BLOCKED": 1,
        "UNSUPPORTED": 1,
        "UNAVAILABLE": 1,
    }
    assert "btts" not in serialized
    assert "TOTALS_INCOMPLETE" not in serialized
    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            original_request,
            source=changed.bundle,
            identity_view=changed_view,
        )
    assert caught.value.code == "SOURCE_MISMATCH"


@pytest.mark.parametrize("age_minutes", [31, 61])
def test_stale_h2h_blocks_fixture_and_publishes_no_constraints(
    repository_root, tmp_path, age_minutes: int
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    stale_at = context.bundle.decision_information_at - timedelta(minutes=age_minutes)

    def stale(bookmaker: CurrentOddsBookmaker) -> CurrentOddsBookmaker:
        h2h = bookmaker.markets[0].model_copy(update={"provider_last_update": stale_at})
        totals = tuple(
            item.model_copy(update={"provider_last_update": stale_at})
            for item in bookmaker.totals_markets
        )
        return bookmaker.model_copy(
            update={
                "provider_last_update": stale_at,
                "age_at_receipt_seconds": int(
                    (context.odds_input.temporal.received_at - stale_at).total_seconds()
                ),
                "markets": (h2h,),
                "totals_markets": totals,
            }
        )

    changed = _transform_event(context, 0, stale)
    view, _request, result = build_from_context(changed)
    affected = _fixture_for_event(result, view, changed, 0)

    assert affected.readiness is CurrentMarketReadiness.BLOCKED
    assert affected.h2h_consensus is None
    assert not affected.constraint_set.constraints
    assert dict((item.reason, item.count) for item in affected.exclusion_counts)["STALE"] >= 2


def test_post_decision_market_evidence_is_excluded(repository_root, tmp_path) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    future_at = context.bundle.decision_information_at + timedelta(minutes=1)

    def future(bookmaker: CurrentOddsBookmaker) -> CurrentOddsBookmaker:
        return bookmaker.model_copy(
            update={
                "markets": (
                    bookmaker.markets[0].model_copy(update={"provider_last_update": future_at}),
                ),
                "totals_markets": tuple(
                    item.model_copy(update={"provider_last_update": future_at})
                    for item in bookmaker.totals_markets
                ),
            }
        )

    changed = _transform_event(context, 0, future)
    view, _request, result = build_from_context(changed)
    affected = _fixture_for_event(result, view, changed, 0)

    assert affected.readiness is CurrentMarketReadiness.BLOCKED
    assert not affected.constraint_set.constraints
    assert (
        dict((item.reason, item.count) for item in affected.exclusion_counts)["FUTURE_OBSERVATION"]
        >= 2
    )


@pytest.mark.parametrize("fallback", (False, True), ids=("market", "bookmaker-fallback"))
@pytest.mark.parametrize(
    ("offset_seconds", "expected_operators"),
    ((-1, 2), (0, 2), (1, 1)),
    ids=("before-receipt", "at-receipt", "after-receipt"),
)
def test_cmr_ir_003_totals_timestamp_is_bounded_by_receipt(
    repository_root,
    tmp_path,
    fallback: bool,
    offset_seconds: int,
    expected_operators: int,
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    book = books[0]
    totals = list(book.totals_markets)
    observed_at = context.odds_input.temporal.received_at + timedelta(seconds=offset_seconds)
    book_updates: dict[str, object] = {}
    if fallback:
        totals[1] = totals[1].model_copy(
            update={
                "provider_last_update": None,
                "provider_last_update_state": "NOT_PUBLISHED",
            }
        )
        book_updates.update(
            {
                "provider_last_update": observed_at,
                "age_at_receipt_seconds": max(0, -offset_seconds),
            }
        )
    else:
        totals[1] = totals[1].model_copy(update={"provider_last_update": observed_at})
    book_updates["totals_markets"] = tuple(totals)
    books[0] = book.model_copy(update=book_updates)
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    view, _request, result = build_from_context(changed)
    affected = _fixture_for_event(result, view, changed, 0)
    consensus = next(item for item in affected.totals_consensuses if item.line == Decimal("2.5"))

    assert consensus.eligible_operator_count == expected_operators
    exclusions = {item.reason: item.count for item in affected.exclusion_counts}
    if offset_seconds > 0:
        assert exclusions["FUTURE_OBSERVATION"] >= 1


def test_cmr_ir_003_future_alias_cannot_displace_valid_older_alias(
    repository_root, tmp_path
) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    totals = list(books[0].totals_markets)
    totals[1] = totals[1].model_copy(
        update={
            "provider_last_update": context.odds_input.temporal.received_at + timedelta(seconds=1)
        }
    )
    books[0] = books[0].model_copy(update={"totals_markets": tuple(totals)})
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    first, second = view.operators
    alias_view = rehash_identity_view(
        view,
        operators=(
            first,
            second.model_copy(
                update={
                    "canonical_operator_id": first.canonical_operator_id,
                    "canonical_operator_key": first.canonical_operator_key,
                }
            ),
        ),
    )
    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)
    consensus = next(item for item in affected.totals_consensuses if item.line == Decimal("2.5"))

    assert consensus.eligible_operator_count == 1
    assert consensus.operator_markets[0].observed_at == (
        books[1].totals_markets[1].provider_last_update
    )
    assert {item.reason: item.count for item in affected.exclusion_counts}[
        "FUTURE_OBSERVATION"
    ] >= 1


def test_cmr_ir_003_all_future_aliases_contribute_nothing(repository_root, tmp_path) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = []
    future_at = context.odds_input.temporal.received_at + timedelta(seconds=1)
    for book in event.bookmakers:
        totals = list(book.totals_markets)
        totals[1] = totals[1].model_copy(update={"provider_last_update": future_at})
        books.append(book.model_copy(update={"totals_markets": tuple(totals)}))
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    first, second = view.operators
    alias_view = rehash_identity_view(
        view,
        operators=(
            first,
            second.model_copy(
                update={
                    "canonical_operator_id": first.canonical_operator_id,
                    "canonical_operator_key": first.canonical_operator_key,
                }
            ),
        ),
    )
    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert Decimal("2.5") not in {item.line for item in affected.totals_consensuses}
    assert {item.reason: item.count for item in affected.exclusion_counts}[
        "FUTURE_OBSERVATION"
    ] == 2


@pytest.mark.parametrize("future_fallback", (False, True), ids=("market", "bookmaker-fallback"))
def test_cmr_ir_003_h2h_future_alias_cannot_suppress_valid_older_alias(
    repository_root, tmp_path, future_fallback: bool
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    received_at = context.odds_input.temporal.received_at
    valid_at = received_at - timedelta(seconds=1)
    future_at = received_at + timedelta(seconds=1)
    assert future_at <= context.bundle.decision_information_at
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    future_market_updates: dict[str, object] = {"provider_last_update": future_at}
    future_book_updates: dict[str, object] = {}
    if future_fallback:
        future_market_updates = {
            "provider_last_update": None,
            "provider_last_update_state": "NOT_PUBLISHED",
        }
        future_book_updates = {
            "provider_last_update": future_at,
            "age_at_receipt_seconds": 0,
        }
    future_book_updates["markets"] = (books[0].markets[0].model_copy(update=future_market_updates),)
    books[0] = books[0].model_copy(update=future_book_updates)
    books[1] = books[1].model_copy(
        update={
            "markets": (books[1].markets[0].model_copy(update={"provider_last_update": valid_at}),)
        }
    )
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    alias_view = _one_operator_alias_view(identity_view(changed))

    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert affected.h2h_consensus is not None
    assert affected.h2h_consensus.operator_count == 1
    assert affected.h2h_consensus.operator_markets[0].observed_at == valid_at
    assert {item.reason: item.count for item in affected.exclusion_counts}[
        "FUTURE_OBSERVATION"
    ] == 1
    if future_fallback:
        assert "H2H_TIMESTAMP_BOOKMAKER_FALLBACK" in affected.warnings

    reversed_events = list(changed.odds_input.events)
    reversed_events[0] = reversed_events[0].model_copy(
        update={"bookmakers": tuple(reversed(reversed_events[0].bookmakers))}
    )
    reordered = recompose(
        changed,
        rehash_odds(changed.odds_input, events=tuple(reversed_events)),
    )
    reordered_view = rehash_identity_view(
        _one_operator_alias_view(identity_view(reordered)),
        operators=tuple(reversed(_one_operator_alias_view(identity_view(reordered)).operators)),
    )
    _view, _request, reordered_result = build_from_context(reordered, reordered_view)
    assert reordered_result == result


def test_cmr_ir_003_h2h_all_future_aliases_contribute_nothing(repository_root, tmp_path) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    future_at = context.odds_input.temporal.received_at + timedelta(seconds=1)
    events = list(context.odds_input.events)
    event = events[0]
    books = tuple(
        book.model_copy(
            update={
                "markets": (book.markets[0].model_copy(update={"provider_last_update": future_at}),)
            }
        )
        for book in event.bookmakers
    )
    events[0] = event.model_copy(update={"bookmakers": books})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    alias_view = _one_operator_alias_view(identity_view(changed))

    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert affected.h2h_consensus is None
    assert affected.readiness is CurrentMarketReadiness.BLOCKED
    assert {item.reason: item.count for item in affected.exclusion_counts}[
        "FUTURE_OBSERVATION"
    ] == 1


def test_cmr_ir_003_h2h_newest_valid_alias_is_selected(repository_root, tmp_path) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    received_at = context.odds_input.temporal.received_at
    newest_at = received_at - timedelta(seconds=1)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    for index, observed_at in enumerate((newest_at, newest_at - timedelta(seconds=1))):
        books[index] = books[index].model_copy(
            update={
                "markets": (
                    books[index]
                    .markets[0]
                    .model_copy(update={"provider_last_update": observed_at}),
                )
            }
        )
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    alias_view = _one_operator_alias_view(identity_view(changed))

    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert affected.h2h_consensus is not None
    assert affected.h2h_consensus.operator_count == 1
    assert affected.h2h_consensus.operator_markets[0].observed_at == newest_at


def test_cmr_ir_003_h2h_tied_identical_aliases_are_deterministic(repository_root, tmp_path) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    tied_at = context.odds_input.temporal.received_at - timedelta(seconds=1)
    first_market = books[0].markets[0].model_copy(update={"provider_last_update": tied_at})
    books[0] = books[0].model_copy(update={"markets": (first_market,)})
    books[1] = books[1].model_copy(
        update={
            "markets": (
                books[1]
                .markets[0]
                .model_copy(
                    update={
                        "provider_last_update": tied_at,
                        "outcomes": first_market.outcomes,
                    }
                ),
            )
        }
    )
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    alias_view = _one_operator_alias_view(identity_view(changed))
    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert affected.h2h_consensus is not None
    assert affected.h2h_consensus.operator_count == 1
    assert affected.h2h_consensus.operator_markets[0].observed_at == tied_at


@pytest.mark.parametrize("attack", ("COHERENT_FULL_SWAP", "PARTICIPANTS_ONLY", "LABELS_ONLY"))
def test_cmr_ir_008_current_event_orientation_is_bound_to_accepted_001b_map(
    repository_root, tmp_path, attack: str
) -> None:
    context, view, _request, result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    swap_participants = attack in {"COHERENT_FULL_SWAP", "PARTICIPANTS_ONLY"}
    swap_labels = attack in {"COHERENT_FULL_SWAP", "LABELS_ONLY"}
    books = []
    for book in event.bookmakers:
        outcomes = tuple(
            outcome.model_copy(
                update={
                    "provider_name": (
                        event.provider_away_team
                        if outcome.outcome == "HOME"
                        else event.provider_home_team
                        if outcome.outcome == "AWAY"
                        else outcome.provider_name
                    )
                }
            )
            if swap_labels
            else outcome
            for outcome in book.markets[0].outcomes
        )
        books.append(
            book.model_copy(
                update={"markets": (book.markets[0].model_copy(update={"outcomes": outcomes}),)}
            )
        )
    event_updates: dict[str, object] = {"bookmakers": tuple(books)}
    if swap_participants:
        event_updates.update(
            provider_home_team=event.provider_away_team,
            provider_away_team=event.provider_home_team,
        )
    events[0] = event.model_copy(update=event_updates)
    changed_odds = rehash_odds(context.odds_input, events=tuple(events))
    changed_source = rehash_unified_source(context, odds_input=changed_odds)
    changed_request = bind_current_market_constraint_request(changed_source, view)

    with pytest.raises(CurrentMarketConstraintError) as built:
        CurrentMarketConstraintService().build(
            changed_request,
            source=changed_source,
            identity_view=view,
        )
    assert built.value.code == "SOURCE_INVALID"

    with pytest.raises(CurrentMarketConstraintError) as verified:
        CurrentMarketConstraintService().verify(
            result,
            changed_request,
            source=changed_source,
            identity_view=view,
        )
    assert verified.value.code == "SOURCE_INVALID"


def test_cmr_ir_008_mutated_001b_mapping_fails_structural_reconstruction(
    repository_root, tmp_path
) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    mappings = list(context.identity_map.fixture_mappings)
    mappings[0] = mappings[0].model_copy(
        update={"provider_home_team": mappings[0].provider_away_team}
    )
    changed_map = context.identity_map.model_copy(update={"fixture_mappings": tuple(mappings)})
    changed_source = context.bundle.model_copy(update={"identity_map": changed_map})
    changed_request = bind_current_market_constraint_request(changed_source, view)

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            changed_request,
            source=changed_source,
            identity_view=view,
        )

    assert caught.value.code == "SOURCE_INVALID"


def test_cmr_ir_008_current_fpl_fixture_orientation_must_match_001b(
    repository_root, tmp_path
) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    mapping = context.identity_map.fixture_mappings[0]
    fixtures = list(context.fpl_input.fixtures)
    index = next(
        index
        for index, fixture in enumerate(fixtures)
        if fixture.provider_fixture_id == mapping.official_fpl_fixture_id
    )
    fixture = fixtures[index]
    fixtures[index] = fixture.model_copy(
        update={
            "home_team_identity": fixture.away_team_identity,
            "away_team_identity": fixture.home_team_identity,
        }
    )
    changed_fpl = context.fpl_input.model_copy(update={"fixtures": tuple(fixtures)})
    changed_source = rehash_unified_source(context, fpl_input=changed_fpl)
    changed_request = bind_current_market_constraint_request(changed_source, view)

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            changed_request,
            source=changed_source,
            identity_view=view,
        )

    assert caught.value.code == "SOURCE_INVALID"


@pytest.mark.parametrize("side", ("HOME", "AWAY"))
def test_cmr_ir_008_exact_001b_team_bridge_rejects_side_mismatch(
    repository_root, tmp_path, side: str
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    mapping = context.identity_map.fixture_mappings[0]
    event = next(
        item
        for item in context.odds_input.events
        if item.provider_event_id == mapping.provider_event_id
    )
    if side == "HOME":
        hostile = mapping.model_copy(
            update={
                "official_home_team_id": mapping.official_away_team_id,
                "official_home_team_identity": mapping.official_away_team_identity,
            }
        )
    else:
        hostile = mapping.model_copy(
            update={
                "official_away_team_id": mapping.official_home_team_id,
                "official_away_team_identity": mapping.official_home_team_identity,
            }
        )

    with pytest.raises(CurrentMarketConstraintError) as caught:
        current_market_module._require_cross_source_orientation(
            context.bundle,
            hostile,
            event,
        )

    assert caught.value.code == "SOURCE_INVALID"


def test_cmr_ir_009_operator_occurrence_applicability_is_semantically_bound(
    repository_root, tmp_path
) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    second_target = events[1]
    events[1] = second_target.model_copy(
        update={
            "bookmakers": tuple(
                book for book in second_target.bookmakers if book.bookmaker_key != "book_alpha"
            )
        }
    )
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    stale_request = bind_current_market_constraint_request(changed.bundle, view)

    with pytest.raises(CurrentMarketConstraintError) as stale:
        CurrentMarketConstraintService().build(
            stale_request,
            source=changed.bundle,
            identity_view=view,
        )
    assert stale.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"

    fresh_view, _fresh_request, fresh_result = build_from_context(changed)
    original = {item.bookmaker_key: item for item in view.operators}
    fresh = {item.bookmaker_key: item for item in fresh_view.operators}
    assert fresh_view.semantic_sha256 != view.semantic_sha256
    assert (
        fresh["book_alpha"].target_occurrence_times_sha256
        != original["book_alpha"].target_occurrence_times_sha256
    )
    assert (
        fresh["book_beta"].target_occurrence_times_sha256
        == original["book_beta"].target_occurrence_times_sha256
    )
    assert len(fresh_result.fixtures) == 2


def test_totals_tied_alias_conflict_excludes_operator_line(repository_root, tmp_path) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    totals = list(books[1].totals_markets)
    tied_at = books[0].totals_markets[1].provider_last_update
    totals[1] = totals[1].model_copy(update={"provider_last_update": tied_at})
    books[1] = books[1].model_copy(update={"totals_markets": tuple(totals)})
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    first, second = view.operators
    alias_view = rehash_identity_view(
        view,
        operators=(
            first,
            second.model_copy(
                update={
                    "canonical_operator_id": first.canonical_operator_id,
                    "canonical_operator_key": first.canonical_operator_key,
                }
            ),
        ),
    )
    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert Decimal("2.5") not in {item.line for item in affected.totals_consensuses}
    assert {item.reason: item.count for item in affected.exclusion_counts}["QUALITY_BLOCKED"] >= 2


@pytest.mark.parametrize(
    ("prices", "fallback", "exponent_relation"),
    (
        ((Decimal("2.20"), Decimal("2.30")), False, "LT_ONE"),
        ((Decimal("2"), Decimal("2")), False, "ONE"),
        ((Decimal("1.000001"), Decimal("1.000002")), True, "NONE"),
        ((Decimal("1.000000000001"), Decimal("1000000000000")), False, "POSITIVE"),
    ),
    ids=("underround", "fair", "fallback", "extreme"),
)
def test_binary_totals_critical_power_and_fallback_paths(
    repository_root,
    tmp_path,
    prices: tuple[Decimal, Decimal],
    fallback: bool,
    exponent_relation: str,
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)

    def change(bookmaker: CurrentOddsBookmaker) -> CurrentOddsBookmaker:
        totals = list(bookmaker.totals_markets)
        market = totals[1]
        outcomes = tuple(
            outcome.model_copy(
                update={"decimal_price": prices[0] if outcome.outcome == "OVER" else prices[1]}
            )
            for outcome in market.outcomes
        )
        totals[1] = market.model_copy(update={"outcomes": outcomes})
        return bookmaker.model_copy(update={"totals_markets": tuple(totals)})

    changed = _transform_event(context, 0, change)
    view, _request, result = build_from_context(changed)
    consensus = next(
        item
        for item in _fixture_for_event(result, view, changed, 0).totals_consensuses
        if item.line == Decimal("2.5")
    )
    assert sum((item.consensus_probability for item in consensus.outcomes), Decimal(0)) == 1
    for operator in consensus.operator_markets:
        assert operator.fallback_used is fallback
        if exponent_relation == "LT_ONE":
            assert operator.power_exponent is not None and operator.power_exponent < 1
        elif exponent_relation == "ONE":
            assert operator.power_exponent == 1
        elif exponent_relation == "NONE":
            assert operator.power_exponent is None
            assert operator.primary_method == "PROPORTIONAL"
        else:
            assert operator.power_exponent is not None and operator.power_exponent > 0


@pytest.mark.parametrize("invalid_kind", ["H2H_INCOMPLETE", "TOTALS_INCOMPLETE", "QUARTER_LINE"])
def test_structurally_invalid_upstream_markets_fail_closed_and_sanitized(
    repository_root, tmp_path, invalid_kind: str
) -> None:
    context, view, request, _result = build_market_context(repository_root, tmp_path)
    events = list(context.odds_input.events)
    event = events[0]
    books = list(event.bookmakers)
    book = books[0]
    if invalid_kind == "H2H_INCOMPLETE":
        invalid_h2h = book.markets[0].model_copy(update={"outcomes": book.markets[0].outcomes[:2]})
        books[0] = book.model_copy(update={"markets": (invalid_h2h,)})
    else:
        totals = book.totals_markets[0]
        if invalid_kind == "TOTALS_INCOMPLETE":
            invalid_totals = totals.model_copy(update={"outcomes": totals.outcomes[:1]})
        else:
            line = Decimal("2.25")
            invalid_totals = totals.model_copy(
                update={
                    "line": line,
                    "outcomes": tuple(
                        item.model_copy(update={"point": line}) for item in totals.outcomes
                    ),
                }
            )
        books[0] = book.model_copy(
            update={"totals_markets": (invalid_totals, *book.totals_markets[1:])}
        )
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    invalid_odds = context.odds_input.model_copy(update={"events": tuple(events)})
    invalid_source = context.bundle.model_copy(update={"odds_input": invalid_odds})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(CurrentMarketConstraintError) as caught:
            CurrentMarketConstraintService().build(
                request,
                source=invalid_source,
                identity_view=view,
            )
    serialized = json.dumps(caught.value.as_error_object(), sort_keys=True)
    assert caught.value.code == "SOURCE_INVALID"
    assert invalid_kind not in str(caught.value)
    assert events[0].provider_event_id not in serialized
    assert book.bookmaker_key not in serialized
    assert str(book.markets[0].outcomes[0].decimal_price) not in serialized


def test_canonical_mapping_failure_and_error_surfaces_are_safe(repository_root, tmp_path) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    incomplete_view = rehash_identity_view(view, operators=view.operators[:1])
    request = bind_current_market_constraint_request(context.bundle, incomplete_view)

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            request,
            source=context.bundle,
            identity_view=incomplete_view,
        )
    surfaces = (
        str(caught.value),
        repr(caught.value),
        json.dumps(caught.value.as_error_object(), sort_keys=True),
    )
    forbidden = (
        {event.provider_event_id for event in context.odds_input.events}
        | {event.provider_home_team for event in context.odds_input.events}
        | {event.provider_away_team for event in context.odds_input.events}
        | {
            bookmaker.bookmaker_key
            for event in context.odds_input.events
            for bookmaker in event.bookmakers
        }
    )
    assert caught.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"
    assert all(secret not in surface for secret in forbidden for surface in surfaces)


def test_runtime_and_rights_hostile_mutations_fail_before_use(repository_root, tmp_path) -> None:
    context, view, request, _result = build_market_context(repository_root, tmp_path)
    hostile_rights = context.bundle.rights.model_copy(update={"private_internal_use": "DENY"})
    hostile_runtime = context.bundle.runtime.model_copy(update={"network_called": True})

    for source in (
        context.bundle.model_copy(update={"rights": hostile_rights}),
        context.bundle.model_copy(update={"runtime": hostile_runtime}),
    ):
        with pytest.raises(CurrentMarketConstraintError) as caught:
            CurrentMarketConstraintService().build(
                request,
                source=source,
                identity_view=view,
            )
        assert caught.value.code == "SOURCE_INVALID"


@pytest.mark.parametrize(
    ("mutation", "value"),
    (
        ("PROFILE_ID", "synthetic_unapproved_profile"),
        ("PROFILE_VERSION", "9.9.9"),
        ("CONFIG_SHA", "f" * 64),
    ),
)
def test_cmr_ir_006_exact_odds_rights_identity_blocks_stale_and_fresh_requests(
    repository_root, tmp_path, mutation: str, value: str
) -> None:
    context, _view, request, result = build_market_context(repository_root, tmp_path)
    if mutation == "CONFIG_SHA":
        changed_odds = context.odds_input.model_copy(
            update={
                "provenance": context.odds_input.provenance.model_copy(
                    update={"rights_config_sha256": value}
                )
            }
        )
    else:
        field = "rights_profile_id" if mutation == "PROFILE_ID" else "rights_profile_version"
        changed_odds = context.odds_input.model_copy(
            update={"rights": context.odds_input.rights.model_copy(update={field: value})}
        )
    changed_source = context.bundle.model_copy(update={"odds_input": changed_odds})

    with pytest.raises(CurrentMarketConstraintError) as stale:
        CurrentMarketConstraintService().build(
            request,
            source=changed_source,
            identity_view=_view,
        )
    assert stale.value.code == ("SOURCE_INVALID" if mutation == "CONFIG_SHA" else "SOURCE_MISMATCH")

    changed_request = bind_current_market_constraint_request(changed_source, _view)
    assert changed_request.odds_rights_sha256 != request.odds_rights_sha256
    with pytest.raises(CurrentMarketConstraintError) as fresh:
        CurrentMarketConstraintService().build(
            changed_request,
            source=changed_source,
            identity_view=_view,
        )
    assert fresh.value.code == ("SOURCE_INVALID" if mutation == "CONFIG_SHA" else "RIGHTS_BLOCKED")
    surfaces = (
        str(fresh.value),
        repr(fresh.value),
        json.dumps(fresh.value.as_error_object(), sort_keys=True),
    )
    assert all(value not in surface for surface in surfaces)
    assert result.lineage.odds_rights_sha256 == current_odds_rights_sha256(context.bundle)


@pytest.mark.parametrize("authority_defect", ("PROVIDER", "STATUS"))
def test_cmr_ir_006_packaged_profile_must_be_provider_matched_and_human_approved(
    repository_root, tmp_path, monkeypatch, authority_defect: str
) -> None:
    context, view, request, _result = build_market_context(repository_root, tmp_path)
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    if authority_defect == "PROVIDER":
        profile = profile.model_copy(update={"provider_key": "synthetic_wrong_provider"})
    else:
        profile = profile.model_copy(update={"status": RightsProfileStatus.DRAFT})
    monkeypatch.setattr(
        current_market_module,
        "load_rights_profiles",
        lambda: {"the_odds_api_private_analytics_v1": profile},
    )

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            request,
            source=context.bundle,
            identity_view=view,
        )

    assert caught.value.code == "SOURCE_INVALID"
    assert "synthetic_wrong_provider" not in str(caught.value)


def test_cmr_ir_006_required_odds_effective_right_denial_is_safe(repository_root, tmp_path) -> None:
    context, view, request, _result = build_market_context(repository_root, tmp_path)
    denied = context.odds_input.rights.model_copy(update={"private_internal_use": "DENY"})
    hostile_odds = context.odds_input.model_copy(update={"rights": denied})
    hostile_source = context.bundle.model_copy(update={"odds_input": hostile_odds})

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            request,
            source=hostile_source,
            identity_view=view,
        )

    assert caught.value.code == "SOURCE_INVALID"


def test_semantic_result_is_order_independent_where_source_contract_allows(
    repository_root, tmp_path
) -> None:
    context, view, _request, result = build_market_context(repository_root, tmp_path)
    changed_events: list[CurrentOddsEvent] = []
    for event in reversed(context.odds_input.events):
        books = []
        for bookmaker in reversed(event.bookmakers):
            market = bookmaker.markets[0].model_copy(
                update={"outcomes": tuple(reversed(bookmaker.markets[0].outcomes))}
            )
            totals = tuple(
                item.model_copy(update={"outcomes": tuple(reversed(item.outcomes))})
                for item in bookmaker.totals_markets
            )
            books.append(
                bookmaker.model_copy(update={"markets": (market,), "totals_markets": totals})
            )
        changed_events.append(event.model_copy(update={"bookmakers": tuple(books)}))
    reordered = recompose(
        context,
        rehash_odds(context.odds_input, events=tuple(changed_events)),
    )
    reordered_view = rehash_identity_view(
        view,
        fixtures=tuple(reversed(view.fixtures)),
        operators=tuple(reversed(view.operators)),
    )
    _view, _request, reordered_result = build_from_context(reordered, reordered_view)

    assert reordered.odds_input.market_semantic_sha256 == (
        context.odds_input.market_semantic_sha256
    )
    assert reordered.bundle.semantic_sha256 == context.bundle.semantic_sha256
    assert reordered_view.semantic_sha256 == view.semantic_sha256
    assert reordered_result == result


def test_provider_aliases_collapse_to_one_canonical_operator(repository_root, tmp_path) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    first, second = view.operators
    aliased = second.model_copy(
        update={
            "canonical_operator_id": first.canonical_operator_id,
            "canonical_operator_key": first.canonical_operator_key,
        }
    )
    alias_view = rehash_identity_view(view, operators=(first, aliased))
    _view, _request, result = build_from_context(context, alias_view)

    for fixture in result.fixtures:
        assert fixture.readiness is CurrentMarketReadiness.MARKET_READY
        assert fixture.h2h_consensus is not None
        assert fixture.h2h_consensus.operator_count == 1
        assert all(item.operator_count == 1 for item in fixture.totals_consensuses)
        exclusions = {item.reason: item.count for item in fixture.exclusion_counts}
        assert exclusions["DUPLICATE_OPERATOR"] >= 1


def test_conflicting_tied_provider_aliases_fail_h2h_closed(repository_root, tmp_path) -> None:
    context, view, _request, _result = build_market_context(repository_root, tmp_path)
    event = context.odds_input.events[0]
    first_time = event.bookmakers[0].markets[0].provider_last_update
    assert first_time is not None
    books = list(event.bookmakers)
    books[1] = books[1].model_copy(
        update={
            "provider_last_update": first_time,
            "markets": (
                books[1].markets[0].model_copy(update={"provider_last_update": first_time}),
            ),
        }
    )
    events = list(context.odds_input.events)
    events[0] = event.model_copy(update={"bookmakers": tuple(books)})
    changed = recompose(context, rehash_odds(context.odds_input, events=tuple(events)))
    first, second = view.operators
    alias_view = rehash_identity_view(
        view,
        operators=(
            first,
            second.model_copy(
                update={
                    "canonical_operator_id": first.canonical_operator_id,
                    "canonical_operator_key": first.canonical_operator_key,
                }
            ),
        ),
    )
    _view, _request, result = build_from_context(changed, alias_view)
    affected = _fixture_for_event(result, alias_view, changed, 0)

    assert affected.readiness is CurrentMarketReadiness.BLOCKED
    assert affected.h2h_consensus is None
    assert not affected.constraint_set.constraints
    assert "H2H_DUPLICATE_OPERATOR_ALIAS_CONFLICT" in affected.warnings


def test_fresh_rebinding_to_different_canonical_fixture_changes_identity(
    repository_root, tmp_path
) -> None:
    context, view, request, result = build_market_context(repository_root, tmp_path)
    first = view.fixtures[0]
    changed_first = first.model_copy(
        update={"canonical_fixture_id": UUID("00000000-0000-0000-0000-000000019999")}
    )
    changed_view = rehash_identity_view(
        view,
        fixtures=(changed_first, *view.fixtures[1:]),
    )
    changed_request = bind_current_market_constraint_request(context.bundle, changed_view)
    changed_result = CurrentMarketConstraintService().build(
        changed_request,
        source=context.bundle,
        identity_view=changed_view,
    )

    assert changed_view.semantic_sha256 != view.semantic_sha256
    assert changed_result.semantic_sha256 != result.semantic_sha256
    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketConstraintService().build(
            request,
            source=context.bundle,
            identity_view=changed_view,
        )
    assert caught.value.code == "SOURCE_MISMATCH"


def test_unified_source_hash_reconstruction_is_exact(repository_root, tmp_path) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    assert current_unified_state_semantic_sha256(context.bundle) == context.bundle.semantic_sha256
