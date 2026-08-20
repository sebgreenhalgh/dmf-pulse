from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import ManagerChip, SampleRightsStatus
from dmf_pulse.rank_strategy.opponent_actions import model_opponent_actions
from dmf_pulse.rank_strategy.opponent_models import OpponentChipAction
from tests.support.opponent_action_fixtures import (
    CUTOFF,
    action_features,
    baseline_candidates,
    behaviour_profile,
    candidate,
    observed_state,
)

pytestmark = pytest.mark.unit


def _probabilities(result) -> dict[str, float]:
    return {item.action_id: item.probability for item in result.actions}


def test_baseline_distribution_is_non_degenerate_transparent_and_reconciled() -> None:
    result = model_opponent_actions(observed_state(), baseline_candidates(), behaviour_profile())

    probabilities = _probabilities(result)
    assert tuple(probabilities) == tuple(sorted(probabilities))
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert all(0.0 < value < 1.0 for value in probabilities.values())
    assert probabilities["one-transfer"] > probabilities["no-transfer"]
    assert result.no_transfer_probability == probabilities["no-transfer"]
    assert result.expected_transfer_count == pytest.approx(probabilities["one-transfer"])
    assert result.expected_hit_points == 0.0
    assert 0.0 < result.normalised_entropy <= 1.0
    assert result.confidence == "B"
    assert result.assumes_perfect_rationality is False


def test_model_supports_every_hidden_action_branch_without_cloning_pulse() -> None:
    candidates = (
        candidate("no-transfer", expected_points=50.0),
        candidate("transfer", expected_points=51.0, transfer_count=1),
        candidate(
            "triple-captain",
            expected_points=52.0,
            chip=OpponentChipAction.TRIPLE_CAPTAIN,
        ),
        candidate(
            "bench-boost",
            expected_points=51.5,
            chip=OpponentChipAction.BENCH_BOOST,
        ),
        candidate(
            "free-hit",
            expected_points=53.0,
            transfer_count=3,
            chip=OpponentChipAction.FREE_HIT,
        ),
        candidate(
            "wildcard",
            expected_points=54.0,
            transfer_count=4,
            chip=OpponentChipAction.WILDCARD,
        ),
        candidate("captain-change", expected_points=52.2, captain="p13", vice="p12"),
    )
    result = model_opponent_actions(observed_state(), candidates, behaviour_profile())

    assert {item.chip_action for item in result.actions} == {
        OpponentChipAction.NONE,
        OpponentChipAction.TRIPLE_CAPTAIN,
        OpponentChipAction.BENCH_BOOST,
        OpponentChipAction.FREE_HIT,
        OpponentChipAction.WILDCARD,
    }
    free_hit = next(item for item in result.actions if item.action_id == "free-hit")
    wildcard = next(item for item in result.actions if item.action_id == "wildcard")
    captain_change = next(item for item in result.actions if item.action_id == "captain-change")
    assert free_hit.manager_plan.active_chip is ManagerChip.FREE_HIT
    assert free_hit.counted_transfer_delta == 0
    assert wildcard.manager_plan.active_chip is ManagerChip.NONE
    assert wildcard.counted_transfer_delta == 0
    assert captain_change.manager_plan.tactical_configuration.captain == "p13"
    assert all(item.probability > 0.0 for item in result.actions)


def test_profile_changes_probabilities_without_becoming_perfectly_rational() -> None:
    candidates = baseline_candidates()
    baseline = model_opponent_actions(observed_state(), candidates, behaviour_profile())
    hotter = model_opponent_actions(
        observed_state(),
        candidates,
        behaviour_profile().model_copy(update={"random_utility_temperature": 20.0}),
    )

    baseline_range = max(_probabilities(baseline).values()) - min(_probabilities(baseline).values())
    hotter_range = max(_probabilities(hotter).values()) - min(_probabilities(hotter).values())
    assert hotter_range < baseline_range
    assert max(_probabilities(baseline).values()) < 1.0
    assert max(_probabilities(hotter).values()) < 1.0


