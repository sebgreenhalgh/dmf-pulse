"""Checkpoint-2.4 governed current FPL-points distribution acceptance."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.current import build_current_football_events
from dmf_pulse.fpl_points.current_acceptance import assess_current_projection
from dmf_pulse.fpl_points.current_points import (
    TARGET_MC_POLICY_SHA256,
    TARGET_PLAYER_POINTS_CAPABILITY_HASH,
    TARGET_RULESET_FILE_SHA256,
    TARGET_RULESET_HASH,
    CurrentFplPointsBundle,
    CurrentFplPointsRunConfig,
    build_current_fpl_points,
    build_current_fpl_points_run_config,
)
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import ProjectionMode, SimulationStatus
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.optimisation.current_initial_squad import optimise_current_initial_squad
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset, load_compiled_ruleset, write_compiled_ruleset
from dmf_pulse.rules.models import RuleCapability, RulesetStatus
from tests.unit.fpl_points.test_current_football_events import (
    _availability,
    _event_approval,
)

pytestmark = pytest.mark.unit

ROOT_SEED = 2026270001
SCENARIO_COUNT = 32


@pytest.fixture(scope="module")
def ruleset_path(repository_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compile the tracked target authority into a disposable canonical artifact."""

    source = repository_root / "config/rules/fpl-2026-27"
    output = tmp_path_factory.mktemp("gw1-target-rules") / "fpl-2026-27.json"
    compiled = compile_ruleset(source)
    capability = compile_capability_artifact(compiled, RuleCapability.PLAYER_POINTS)

    assert compiled.schema_version == "1.1"
    assert compiled.ruleset_id == "fpl-2026-27"
    assert compiled.season_code == "2026/2027"
    assert compiled.ruleset_version == "1.0.0"
    assert compiled.status is RulesetStatus.VERIFIED
    assert compiled.ruleset_hash == TARGET_RULESET_HASH
    assert capability.capability is RuleCapability.PLAYER_POINTS
    assert capability.capability_hash == TARGET_PLAYER_POINTS_CAPABILITY_HASH
    assert capability.source_backed
    assert capability.production_eligible
    assert not capability.blockers

    write_compiled_ruleset(compiled, output)
    reloaded = load_compiled_ruleset(output)
    assert reloaded == compiled
    assert hashlib.sha256(output.read_bytes()).hexdigest() == TARGET_RULESET_FILE_SHA256
    return output


@pytest.fixture(scope="module")
def mc_policy_path(repository_root: Path) -> Path:
    return repository_root / "config/models/fpl_points_simulation.yaml"


@pytest.fixture(scope="module")
def current_event_source(repository_root: Path, tmp_path_factory: pytest.TempPathFactory):
    availability = _availability(repository_root, tmp_path_factory.mktemp("gw1-current-points"))
    return build_current_football_events(availability, _event_approval(availability))


@pytest.fixture(scope="module")
def run_config(current_event_source, ruleset_path: Path, mc_policy_path: Path):
    return build_current_fpl_points_run_config(
        current_event_source,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
        root_seed=ROOT_SEED,
        scenario_count=SCENARIO_COUNT,
    )


@pytest.fixture(scope="module")
def projected(
    current_event_source,
    run_config: CurrentFplPointsRunConfig,
    ruleset_path: Path,
    mc_policy_path: Path,
) -> CurrentFplPointsBundle:
    return build_current_fpl_points(
        current_event_source,
        run_config,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
    )


def test_verified_target_rules_execute_only_explicit_preseason_mode(
    ruleset_path: Path,
) -> None:
    adapter = AcceptedRulesAdapter.from_paths(ruleset_path)

    adapter.assert_mode_allowed(ProjectionMode.PRESEASON_DECISION_SUPPORT)
    assert adapter.identity.status == "VERIFIED"
    assert adapter.identity.ruleset_hash == TARGET_RULESET_HASH
    assert adapter.identity.human_approval_recorded is False
    with pytest.raises(FplPointsError, match="ACTIVE ruleset"):
        adapter.assert_mode_allowed(ProjectionMode.PRODUCTION)


