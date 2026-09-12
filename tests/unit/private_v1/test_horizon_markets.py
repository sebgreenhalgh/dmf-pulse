"""R8B synthetic source-lineage and shared-market-kernel acceptance tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.current import build_exact_fixture_market_constraints
from dmf_pulse.markets.policy import load_market_normalisation_policy
from dmf_pulse.private_v1.horizon_markets import (
    _exact_event,
    build_future_market_evidence,
    horizon_future_market_evidence_sha256,
    verify_future_market_evidence,
)
from tests.unit.markets.current_market_test_support import (
    build_market_context,
    rehash_odds,
    rehash_unified_source,
)

pytestmark = pytest.mark.unit


def _root_fixture(context, official_fpl_fixture_id: int):
    return next(
        item
        for item in context.fpl_input.fixtures
        if item.provider_fixture_id == official_fpl_fixture_id
    )


def _rehash_evidence(evidence, **updates):
    payload = {name: getattr(evidence, name) for name in type(evidence).model_fields}
    payload.update(updates)
    payload["semantic_sha256"] = "0" * 64
    provisional = type(evidence).model_construct(**payload)
    payload["semantic_sha256"] = horizon_future_market_evidence_sha256(provisional)
    return type(evidence).model_validate(payload)


def _source_without_later_pair(context):
    return rehash_unified_source(
        context,
        odds_input=rehash_odds(context.odds_input, events=context.odds_input.events[:2]),
    )


def test_root_wrapper_and_extracted_kernel_are_exactly_equal(repository_root, tmp_path) -> None:
    context, view, _request, wrapped = build_market_context(repository_root, tmp_path)
    fixture = view.fixtures[0]
    event = next(
        item
        for item in context.odds_input.events
        if item.provider_event_id == fixture.provider_event_id
    )

    direct = build_exact_fixture_market_constraints(
        source=context.bundle,
        event=event,
        fixture=fixture,
        identity_view=view,
        mapping_cutoff=context.bundle.identity_map.mapping_decided_at,
        policy=load_market_normalisation_policy(),
        score_policy=load_score_baseline_policy(),
        market_as_of=max(
            context.bundle.decision_information_at,
            context.bundle.identity_map.mapping_decided_at,
        ),
    )

    assert direct == wrapped.fixtures[0]


def test_future_evidence_is_reconstructed_from_complete_source(repository_root, tmp_path) -> None:
    context, view, _request, _wrapped = build_market_context(repository_root, tmp_path)
    fixture = _root_fixture(context, view.fixtures[0].official_fpl_fixture_id)
    canonical_fixture_id = view.fixtures[0].canonical_fixture_id
    source = _source_without_later_pair(context)
    evidence = build_future_market_evidence(
        source, fixture=fixture, canonical_fixture_id=canonical_fixture_id
    )

    assert evidence.classification == "MARKET_BACKED"
    assert (
        evidence.original_response_body_sha256 == context.odds_input.provenance.response_body_sha256
    )
    assert (
        evidence.original_request_fingerprint == context.odds_input.provenance.request_fingerprint
    )
    assert (
        verify_future_market_evidence(
            evidence, source, fixture=fixture, canonical_fixture_id=canonical_fixture_id
        )
        == evidence
    )

    tampered = _rehash_evidence(evidence, provider_event_id="substituted-provider-event")
    with pytest.raises(IngestionError, match="future evidence differs from source"):
        verify_future_market_evidence(
            tampered, source, fixture=fixture, canonical_fixture_id=canonical_fixture_id
        )


def test_future_event_without_books_is_explicitly_prior_only(repository_root, tmp_path) -> None:
    context, view, _request, _wrapped = build_market_context(repository_root, tmp_path)
    fixture = _root_fixture(context, view.fixtures[0].official_fpl_fixture_id)
    event = context.odds_input.events[0].model_copy(update={"bookmakers": ()})
    odds = rehash_odds(context.odds_input, events=(event, context.odds_input.events[1]))
    source = rehash_unified_source(context, odds_input=odds)

    evidence = build_future_market_evidence(
        source, fixture=fixture, canonical_fixture_id=view.fixtures[0].canonical_fixture_id
    )

    assert evidence.classification == "H2H_UNAVAILABLE"
    assert evidence.constraints == ()
    assert evidence.warnings == ("FUTURE_MARKET_H2H_UNAVAILABLE",)


def test_unrelated_same_time_event_is_ignored_but_reversal_blocks(
    repository_root, tmp_path
) -> None:
    context, view, _request, _wrapped = build_market_context(repository_root, tmp_path)
    fixture = _root_fixture(context, view.fixtures[0].official_fpl_fixture_id)
    target = context.odds_input.events[0]
    unrelated = target.model_copy(
        update={
            "provider_event_id": "unrelated-same-time",
            "provider_home_team": "Gamma City",
            "provider_away_team": "Delta United",
        }
    )
    source = rehash_unified_source(
        context,
        odds_input=rehash_odds(context.odds_input, events=(target, unrelated)),
    )
    assert _exact_event(source, fixture) == target

    reversal = target.model_copy(
        update={
            "provider_event_id": "reversed-same-time",
            "provider_home_team": target.provider_away_team,
            "provider_away_team": target.provider_home_team,
        }
    )
    blocked_source = rehash_unified_source(
        context,
        odds_input=rehash_odds(context.odds_input, events=(target, reversal)),
    )
    with pytest.raises(IngestionError, match="contradicts official orientation"):
        _exact_event(blocked_source, fixture)


def test_unresolvable_exact_kickoff_event_cannot_be_relabelled_as_absence(
    repository_root, tmp_path
) -> None:
    context, view, _request, _wrapped = build_market_context(repository_root, tmp_path)
    fixture = _root_fixture(context, view.fixtures[0].official_fpl_fixture_id)
    unresolved_target = context.odds_input.events[0].model_copy(
        update={
            "provider_home_team": "Unresolvable Target Home",
            "provider_away_team": "Unresolvable Target Away",
        }
    )
    source = rehash_unified_source(
        context,
        odds_input=rehash_odds(context.odds_input, events=(unresolved_target,)),
    )

    with pytest.raises(IngestionError, match="unresolvable provider event"):
        build_future_market_evidence(
            source, fixture=fixture, canonical_fixture_id=view.fixtures[0].canonical_fixture_id
        )


def test_future_fixture_source_substitution_is_never_accepted(repository_root, tmp_path) -> None:
    context, view, _request, _wrapped = build_market_context(repository_root, tmp_path)
    fixture = _root_fixture(context, view.fixtures[0].official_fpl_fixture_id)
    source = _source_without_later_pair(context)
    evidence = build_future_market_evidence(
        source, fixture=fixture, canonical_fixture_id=view.fixtures[0].canonical_fixture_id
    )
    substituted = _rehash_evidence(
        evidence, information_cutoff=evidence.information_cutoff - timedelta(seconds=1)
    )
    with pytest.raises(IngestionError, match="future evidence differs from source"):
        verify_future_market_evidence(
            substituted,
            source,
            fixture=fixture,
            canonical_fixture_id=view.fixtures[0].canonical_fixture_id,
        )
