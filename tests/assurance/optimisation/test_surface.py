from fractions import Fraction
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, semantic_sha256
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.artifacts import load_canonical_json, persist_result
from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario
from dmf_pulse.optimisation.candidate_pool import (
    enumerate_squads,
    snapshot_hash,
)
from dmf_pulse.optimisation.errors import InfeasibleError, OptimisationError, ResourceLimitError
from dmf_pulse.optimisation.legality import (
    validate_squad_legality,
    validate_tactical_configuration,
)
from dmf_pulse.optimisation.models import (
    CandidatePoolSnapshot,
    CandidateSquad,
    LegalityReport,
    OneGameweekOptimisationResult,
    OneGameweekOptimiserPolicy,
    OptimalityGuarantee,
    OptimisationLineage,
    OptimisationStatus,
    SearchScope,
    SolverStatus,
    TacticalConfiguration,
)
from dmf_pulse.optimisation.policy import load_policy
from dmf_pulse.optimisation.tactics import (
    _quantile,
    enumerate_tactical_configurations,
    evaluate_tactical_configuration,
    tactical_configuration_upper_bound,
)
from dmf_pulse.optimisation.validation import validate_plan_against_request
from dmf_pulse.rules.capabilities import load_capability_artifact
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import RuleCapability, RulesetStatus
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import (
    players,
    projection,
    request,
    scenario_set,
    synthetic_ruleset,
)


def _policy() -> OneGameweekOptimiserPolicy:
    return OneGameweekOptimiserPolicy(
        max_squad_candidates=12,
        max_tactical_configurations=5_000_000,
        max_scenario_score_operations=20_000_000,
        max_returned_ties=16,
    )


def test_artifacts_policy_and_candidate_snapshot(tmp_path: Path) -> None:
    req = request()
    assert snapshot_hash(req.candidate_pool)
    path = tmp_path / "squad.json"
    path.write_bytes(canonical_json_bytes(req.fixed_squad))
    loaded = load_canonical_json(path, CandidateSquad)
    assert loaded == req.fixed_squad
    persisted = persist_result(req.fixed_squad, artifact_root=tmp_path, gameweek_id="GW1")
    assert persisted.exists()
    persist_result(req.fixed_squad, artifact_root=tmp_path, gameweek_id="GW1")
    persisted.write_bytes(b"collision")
    with pytest.raises(OptimisationError):
        persist_result(req.fixed_squad, artifact_root=tmp_path, gameweek_id="GW1")
    persisted.write_bytes(canonical_json_bytes(req.fixed_squad))
    persisted.with_suffix(".sha256").write_text("bad  bad.json\n", encoding="ascii")
    with pytest.raises(OptimisationError):
        persist_result(req.fixed_squad, artifact_root=tmp_path, gameweek_id="GW1")
    assert load_policy().max_returned_ties == 16
    path.write_bytes(b"not-json\n")
    with pytest.raises(OptimisationError):
        load_canonical_json(path, CandidateSquad)
    path.write_text('{"player_ids":["p00"]}\n', encoding="utf-8")
    with pytest.raises(OptimisationError):
        load_canonical_json(path, CandidateSquad)


