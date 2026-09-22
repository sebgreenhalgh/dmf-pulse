"""Locked synthetic 001P case definitions; never fitted model policy or live evidence."""

from dataclasses import dataclass, replace
from decimal import Decimal

from dmf_pulse.private_v1.models import seal_candidate_action_policy, seal_execution_input
from dmf_pulse.private_v1.rolling_models import seal_rolling_execution_input


@dataclass(frozen=True)
class Case:
    name: str
    source_variant: int
    seed: int
    screen: bool
    classification: str
    utility_delta: Decimal
    moved_rows: int


# Expectations were observed before this acceptance table was written. Ordinary
# tests do not regenerate it. These deliberately small one-draw cases establish
# control/decision behavior, not calibrated live xP or prospective model value.
CASES = (
    Case(
        "A_ROBUST", 2, 4, False, "PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST", Decimal(-1), 23
    ),
    Case("B_ROOT", 0, 1, False, "TEAM_STRENGTH_ROOT_ACTION_MATERIAL", Decimal(-5), 68),
    Case(
        "C_CONTINUATION", 0, 3, False, "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE", Decimal(21), 55
    ),
    Case("D_TACTICS", 0, 2, False, "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE", Decimal(52), 126),
    Case("E_SCREEN", 0, 2, True, "CANDIDATE_SCREEN_CONFOUNDED", Decimal(50), 126),
)


def case_prepared(prepared, case: Case):
    """Vary only shared synthetic controls before freezing either world."""
    execution = prepared.rolling_execution
    current = execution.current_execution
    updates = {"root_seed": case.seed}
    if case.screen:
        owned = {row.official_fpl_element_id for row in current.ownership.members}
        incoming = tuple(
            sorted(
                row.provider_element_id
                for row in current.current_state.fpl_input.players
                if row.position.value == "GK" and row.provider_element_id not in owned
            )
        )
        policy = current.candidate_action_policy
        updates["candidate_action_policy"] = seal_candidate_action_policy(
            type(policy).model_construct(
                **(
                    dict(policy)
                    | {
                        "allowed_transfer_in_element_ids": incoming,
                        "rationale": "PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1: synthetic complete goalkeeper candidate universe",
                    }
                )
            )
        )
    current = seal_execution_input(type(current).model_construct(**(dict(current) | updates)))
    execution = seal_rolling_execution_input(
        type(execution).model_construct(**(dict(execution) | {"current_execution": current}))
    )
    return replace(prepared, rolling_execution=execution)


def assert_case(case: Case, comparison):
    result = comparison.comparison
    assert result.classification == case.classification
    assert result.utility_delta == case.utility_delta
    assert comparison.movement.material_player_gameweek_count == case.moved_rows
    assert comparison.worlds[0].controls == comparison.worlds[1].controls
    assert comparison.movement.player_count == 120
    assert comparison.movement.player_gameweek_count == 360
    assert any(row.baseline_prior_sha256 != row.shadow_prior_sha256 for row in comparison.fixtures)
    left, right = (world.signature for world in comparison.worlds)
    assert all(world.canonical_legal_actions > 0 for world in comparison.worlds)
    if case.name == "A_ROBUST":
        assert left.action_sha256s == right.action_sha256s
        assert left.tactical_selection_sha256s == right.tactical_selection_sha256s
        assert not any(
            (
                result.root_action_changed,
                result.captain_changed,
                result.starting_xi_changed,
                result.continuation_changed,
            )
        )
    elif case.name == "B_ROOT":
        assert (
            result.root_action_changed
            and result.decision_material
            and result.candidate_screen_equal
        )
        assert not left.by_gameweek[0].transfers and right.by_gameweek[0].transfer_count == 1
    elif case.name == "C_CONTINUATION":
        assert not result.root_action_changed and result.continuation_changed
        assert not left.by_gameweek[1].transfers and left.by_gameweek[2].transfer_count == 1
        assert right.by_gameweek[1].transfer_count == 1 and not right.by_gameweek[2].transfers
    elif case.name == "D_TACTICS":
        assert (
            not result.root_action_changed and result.captain_changed and result.starting_xi_changed
        )
    else:
        assert result.root_action_changed and not result.candidate_screen_equal
