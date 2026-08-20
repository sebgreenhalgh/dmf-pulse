from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.opponent_actions import model_opponent_actions
from dmf_pulse.rank_strategy.opponent_models import (
    OpponentActionDistribution,
    OpponentBehaviourProfile,
    OpponentChipAction,
    OpponentObservedState,
)
from tests.support.opponent_action_fixtures import (
    CUTOFF,
    DEADLINE,
    baseline_candidates,
    behaviour_profile,
    candidate,
    observed_state,
)

pytestmark = pytest.mark.unit


def test_observed_state_rejects_temporal_and_manager_mismatch() -> None:
    payload = observed_state().model_dump(mode="python")
    payload["observed_at"] = CUTOFF + timedelta(seconds=1)
    with pytest.raises(ValidationError):
        OpponentObservedState.model_validate(payload)

    payload = observed_state().model_dump(mode="python")
    payload["information_cutoff"] = DEADLINE + timedelta(seconds=1)
    with pytest.raises(ValidationError):
        OpponentObservedState.model_validate(payload)

    payload = observed_state().model_dump(mode="python")
    payload["observed_plan"] = {**payload["observed_plan"], "manager_id": "other"}
    with pytest.raises(ValidationError):
        OpponentObservedState.model_validate(payload)


def test_profile_rejects_future_estimate_and_non_utc_timestamp() -> None:
    payload = behaviour_profile().model_dump(mode="python")
    payload["estimated_at"] = CUTOFF + timedelta(seconds=1)
    with pytest.raises(ValidationError):
        OpponentBehaviourProfile.model_validate(payload)

    payload = behaviour_profile().model_dump(mode="python")
    payload["information_cutoff"] = payload["information_cutoff"].replace(tzinfo=None)
    with pytest.raises(ValidationError):
        OpponentBehaviourProfile.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda payload: payload.update(chip_action=OpponentChipAction.BENCH_BOOST),
            "chip descriptor",
        ),
        (lambda payload: payload.update(counted_transfer_delta=0), "ordinary transfers"),
        (
            lambda payload: payload.update(
                transfer_count=3,
                counted_transfer_delta=3,
                chip_action=OpponentChipAction.FREE_HIT,
                manager_plan=candidate(
                    "free-hit-contract",
                    transfer_count=3,
                    chip=OpponentChipAction.FREE_HIT,
                ).manager_plan.model_dump(mode="python"),
            ),
            "Free Hit and Wildcard",
        ),
        (
            lambda payload: payload.update(
                transfer_count=0,
                counted_transfer_delta=0,
                manager_plan={**payload["manager_plan"], "transfer_hit_points": 4},
            ),
            "no-transfer",
        ),
        (
            lambda payload: payload.update(
                transfer_count=0,
                counted_transfer_delta=0,
                chip_action=OpponentChipAction.WILDCARD,
            ),
            "Wildcard candidate",
        ),
    ],
)
def test_action_candidate_rejects_semantic_inconsistency(mutation, match: str) -> None:
    payload = candidate("transfer", expected_points=52.0, transfer_count=1).model_dump(
        mode="python"
    )
    mutation(payload)
    with pytest.raises(ValidationError, match=match):
        candidate("transfer", expected_points=52.0, transfer_count=1).__class__.model_validate(
            payload
        )


def test_action_candidate_rejects_feature_after_generation() -> None:
    payload = candidate("transfer", expected_points=52.0, transfer_count=1).model_dump(
        mode="python"
    )
    payload["features"] = {
        **payload["features"],
        "observed_at": payload["generated_at"] + timedelta(seconds=1),
    }
    with pytest.raises(ValidationError, match="features cannot postdate"):
        candidate("transfer", expected_points=52.0, transfer_count=1).__class__.model_validate(
            payload
        )


@pytest.mark.parametrize(
    "chip",
    [OpponentChipAction.FREE_HIT, OpponentChipAction.WILDCARD],
)
def test_free_hit_and_wildcard_actions_cannot_carry_transfer_hits(
    chip: OpponentChipAction,
) -> None:
    action = candidate(f"{chip.value.lower()}-hits", transfer_count=2, chip=chip)
    payload = action.model_dump(mode="python")
    payload["manager_plan"] = {
        **payload["manager_plan"],
        "transfer_hit_points": 4,
    }

    with pytest.raises(ValidationError, match="transfer-hit deductions"):
        type(action).model_validate(payload)


def test_distribution_rejects_invalid_probability_vector_and_diagnostics() -> None:
    result = model_opponent_actions(observed_state(), baseline_candidates(), behaviour_profile())
    mutations = (
        lambda payload: payload.update(actions=tuple(reversed(payload["actions"]))),
        lambda payload: payload.update(
            actions=tuple({**item, "probability": 0.2} for item in payload["actions"])
        ),
        lambda payload: payload.update(no_transfer_probability=0.0),
        lambda payload: payload.update(expected_transfer_count=99.0),
        lambda payload: payload.update(expected_hit_points=99.0),
        lambda payload: payload.update(entropy=0.0),
        lambda payload: payload.update(normalised_entropy=0.0),
    )
    for mutation in mutations:
        payload = result.model_dump(mode="python")
        mutation(payload)
        with pytest.raises(ValidationError):
            OpponentActionDistribution.model_validate(payload)