def test_invalid_rights_fail_before_numerical_opponent_modelling() -> None:
    with pytest.raises(RankStrategyError) as exc_info:
        model_opponent_actions(
            observed_state(rights=SampleRightsStatus.UNKNOWN),
            baseline_candidates(),
            behaviour_profile(),
        )
    assert exc_info.value.code == "RANK_OPPONENT_RIGHTS_INVALID"


def test_profile_cannot_claim_perfect_rationality() -> None:
    payload = behaviour_profile().model_dump(mode="python")
    payload["assumes_perfect_rationality"] = True
    with pytest.raises(ValidationError):
        behaviour_profile().__class__.model_validate(payload)


def test_future_action_feature_and_postdeadline_label_leakage_have_distinct_codes() -> None:
    cases = (
        (
            candidate("future-action", generated_at=CUTOFF + timedelta(seconds=1)),
            "RANK_OPPONENT_FUTURE_ACTION_LEAKAGE",
        ),
        (
            candidate("future-feature", feature_observed_at=CUTOFF + timedelta(seconds=1)),
            "RANK_OPPONENT_FUTURE_FEATURE_LEAKAGE",
        ),
        (
            candidate("postdeadline-label", postdeadline_label=True),
            "RANK_OPPONENT_POSTDEADLINE_LABEL_LEAKAGE",
        ),
    )
    for invalid, expected_code in cases:
        candidates = (candidate("no-transfer"), invalid)
        with pytest.raises(RankStrategyError) as exc_info:
            model_opponent_actions(observed_state(), candidates, behaviour_profile())
        assert exc_info.value.code == expected_code


def test_feature_confidence_flows_to_distribution_confidence() -> None:
    low_confidence = candidate("transfer", expected_points=52.0, transfer_count=1).model_copy(
        update={"features": action_features(52.0, confidence="D")}
    )
    result = model_opponent_actions(
        observed_state(),
        (candidate("no-transfer"), low_confidence),
        behaviour_profile(),
    )
    assert result.confidence == "D"


def test_model_is_deterministic_and_input_order_invariant() -> None:
    candidates = baseline_candidates()
    first = model_opponent_actions(observed_state(), candidates, behaviour_profile())
    second = model_opponent_actions(
        observed_state(), tuple(reversed(candidates)), behaviour_profile()
    )
    assert first == second
    assert first.distribution_hash == second.distribution_hash


def test_counted_transfer_state_is_exact_for_transfer_and_noncounting_chips() -> None:
    candidates = (
        candidate("no-transfer"),
        candidate("transfer", expected_points=52.0, transfer_count=1),
        candidate(
            "free-hit",
            expected_points=53.0,
            transfer_count=3,
            chip=OpponentChipAction.FREE_HIT,
        ),
        candidate(
            "wildcard",
            expected_points=54.0,
            transfer_count=4,
            chip=OpponentChipAction.WILDCARD,
        ),
    )
    result = model_opponent_actions(observed_state(), candidates, behaviour_profile())
    by_id = {item.action_id: item for item in result.actions}
    assert by_id["no-transfer"].manager_plan.counted_transfers == 5
    assert by_id["transfer"].manager_plan.counted_transfers == 6
    assert by_id["free-hit"].manager_plan.counted_transfers == 5
    assert by_id["wildcard"].manager_plan.counted_transfers == 5


def test_transfer_hit_is_retained_for_later_exact_manager_scoring() -> None:
    candidates = (
        candidate("no-transfer"),
        candidate("hit-transfer", expected_points=58.0, transfer_count=1, hit_points=4),
    )
    result = model_opponent_actions(observed_state(), candidates, behaviour_profile())
    hit = next(item for item in result.actions if item.action_id == "hit-transfer")
    assert hit.manager_plan.transfer_hit_points == 4
    assert result.expected_hit_points == pytest.approx(4.0 * hit.probability)


def test_model_does_not_mutate_exact_observed_state() -> None:
    state = observed_state()
    before = state.model_dump(mode="json")
    model_opponent_actions(state, baseline_candidates(), behaviour_profile())
    assert state.model_dump(mode="json") == before