def test_current_stage9_builds_private_player_distribution_table_without_xp_formula(
    current_event_source,
    run_config: CurrentFplPointsRunConfig,
    projected: CurrentFplPointsBundle,
) -> None:
    summary = projected.safe_summary()

    assert projected.projection_mode is ProjectionMode.PRESEASON_DECISION_SUPPORT
    assert projected.production_status == "NON_PRODUCTION"
    assert projected.handcrafted_xp is False
    assert projected.source_event_semantic_sha256 == current_event_source.semantic_sha256
    assert projected.run_config == run_config
    assert len(projected.fixture_projections) == 1
    assert len(projected.player_table) == 44
    assert len(projected.gameweek_projection.scenario_set.scenarios) == SCENARIO_COUNT
    assert all(
        row.projection.status is SimulationStatus.SUCCESS
        and row.projection.projection_mode is ProjectionMode.PRESEASON_DECISION_SUPPORT
        and row.projection.ruleset.status == "VERIFIED"
        and not row.projection.ruleset.human_approval_recorded
        and row.projection.simulation_request.root_seed == ROOT_SEED
        for row in projected.fixture_projections
    )
    assert all(
        row.player_name.startswith("P")
        and row.team_name
        and row.current_price_tenths > 0
        and row.probability_appearance.count(".") == 1
        and row.probability_start.count(".") == 1
        and row.expected_minutes.count(".") == 1
        and set(row.selected_percentiles)
        == {"p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"}
        and abs(sum(row.points_pmf.values()) - 1.0) < 1e-10
        and row.provenance.ruleset_hash == TARGET_RULESET_HASH
        and row.provenance.player_points_capability_hash == TARGET_PLAYER_POINTS_CAPABILITY_HASH
        and row.provenance.mc_policy_sha256 == TARGET_MC_POLICY_SHA256
        for row in projected.player_table
    )
    assert summary.status == "PROJECTED_WITH_MATERIAL_LIMITATIONS"
    assert summary.ruleset_status == "VERIFIED"
    assert summary.human_activation_recorded is False
    assert summary.monte_carlo_stopping_result == "CONTINUE"
    assert "ESS_BELOW_THRESHOLD" in summary.monte_carlo_stopping_reasons
    assert summary.next_checkpoint == "2.5_PROJECTION_ACCEPTANCE"


def test_shared_root_seed_and_outcome_draw_identity_are_preserved(
    projected: CurrentFplPointsBundle,
) -> None:
    fixture_results = tuple(row.projection for row in projected.fixture_projections)
    expected_draws = {scenario.outcome_draw_id for scenario in fixture_results[0].scenarios}

    assert all(
        {scenario.outcome_draw_id for scenario in result.scenarios} == expected_draws
        for result in fixture_results
    )
    assert {
        scenario.outcome_draw_id
        for scenario in projected.gameweek_projection.scenario_set.scenarios
    } == expected_draws
    assert all(
        result.simulation_request.root_seed == projected.run_config.root_seed
        for result in fixture_results
    )


def test_projection_acceptance_reconciles_official_rows_and_retains_mc_blocker(
    current_event_source,
    projected: CurrentFplPointsBundle,
    ruleset_path: Path,
) -> None:
    report = assess_current_projection(current_event_source, projected)
    rendered = report.model_dump_json()

    assert report.status == "BLOCKED"
    assert report.accepted_for_initial_squad is False
    assert report.blocker_codes == ("UPSTREAM_MONTE_CARLO_CONTINUE",)
    assert report.player_count == 44
    assert report.fixture_count == 1
    assert "STAGE7_CURRENT_ROSTER_COLD_START" in report.warnings
    assert report.handcrafted_xp is False
    assert "P1001" not in rendered
    assert "current_price" not in rendered

    compiled = load_compiled_ruleset(ruleset_path)
    capability = compile_capability_artifact(compiled, RuleCapability.GW1_INITIAL_SQUAD)
    decision = optimise_current_initial_squad(current_event_source, projected, compiled, capability)
    assert decision.status == "BLOCKED"
    assert decision.blocker_codes == ("UPSTREAM_MONTE_CARLO_CONTINUE",)
    assert not decision.portfolios
    assert decision.persistence_performed is False
    assert decision.automated_fpl_account_action is False


