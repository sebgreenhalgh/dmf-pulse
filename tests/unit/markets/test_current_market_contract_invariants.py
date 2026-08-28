"""Invariant and defensive-branch tests for current-market public contracts."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.markets.current import (
    CurrentFixtureMarketConstraints,
    CurrentMarketConstraintBundle,
    CurrentMarketConstraintError,
    CurrentMarketConstraintRequest,
    CurrentMarketConstraintService,
    CurrentMarketExclusionCount,
    CurrentMarketReadiness,
    CurrentTotalsConsensus,
    CurrentTotalsConsensusOutcome,
    CurrentTotalsOperatorMarket,
)

from .current_market_test_support import build_market_context


def _assert_invalid(model, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_identity_view_invariants_and_safe_lookup_failures(repository_root, tmp_path) -> None:
    _context, view, _request, _result = build_market_context(repository_root, tmp_path)

    mutations = (
        {"resolved_at": view.resolution_cutoff + timedelta(seconds=1)},
        {"database_write_performed": True},
        {"authority": "DAT_003_READ_ONLY", "database_read_performed": False},
        {"fixtures": (view.fixtures[0], view.fixtures[0])},
        {"operators": (view.operators[0], view.operators[0])},
        {"semantic_sha256": "0" * 64},
    )
    for update in mutations:
        with pytest.raises(ValueError):
            view.model_copy(update=update).validate_view()

    with pytest.raises(CurrentMarketConstraintError) as fixture_error:
        view.fixture(999_999)
    with pytest.raises(CurrentMarketConstraintError) as operator_error:
        view.operator("missing-provider-book")
    assert fixture_error.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"
    assert operator_error.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"


def test_naive_public_request_time_is_rejected(repository_root, tmp_path) -> None:
    _context, _view, request, _result = build_market_context(repository_root, tmp_path)
    payload = request.model_dump(mode="python")
    payload["information_cutoff"] = request.information_cutoff.replace(tzinfo=None)
    _assert_invalid(CurrentMarketConstraintRequest, payload)


def test_totals_operator_and_outcome_invariants(repository_root, tmp_path) -> None:
    _context, _view, _request, result = build_market_context(repository_root, tmp_path)
    operator = result.fixtures[0].totals_consensuses[0].operator_markets[0]
    operator_payload = operator.model_dump(mode="python")
    operator_mutations = (
        {"line": Decimal("2.25")},
        {"over_probability": Decimal("0.6")},
        {"proportional_under_probability": Decimal("0.4")},
        {"observed_at": operator.usable_at + timedelta(seconds=1)},
        {"fallback_used": True},
    )
    for mutation in operator_mutations:
        _assert_invalid(CurrentTotalsOperatorMarket, {**operator_payload, **mutation})

    outcome = result.fixtures[0].totals_consensuses[0].outcomes[0]
    outcome_payload = outcome.model_dump(mode="python")
    _assert_invalid(
        CurrentTotalsConsensusOutcome,
        {**outcome_payload, "lower_bound": outcome.consensus_probability + Decimal("0.1")},
    )


def test_totals_consensus_invariants(repository_root, tmp_path) -> None:
    _context, _view, _request, result = build_market_context(repository_root, tmp_path)
    consensus = result.fixtures[0].totals_consensuses[0]
    payload = consensus.model_dump(mode="python")
    changed_outcome = consensus.outcomes[0].model_copy(
        update={
            "consensus_probability": consensus.outcomes[0].consensus_probability - Decimal("0.1")
        }
    )
    mutations = (
        {"line": Decimal("2.25")},
        {"outcomes": tuple(reversed(consensus.outcomes))},
        {"outcomes": (changed_outcome, consensus.outcomes[1])},
        {"operator_count": consensus.operator_count + 1},
        {"provider_count": consensus.provider_count + 1},
        {"eligible_operator_count": consensus.eligible_operator_count + 1},
        {"market_disagreement": Decimal("0")},
        {"minimum_age_seconds": consensus.maximum_age_seconds + 1},
        {"mapping_cutoff": consensus.as_of + timedelta(seconds=1)},
        {"result_sha256": "0" * 64},
    )
    for mutation in mutations:
        _assert_invalid(CurrentTotalsConsensus, {**payload, **mutation})


def _fixture_payload(fixture) -> dict[str, object]:
    payload = fixture.model_dump(mode="python")
    payload["h2h_consensus"] = fixture.h2h_consensus
    return payload


def test_fixture_result_invariants(repository_root, tmp_path) -> None:
    _context, _view, _request, result = build_market_context(repository_root, tmp_path)
    fixture = result.fixtures[0]
    payload = _fixture_payload(fixture)
    first_constraint = fixture.constraint_set.constraints[0]
    postcut_constraint = first_constraint.model_copy(
        update={"usable_at": fixture.constraint_set.as_of + timedelta(seconds=1)}
    )
    postcut_set = fixture.constraint_set.model_copy(
        update={"constraints": (postcut_constraint, *fixture.constraint_set.constraints[1:])}
    )
    missing_totals_constraint_set = fixture.constraint_set.model_copy(
        update={"constraints": fixture.constraint_set.constraints[:-1]}
    )
    unsorted_exclusions = (
        CurrentMarketExclusionCount(reason="Z_REASON", count=1),
        CurrentMarketExclusionCount(reason="A_REASON", count=1),
    )
    mutations = (
        {"constraint_set": postcut_set},
        {"totals_consensuses": ()},
        {"readiness": CurrentMarketReadiness.H2H_ONLY_DEGRADED},
        {"readiness": CurrentMarketReadiness.BLOCKED},
        {"constraint_set": missing_totals_constraint_set},
        {"warnings": ("Z_WARNING", "A_WARNING", "Z_WARNING")},
        {"exclusion_counts": unsorted_exclusions},
        {"semantic_sha256": "0" * 64},
    )
    for mutation in mutations:
        _assert_invalid(CurrentFixtureMarketConstraints, {**payload, **mutation})


def test_bundle_and_summary_invariants(repository_root, tmp_path) -> None:
    _context, _view, _request, result = build_market_context(repository_root, tmp_path)
    payload = result.model_dump(mode="python")
    payload["fixtures"] = result.fixtures
    mutations = (
        {"fixtures": tuple(reversed(result.fixtures))},
        {"decision_information_at": result.information_cutoff + timedelta(seconds=1)},
        {"limitations": result.limitations[:-1]},
        {"runtime": result.runtime.model_copy(update={"persistence_performed": True})},
        {"runtime": result.runtime.model_copy(update={"network_called": True})},
        {"semantic_sha256": "0" * 64},
    )
    for mutation in mutations:
        _assert_invalid(CurrentMarketConstraintBundle, {**payload, **mutation})

    summary = result.safe_summary()
    summary_payload = summary.model_dump(mode="python")
    summary_payload["fixture_count"] += 1
    _assert_invalid(type(summary), summary_payload)


def test_policy_hash_and_wrapper_failures_are_sanitized(
    repository_root, tmp_path, monkeypatch
) -> None:
    context, view, request, _result = build_market_context(repository_root, tmp_path)
    wrong_policy_request = request.model_copy(update={"market_policy_sha256": "0" * 64})
    with pytest.raises(CurrentMarketConstraintError) as policy_error:
        CurrentMarketConstraintService().build(
            wrong_policy_request,
            source=context.bundle,
            identity_view=view,
        )
    assert policy_error.value.code == "MARKET_POLICY_INVALID"

    service = CurrentMarketConstraintService()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise ValueError("provider-private synthetic detail")

    monkeypatch.setattr(service, "_build", fail)
    with pytest.raises(CurrentMarketConstraintError) as wrapped:
        service.build(request, source=context.bundle, identity_view=view)
    assert wrapped.value.code == "SOURCE_INVALID"
    assert "provider-private" not in str(wrapped.value)

    with pytest.raises(CurrentMarketConstraintError) as verify_error:
        CurrentMarketConstraintService().verify(
            object(),  # type: ignore[arg-type]
            request,
            source=context.bundle,
            identity_view=view,
        )
    assert verify_error.value.code == "VERIFICATION_FAILED"
