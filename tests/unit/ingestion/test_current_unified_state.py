"""Positive composition and disclosure tests for CURRENT-FPL-STATE-001D."""

from __future__ import annotations

import json

from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateRequest,
    CurrentUnifiedStateService,
    current_unified_state_semantic_sha256,
)

from .current_identity_test_support import OUTSIDE_PROVIDER_EVENT_ID
from .current_unified_state_test_support import build_context, build_two_fixture_context, verify


def test_composes_one_usable_gw2_family_before_deadline(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    bundle = context.bundle

    assert bundle.status == "USABLE"
    assert bundle.target_gameweek == 2
    assert bundle.information_cutoff < bundle.target_deadline_at
    assert (
        OUTSIDE_PROVIDER_EVENT_ID in bundle.identity_map.coverage.outside_target_provider_event_ids
    )
    assert bundle.identity_map.mapping_outcome == "COMPLETE"
    assert bundle.manager_state.source_class == "OPERATOR_DECLARED"
    assert bundle.manager_state.attestation_status == "HUMAN_ATTESTED"
    assert bundle.manager_state.provider_verification == "NOT_PROVIDER_VERIFIED"
    assert bundle.runtime.storage_mode == "TRANSIENT_IN_MEMORY"
    assert bundle.runtime.persistence_performed is False
    assert bundle.runtime.database_accessed is False
    assert bundle.runtime.network_called is False
    assert bundle.semantic_sha256 == current_unified_state_semantic_sha256(bundle)
    assert verify(context) == bundle


def test_decision_information_time_is_latest_required_readiness(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    expected = max(
        context.fpl_input.provenance.usable_at,
        context.odds_input.temporal.usable_at,
        context.identity_map.mapping_decided_at,
        context.manager_state.usable_at,
    )
    assert context.bundle.decision_information_at == expected
    assert expected != context.bundle.information_cutoff


def test_two_target_fixtures_and_unrelated_future_event_are_supported(
    repository_root, tmp_path
) -> None:
    context = build_two_fixture_context(repository_root, tmp_path)
    coverage = context.bundle.identity_map.coverage
    assert coverage.target_fpl_fixture_count == 2
    assert coverage.mapped_event_count == 2
    assert coverage.outside_target_provider_event_count == 1
    assert len(context.bundle.odds_input.events) == 3
    assert context.bundle.status == "USABLE"


def test_request_is_path_free_and_binds_all_source_views(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    names = set(CurrentUnifiedStateRequest.model_fields)
    assert not any("path" in name or "url" in name for name in names)
    assert context.request.fpl_input_semantic_sha256 == context.fpl_input.semantic_sha256
    assert context.request.odds_market_semantic_sha256 == context.odds_input.market_semantic_sha256
    assert (
        context.request.manager_declaration_semantic_sha256
        == context.manager_state.lineage.manager_declaration_semantic_sha256
    )


def test_summary_exposes_only_bounded_counts_classes_hashes_and_times(
    repository_root, tmp_path
) -> None:
    context = build_context(repository_root, tmp_path)
    summary = context.bundle.safe_summary()
    payload = summary.model_dump(mode="json")
    text = json.dumps(payload, sort_keys=True)
    field_names = set(payload)
    assert field_names == {
        "schema_version",
        "contract",
        "status",
        "season_code",
        "target_gameweek",
        "target_deadline_at",
        "information_cutoff",
        "decision_information_at",
        "fpl_team_count",
        "fpl_player_count",
        "target_fpl_fixture_count",
        "odds_event_count",
        "mapped_target_fixture_count",
        "manager_squad_count",
        "identity_coverage",
        "manager_source_class",
        "manager_attestation_status",
        "manager_provider_verification",
        "lineage",
        "rights",
        "runtime",
        "unified_state_semantic_sha256",
    }
    assert context.manager_state.attestation.operator_reference not in text
    assert context.odds_input.events[0].provider_event_id not in text
    assert context.odds_input.events[0].provider_home_team not in text
    assert context.fpl_input.teams[0].official_name not in text
    assert "bookmaker" not in text.lower()
    assert "price_tenths" not in text
    assert "captain_element" not in text
    assert "chip_token" not in text


def test_composition_is_pure_and_repeatable(repository_root, tmp_path) -> None:
    context = build_context(repository_root, tmp_path)
    service = CurrentUnifiedStateService()
    second = service.compose(
        context.request,
        fpl_input=context.fpl_input,
        odds_input=context.odds_input,
        identity_map=context.identity_map,
        manager_state=context.manager_state,
        ruleset=context.ruleset,
        capability=context.capability,
    )
    assert second == context.bundle
