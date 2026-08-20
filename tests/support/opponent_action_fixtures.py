"""Cutoff-safe synthetic opponent action fixtures for Stage 15."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dmf_pulse.rank_strategy.models import ManagerChip, SampleRightsStatus
from dmf_pulse.rank_strategy.opponent_models import (
    OpponentActionCandidate,
    OpponentActionFeatures,
    OpponentBehaviourProfile,
    OpponentChipAction,
    OpponentObservedState,
)
from tests.support.rank_strategy_fixtures import manager_plan

CUTOFF = datetime(2026, 8, 20, 12, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def observed_state(
    manager_id: str = "rival",
    *,
    rights: SampleRightsStatus = SampleRightsStatus.NAMED_RIVAL_AUTHORISED,
) -> OpponentObservedState:
    return OpponentObservedState(
        state_id=f"state-{manager_id}",
        manager_id=manager_id,
        observed_plan=manager_plan(manager_id, cumulative_points=100, counted_transfers=5),
        rights_status=rights,
        observed_at=CUTOFF - timedelta(hours=2),
        information_cutoff=CUTOFF,
        deadline=DEADLINE,
    )


def behaviour_profile(manager_id: str = "rival") -> OpponentBehaviourProfile:
    return OpponentBehaviourProfile(
        profile_id=f"profile-{manager_id}",
        manager_id=manager_id,
        estimated_at=CUTOFF - timedelta(hours=1),
        information_cutoff=CUTOFF,
        points_coefficient=0.18,
        popularity_coefficient=0.15,
        recent_form_coefficient=0.10,
        price_pressure_coefficient=0.05,
        relative_risk_coefficient=0.04,
        no_transfer_bias=0.25,
        hit_point_penalty=0.30,
        chip_biases={
            OpponentChipAction.TRIPLE_CAPTAIN: -0.40,
            OpponentChipAction.BENCH_BOOST: -0.30,
            OpponentChipAction.FREE_HIT: -0.20,
            OpponentChipAction.WILDCARD: -0.10,
        },
        random_utility_temperature=2.0,
        probability_floor=0.01,
        confidence="B",
    )


def action_features(
    expected_points: float,
    *,
    popularity: float = 0.0,
    recent_form: float = 0.0,
    price_pressure: float = 0.0,
    relative_risk: float = 0.0,
    confidence: str = "B",
    observed_at: datetime = CUTOFF - timedelta(minutes=30),
    contains_postdeadline_action_label: bool = False,
) -> OpponentActionFeatures:
    return OpponentActionFeatures(
        observed_at=observed_at,
        contains_postdeadline_action_label=contains_postdeadline_action_label,
        perceived_expected_points=expected_points,
        popularity_signal=popularity,
        recent_form_signal=recent_form,
        price_pressure_signal=price_pressure,
        relative_risk_signal=relative_risk,
        confidence=confidence,
    )


def _ordinary_transfer_plan(manager_id: str, *, hit_points: int = 0):
    source = manager_plan(manager_id, cumulative_points=100, counted_transfers=6)
    replacement = tuple(sorted((*[item for item in source.permanent_squad if item != "p11"], "p15")))
    return source.model_copy(
        update={
            "plan_id": f"plan-{manager_id}-ordinary-transfer-{hit_points}",
            "permanent_squad": replacement,
            "tactical_configuration": source.tactical_configuration.model_copy(
                update={
                    "starting_xi": tuple(
                        "p15" if item == "p10" else item
                        for item in source.tactical_configuration.starting_xi
                    ),
                    "bench_order": tuple(
                        "p10" if item == "p11" else item
                        for item in source.tactical_configuration.bench_order
                    ),
                }
            ),
            "transfer_hit_points": hit_points,
        }
    )


def candidate(
    action_id: str,
    *,
    manager_id: str = "rival",
    expected_points: float = 50.0,
    transfer_count: int = 0,
    chip: OpponentChipAction = OpponentChipAction.NONE,
    captain: str = "p12",
    vice: str = "p13",
    generated_at: datetime = CUTOFF - timedelta(minutes=10),
    feature_observed_at: datetime = CUTOFF - timedelta(minutes=30),
    postdeadline_label: bool = False,
    hit_points: int = 0,
) -> OpponentActionCandidate:
    if chip is OpponentChipAction.FREE_HIT:
        plan = manager_plan(
            manager_id,
            chip=ManagerChip.FREE_HIT,
            free_hit=True,
            captain=captain,
            vice=vice,
            cumulative_points=100,
            counted_transfers=5,
        )
    elif chip is OpponentChipAction.WILDCARD:
        plan = _ordinary_transfer_plan(manager_id)
        plan = plan.model_copy(
            update={
                "plan_id": f"plan-{manager_id}-wildcard",
                "counted_transfers": 5,
            }
        )
    elif transfer_count > 0:
        plan = _ordinary_transfer_plan(manager_id, hit_points=hit_points)
    else:
        manager_chip = {
            OpponentChipAction.NONE: ManagerChip.NONE,
            OpponentChipAction.TRIPLE_CAPTAIN: ManagerChip.TRIPLE_CAPTAIN,
            OpponentChipAction.BENCH_BOOST: ManagerChip.BENCH_BOOST,
        }[chip]
        plan = manager_plan(
            manager_id,
            chip=manager_chip,
            captain=captain,
            vice=vice,
            cumulative_points=100,
            counted_transfers=5,
        )
    plan = plan.model_copy(update={"plan_id": f"plan-{manager_id}-{action_id}"})
    return OpponentActionCandidate(
        action_id=action_id,
        manager_plan=plan,
        transfer_count=transfer_count,
        counted_transfer_delta=(
            0 if chip in {OpponentChipAction.FREE_HIT, OpponentChipAction.WILDCARD} else transfer_count
        ),
        chip_action=chip,
        generated_at=generated_at,
        features=action_features(
            expected_points,
            observed_at=feature_observed_at,
            contains_postdeadline_action_label=postdeadline_label,
        ),
    )


def baseline_candidates(manager_id: str = "rival") -> tuple[OpponentActionCandidate, ...]:
    return (
        candidate("no-transfer", manager_id=manager_id, expected_points=49.0),
        candidate(
            "one-transfer",
            manager_id=manager_id,
            expected_points=53.0,
            transfer_count=1,
        ),
        candidate(
            "triple-captain",
            manager_id=manager_id,
            expected_points=54.0,
            chip=OpponentChipAction.TRIPLE_CAPTAIN,
        ),
    )
