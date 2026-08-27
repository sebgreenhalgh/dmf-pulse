"""Temporal, rights, ordering and source-family boundaries for CURRENT-FPL-STATE-001D."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateRequest,
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.current import current_odds_market_semantic_sha256

from .current_identity_test_support import rehash_odds_input
from .current_unified_state_test_support import build_context, verify


@pytest.mark.parametrize(
    "field",
    [
        "fpl_input_semantic_sha256",
        "fpl_identity_view_sha256",
        "fpl_catalogue_view_sha256",
        "odds_market_semantic_sha256",
        "odds_identity_semantic_sha256",
        "odds_provider_provenance_sha256",
        "fpl_odds_identity_map_semantic_sha256",
        "manager_state_semantic_sha256",
        "manager_declaration_semantic_sha256",
        "ruleset_sha256",
        "full_season_capability_sha256",
    ],
)
def test_each_request_hash_is_mandatory_and_exact(repository_root, tmp_path, field) -> None:
    context = build_context(repository_root, tmp_path)
    bad = context.request.model_copy(update={field: "f" * 64})
    with pytest.raises(IngestionError, match="request bindings"):
        CurrentUnifiedStateService().compose(
            bad,
            fpl_input=context.fpl_input,
            odds_input=context.odds_input,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )


def test_wrong_target_gameweek_and_request_cutoff_block(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    for update in (
        {"target_gameweek": 3},
        {"information_cutoff": context.request.information_cutoff - timedelta(seconds=1)},
    ):
        bad = context.request.model_copy(update=update)
        with pytest.raises(IngestionError, match="request bindings"):
            CurrentUnifiedStateService().compose(
                bad,
                fpl_input=context.fpl_input,
                odds_input=context.odds_input,
                identity_map=context.identity_map,
                manager_state=context.manager_state,
                ruleset=context.ruleset,
                capability=context.capability,
            )


def test_naive_request_cutoff_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CurrentUnifiedStateRequest(
            target_gameweek=2,
            information_cutoff=datetime(2026, 8, 26, 12),
            fpl_input_semantic_sha256="a" * 64,
            fpl_identity_view_sha256="a" * 64,
            fpl_catalogue_view_sha256="a" * 64,
            odds_market_semantic_sha256="a" * 64,
            odds_identity_semantic_sha256="a" * 64,
            odds_provider_provenance_sha256="a" * 64,
            fpl_odds_identity_map_semantic_sha256="a" * 64,
            manager_state_semantic_sha256="a" * 64,
            manager_declaration_semantic_sha256="a" * 64,
            ruleset_sha256="a" * 64,
            full_season_capability_sha256="a" * 64,
        )


def test_source_substitution_fpl_map_odds_map_and_manager_fpl_block(
    repository_root, tmp_path
) -> None:
    first = build_context(repository_root, tmp_path / "first")
    second = build_context(repository_root, tmp_path / "second")
    different_odds = second.odds_input.model_copy(
        update={
            "provenance": second.odds_input.provenance.model_copy(
                update={"source_snapshot_id": UUID("00000000-0000-0000-0000-000000009999")}
            )
        }
    )
    with pytest.raises(IngestionError):
        verify(first, odds_input=different_odds)

    changed_player = first.fpl_input.players[0].model_copy(
        update={"current_price_tenths": first.fpl_input.players[0].current_price_tenths + 1}
    )
    different_fpl = first.fpl_input.model_copy(
        update={"players": (changed_player, *first.fpl_input.players[1:])}
    )
    with pytest.raises(IngestionError):
        verify(first, fpl_input=different_fpl)


def test_manager_and_rules_source_substitution_blocks(repository_root, tmp_path) -> None:
    first = build_context(repository_root, tmp_path / "first")
    changed_manager = first.manager_state.model_copy(update={"bank_tenths": 999})
    with pytest.raises(IngestionError):
        verify(first, manager_state=changed_manager)

    changed_rules = first.ruleset.model_copy(update={"ruleset_hash": "e" * 64})
    with pytest.raises(IngestionError):
        verify(first, ruleset=changed_rules)


def test_nonsemantic_odds_event_order_does_not_change_composition_hash(
    repository_root, tmp_path
) -> None:
    context = build_context(repository_root, tmp_path)
    reordered_odds = rehash_odds_input(
        context.odds_input, events=tuple(reversed(context.odds_input.events))
    )
    assert reordered_odds.market_semantic_sha256 == context.odds_input.market_semantic_sha256
    request = bind_current_unified_state_request(
        context.fpl_input,
        reordered_odds,
        context.identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    reordered = CurrentUnifiedStateService().compose(
        request,
        fpl_input=context.fpl_input,
        odds_input=reordered_odds,
        identity_map=context.identity_map,
        manager_state=context.manager_state,
        ruleset=context.ruleset,
        capability=context.capability,
    )
    assert reordered.semantic_sha256 == context.bundle.semantic_sha256
    with pytest.raises(IngestionError, match="differs from its exact source family"):
        verify(context, value=reordered)


def test_odds_price_is_bound_separately_from_event_identity(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    event = context.odds_input.events[0]
    bookmaker = event.bookmakers[0]
    market = bookmaker.markets[0]
    outcome = market.outcomes[0].model_copy(
        update={"decimal_price": market.outcomes[0].decimal_price + 1}
    )
    changed_market = market.model_copy(update={"outcomes": (outcome, *market.outcomes[1:])})
    changed_bookmaker = bookmaker.model_copy(update={"markets": (changed_market,)})
    changed_event = event.model_copy(
        update={"bookmakers": (changed_bookmaker, *event.bookmakers[1:])}
    )
    provisional = context.odds_input.model_copy(
        update={"events": (changed_event, *context.odds_input.events[1:])}
    )
    changed_odds = provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )
    assert changed_odds.market_semantic_sha256 != context.odds_input.market_semantic_sha256
    with pytest.raises(IngestionError, match="request bindings"):
        verify(context, odds_input=changed_odds)
    rebound = bind_current_unified_state_request(
        context.fpl_input,
        changed_odds,
        context.identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    changed_bundle = CurrentUnifiedStateService().compose(
        rebound,
        fpl_input=context.fpl_input,
        odds_input=changed_odds,
        identity_map=context.identity_map,
        manager_state=context.manager_state,
        ruleset=context.ruleset,
        capability=context.capability,
    )
    assert changed_bundle.semantic_sha256 != context.bundle.semantic_sha256


def test_stale_odds_market_hash_blocks_even_when_request_repeats_it(
    repository_root, tmp_path
) -> None:
    context = build_context(repository_root, tmp_path)
    event = context.odds_input.events[0].model_copy(
        update={"commence_time": context.odds_input.events[0].commence_time + timedelta(seconds=1)}
    )
    stale_odds = context.odds_input.model_copy(
        update={"events": (event, *context.odds_input.events[1:])}
    )
    request = bind_current_unified_state_request(
        context.fpl_input,
        stale_odds,
        context.identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    with pytest.raises(IngestionError, match="structural revalidation"):
        CurrentUnifiedStateService().compose(
            request,
            fpl_input=context.fpl_input,
            odds_input=stale_odds,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )


@pytest.mark.parametrize("component", ["fpl", "odds", "identity", "manager"])
def test_each_source_cutoff_mismatch_blocks(repository_root, tmp_path, component) -> None:
    context = build_context(repository_root, tmp_path)
    changed = context.request.information_cutoff - timedelta(seconds=1)
    updates: dict[str, object] = {}
    if component == "fpl":
        provenance = context.fpl_input.provenance.model_copy(update={"information_cutoff": changed})
        updates["fpl_input"] = context.fpl_input.model_copy(update={"provenance": provenance})
    elif component == "odds":
        temporal = context.odds_input.temporal.model_copy(update={"information_cutoff": changed})
        updates["odds_input"] = context.odds_input.model_copy(update={"temporal": temporal})
    elif component == "identity":
        updates["identity_map"] = context.identity_map.model_copy(
            update={"information_cutoff": changed}
        )
    else:
        updates["manager_state"] = context.manager_state.model_copy(
            update={"information_cutoff": changed}
        )
    with pytest.raises(IngestionError):
        verify(context, **updates)


def test_odds_acquisition_lineage_remains_distinct_from_market_semantics(
    repository_root, tmp_path
) -> None:
    context = build_context(repository_root, tmp_path)
    provenance = context.odds_input.provenance.model_copy(
        update={"source_snapshot_id": UUID("00000000-0000-0000-0000-000000009999")}
    )
    changed_odds = context.odds_input.model_copy(update={"provenance": provenance})
    assert changed_odds.market_semantic_sha256 == context.odds_input.market_semantic_sha256
    rebound = bind_current_unified_state_request(
        context.fpl_input,
        changed_odds,
        context.identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    with pytest.raises(IngestionError):
        CurrentUnifiedStateService().compose(
            rebound,
            fpl_input=context.fpl_input,
            odds_input=changed_odds,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )


def test_outside_target_exact_collision_cannot_be_composed(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    target = context.odds_input.events[0]
    outside = context.odds_input.events[1].model_copy(
        update={
            "provider_home_team": target.provider_home_team,
            "provider_away_team": target.provider_away_team,
            "commence_time": target.commence_time,
        }
    )
    changed_odds = rehash_odds_input(context.odds_input, events=(target, outside))
    rebound = bind_current_unified_state_request(
        context.fpl_input,
        changed_odds,
        context.identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    with pytest.raises(IngestionError):
        CurrentUnifiedStateService().compose(
            rebound,
            fpl_input=context.fpl_input,
            odds_input=changed_odds,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )


@pytest.mark.parametrize(
    ("source", "field", "value"),
    [
        ("fpl", "automated_access", "ALLOW"),
        ("fpl", "raw_storage", "ALLOW"),
        ("fpl", "derived_storage", "ALLOW"),
        ("fpl", "cache", "ALLOW"),
        ("fpl", "backup", "ALLOW"),
        ("fpl_provenance", "transport_called", True),
        ("fpl_provenance", "database_accessed", True),
        ("fpl_provenance", "raw_storage_performed", True),
        ("fpl_provenance", "derived_storage_performed", True),
        ("odds", "raw_retention_seconds", 1),
        ("odds", "public_display", "ALLOW"),
        ("odds", "redistribution", "ALLOW"),
        ("odds", "private_internal_use", "DENY"),
    ],
)
def test_source_rights_mutations_block(repository_root, tmp_path, source, field, value) -> None:
    context = build_context(repository_root, tmp_path)
    if source == "fpl":
        rights = context.fpl_input.rights.model_copy(update={field: value})
        changed = context.fpl_input.model_copy(update={"rights": rights})
        with pytest.raises(IngestionError):
            verify(context, fpl_input=changed)
    elif source == "fpl_provenance":
        provenance = context.fpl_input.provenance.model_copy(update={field: value})
        changed = context.fpl_input.model_copy(update={"provenance": provenance})
        with pytest.raises(IngestionError):
            verify(context, fpl_input=changed)
    else:
        rights = context.odds_input.rights.model_copy(update={field: value})
        changed = context.odds_input.model_copy(update={"rights": rights})
        with pytest.raises(IngestionError):
            verify(context, odds_input=changed)


@pytest.mark.parametrize("field", ["persistence_performed", "database_accessed", "network_called"])
def test_manager_runtime_mutations_block(repository_root, tmp_path, field) -> None:
    context = build_context(repository_root, tmp_path)
    runtime = context.manager_state.runtime.model_copy(update={field: True})
    manager = context.manager_state.model_copy(update={"runtime": runtime})
    with pytest.raises(IngestionError):
        verify(context, manager_state=manager)
