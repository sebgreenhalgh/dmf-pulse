"""Adversarial current-market source, cutoff, identity and readiness tests."""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from dmf_pulse.ingestion.current_state import current_unified_state_semantic_sha256
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
)

from .current_market_test_support import (
    build_from_context,
    build_market_context,
    recompose,
    rehash_identity_view,
    rehash_odds,
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
        "INCOMPLETE": 1,
        "UNSUPPORTED": 1,
    }
    assert {item.reason: item.count for item in summary.exclusion_counts} == {
        "INCOMPLETE": 1,
        "UNSUPPORTED": 1,
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