def test_candidate_preflight_bounded_and_resource_failures() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    priced = CandidatePoolSnapshot(
        information_cutoff_utc="2026-08-16T00:00:00Z",
        candidates=tuple(
            player.model_copy(update={"initial_selection_cost_tenths": 1}) for player in players()
        ),
    )
    bounded = request(scope=SearchScope.BOUNDED_PLAYER_POOL).model_copy(
        update={"candidate_pool": priced}
    )
    squads, upper = enumerate_squads(bounded, view, _policy())
    assert upper == 1
    assert next(squads).initial_selection_cost_tenths == 15
    with pytest.raises(ResourceLimitError):
        enumerate_squads(request(), view, _policy().model_copy(update={"max_squad_candidates": 0}))
    with pytest.raises(ResourceLimitError):
        enumerate_tactical_configurations(
            CandidateSquad(player_ids=tuple(player.player_id for player in players())),
            {player.player_id: player for player in players()},
            view,
            _policy().model_copy(update={"max_tactical_configurations": 0}),
        )
    with pytest.raises(InfeasibleError):
        enumerate_squads(
            request().model_copy(update={"required_player_ids": ("not-in-pool",)}), view, _policy()
        )
    expensive = CandidatePoolSnapshot(
        information_cutoff_utc="2026-08-16T00:00:00Z",
        candidates=tuple(
            player.model_copy(update={"initial_selection_cost_tenths": 100}) for player in players()
        ),
    )
    generated, _ = enumerate_squads(
        bounded.model_copy(update={"candidate_pool": expensive}), view, _policy()
    )
    assert tuple(generated) == ()
    provided = request(scope=SearchScope.PROVIDED_SQUADS)
    with pytest.raises(InfeasibleError):
        enumerate_squads(
            provided.model_copy(
                update={"provided_squads": (CandidateSquad.model_construct(player_ids=("p00",)),)}
            ),
            view,
            _policy(),
        )
    with pytest.raises(InfeasibleError):
        enumerate_squads(
            provided.model_copy(
                update={
                    "provided_squads": (
                        CandidateSquad.model_construct(player_ids=("unknown",) * 15),
                    )
                }
            ),
            view,
            _policy(),
        )
    with pytest.raises(InfeasibleError):
        enumerate_squads(
            request().model_copy(update={"excluded_player_ids": ("p00",)}), view, _policy()
        )


def test_tactic_legality_autosub_and_plan_evaluation() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    player_map = {player.player_id: player for player in players()}
    squad = CandidateSquad(player_ids=tuple(player_map))
    tactics, upper = enumerate_tactical_configurations(squad, player_map, view, _policy())
    tactic = next(tactics)
    assert upper == 363_000
    assert validate_squad_legality(squad, player_map, view).legal
    assert validate_tactical_configuration(squad, tactic, player_map, view).legal
    scenario = scenario_set(rules.ruleset_hash).scenarios[0]
    score, _ = evaluate_scenario(scenario, tactic, player_map, view)
    assert score.manager_points == 0
    plan, objective = evaluate_tactical_configuration(squad, tactic, (scenario,), player_map, view)
    assert plan.legality_report.legal
    assert objective == 0
    assert tactical_configuration_upper_bound(squad, player_map, view) == 363_000
    values = {player: 0 for player in player_map}
    for player in tactic.outfield_bench_order:
        values[player] = 2
    values[tactic.bench_goalkeeper] = 2
    active_score, _ = evaluate_scenario(
        scenario_set(rules.ruleset_hash, values=(values,)).scenarios[0], tactic, player_map, view
    )
    assert active_score.autosub_events
    starter_def = next(
        player for player in tactic.starting_xi if player_map[player].position is PlayerPosition.DEF
    )
    bench_def = next(
        player
        for player in tactic.outfield_bench_order
        if player_map[player].position is PlayerPosition.DEF
    )
    event_values = {player: 1 for player in player_map}
    event_values[starter_def] = 0
    for bench in tactic.outfield_bench_order:
        event_values[bench] = 0
    event_values[bench_def] = 1
    outfield_score, _ = evaluate_scenario(
        scenario_set(rules.ruleset_hash, values=(event_values,)).scenarios[0],
        tactic,
        player_map,
        view,
    )
    assert any(event.position is PlayerPosition.DEF for event in outfield_score.autosub_events)
    all_appeared = {player: 1 for player in player_map}
    captain_score, _ = evaluate_scenario(
        scenario_set(rules.ruleset_hash, values=(all_appeared,)).scenarios[0],
        tactic,
        player_map,
        view,
    )
    assert captain_score.captain_resolution.multiplier_player == tactic.captain
    with pytest.raises(ValueError):
        evaluate_tactical_configuration(
            squad,
            TacticalConfiguration.model_construct(
                starting_xi=("p00",),
                bench_goalkeeper="p01",
                outfield_bench_order=(),
                captain="p00",
                vice_captain="p00",
            ),
            (scenario,),
            player_map,
            view,
        )


