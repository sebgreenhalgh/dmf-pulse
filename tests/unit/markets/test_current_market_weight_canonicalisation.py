"""PRIVATE-V1-ONE-COMMAND-001G exact public totals-weight regressions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.football_events.market_constraints import (
    MarketConstraintSet,
    MarketFamily,
    cap_market_family_weights,
)
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.markets.current import (
    CurrentFixtureMarketConstraints,
    CurrentMarketConstraintBundle,
    _totals_constraints,
    current_fixture_market_constraints_sha256,
    current_market_constraint_bundle_sha256,
    current_totals_consensus_sha256,
)

from .current_market_test_support import build_market_context


def _regrade_bundle(
    source: CurrentMarketConstraintBundle, grade: str
) -> CurrentMarketConstraintBundle:
    policy = load_score_baseline_policy().projection
    fixtures: list[CurrentFixtureMarketConstraints] = []
    for fixture in source.fixtures:
        totals = []
        constraints = [
            item
            for item in fixture.constraint_set.constraints
            if item.family is not MarketFamily.TOTALS
        ]
        for original in fixture.totals_consensuses:
            provisional = original.model_copy(
                update={"confidence_grade": grade, "result_sha256": "0" * 64}
            )
            consensus = provisional.model_copy(
                update={"result_sha256": current_totals_consensus_sha256(provisional)}
            )
            totals.append(consensus)
            constraints.extend(
                _totals_constraints(
                    consensus,
                    uncertainty_floor=policy.market_uncertainty_floor,
                )
            )
        constraint_set = cap_market_family_weights(
            MarketConstraintSet(
                as_of=fixture.constraint_set.as_of,
                constraints=tuple(constraints),
                source_result_sha256=canonical_sha256(
                    {
                        "h2h": (
                            fixture.h2h_consensus.result_sha256
                            if fixture.h2h_consensus is not None
                            else None
                        ),
                        "totals": [item.result_sha256 for item in totals],
                    }
                ),
            ),
            policy.family_cap_map,
        )
        provisional_fixture = fixture.model_copy(
            update={
                "totals_consensuses": tuple(totals),
                "constraint_set": constraint_set,
                "semantic_sha256": "0" * 64,
            }
        )
        fixtures.append(
            provisional_fixture.model_copy(
                update={
                    "semantic_sha256": current_fixture_market_constraints_sha256(
                        provisional_fixture
                    )
                }
            )
        )
    provisional_bundle = source.model_copy(
        update={"fixtures": tuple(fixtures), "semantic_sha256": "0" * 64}
    )
    return CurrentMarketConstraintBundle.model_validate_json(
        canonical_json_bytes(
            provisional_bundle.model_copy(
                update={
                    "semantic_sha256": current_market_constraint_bundle_sha256(provisional_bundle)
                }
            ).model_dump(mode="json")
        )
    )


@pytest.mark.parametrize(
    ("grade", "expected_pair_total"),
    (("A", Decimal("1")), ("B", Decimal("0.75")), ("C", Decimal("0.50")), ("D", Decimal("0.25"))),
)
def test_totals_weight_pairs_are_exact_public_scale_and_bundle_round_trip(
    repository_root, tmp_path, grade: str, expected_pair_total: Decimal
) -> None:
    _context, _view, _request, source = build_market_context(repository_root, tmp_path)
    bundle = _regrade_bundle(source, grade)

    for fixture in bundle.fixtures:
        for consensus in fixture.totals_consensuses:
            pair = tuple(
                item
                for item in fixture.constraint_set.constraints
                if item.family is MarketFamily.TOTALS and item.line == consensus.line
            )
            # Two lines share the unchanged TOTALS family cap of one after pair production.
            expected_after_cap = min(expected_pair_total, Decimal("0.5"))
            assert sum((item.weight for item in pair), Decimal(0)) == expected_after_cap
            assert all(item.weight.as_tuple().exponent == -12 for item in pair)
            assert all(item.confidence_grade == grade for item in pair)
        totals_weight = sum(
            (
                item.weight
                for item in fixture.constraint_set.constraints
                if item.family is MarketFamily.TOTALS
            ),
            Decimal(0),
        )
        assert totals_weight == min(
            Decimal(1), expected_pair_total * len(fixture.totals_consensuses)
        )

    payload = bundle.model_dump(mode="json")
    restored = CurrentMarketConstraintBundle.model_validate_json(canonical_json_bytes(payload))
    assert restored == bundle
    assert restored.semantic_sha256 == current_market_constraint_bundle_sha256(restored)


@pytest.mark.parametrize(
    ("grade", "expected"),
    (("B", Decimal("0.75")), ("C", Decimal("0.50")), ("D", Decimal("0.25"))),
)
def test_uncapped_totals_producer_preserves_exact_pair_total(
    repository_root, tmp_path, grade: str, expected: Decimal
) -> None:
    _context, _view, _request, bundle = build_market_context(repository_root, tmp_path)
    original = bundle.fixtures[0].totals_consensuses[0]
    provisional = original.model_copy(update={"confidence_grade": grade, "result_sha256": "0" * 64})
    consensus = provisional.model_copy(
        update={"result_sha256": current_totals_consensus_sha256(provisional)}
    )

    constraints = _totals_constraints(
        consensus,
        uncertainty_floor=load_score_baseline_policy().projection.market_uncertainty_floor,
    )

    assert sum((item.weight for item in constraints), Decimal(0)) == expected
    assert all(item.weight.as_tuple().exponent == -12 for item in constraints)
    assert tuple(item.target_probability for item in constraints) == tuple(
        item.consensus_probability for item in consensus.outcomes
    )
    assert tuple(item.uncertainty for item in constraints) == tuple(
        max(
            (item.upper_bound - item.lower_bound) / Decimal(2),
            consensus.market_disagreement,
            load_score_baseline_policy().projection.market_uncertainty_floor,
        )
        for item in consensus.outcomes
    )
