"""Focused coverage regressions for OPT-010's guarded public paths."""

from __future__ import annotations

from copy import deepcopy

import pytest

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.candidate_pool import enumerate_squads
from dmf_pulse.optimisation.errors import InfeasibleError
from dmf_pulse.optimisation.models import (
    CandidatePoolSnapshot,
    CandidateSquad,
    OneGameweekOptimisationRequest,
    OneGameweekOptimiserPolicy,
    SearchScope,
)
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import players, request, synthetic_ruleset


def _policy() -> OneGameweekOptimiserPolicy:
    return OneGameweekOptimiserPolicy(
        max_squad_candidates=10,
        max_tactical_configurations=1_000,
        max_scenario_score_operations=1_000,
        max_returned_ties=10,
    )


def _constructed_request(
    base: OneGameweekOptimisationRequest, **updates: object
) -> OneGameweekOptimisationRequest:
    return OneGameweekOptimisationRequest.model_construct(**{**base.model_dump(), **updates})


def test_candidate_preflight_rejects_an_illegal_position_quota() -> None:
    base = request()
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    assert base.fixed_squad is not None
    squad = CandidateSquad.model_construct(player_ids=("p02", *base.fixed_squad.player_ids[1:]))

    with pytest.raises(InfeasibleError, match="position quotas"):
        enumerate_squads(base.model_copy(update={"fixed_squad": squad}), view, _policy())


def test_candidate_preflight_accepts_a_rules_view_without_a_club_cap() -> None:
    base = request()
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    unlimited = view.model_copy(update={"max_players_per_club": None})

    squads, upper = enumerate_squads(base, unlimited, _policy())

    assert upper == 1
    assert tuple(squads) == (base.fixed_squad,)


def test_candidate_preflight_rejects_a_compiled_club_cap_breach() -> None:
    base = request()
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    same_club_pool = CandidatePoolSnapshot(
        information_cutoff_utc=base.candidate_pool.information_cutoff_utc,
        candidates=tuple(player.model_copy(update={"club_id": "one-club"}) for player in players()),
    )

    with pytest.raises(InfeasibleError, match="club cap"):
        enumerate_squads(
            base.model_copy(update={"candidate_pool": same_club_pool}), view, _policy()
        )


def test_bounded_pool_requires_complete_selection_costs() -> None:
    bounded = request(scope=SearchScope.BOUNDED_PLAYER_POOL)
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)

    squads, upper = enumerate_squads(bounded, view, _policy())

    assert upper == 1
    assert tuple(squads) == ()


def test_fixed_scope_requires_a_fixed_squad() -> None:
    base = request()
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)

    with pytest.raises(InfeasibleError, match="requires one supplied fixed squad"):
        enumerate_squads(_constructed_request(base, fixed_squad=None), view, _policy())


def test_provided_scope_rejects_duplicate_unvalidated_squads() -> None:
    base = request(scope=SearchScope.PROVIDED_SQUADS)
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    assert base.provided_squads
    duplicate = _constructed_request(
        base, provided_squads=(base.provided_squads[0], base.provided_squads[0])
    )

    with pytest.raises(InfeasibleError, match="must be unique"):
        enumerate_squads(duplicate, view, _policy())


def test_provided_scope_allows_an_empty_unvalidated_collection() -> None:
    base = request(scope=SearchScope.PROVIDED_SQUADS)
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)

    squads, upper = enumerate_squads(
        _constructed_request(base, provided_squads=()), view, _policy()
    )

    assert upper == 0
    assert tuple(squads) == ()


def test_rules_view_rejects_an_invalid_controlled_autosub_literal() -> None:
    compiled = synthetic_ruleset()
    rules = deepcopy(compiled.rules)
    rules["lineup"]["automatic_substitutions"]["evaluation_scope"] = "BEFORE_FIXTURES"
    invalid = compiled.model_copy(update={"rules": rules})

    with pytest.raises(RulesValidationError, match="controlled value"):
        build_one_gameweek_rules_view(invalid, projection_mode=ProjectionMode.TEST)