def test_fail_closed_upstream_and_rules_errors() -> None:
    rules = synthetic_ruleset()
    req = request()
    base = projection(rules.ruleset_hash)
    continued = base.model_copy(
        update={
            "monte_carlo": base.monte_carlo.model_copy(
                update={"stopping_result": "CONTINUE", "stopping_reasons": ("test",)}
            )
        }
    )
    continued = continued.model_copy(
        update={
            "result_sha256": semantic_sha256(
                {**continued.model_dump(mode="json"), "result_sha256": None}
            )
        }
    )
    from dmf_pulse.optimisation.service import optimise_one_gameweek

    assert (
        optimise_one_gameweek(req, continued, rules).error_code == "UPSTREAM_MONTE_CARLO_CONTINUE"
    )
    blocked = base.model_copy(
        update={
            "monte_carlo": base.monte_carlo.model_copy(
                update={"stopping_result": "BLOCKED", "stopping_reasons": ("test",)}
            )
        }
    )
    blocked = blocked.model_copy(
        update={
            "result_sha256": semantic_sha256(
                {**blocked.model_dump(mode="json"), "result_sha256": None}
            )
        }
    )
    assert optimise_one_gameweek(req, blocked, rules).error_code == "UPSTREAM_MONTE_CARLO_BLOCKED"
    assert (
        optimise_one_gameweek(
            req.model_copy(update={"request_sha256": "0" * 64}), base, rules
        ).error_code
        == "OPTIMISATION_INPUT_INVALID"
    )
    assert (
        optimise_one_gameweek(req.model_copy(update={"gameweek_id": "GW2"}), base, rules).error_code
        == "STAGE9_CONTRACT_MISMATCH"
    )
    assert (
        optimise_one_gameweek(
            req, base, rules.model_copy(update={"ruleset_hash": "1" * 64})
        ).error_code
        == "RULESET_IDENTITY_MISMATCH"
    )
    assert (
        optimise_one_gameweek(
            req, base, rules, policy=_policy().model_copy(update={"max_squad_candidates": 0})
        ).error_code
        == "ONE_GAMEWEEK_RESOURCE_LIMIT"
    )
    with pytest.raises(RulesValidationError):
        build_one_gameweek_rules_view(
            rules.model_copy(update={"rules": {}}), projection_mode=ProjectionMode.TEST
        )
    with pytest.raises(RulesValidationError):
        build_one_gameweek_rules_view(
            rules.model_copy(update={"status": "CAPTURED_UNVERIFIED"}),
            projection_mode=ProjectionMode.TEST,
        )
    with pytest.raises(RulesValidationError):
        build_one_gameweek_rules_view(
            rules.model_copy(update={"rules": {"positions": {"positions": {}}}}),
            projection_mode=ProjectionMode.TEST,
        )
    with pytest.raises(RulesValidationError):
        build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.PRODUCTION)


def test_plan_validator_and_canonical_request_hash() -> None:
    rules = synthetic_ruleset()
    req = request()
    result = __import__(
        "dmf_pulse.optimisation.service", fromlist=["optimise_one_gameweek"]
    ).optimise_one_gameweek(req, projection(rules.ruleset_hash), rules)
    assert result.recommended_plan is not None
    report = validate_plan_against_request(
        req, projection(rules.ruleset_hash), rules, result.recommended_plan
    )
    assert report.legal


def test_legality_reports_each_structural_issue() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    player_map = {player.player_id: player for player in players()}
    bad_squad = CandidateSquad.model_construct(player_ids=("unknown",))
    report = validate_squad_legality(bad_squad, player_map, view)
    assert {issue.code for issue in report.issues} >= {"SQUAD_SIZE", "UNKNOWN_PLAYER"}
    bad_tactic = TacticalConfiguration.model_construct(
        starting_xi=("p00",),
        bench_goalkeeper="p02",
        outfield_bench_order=(),
        captain="unknown",
        vice_captain="unknown",
    )
    tactic_report = validate_tactical_configuration(bad_squad, bad_tactic, player_map, view)
    assert {issue.code for issue in tactic_report.issues} >= {
        "TACTIC_SQUAD_MISMATCH",
        "XI_SIZE",
        "BENCH_SIZE",
        "BENCH_GK",
        "CAPTAIN_START",
        "CAPTAIN_DISTINCT",
    }
    duplicate_report = validate_squad_legality(
        CandidateSquad.model_construct(player_ids=("p00",) * 15), player_map, view
    )
    assert any(issue.code == "DUPLICATE_PLAYER" for issue in duplicate_report.issues)
    capped_players = {
        player_id: player.model_copy(update={"club_id": "same"})
        for player_id, player in player_map.items()
    }
    assert any(
        issue.code == "CLUB_CAP"
        for issue in validate_squad_legality(
            CandidateSquad(player_ids=tuple(player_map)), capped_players, view
        ).issues
    )


