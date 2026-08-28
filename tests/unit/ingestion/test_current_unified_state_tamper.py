"""Rehashed nested-tamper tests for CURRENT-FPL-STATE-001D."""

from __future__ import annotations

from datetime import timedelta

import pytest

from dmf_pulse.chips.inventory import TokenStatus
from dmf_pulse.ingestion.current_state import current_fpl_full_representation_sha256
from dmf_pulse.ingestion.errors import IngestionError

from .current_unified_state_test_support import (
    build_context,
    mutate_non_view_fpl,
    rehash_bundle,
    verify,
)


@pytest.mark.parametrize(
    "mutation",
    [
        "fpl_player_identity",
        "fpl_team_identity",
        "fpl_fixture_kickoff",
        "fpl_target_gameweek",
        "fpl_current_price",
        "fpl_non_view_player_status",
        "fpl_non_view_chance_this_round",
        "fpl_non_view_chance_next_round",
        "fpl_non_view_player_news",
        "fpl_non_view_player_news_added",
        "fpl_non_view_game_settings",
        "fpl_non_view_non_target_event_finished",
        "fpl_non_view_non_target_event_data_checked",
        "fpl_non_view_non_target_event_flags",
        "fpl_non_view_fixture_finished",
        "fpl_non_view_fixture_started",
        "fpl_non_view_fixture_finished_provisional",
        "odds_event_identity",
        "odds_participant",
        "odds_commence",
        "odds_bookmaker_price",
        "odds_totals_line",
        "odds_provenance",
        "identity_team_mapping",
        "identity_fixture_mapping",
        "identity_source_hash",
        "manager_squad",
        "manager_purchase_price",
        "manager_current_price",
        "manager_sell_price",
        "manager_bank",
        "manager_ft",
        "manager_lineup",
        "manager_bench",
        "manager_captain",
        "manager_vice",
        "manager_chip_state",
        "rules_hash",
        "capability_hash",
        "cutoff",
        "deadline",
        "decision_information_at",
        "manager_verification_class",
    ],
)
def test_rehashed_nested_tamper_never_survives_external_verify(
    repository_root, tmp_path, mutation
) -> None:
    context = build_context(repository_root, tmp_path)
    bundle = context.bundle
    fpl = bundle.fpl_input
    odds = bundle.odds_input
    bridge = bundle.identity_map
    manager = bundle.manager_state

    if mutation == "fpl_player_identity":
        player = fpl.players[0].model_copy(update={"identity": fpl.players[1].identity})
        nested = fpl.model_copy(update={"players": (player, *fpl.players[1:])})
        tampered = rehash_bundle(bundle, fpl_input=nested)
    elif mutation == "fpl_team_identity":
        team = fpl.teams[0].model_copy(update={"identity": fpl.teams[1].identity})
        nested = fpl.model_copy(update={"teams": (team, *fpl.teams[1:])})
        tampered = rehash_bundle(bundle, fpl_input=nested)
    elif mutation == "fpl_fixture_kickoff":
        fixture = fpl.fixtures[-1].model_copy(
            update={"kickoff_at": fpl.fixtures[-1].kickoff_at + timedelta(minutes=1)}
        )
        nested = fpl.model_copy(update={"fixtures": (*fpl.fixtures[:-1], fixture)})
        tampered = rehash_bundle(bundle, fpl_input=nested)
    elif mutation == "fpl_target_gameweek":
        tampered = rehash_bundle(bundle, fpl_input=fpl.model_copy(update={"target_gameweek": 3}))
    elif mutation == "fpl_current_price":
        player = fpl.players[0].model_copy(
            update={"current_price_tenths": fpl.players[0].current_price_tenths + 1}
        )
        tampered = rehash_bundle(
            bundle, fpl_input=fpl.model_copy(update={"players": (player, *fpl.players[1:])})
        )
    elif mutation.startswith("fpl_non_view_"):
        nested = mutate_non_view_fpl(fpl, mutation.removeprefix("fpl_non_view_"))
        lineage = bundle.lineage.model_copy(
            update={
                "fpl_full_representation_sha256": current_fpl_full_representation_sha256(nested)
            }
        )
        tampered = rehash_bundle(bundle, fpl_input=nested, lineage=lineage)
    elif mutation in {"odds_event_identity", "odds_participant", "odds_commence"}:
        updates = {
            "odds_event_identity": {"provider_event_id": "tampered-event"},
            "odds_participant": {"provider_home_team": "Tampered Team"},
            "odds_commence": {"commence_time": odds.events[0].commence_time + timedelta(minutes=1)},
        }[mutation]
        event = odds.events[0].model_copy(update=updates)
        tampered = rehash_bundle(
            bundle, odds_input=odds.model_copy(update={"events": (event, *odds.events[1:])})
        )
    elif mutation in {"odds_bookmaker_price", "odds_totals_line"}:
        event = odds.events[0]
        bookmaker = event.bookmakers[0]
        if mutation == "odds_bookmaker_price":
            market = bookmaker.markets[0]
            outcome = market.outcomes[0].model_copy(
                update={"decimal_price": market.outcomes[0].decimal_price + 1}
            )
            bookmaker = bookmaker.model_copy(
                update={
                    "markets": (
                        market.model_copy(update={"outcomes": (outcome, *market.outcomes[1:])}),
                    )
                }
            )
        else:
            bookmaker_index, bookmaker = next(
                (index, item) for index, item in enumerate(event.bookmakers) if item.totals_markets
            )
            total = bookmaker.totals_markets[0]
            bookmaker = bookmaker.model_copy(
                update={
                    "totals_markets": (
                        total.model_copy(update={"line": total.line + 1}),
                        *bookmaker.totals_markets[1:],
                    )
                }
            )
        if mutation == "odds_bookmaker_price":
            bookmakers = (bookmaker, *event.bookmakers[1:])
        else:
            bookmakers = tuple(
                bookmaker if index == bookmaker_index else item
                for index, item in enumerate(event.bookmakers)
            )
        event = event.model_copy(update={"bookmakers": bookmakers})
        tampered = rehash_bundle(
            bundle, odds_input=odds.model_copy(update={"events": (event, *odds.events[1:])})
        )
    elif mutation == "odds_provenance":
        provenance = odds.provenance.model_copy(update={"response_body_sha256": "a" * 64})
        tampered = rehash_bundle(
            bundle, odds_input=odds.model_copy(update={"provenance": provenance})
        )
    elif mutation == "identity_team_mapping":
        mapping = bridge.team_mappings[0].model_copy(
            update={"official_fpl_team_id": bridge.team_mappings[0].official_fpl_team_id + 1}
        )
        tampered = rehash_bundle(
            bundle,
            identity_map=bridge.model_copy(
                update={"team_mappings": (mapping, *bridge.team_mappings[1:])}
            ),
        )
    elif mutation == "identity_fixture_mapping":
        mapping = bridge.fixture_mappings[0].model_copy(
            update={
                "official_fpl_fixture_id": bridge.fixture_mappings[0].official_fpl_fixture_id + 1
            }
        )
        tampered = rehash_bundle(
            bundle, identity_map=bridge.model_copy(update={"fixture_mappings": (mapping,)})
        )
    elif mutation == "identity_source_hash":
        tampered = rehash_bundle(
            bundle,
            identity_map=bridge.model_copy(update={"fpl_input_semantic_sha256": "a" * 64}),
        )
    elif mutation == "manager_squad":
        tampered = rehash_bundle(
            bundle, manager_state=manager.model_copy(update={"squad": manager.squad[:-1]})
        )
    elif mutation in {"manager_purchase_price", "manager_current_price", "manager_sell_price"}:
        field = {
            "manager_purchase_price": "purchase_price_tenths",
            "manager_current_price": "current_price_tenths",
            "manager_sell_price": "selling_price_tenths",
        }[mutation]
        member = manager.squad[0].model_copy(update={field: getattr(manager.squad[0], field) + 1})
        tampered = rehash_bundle(
            bundle, manager_state=manager.model_copy(update={"squad": (member, *manager.squad[1:])})
        )
    elif mutation in {"manager_bank", "manager_ft"}:
        field = "bank_tenths" if mutation == "manager_bank" else "free_transfers"
        tampered = rehash_bundle(
            bundle, manager_state=manager.model_copy(update={field: getattr(manager, field) + 1})
        )
    elif mutation in {"manager_lineup", "manager_bench", "manager_captain", "manager_vice"}:
        lineup = manager.lineup
        updates = {
            "manager_lineup": {"starting_xi_element_ids": lineup.starting_xi_element_ids[:-1]},
            "manager_bench": {
                "bench_outfield_element_ids": tuple(reversed(lineup.bench_outfield_element_ids))
            },
            "manager_captain": {"captain_element_id": lineup.vice_captain_element_id},
            "manager_vice": {"vice_captain_element_id": lineup.captain_element_id},
        }[mutation]
        tampered = rehash_bundle(
            bundle,
            manager_state=manager.model_copy(update={"lineup": lineup.model_copy(update=updates)}),
        )
    elif mutation == "manager_chip_state":
        token = manager.chip_inventory.tokens[0].model_copy(update={"status": TokenStatus.USED})
        inventory = manager.chip_inventory.model_copy(
            update={"tokens": (token, *manager.chip_inventory.tokens[1:])}
        )
        tampered = rehash_bundle(
            bundle, manager_state=manager.model_copy(update={"chip_inventory": inventory})
        )
    elif mutation == "rules_hash":
        lineage = bundle.lineage.model_copy(update={"ruleset_sha256": "a" * 64})
        tampered = rehash_bundle(bundle, lineage=lineage)
    elif mutation == "capability_hash":
        lineage = bundle.lineage.model_copy(update={"full_season_capability_sha256": "a" * 64})
        tampered = rehash_bundle(bundle, lineage=lineage)
    elif mutation == "cutoff":
        tampered = rehash_bundle(
            bundle, information_cutoff=bundle.information_cutoff - timedelta(seconds=1)
        )
    elif mutation == "deadline":
        tampered = rehash_bundle(
            bundle, target_deadline_at=bundle.target_deadline_at + timedelta(seconds=1)
        )
    elif mutation == "decision_information_at":
        tampered = rehash_bundle(
            bundle, decision_information_at=bundle.decision_information_at + timedelta(seconds=1)
        )
    else:
        tampered = rehash_bundle(
            bundle,
            manager_state=manager.model_copy(update={"provider_verification": "PROVIDER_VERIFIED"}),
        )

    with pytest.raises((IngestionError, ValueError)):
        verify(context, value=tampered)
