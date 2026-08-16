from dmf_pulse.optimisation.models import OneGameweekOptimiserPolicy


def test_packaged_caps_are_frozen() -> None:
    policy = OneGameweekOptimiserPolicy(
        max_squad_candidates=12,
        max_tactical_configurations=5_000_000,
        max_scenario_score_operations=20_000_000,
        max_returned_ties=16,
    )
    assert policy.objective_tolerance is None