def test_model_boundary_requires_profile_manager_and_cutoff_match() -> None:
    profile = behaviour_profile().model_copy(update={"manager_id": "other"})
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), baseline_candidates(), profile)
    assert exc_info.value.code == "RANK_OPPONENT_PROFILE_MANAGER_MISMATCH"

    profile = behaviour_profile().model_copy(
        update={"information_cutoff": CUTOFF - timedelta(minutes=1)}
    )
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), baseline_candidates(), profile)
    assert exc_info.value.code == "RANK_OPPONENT_PROFILE_CUTOFF_MISMATCH"


def test_model_boundary_requires_nontrivial_unique_action_set_and_valid_floor() -> None:
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), (candidate("only"),), behaviour_profile())
    assert exc_info.value.code == "RANK_OPPONENT_ACTION_SET_TOO_SMALL"

    duplicate = candidate("same")
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), (duplicate, duplicate), behaviour_profile())
    assert exc_info.value.code == "RANK_OPPONENT_ACTION_DUPLICATE"

    profile = behaviour_profile().model_copy(update={"probability_floor": 0.4})
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), baseline_candidates(), profile)
    assert exc_info.value.code == "RANK_OPPONENT_PROBABILITY_FLOOR_INVALID"


def test_model_boundary_requires_transfer_and_no_transfer_branches() -> None:
    transfers_only = (
        candidate("transfer-a", expected_points=52.0, transfer_count=1),
        candidate("transfer-b", expected_points=53.0, transfer_count=1),
    )
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), transfers_only, behaviour_profile())
    assert exc_info.value.code == "RANK_OPPONENT_NO_TRANSFER_MISSING"

    no_transfers_only = (
        candidate("no-transfer-a", expected_points=50.0),
        candidate("no-transfer-b", expected_points=51.0, captain="p13", vice="p12"),
    )
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(observed_state(), no_transfers_only, behaviour_profile())
    assert exc_info.value.code == "RANK_OPPONENT_TRANSFER_ACTION_MISSING"


def test_model_boundary_rejects_semantic_duplicate_plans() -> None:
    first = candidate("transfer-a", expected_points=52.0, transfer_count=1)
    second = first.model_copy(update={"action_id": "transfer-b"})
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(
            observed_state(),
            (candidate("no-transfer"), first, second),
            behaviour_profile(),
        )
    assert exc_info.value.code == "RANK_OPPONENT_PLAN_DUPLICATE"


def test_model_boundary_rejects_manager_points_and_counted_transfer_mutation() -> None:
    transfer = candidate("transfer", expected_points=52.0, transfer_count=1)
    cases = (
        (
            transfer.model_copy(
                update={
                    "manager_plan": transfer.manager_plan.model_copy(update={"manager_id": "other"})
                }
            ),
            "RANK_OPPONENT_ACTION_MANAGER_MISMATCH",
        ),
        (
            transfer.model_copy(
                update={
                    "manager_plan": transfer.manager_plan.model_copy(
                        update={"cumulative_points": 101}
                    )
                }
            ),
            "RANK_OPPONENT_CUMULATIVE_POINTS_MUTATION",
        ),
        (
            transfer.model_copy(
                update={
                    "manager_plan": transfer.manager_plan.model_copy(
                        update={"counted_transfers": 5}
                    )
                }
            ),
            "RANK_OPPONENT_COUNTED_TRANSFER_MISMATCH",
        ),
    )
    for invalid, expected_code in cases:
        with pytest.raises(RankStrategyError) as exc_info:
            model_opponent_actions(
                observed_state(),
                (candidate("no-transfer"), invalid),
                behaviour_profile(),
            )
        assert exc_info.value.code == expected_code


def test_model_boundary_rejects_squad_mutation_inconsistent_with_action() -> None:
    no_transfer = candidate("no-transfer")
    mutated_no_transfer = no_transfer.model_copy(
        update={
            "manager_plan": no_transfer.manager_plan.model_copy(
                update={
                    "permanent_squad": tuple(reversed(no_transfer.manager_plan.permanent_squad))
                }
            )
        }
    )
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(
            observed_state(),
            (mutated_no_transfer, candidate("transfer", transfer_count=1)),
            behaviour_profile(),
        )
    assert exc_info.value.code == "RANK_OPPONENT_NO_TRANSFER_SQUAD_MUTATION"

    transfer = candidate("transfer", transfer_count=1)
    unchanged_transfer = transfer.model_copy(
        update={
            "manager_plan": transfer.manager_plan.model_copy(
                update={"permanent_squad": observed_state().observed_plan.permanent_squad}
            )
        }
    )
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(
            observed_state(),
            (candidate("no-transfer"), unchanged_transfer),
            behaviour_profile(),
        )
    assert exc_info.value.code == "RANK_OPPONENT_TRANSFER_SQUAD_UNCHANGED"

    free_hit = candidate(
        "free-hit", transfer_count=3, chip=OpponentChipAction.FREE_HIT, expected_points=54.0
    )
    mutated_free_hit = free_hit.model_copy(
        update={
            "manager_plan": free_hit.manager_plan.model_copy(
                update={"permanent_squad": tuple(reversed(free_hit.manager_plan.permanent_squad))}
            )
        }
    )
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(
            observed_state(),
            (candidate("no-transfer"), mutated_free_hit),
            behaviour_profile(),
        )
    assert exc_info.value.code == "RANK_OPPONENT_FREE_HIT_PERMANENT_MUTATION"