def test_legality_boundary_inputs_and_rule_capability_forgery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    player_map = {player.player_id: player for player in players()}
    squad = CandidateSquad(player_ids=tuple(player_map))
    stage9_report = validate_squad_legality(
        squad,
        player_map,
        view,
        stage9_player_ids=tuple(player_id for player_id in player_map if player_id != "p00"),
    )
    assert "STAGE9_PLAYER_UNIVERSE" in {issue.code for issue in stage9_report.issues}
    boundary_report = validate_squad_legality(
        squad,
        player_map,
        view,
        required_player_ids=("required-but-missing",),
        excluded_player_ids=("p00",),
    )
    assert {issue.code for issue in boundary_report.issues} >= {
        "REQUIRED_PLAYER_MISSING",
        "EXCLUDED_PLAYER_INCLUDED",
    }
    assert "BUDGET_INPUT_UNAVAILABLE" in {
        issue.code
        for issue in validate_squad_legality(squad, player_map, view, enforce_budget=True).issues
    }
    priced = {
        player_id: player.model_copy(update={"initial_selection_cost_tenths": 1})
        for player_id, player in player_map.items()
    }
    limited = view.model_copy(update={"initial_budget_tenths": 1})
    assert "BUDGET_CAP" in {
        issue.code
        for issue in validate_squad_legality(squad, priced, limited, enforce_budget=True).issues
    }
    tactic = next(enumerate_tactical_configurations(squad, player_map, view, _policy())[0])
    malformed = TacticalConfiguration.model_construct(
        starting_xi=(*tactic.starting_xi[1:], tactic.starting_xi[1]),
        bench_goalkeeper=tactic.bench_goalkeeper,
        outfield_bench_order=("p00", "outside", tactic.outfield_bench_order[-1]),
        captain=tactic.captain,
        vice_captain=tactic.vice_captain,
    )
    tactic_report = validate_tactical_configuration(squad, malformed, player_map, view)
    assert {issue.code for issue in tactic_report.issues} >= {
        "TACTIC_DUPLICATE_PLAYER",
        "BENCH_OUTSIDE_SQUAD",
        "STARTING_GK",
        "OUTFIELD_BENCH_GK",
    }
    active = rules.model_copy(update={"status": RulesetStatus.ACTIVE, "production_eligible": True})
    supplied = load_capability_artifact(
        Path("artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.player-points.json")
    ).model_copy(update={"capability": RuleCapability.FULL_SEASON, "source_backed": False})
    monkeypatch.setattr(
        "dmf_pulse.rules.one_gameweek.compile_capability_artifact",
        lambda *_args: supplied,
    )
    with pytest.raises(RulesValidationError, match="does not match"):
        build_one_gameweek_rules_view(
            active, projection_mode=ProjectionMode.PRODUCTION, capability=supplied
        )
    verified = supplied.model_copy(
        update={
            "source_backed": True,
            "production_eligible": True,
            "blockers": (),
        }
    )
    monkeypatch.setattr(
        "dmf_pulse.rules.one_gameweek.compile_capability_artifact",
        lambda *_args: verified,
    )
    production_view = build_one_gameweek_rules_view(
        active, projection_mode=ProjectionMode.PRODUCTION, capability=verified
    )
    assert production_view.capability == RuleCapability.FULL_SEASON.value
    with pytest.raises(ValueError, match="point-mass probabilities"):
        _quantile({}, Fraction(1, 2))


