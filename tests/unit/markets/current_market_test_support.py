"""Synthetic-only coherent families for CURRENT-MARKETS-001A tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateBundle,
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
    current_fpl_full_representation_sha256,
    current_unified_state_semantic_sha256,
)
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from dmf_pulse.ingestion.fpl.manager_current import current_fpl_catalogue_view_sha256
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsMarket,
    CurrentOddsQualityState,
    CurrentOddsQuotaState,
    CurrentOddsTemporalState,
    CurrentOddsTotalsMarket,
    CurrentOddsTotalsOutcome,
    OddsProviderCurrentInput,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.identity import (
    bind_current_fixture_resolution_request,
    bind_current_team_resolution_request,
    current_fpl_identity_view_sha256,
    current_odds_identity_semantic_sha256,
    current_odds_provider_provenance_sha256,
    resolve_current_fixture_identities,
    resolve_current_team_identities,
)
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalFixture,
    CurrentMarketCanonicalIdentityView,
    CurrentMarketCanonicalOperator,
    CurrentMarketConstraintBundle,
    CurrentMarketConstraintRequest,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
    current_market_identity_view_sha256,
)
from tests.unit.ingestion.current_unified_state_test_support import (
    CurrentUnifiedTestContext,
    build_two_fixture_context,
)

PROVIDER_ID = UUID("00000000-0000-0000-0000-000000009001")
OPERATOR_IDS = {
    "book_alpha": UUID("00000000-0000-0000-0000-000000009101"),
    "book_beta": UUID("00000000-0000-0000-0000-000000009102"),
}


def _totals_market(
    line: Decimal,
    *,
    over: Decimal,
    under: Decimal,
    updated_at,
) -> CurrentOddsTotalsMarket:
    return CurrentOddsTotalsMarket(
        line=line,
        provider_last_update=updated_at,
        provider_last_update_state="PUBLISHED",
        outcomes=(
            CurrentOddsTotalsOutcome(
                provider_name=f"Over {line}",
                outcome="OVER",
                decimal_price=over,
                point=line,
            ),
            CurrentOddsTotalsOutcome(
                provider_name=f"Under {line}",
                outcome="UNDER",
                decimal_price=under,
                point=line,
            ),
        ),
    )


def _fresh_odds(value: OddsProviderCurrentInput) -> OddsProviderCurrentInput:
    cutoff = value.temporal.information_cutoff
    received_at = value.temporal.received_at + timedelta(minutes=30)
    usable_at = value.temporal.usable_at + timedelta(minutes=30)
    events = []
    for event_index, event in enumerate(value.events):
        bookmakers = []
        for bookmaker_index, bookmaker in enumerate(event.bookmakers):
            updated_at = received_at - timedelta(minutes=5 + bookmaker_index)
            h2h = bookmaker.markets[0].model_copy(
                update={
                    "provider_last_update": updated_at,
                    "provider_last_update_state": "PUBLISHED",
                }
            )
            totals = (
                _totals_market(
                    Decimal("1.5"),
                    over=Decimal("1.31") + Decimal(event_index) / Decimal(100),
                    under=Decimal("3.50") - Decimal(bookmaker_index) / Decimal(10),
                    updated_at=updated_at,
                ),
                _totals_market(
                    Decimal("2.5"),
                    over=Decimal("1.91") + Decimal(bookmaker_index) / Decimal(100),
                    under=Decimal("1.95") - Decimal(event_index) / Decimal(100),
                    updated_at=updated_at,
                ),
            )
            bookmakers.append(
                bookmaker.model_copy(
                    update={
                        "provider_last_update": updated_at,
                        "age_at_receipt_seconds": int((received_at - updated_at).total_seconds()),
                        "markets": (h2h,),
                        "totals_markets": totals,
                    }
                )
            )
        events.append(event.model_copy(update={"bookmakers": tuple(bookmakers)}))
    temporal = CurrentOddsTemporalState(
        request_started_at=received_at - timedelta(seconds=1),
        received_at=received_at,
        captured_at=received_at,
        information_cutoff=cutoff,
        usable_at=usable_at,
    )
    quota = CurrentOddsQuotaState(
        remaining=value.quota.remaining,
        used=value.quota.used,
        configured_request_cost=value.quota.configured_request_cost,
        provider_last_request_cost=value.quota.provider_last_request_cost,
        observed_at=received_at,
    )
    provisional = value.model_copy(
        update={
            "events": tuple(events),
            "temporal": temporal,
            "quota": quota,
            "quality": CurrentOddsQualityState(status="PASS"),
            "market_semantic_sha256": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )


def recompose(
    context: CurrentUnifiedTestContext,
    odds_input: OddsProviderCurrentInput,
) -> CurrentUnifiedTestContext:
    team_plan = context.identity_map.team_alias_plan
    fixture_approved_at = odds_input.temporal.usable_at + timedelta(minutes=9)
    mapping_decided_at = max(
        context.identity_map.mapping_decided_at,
        odds_input.temporal.usable_at + timedelta(seconds=30),
        fixture_approved_at + timedelta(minutes=10),
    )
    team_request = bind_current_team_resolution_request(
        context.fpl_input,
        odds_input,
        team_plan,
        mapping_decided_at=mapping_decided_at,
    )
    team_map = resolve_current_team_identities(
        context.fpl_input,
        odds_input,
        team_plan,
        team_request,
    )
    original_fixture_plan = context.identity_map.fixture_mapping_plan
    fixture_plan_payload = original_fixture_plan.model_dump(mode="python")
    fixture_plan_payload["approved_at"] = fixture_approved_at
    fixture_plan_payload["fixture_mappings"] = tuple(
        mapping.model_copy(update={"approved_at": fixture_approved_at})
        for mapping in original_fixture_plan.fixture_mappings
    )
    fixture_plan = type(original_fixture_plan).model_validate(fixture_plan_payload)
    fixture_request = bind_current_fixture_resolution_request(
        context.fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        mapping_decided_at=mapping_decided_at,
    )
    identity_map = resolve_current_fixture_identities(
        context.fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        fixture_request,
    )
    request = bind_current_unified_state_request(
        context.fpl_input,
        odds_input,
        identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    bundle = CurrentUnifiedStateService().compose(
        request,
        fpl_input=context.fpl_input,
        odds_input=odds_input,
        identity_map=identity_map,
        manager_state=context.manager_state,
        ruleset=context.ruleset,
        capability=context.capability,
    )
    return replace(
        context,
        odds_input=odds_input,
        identity_map=identity_map,
        request=request,
        bundle=bundle,
    )


def build_source_context(repository_root: Path, tmp_path: Path) -> CurrentUnifiedTestContext:
    context = build_two_fixture_context(repository_root, tmp_path)
    return recompose(context, _fresh_odds(context.odds_input))


def identity_view(context: CurrentUnifiedTestContext) -> CurrentMarketCanonicalIdentityView:
    fixtures = tuple(
        CurrentMarketCanonicalFixture(
            official_fpl_fixture_id=mapping.official_fpl_fixture_id,
            official_fpl_fixture_lookup_sha256=(
                mapping.official_fpl_fixture_identity.canonical_lookup_sha256
            ),
            provider_event_id=mapping.provider_event_id,
            provider_event_identity_sha256=mapping.provider_event_identity_sha256,
            canonical_fixture_id=UUID(f"00000000-0000-0000-0000-{9100 + index:012d}"),
            official_fpl_external_mapping_id=UUID(f"00000000-0000-0000-0000-{9200 + index:012d}"),
            odds_event_external_mapping_id=UUID(f"00000000-0000-0000-0000-{9250 + index:012d}"),
            fixture_binding_sha256=mapping.fixture_binding_sha256,
        )
        for index, mapping in enumerate(
            sorted(
                context.identity_map.fixture_mappings,
                key=lambda item: item.official_fpl_fixture_id,
            ),
            start=1,
        )
    )
    books = {
        bookmaker.bookmaker_key: bookmaker.bookmaker_title
        for event in context.odds_input.events
        if event.provider_event_id
        in {item.provider_event_id for item in context.identity_map.fixture_mappings}
        for bookmaker in event.bookmakers
    }
    operators = tuple(
        CurrentMarketCanonicalOperator(
            bookmaker_key=key,
            bookmaker_title=title,
            canonical_operator_id=OPERATOR_IDS[key],
            canonical_operator_key=f"SYNTHETIC_{key.upper()}",
            external_mapping_id=UUID(f"00000000-0000-0000-0000-{9300 + index:012d}"),
            target_occurrence_times_sha256=canonical_sha256(
                {
                    "bookmaker_key": key,
                    "contract_version": "current-market-operator-applicability-v1",
                    "target_occurrence_times": [
                        value.isoformat()
                        for value in sorted(
                            {
                                event.commence_time
                                for event in context.odds_input.events
                                if event.provider_event_id
                                in {
                                    item.provider_event_id
                                    for item in context.identity_map.fixture_mappings
                                }
                                for bookmaker in event.bookmakers
                                if bookmaker.bookmaker_key == key
                            }
                        )
                    ],
                }
            ),
        )
        for index, (key, title) in enumerate(sorted(books.items()), start=1)
    )
    provisional = CurrentMarketCanonicalIdentityView.model_construct(
        authority="TEST_ONLY",
        resolved_at=context.bundle.decision_information_at,
        resolution_cutoff=context.bundle.information_cutoff,
        database_read_performed=False,
        provider_id=PROVIDER_ID,
        fixtures=fixtures,
        operators=operators,
        semantic_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["semantic_sha256"] = current_market_identity_view_sha256(provisional)
    return CurrentMarketCanonicalIdentityView.model_validate(payload)


def build_market_context(
    repository_root: Path,
    tmp_path: Path,
) -> tuple[
    CurrentUnifiedTestContext,
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintRequest,
    CurrentMarketConstraintBundle,
]:
    context = build_source_context(repository_root, tmp_path)
    view = identity_view(context)
    request = bind_current_market_constraint_request(context.bundle, view)
    result = CurrentMarketConstraintService().build(
        request,
        source=context.bundle,
        identity_view=view,
    )
    return context, view, request, result


def build_from_context(
    context: CurrentUnifiedTestContext,
    view: CurrentMarketCanonicalIdentityView | None = None,
) -> tuple[
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintRequest,
    CurrentMarketConstraintBundle,
]:
    selected_view = view or identity_view(context)
    request = bind_current_market_constraint_request(context.bundle, selected_view)
    result = CurrentMarketConstraintService().build(
        request,
        source=context.bundle,
        identity_view=selected_view,
    )
    return selected_view, request, result


def rehash_odds(
    value: OddsProviderCurrentInput,
    *,
    events: tuple[object, ...],
) -> OddsProviderCurrentInput:
    provisional = value.model_copy(update={"events": events, "market_semantic_sha256": "0" * 64})
    return provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )


def rehash_identity_view(
    value: CurrentMarketCanonicalIdentityView,
    **updates: object,
) -> CurrentMarketCanonicalIdentityView:
    provisional = value.model_copy(update={**updates, "semantic_sha256": "0" * 64})
    return provisional.model_copy(
        update={"semantic_sha256": current_market_identity_view_sha256(provisional)}
    )


def rehash_unified_source(
    context: CurrentUnifiedTestContext,
    *,
    odds_input: OddsProviderCurrentInput | None = None,
    fpl_input: CurrentFplInputBundle | None = None,
) -> CurrentUnifiedStateBundle:
    """Rebuild only mutable 001D outer bindings while retaining its accepted 001B map."""

    selected_odds = odds_input or context.odds_input
    selected_fpl = fpl_input or context.fpl_input
    lineage = context.bundle.lineage.model_copy(
        update={
            "fpl_input_semantic_sha256": selected_fpl.semantic_sha256,
            "fpl_full_representation_sha256": current_fpl_full_representation_sha256(selected_fpl),
            "fpl_identity_view_sha256": current_fpl_identity_view_sha256(selected_fpl),
            "fpl_catalogue_view_sha256": current_fpl_catalogue_view_sha256(selected_fpl),
            "odds_market_semantic_sha256": selected_odds.market_semantic_sha256,
            "odds_identity_semantic_sha256": current_odds_identity_semantic_sha256(selected_odds),
            "odds_provider_provenance_sha256": current_odds_provider_provenance_sha256(
                selected_odds
            ),
        }
    )
    provisional = context.bundle.model_copy(
        update={
            "fpl_input": selected_fpl,
            "odds_input": selected_odds,
            "lineage": lineage,
            "semantic_sha256": "0" * 64,
        }
    )
    checked = provisional.model_copy(
        update={"semantic_sha256": current_unified_state_semantic_sha256(provisional)}
    )
    return CurrentUnifiedStateBundle.model_validate(checked.model_dump(mode="python"))


def replace_odds(
    context: CurrentUnifiedTestContext,
    *,
    event_index: int,
    bookmaker_index: int,
    h2h_market: CurrentOddsMarket | None = None,
    totals_markets: tuple[CurrentOddsTotalsMarket, ...] | None = None,
) -> CurrentUnifiedTestContext:
    events = list(context.odds_input.events)
    event = events[event_index]
    bookmakers = list(event.bookmakers)
    bookmaker = bookmakers[bookmaker_index]
    updates: dict[str, object] = {}
    if h2h_market is not None:
        updates["markets"] = (h2h_market,)
    if totals_markets is not None:
        updates["totals_markets"] = totals_markets
    bookmakers[bookmaker_index] = bookmaker.model_copy(update=updates)
    events[event_index] = event.model_copy(update={"bookmakers": tuple(bookmakers)})
    provisional = context.odds_input.model_copy(
        update={"events": tuple(events), "market_semantic_sha256": "0" * 64}
    )
    odds = provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )
    return recompose(context, odds)
