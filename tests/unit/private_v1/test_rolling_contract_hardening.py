from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.rolling_models import (
    PrivateRollingFixtureCoverage,
    PrivateV1RollingExecutionInput,
    seal_rolling_execution_input,
    seal_rolling_fixture_input,
    seal_rolling_frontier,
    seal_rolling_frontier_point,
    seal_rolling_gameweek_input,
    seal_rolling_horizon_comparison,
)
from tests.unit.private_v1.e2e_test_support import build_rolling_execution_input


def _construct(value, **updates):
    payload = {name: getattr(value, name) for name in type(value).model_fields}
    payload.update(updates)
    return type(value).model_construct(**payload)


@pytest.fixture(scope="module")
def rolling_execution(repository_root, tmp_path_factory):
    return build_rolling_execution_input(
        repository_root,
        tmp_path_factory.mktemp("rolling-contract-hardening"),
    )


@pytest.fixture(scope="module")
def rolling_decision(rolling_execution):
    return PrivateV1RollingRecommendationService().run(rolling_execution).decision


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"home_official_fpl_team_id": 2}, "teams must differ"),
        ({"home_canonical_team_id": None}, "canonical teams must differ"),
        ({"kickoff_at": None}, "kickoff must be after"),
        ({"canonical_fixture_id": None}, "identity or cutoff differs"),
        ({"blocked_reason": "unexpected"}, "cannot carry market evidence"),
        ({"market_mode": "MARKET_BACKED"}, "requires constraints"),
        ({"market_mode": "BLOCKED"}, "requires one typed blocker"),
        ({"warnings": ("Z", "A")}, "warnings must be unique and sorted"),
        ({"semantic_sha256": "f" * 64}, "semantic hash does not match"),
    ),
)
def test_future_fixture_contract_rejects_hostile_mutations(
    rolling_execution, updates, message
) -> None:
    fixture = rolling_execution.future_gameweeks[0].fixtures[0]
    resolved = dict(updates)
    if resolved.get("home_canonical_team_id") is None and "home_canonical_team_id" in resolved:
        resolved["home_canonical_team_id"] = fixture.away_canonical_team_id
    if resolved.get("kickoff_at") is None and "kickoff_at" in resolved:
        resolved["kickoff_at"] = fixture.information_cutoff
    if resolved.get("canonical_fixture_id") is None and "canonical_fixture_id" in resolved:
        resolved["canonical_fixture_id"] = fixture.home_canonical_team_id

    with pytest.raises(ValidationError, match=message):
        fixture.model_copy(update=resolved)


def test_future_market_modes_accept_cutoff_evidence_and_reject_post_cutoff(
    rolling_execution,
) -> None:
    fixture = rolling_execution.future_gameweeks[0].fixtures[0]
    constraint = rolling_execution.current_execution.market_constraints.fixtures[
        0
    ].constraint_set.constraints[0]
    market_backed = seal_rolling_fixture_input(
        _construct(
            fixture,
            market_mode="MARKET_BACKED",
            market_constraints=(constraint,),
            semantic_sha256="0" * 64,
        )
    )

    assert market_backed.market_mode == "MARKET_BACKED"
    with pytest.raises(ValueError, match="post-cutoff"):
        seal_rolling_fixture_input(
            _construct(
                market_backed,
                market_constraints=(
                    constraint.model_copy(
                        update={"usable_at": fixture.information_cutoff + timedelta(seconds=1)}
                    ),
                ),
                semantic_sha256="0" * 64,
            )
        )


def test_gameweek_and_execution_fixture_sets_are_canonical_and_complete(
    rolling_execution,
) -> None:
    gameweek = rolling_execution.future_gameweeks[0]
    first, *remaining = gameweek.fixtures
    with pytest.raises(ValueError, match="unique and sorted"):
        seal_rolling_gameweek_input(
            _construct(
                gameweek,
                fixtures=(first, first, *remaining),
                semantic_sha256="0" * 64,
            )
        )
    incomplete = seal_rolling_gameweek_input(
        _construct(gameweek, fixtures=tuple(remaining), semantic_sha256="0" * 64)
    )
    with pytest.raises(ValueError, match="every officially assigned fixture"):
        seal_rolling_execution_input(
            _construct(
                rolling_execution,
                future_gameweeks=(incomplete, rolling_execution.future_gameweeks[1]),
                semantic_sha256="0" * 64,
            )
        )
    with pytest.raises(ValidationError, match="semantic hash does not match"):
        rolling_execution.model_copy(update={"semantic_sha256": "f" * 64})

    with pytest.raises(ValueError, match="must derive from the current governed candidate policy"):
        seal_rolling_execution_input(
            _construct(
                rolling_execution,
                maximum_transfers_per_deadline=(
                    rolling_execution.maximum_transfers_per_deadline + 1
                ),
                semantic_sha256="0" * 64,
            )
        )