def test_rules_scalar_resolution_errors() -> None:
    import dmf_pulse.rules.one_gameweek as rules_module

    rules = synthetic_ruleset()
    unresolved = rules.model_copy(
        update={
            "rules": {
                "positions": {
                    "positions": {"GK": {"verification_status": "UNKNOWN", "value": None}}
                }
            }
        }
    )
    with pytest.raises(RulesValidationError):
        build_one_gameweek_rules_view(unresolved, projection_mode=ProjectionMode.TEST)
    wrong_position = rules.model_copy(update={"rules": {"positions": {"positions": {"GK": 1}}}})
    with pytest.raises(RulesValidationError):
        build_one_gameweek_rules_view(wrong_position, projection_mode=ProjectionMode.TEST)
    with pytest.raises(RulesValidationError):
        rules_module._plain({"verification_status": "UNKNOWN", "value": None}, "/test")
    with pytest.raises(RulesValidationError):
        rules_module._plain({"value": None, "verification_status": "VERIFIED"}, "/test")
    assert rules_module._plain({"value": 3, "verification_status": "VERIFIED"}, "/test") == 3
    with pytest.raises(RulesValidationError):
        rules_module._mapping({}, "missing")
    with pytest.raises(RulesValidationError):
        rules_module._mapping({"a": 1}, "a")
    with pytest.raises(RulesValidationError):
        rules_module._int(-1, "/test")
    with pytest.raises(RulesValidationError):
        rules_module._bool("true", "/test")


def test_autosubstitution_resolution_has_a_legal_event() -> None:
    from dmf_pulse.rules.one_gameweek import resolve_outfield_substitutions

    positions = {
        "a": PlayerPosition.DEF,
        "b": PlayerPosition.DEF,
        "c": PlayerPosition.MID,
        "d": PlayerPosition.MID,
    }
    result = resolve_outfield_substitutions(
        starting_outfield=("a", "c"),
        bench_outfield=("b", "d"),
        positions=positions,
        appeared={"b", "d"},
        lineup_min={
            PlayerPosition.GK: 0,
            PlayerPosition.DEF: 1,
            PlayerPosition.MID: 1,
            PlayerPosition.FWD: 0,
        },
        lineup_max={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 5,
            PlayerPosition.MID: 5,
            PlayerPosition.FWD: 3,
        },
    )
    assert len(result) == 2
    assert (
        len(
            resolve_outfield_substitutions(
                starting_outfield=("a",),
                bench_outfield=("b", "d"),
                positions=positions,
                appeared={"b", "d"},
                lineup_min={
                    PlayerPosition.GK: 0,
                    PlayerPosition.DEF: 0,
                    PlayerPosition.MID: 0,
                    PlayerPosition.FWD: 0,
                },
                lineup_max={
                    PlayerPosition.GK: 1,
                    PlayerPosition.DEF: 5,
                    PlayerPosition.MID: 5,
                    PlayerPosition.FWD: 3,
                },
            )
        )
        == 1
    )
    assert (
        resolve_outfield_substitutions(
            starting_outfield=("a",),
            bench_outfield=("b", "d"),
            positions=positions,
            appeared={"a", "b", "d"},
            lineup_min={
                PlayerPosition.GK: 0,
                PlayerPosition.DEF: 0,
                PlayerPosition.MID: 0,
                PlayerPosition.FWD: 0,
            },
            lineup_max={
                PlayerPosition.GK: 1,
                PlayerPosition.DEF: 5,
                PlayerPosition.MID: 5,
                PlayerPosition.FWD: 3,
            },
        )
        == ()
    )


