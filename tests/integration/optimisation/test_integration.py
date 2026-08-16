from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, semantic_sha256, sha256_bytes
from dmf_pulse.optimisation.service import optimise_one_gameweek
from tests.support.optimisation_factories import projection, request, synthetic_ruleset


def test_optimisation_lineage_binds_stage9_and_rules() -> None:
    rules = synthetic_ruleset()
    stage9 = projection(rules.ruleset_hash)
    result = optimise_one_gameweek(request(), stage9, rules)
    assert result.lineage.ruleset_hash == rules.ruleset_hash
    assert result.lineage.stage9_result_sha256 == stage9.result_sha256
    assert result.lineage.stage9_artifact_sha256 == sha256_bytes(canonical_json_bytes(stage9))
    assert result.lineage.stage9_artifact_sha256 != result.lineage.stage9_result_sha256
    assert result.lineage.stage9_scenario_set_sha256 == semantic_sha256(stage9.scenario_set)
    assert result.lineage.stage9_joint_matrix_sha256 == semantic_sha256(stage9.joint_matrix)
