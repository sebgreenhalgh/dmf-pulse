from dmf_pulse.optimisation.service import optimise_one_gameweek
from tests.support.optimisation_factories import projection, request, synthetic_ruleset


def test_optimisation_lineage_binds_stage9_and_rules() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(request(), projection(rules.ruleset_hash), rules)
    assert result.lineage.ruleset_hash == rules.ruleset_hash
    assert result.lineage.gameweek_artifact_sha256
