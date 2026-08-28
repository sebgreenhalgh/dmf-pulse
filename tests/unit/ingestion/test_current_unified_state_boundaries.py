"""Temporal, rights, ordering and source-family boundaries for CURRENT-FPL-STATE-001D."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID

import pytest

import dmf_pulse.ingestion.current_state as current_state_module
import dmf_pulse.ingestion.odds.identity as identity_module
from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateRequest,
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
    current_fpl_full_representation_sha256,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.manager_current import current_fpl_catalogue_view_sha256
from dmf_pulse.ingestion.odds.current import current_odds_market_semantic_sha256
from dmf_pulse.ingestion.odds.identity import current_fpl_identity_view_sha256

from .current_identity_test_support import (
    fixture_binding,
    fixture_plan,
    rehash_odds_input,
    resolve_team_map,
)
from .current_unified_state_test_support import build_context, mutate_non_view_fpl, verify


@pytest.mark.parametrize(
    "field",
    [
        "fpl_input_semantic_sha256",
        "fpl_full_representation_sha256",
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
            fpl_full_representation_sha256="a" * 64,
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


@pytest.mark.parametrize(
    "mutation",
    [
        "player_status",
        "chance_this_round",
        "chance_next_round",
        "player_news",
        "player_news_added",
        "game_settings",
        "non_target_event_finished",
        "non_target_event_data_checked",
        "non_target_event_flags",
        "fixture_finished",
        "fixture_started",
        "fixture_finished_provisional",
    ],
)
def test_full_fpl_representation_binds_each_non_view_mutation(
    repository_root, tmp_path, mutation
) -> None:
    context = build_context(repository_root, tmp_path)
    changed_fpl = mutate_non_view_fpl(context.fpl_input, mutation)

    assert changed_fpl.semantic_sha256 == context.fpl_input.semantic_sha256
    assert current_fpl_identity_view_sha256(changed_fpl) == (
        current_fpl_identity_view_sha256(context.fpl_input)
    )
    assert current_fpl_catalogue_view_sha256(changed_fpl) == (
        current_fpl_catalogue_view_sha256(context.fpl_input)
    )
    assert current_fpl_full_representation_sha256(changed_fpl) != (
        current_fpl_full_representation_sha256(context.fpl_input)
    )

    with pytest.raises(IngestionError, match="request bindings"):
        CurrentUnifiedStateService().compose(
            context.request,
            fpl_input=changed_fpl,
            odds_input=context.odds_input,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )
    with pytest.raises(IngestionError, match="request bindings"):
        verify(context, fpl_input=changed_fpl)


@pytest.mark.parametrize(
    "mutation",
    ["player_status", "game_settings", "non_target_event_flags", "fixture_finished"],
)
def test_fresh_fpl_rebind_changes_unified_identity(repository_root, tmp_path, mutation) -> None:
    context = build_context(repository_root, tmp_path)
    changed_fpl = mutate_non_view_fpl(context.fpl_input, mutation)
    rebound = bind_current_unified_state_request(
        changed_fpl,
        context.odds_input,
        context.identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )

    changed_bundle = CurrentUnifiedStateService().compose(
        rebound,
        fpl_input=changed_fpl,
        odds_input=context.odds_input,
        identity_map=context.identity_map,
        manager_state=context.manager_state,
        ruleset=context.ruleset,
        capability=context.capability,
    )

    assert rebound.fpl_full_representation_sha256 != (
        context.request.fpl_full_representation_sha256
    )
    assert changed_bundle.lineage.fpl_full_representation_sha256 != (
        context.bundle.lineage.fpl_full_representation_sha256
    )
    assert changed_bundle.semantic_sha256 != context.bundle.semantic_sha256


def test_nonsemantic_fpl_catalogue_order_does_not_change_full_digest(
    repository_root, tmp_path
) -> None:
    context = build_context(repository_root, tmp_path)
    reordered = context.fpl_input.model_copy(
        update={
            "events": tuple(reversed(context.fpl_input.events)),
            "teams": tuple(reversed(context.fpl_input.teams)),
            "positions": tuple(reversed(context.fpl_input.positions)),
            "players": tuple(reversed(context.fpl_input.players)),
            "fixtures": tuple(reversed(context.fpl_input.fixtures)),
        }
    )

    assert current_fpl_full_representation_sha256(reordered) == (
        current_fpl_full_representation_sha256(context.fpl_input)
    )


def _assert_safe_reconstruction_error(
    error: IngestionError, *, expected_message: str, forbidden: tuple[object, ...]
) -> None:
    assert error.code == "MAPPING_CONFLICT"
    assert error.message == expected_message
    assert error.details == {}
    public_surfaces = "\n".join(
        (
            json.dumps(error.as_error_object(), sort_keys=True),
            str(error),
            repr(error),
        )
    )
    for value in forbidden:
        assert str(value) not in public_surfaces


@pytest.mark.parametrize(
    ("upstream_name", "private_value"),
    [
        ("bind_current_team_resolution_request", "FPL-TEAM-PRIVATE-700001"),
        ("resolve_current_team_identities", "PROVIDER-TEAM-PRIVATE-700002"),
        ("bind_current_fixture_resolution_request", "PROVIDER-EVENT-PRIVATE-700003"),
        ("resolve_current_fixture_identities", "FPL-FIXTURE-PRIVATE-700004"),
    ],
)
def test_identity_reconstruction_errors_are_detail_free(
    repository_root, tmp_path, monkeypatch, upstream_name, private_value
) -> None:
    context = build_context(repository_root, tmp_path)

    def fail_reconstruction(*args, **kwargs):
        raise IngestionError(
            "QUALITY_BLOCKED",
            f"upstream leaked {private_value}",
            details={"private_source_value": private_value},
        )

    monkeypatch.setattr(current_state_module, upstream_name, fail_reconstruction)
    with pytest.raises(IngestionError) as captured:
        CurrentUnifiedStateService().compose(
            context.request,
            fpl_input=context.fpl_input,
            odds_input=context.odds_input,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )
    _assert_safe_reconstruction_error(
        captured.value,
        expected_message="FPL/Odds identity reconstruction failed",
        forbidden=(private_value,),
    )


def test_incomplete_fixture_coverage_hides_upstream_fixture_id(
    repository_root, tmp_path, monkeypatch
) -> None:
    context = build_context(repository_root, tmp_path)
    source_fixture = next(
        fixture
        for fixture in context.fpl_input.fixtures
        if fixture.event_identity == context.fpl_input.target_event.identity
    )
    synthetic_fixture_id = 900103
    identity_material = source_fixture.identity.model_dump(
        mode="json", exclude={"canonical_lookup_sha256"}
    )
    identity_material["external_id_text"] = str(synthetic_fixture_id)
    changed_identity = source_fixture.identity.model_copy(
        update={
            "external_id_text": str(synthetic_fixture_id),
            "canonical_lookup_sha256": canonical_sha256(identity_material),
        }
    )
    extra_fixture = source_fixture.model_copy(
        update={
            "identity": changed_identity,
            "provider_fixture_id": synthetic_fixture_id,
            "provider_code": synthetic_fixture_id,
            "kickoff_at": source_fixture.kickoff_at + timedelta(hours=2),
        }
    )
    changed_fpl = context.fpl_input.model_copy(
        update={"fixtures": (*context.fpl_input.fixtures, extra_fixture)}
    )
    team_plan = context.identity_map.team_alias_plan
    changed_team_map = resolve_team_map(changed_fpl, context.odds_input, team_plan)
    changed_fixture_plan = fixture_plan(
        changed_fpl,
        context.odds_input,
        team_plan,
        bindings=(
            fixture_binding(
                changed_fpl,
                context.odds_input,
                team_plan,
                fixture=source_fixture,
            ),
        ),
    )
    provisional_identity_map = context.identity_map.model_copy(
        update={
            "fpl_identity_view_sha256": current_fpl_identity_view_sha256(changed_fpl),
            "team_identity_map_semantic_sha256": changed_team_map.semantic_sha256,
            "fixture_mapping_plan": changed_fixture_plan,
            "fixture_mapping_plan_sha256": changed_fixture_plan.sha256,
        }
    )
    provisional_identity_map = provisional_identity_map.model_copy(
        update={
            "source_lineage_sha256": identity_module._identity_source_lineage_sha256(
                provisional_identity_map
            )
        }
    )
    provisional_identity_map = provisional_identity_map.model_copy(
        update={
            "semantic_sha256": identity_module._fpl_odds_identity_map_sha256(
                provisional_identity_map
            )
        }
    )
    changed_identity_map = type(context.identity_map).model_validate(
        provisional_identity_map.model_dump(mode="python")
    )
    rebound = bind_current_unified_state_request(
        changed_fpl,
        context.odds_input,
        changed_identity_map,
        context.manager_state,
        context.ruleset,
        context.capability,
    )
    original_resolver = current_state_module.resolve_current_fixture_identities
    internal_error_text = ""

    def observe_internal_error(*args, **kwargs):
        nonlocal internal_error_text
        try:
            return original_resolver(*args, **kwargs)
        except IngestionError as error:
            internal_error_text = json.dumps(error.as_error_object(), sort_keys=True)
            raise

    monkeypatch.setattr(
        current_state_module, "resolve_current_fixture_identities", observe_internal_error
    )
    with pytest.raises(IngestionError) as captured:
        CurrentUnifiedStateService().compose(
            rebound,
            fpl_input=changed_fpl,
            odds_input=context.odds_input,
            identity_map=changed_identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )

    assert str(synthetic_fixture_id) in internal_error_text
    _assert_safe_reconstruction_error(
        captured.value,
        expected_message="FPL/Odds identity reconstruction failed",
        forbidden=(synthetic_fixture_id,),
    )


@pytest.mark.parametrize(
    ("failure_class", "private_values"),
    [
        (
            "catalogue-source",
            (
                "FPL-PLAYER-PRIVATE-800001",
                "PURCHASE-PRICE-PRIVATE-800002",
                "SELLING-PRICE-PRIVATE-800003",
                "BANK-PRIVATE-800004",
                "FT-PRIVATE-800005",
            ),
        ),
        (
            "rules",
            (
                "CAPTAIN-PRIVATE-800006",
                "VICE-PRIVATE-800007",
                "BENCH-PRIVATE-800008",
                "CHIP-TOKEN-PRIVATE-800009",
                "OPERATOR-REFERENCE-PRIVATE-800010",
            ),
        ),
    ],
)
def test_manager_reconstruction_errors_are_detail_free(
    repository_root, tmp_path, monkeypatch, failure_class, private_values
) -> None:
    context = build_context(repository_root, tmp_path)

    def fail_manager_verify(*args, **kwargs):
        raise IngestionError(
            "VALIDATION_FAILED",
            f"upstream {failure_class} leaked {private_values[0]}",
            details={f"private_{index}": value for index, value in enumerate(private_values)},
        )

    monkeypatch.setattr(
        current_state_module.CurrentManagerStateService, "verify", fail_manager_verify
    )
    with pytest.raises(IngestionError) as captured:
        CurrentUnifiedStateService().compose(
            context.request,
            fpl_input=context.fpl_input,
            odds_input=context.odds_input,
            identity_map=context.identity_map,
            manager_state=context.manager_state,
            ruleset=context.ruleset,
            capability=context.capability,
        )
    _assert_safe_reconstruction_error(
        captured.value,
        expected_message="current manager reconstruction failed",
        forbidden=private_values,
    )