def test_service_error_branches_are_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import dmf_pulse.optimisation.service as service
    from dmf_pulse.optimisation.errors import OptimisationError
    from dmf_pulse.optimisation.models import SolverStatus
    from dmf_pulse.optimisation.solver import SearchOutput

    rules = synthetic_ruleset()
    req = request()
    base = projection(rules.ruleset_hash)
    original_build = service.build_one_gameweek_rules_view
    bad_snapshot = req.candidate_pool.model_copy(update={"candidate_snapshot_sha256": "0" * 64})
    assert (
        service.optimise_one_gameweek(
            req.model_copy(update={"candidate_pool": bad_snapshot}), base, rules
        ).error_code
        == "OPTIMISATION_INPUT_INVALID"
    )
    production = req.model_copy(update={"projection_mode": ProjectionMode.PRODUCTION})
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    monkeypatch.setattr(service, "build_one_gameweek_rules_view", lambda *args, **kwargs: view)
    assert (
        service.optimise_one_gameweek(production, base, rules).error_code
        == "STAGE9_CUTOFF_LINEAGE_UNAVAILABLE"
    )
    monkeypatch.setattr(
        service,
        "solve",
        lambda *args, **kwargs: SearchOutput(plans=(), objective=None, status=SolverStatus()),
    )
    assert service.optimise_one_gameweek(req, base, rules).error_code == "ONE_GAMEWEEK_INFEASIBLE"
    monkeypatch.setattr(
        service,
        "solve",
        lambda *args, **kwargs: (_ for _ in ()).throw(OptimisationError("TEST_ERROR", "test")),
    )
    assert service.optimise_one_gameweek(req, base, rules).error_code == "TEST_ERROR"
    monkeypatch.setattr(service, "build_one_gameweek_rules_view", original_build)
    monkeypatch.setattr(
        service,
        "solve",
        lambda *args, **kwargs: SearchOutput(plans=(), objective=None, status=SolverStatus()),
    )
    assert (
        service.optimise_one_gameweek(req, base, rules.model_copy(update={"rules": {}})).error_code
        == "RULESET_VALUE_MISSING"
    )
    player_map = {player.player_id: player for player in players()}
    squad = CandidateSquad(player_ids=tuple(player_map))
    tactics, _ = enumerate_tactical_configurations(squad, player_map, view, _policy())
    plan, _ = evaluate_tactical_configuration(
        squad, next(tactics), (base.scenario_set.scenarios[0],), player_map, view
    )
    bad_plan = plan.model_copy(update={"legality_report": LegalityReport(legal=False, issues=())})
    monkeypatch.setattr(
        service,
        "solve",
        lambda *args, **kwargs: SearchOutput(
            plans=(bad_plan,), objective=None, status=SolverStatus()
        ),
    )
    assert (
        service.optimise_one_gameweek(req, base, rules).error_code
        == "OPTIMISER_EMITTED_ILLEGAL_PLAN"
    )


def test_public_model_validators_reject_noncanonical_shapes() -> None:
    pool = request().candidate_pool
    with pytest.raises(ValueError):
        CandidatePoolSnapshot(
            information_cutoff_utc=pool.information_cutoff_utc,
            candidates=tuple(reversed(pool.candidates)),
        )
    with pytest.raises(ValueError):
        CandidatePoolSnapshot(
            information_cutoff_utc=pool.information_cutoff_utc,
            candidates=(pool.candidates[0], pool.candidates[0]),
        )
    with pytest.raises(ValueError):
        CandidateSquad(player_ids=("p01", "p00"))
    with pytest.raises(ValueError):
        CandidateSquad(player_ids=("p00", "p00"))
    with pytest.raises(ValueError):
        TacticalConfiguration(
            starting_xi=("p00",),
            bench_goalkeeper="p01",
            outfield_bench_order=(),
            captain="p00",
            vice_captain="p00",
        )
    lineage = OptimisationLineage(
        request_sha256="0" * 64,
        candidate_snapshot_sha256="0" * 64,
        gameweek_artifact_sha256="0" * 64,
        ruleset_hash="0" * 64,
        capability_hash=None,
        input_sha256="0" * 64,
        plan_sha256=None,
        result_sha256=None,
    )
    with pytest.raises(ValueError):
        OneGameweekOptimisationResult(
            status=OptimisationStatus.SUCCESS,
            search_scope=SearchScope.FIXED_SQUAD,
            optimality_guarantee=OptimalityGuarantee.EXACT_FIXED_SQUAD,
            solver_status=SolverStatus(),
            lineage=lineage,
        )