def test_output_value_contracts_reject_arithmetic_and_canonicality_drift(
    rolling_decision,
) -> None:
    gameweek = rolling_decision.do_now
    with pytest.raises(ValidationError, match="transfer count differs from its moves"):
        gameweek.model_copy(update={"transfer_count": gameweek.transfer_count + 1})
    with pytest.raises(ValidationError, match="hit differs"):
        gameweek.model_copy(update={"hit_points": gameweek.hit_points + 4})
    with pytest.raises(ValidationError, match="points do not reconcile"):
        gameweek.model_copy(
            update={
                "expected_manager_points_after_hit": (
                    gameweek.expected_manager_points_after_hit + Decimal(1)
                )
            }
        )
    with pytest.raises(ValidationError, match="squad must be unique and sorted"):
        gameweek.model_copy(
            update={"squad_after": (*gameweek.squad_after, gameweek.squad_after[0])}
        )
    with pytest.raises(ValidationError, match="limitations must be unique and sorted"):
        gameweek.model_copy(update={"limitations": ("Z", "A")})
    with pytest.raises(ValidationError, match="coverage counts do not reconcile"):
        PrivateRollingFixtureCoverage(
            fixtures_total=1,
            market_backed_fixtures=1,
            score_prior_only_fixtures=1,
            blocked_fixtures=0,
        )


def test_comparison_frontier_and_decision_hashes_fail_closed(rolling_decision) -> None:
    comparison = rolling_decision.horizon_comparison
    with pytest.raises(ValueError, match="comparison does not reconcile"):
        seal_rolling_horizon_comparison(
            _construct(
                comparison,
                expected_uplift=comparison.expected_uplift + Decimal(1),
                semantic_sha256="0" * 64,
            )
        )
    point = rolling_decision.transfer_frontier.points[-1]
    with pytest.raises(ValueError, match="frontier point does not reconcile"):
        seal_rolling_frontier_point(
            _construct(
                point,
                expected_horizon_utility=point.expected_horizon_utility + Decimal(1),
                semantic_sha256="0" * 64,
            )
        )
    with pytest.raises(ValueError, match="frontier is not canonical"):
        seal_rolling_frontier(
            _construct(
                rolling_decision.transfer_frontier,
                points=(),
                semantic_sha256="0" * 64,
            )
        )
    with pytest.raises(ValidationError, match="decomposition does not reconcile"):
        rolling_decision.one_gameweek_comparison.model_copy(
            update={
                "total_horizon_utility_difference": (
                    rolling_decision.one_gameweek_comparison.total_horizon_utility_difference
                    + Decimal(1)
                )
            }
        )


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("horizon_gameweeks", "by-Gameweek decisions differ"),
        ("do_now", "root action must be the only DO NOW"),
        ("future_plan", "Field required"),
        ("action_space_disclosure", "action-space disclosures differ"),
        ("warnings", "warnings must be unique and sorted"),
        ("semantic_sha256", "semantic hash does not match"),
    ),
)
def test_rolling_decision_rejects_structural_or_hash_drift(
    rolling_decision, field, message
) -> None:
    updates = {
        "horizon_gameweeks": (1, 2, 4),
        "do_now": rolling_decision.by_gameweek[1],
        "future_plan": (),
        "action_space_disclosure": "different",
        "warnings": ("Z", "A"),
        "semantic_sha256": "f" * 64,
    }
    with pytest.raises(ValidationError, match=message):
        rolling_decision.model_copy(update={field: updates[field]})


def test_rolling_cutoff_rejects_naive_datetime(rolling_decision) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        rolling_decision.model_copy(update={"information_cutoff": datetime(2026, 8, 1)})


def test_decision_rejects_transfer_counts_above_derived_scope(rolling_decision) -> None:
    with pytest.raises(ValidationError, match="exceeds its derived governed scope"):
        rolling_decision.model_copy(update={"maximum_transfers_per_deadline": 0})


def test_service_revalidates_even_constructed_execution_inputs(rolling_execution) -> None:
    invalid = PrivateV1RollingExecutionInput.model_construct(
        **{
            **{
                name: getattr(rolling_execution, name)
                for name in PrivateV1RollingExecutionInput.model_fields
            },
            "semantic_sha256": "f" * 64,
        }
    )

    with pytest.raises(PrivateV1Error) as caught:
        PrivateV1RollingRecommendationService().run(invalid)

    assert caught.value.code == "PRIVATE_ROLLING_EXECUTION_INPUT_INVALID"