def test_run_configuration_is_deterministic_and_exactly_source_bound(
    current_event_source,
    run_config: CurrentFplPointsRunConfig,
    ruleset_path: Path,
    mc_policy_path: Path,
) -> None:
    repeated = build_current_fpl_points_run_config(
        current_event_source,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
        root_seed=ROOT_SEED,
        scenario_count=SCENARIO_COUNT,
    )
    assert repeated == run_config

    hostile = run_config.model_copy(update={"source_event_semantic_sha256": "f" * 64})
    with pytest.raises(IngestionError, match="not bound"):
        build_current_fpl_points(
            current_event_source,
            hostile,
            ruleset_path=ruleset_path,
            mc_policy_path=mc_policy_path,
        )


def test_rules_and_mc_policy_drift_fail_closed(
    current_event_source,
    repository_root: Path,
    tmp_path: Path,
    ruleset_path: Path,
    mc_policy_path: Path,
) -> None:
    missing_rules = tmp_path / "missing-rules.json"
    with pytest.raises(IngestionError, match="ruleset artifact is unavailable"):
        build_current_fpl_points_run_config(
            current_event_source,
            ruleset_path=missing_rules,
            mc_policy_path=mc_policy_path,
            root_seed=ROOT_SEED,
            scenario_count=SCENARIO_COUNT,
        )

    drifted_source = tmp_path / "drifted-source"
    shutil.copytree(repository_root / "config/rules/fpl-2026-27", drifted_source)
    for filename in ("season_manifest.yaml", "target_2026_27_claims.yaml"):
        path = drifted_source / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace('"1.0.0"', '"1.0.1"'),
            encoding="utf-8",
        )
    older_rules = tmp_path / "drifted-rules.json"
    write_compiled_ruleset(compile_ruleset(drifted_source), older_rules)
    with pytest.raises(IngestionError, match="differs from the accepted revision"):
        build_current_fpl_points_run_config(
            current_event_source,
            ruleset_path=older_rules,
            mc_policy_path=mc_policy_path,
            root_seed=ROOT_SEED,
            scenario_count=SCENARIO_COUNT,
        )

    invalid_policy = tmp_path / "invalid-policy.yaml"
    invalid_policy.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(IngestionError, match="unavailable or invalid"):
        build_current_fpl_points_run_config(
            current_event_source,
            ruleset_path=ruleset_path,
            mc_policy_path=invalid_policy,
            root_seed=ROOT_SEED,
            scenario_count=SCENARIO_COUNT,
        )

    drifted_policy = tmp_path / "drifted-policy.yaml"
    drifted_policy.write_bytes(mc_policy_path.read_bytes() + b"\n")
    with pytest.raises(IngestionError, match="differs from the accepted revision"):
        build_current_fpl_points_run_config(
            current_event_source,
            ruleset_path=ruleset_path,
            mc_policy_path=drifted_policy,
            root_seed=ROOT_SEED,
            scenario_count=SCENARIO_COUNT,
        )


def test_preseason_mode_cannot_be_relabelled_as_production(
    run_config: CurrentFplPointsRunConfig,
) -> None:
    payload = run_config.model_dump(mode="python")
    payload["projection_mode"] = ProjectionMode.PRODUCTION
    with pytest.raises(ValidationError):
        CurrentFplPointsRunConfig.model_validate(payload)

    payload = run_config.model_dump(mode="python")
    payload["config_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="configuration hash"):
        CurrentFplPointsRunConfig.model_validate(payload)


def test_bundle_and_private_rows_reject_serialized_tampering(
    projected: CurrentFplPointsBundle,
) -> None:
    assert CurrentFplPointsBundle.model_validate_json(projected.model_dump_json()) == projected

    payload = json.loads(projected.model_dump_json())
    payload["player_table"][0]["mean_expected_fpl_points"] += 1.0
    with pytest.raises(ValidationError):
        CurrentFplPointsBundle.model_validate_json(json.dumps(payload))

    payload = json.loads(projected.model_dump_json())
    payload["semantic_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="bundle lineage"):
        CurrentFplPointsBundle.model_validate_json(json.dumps(payload))


def test_safe_summary_does_not_disclose_player_names_prices_or_distributions(
    projected: CurrentFplPointsBundle,
) -> None:
    rendered = projected.safe_summary().model_dump_json()

    assert "P1001" not in rendered
    assert "current_price" not in rendered
    assert "points_pmf" not in rendered
    assert "decimal_price" not in rendered
    assert "bookmaker" not in rendered.lower()
