"""Semantic branch proofs for the remaining frozen Stage-7 mathematical core."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability import decimal_integrity as exact
from dmf_pulse.availability import lineup, minutes, pipeline, projection
from dmf_pulse.availability.models import HistoryRow

pytestmark = pytest.mark.unit


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def training(repository_root: Path) -> dict[str, object]:
    return _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")


@pytest.fixture(scope="module")
def history(repository_root: Path) -> dict[str, object]:
    return _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json")


@pytest.fixture(scope="module")
def policy(repository_root: Path) -> dict[str, object]:
    return _read(repository_root / "fixtures/availability/MIN-007G/minutes_baseline_policy.json")


@pytest.fixture(scope="module")
def minute_artifact(
    training: dict[str, object], policy: dict[str, object]
) -> minutes.MinutePriorArtifact:
    return minutes.fit_minute_priors(training, policy=policy)


def _candidates() -> list[dict[str, object]]:
    positions = ["GK", "GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 10
    return [
        {
            "player_id": str(uuid5(NAMESPACE_URL, f"min007hr4-{index}")),
            "player_key": f"hr4_{index}",
            "position": position,
            "start_weight": "0.500000",
            "bench_weight": "0.500000",
            "hard_ineligible": False,
        }
        for index, position in enumerate(positions)
    ]


@pytest.fixture(scope="module")
def lineup_result(policy: dict[str, object]) -> lineup.ProjectedLineupResult:
    result = lineup.sample_coherent_lineups(
        _candidates(),
        fixture_id=str(uuid5(NAMESPACE_URL, "min007hr4-fixture")),
        team_id=str(uuid5(NAMESPACE_URL, "min007hr4-team")),
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert isinstance(result, lineup.ProjectedLineupResult)
    return result


@pytest.fixture(scope="module")
def pipeline_fixture(
    repository_root: Path,
    training: dict[str, object],
    history: dict[str, object],
    policy: dict[str, object],
) -> tuple[pipeline.MinutesModelArtifact, projection.MinutesPredictionResult, dict[str, object]]:
    context = _read(repository_root / "fixtures/availability/MIN-007G/contexts/stable_xi.json")
    artifact = pipeline.fit_projection_artifact(training, policy=policy)
    result = pipeline.predict_minutes_baseline(history, artifact, context=context, policy=policy)
    assert result.status == "PROJECTED" and result.projection is not None
    return artifact, result, context


def _raises(message: str, function: object, *args: object, **kwargs: object) -> None:
    assert callable(function)
    with pytest.raises((ValueError, TypeError), match=message):
        function(*args, **kwargs)


def test_exact_decimal_empty_zero_nonfinite_and_order_boundaries() -> None:
    assert exact.exact_decimal_sum(()) == Decimal(0)
    assert exact.exact_decimal_sum((Decimal("0.00"),)) == Decimal(0)
    assert exact.exact_sum_equals_one(()) is False
    assert exact.exact_sum_leq_one(()) is True
    assert exact.exact_decimal_sum((Decimal("1E+3"), Decimal("-999.9"))) == Decimal("0.1")
    assert exact.exact_one_minus(Decimal("1.25")) == Decimal("-0.25")
    _raises("finite Decimal", exact.exact_decimal_sum, (Decimal("Infinity"),))
    _raises("finite Decimal", exact.exact_sum_equals_one, ("1",))


def test_minute_decimal_mapping_vector_and_prior_coercion_boundaries() -> None:
    assert minutes._decimal(Decimal("1.25"), label="value") == Decimal("1.25")
    for value in (True, 1.5):
        _raises("must not be a float", minutes._decimal, value, label="value")
    _raises("must be a decimal", minutes._decimal, object(), label="value")

    class Dumpable:
        def model_dump(self, *, mode: str) -> object:
            assert mode == "json"
            return ["not-a-mapping"]

    _raises("mapping or validated", minutes._mapping, Dumpable(), label="value")
    _raises("mapping or validated", minutes._mapping, object(), label="value")
    _raises("minute_priors must be a mapping", minutes._coerce_priors, [])
    _raises("positions are invalid", minutes._coerce_priors, {1: {}})
    _raises("role vectors are invalid", minutes._coerce_priors, {"GK": {"START": "bad"}})

    _raises("91 Decimal bins", minutes._correct_stored_pmf, (Decimal(1),), role="BENCH")
    bad = [Decimal(0)] * 91
    bad[1] = Decimal("NaN")
    _raises("finite non-negative", minutes._correct_stored_pmf, tuple(bad), role="BENCH")
    at_zero = [Decimal(0)] * 91
    at_zero[0] = Decimal(1)
    _raises("START minute zero", minutes._correct_stored_pmf, tuple(at_zero), role="START")
    with localcontext() as decimal_context:
        decimal_context.traps[InvalidOperation] = False
        _raises(
            "residual correction failed",
            minutes._public_vector,
            (Decimal("Infinity"), Decimal(0)),
        )


def test_minute_artifact_rejects_each_frozen_contract_violation(
    minute_artifact: minutes.MinutePriorArtifact,
) -> None:
    body = minute_artifact.model_dump(mode="python")
    cases = (
        ("artifact_sha256", "0" * 64, "identity"),
        ("policy_sha256", "0" * 64, "policy lineage"),
        ("training_dataset_sha256", "0" * 64, "training lineage"),
        ("training_example_count", 367, "training count"),
        ("probability_decimal_places", 11, "precision"),
        ("minute_prior_strength", "2.000000", "prior constants"),
    )
    for key, value, message in cases:
        changed = copy.deepcopy(body)
        changed[key] = value
        _raises(message, minutes.MinutePriorArtifact.model_validate, changed)

    changed = copy.deepcopy(body)
    changed["minute_priors"] = {"GK": changed["minute_priors"]["GK"]}
    _raises("positions are incomplete", minutes.MinutePriorArtifact.model_validate, changed)
    changed = copy.deepcopy(body)
    changed["minute_priors"]["GK"] = {"START": changed["minute_priors"]["GK"]["START"]}
    _raises("roles are incomplete", minutes.MinutePriorArtifact.model_validate, changed)
    changed = copy.deepcopy(body)
    changed["minute_priors"]["GK"]["BENCH"] = (Decimal(1),)
    _raises("vectors are invalid", minutes.MinutePriorArtifact.model_validate, changed)
    changed = copy.deepcopy(body)
    vector = list(changed["minute_priors"]["GK"]["BENCH"])
    vector[0] += Decimal("0.1")
    changed["minute_priors"]["GK"]["BENCH"] = tuple(vector)
    _raises("does not sum", minutes.MinutePriorArtifact.model_validate, changed)
    changed = copy.deepcopy(body)
    vector = list(changed["minute_priors"]["GK"]["START"])
    transfer = vector[1] / Decimal(2)
    vector[0], vector[1] = transfer, vector[1] - transfer
    changed["minute_priors"]["GK"]["START"] = tuple(vector)
    _raises("minute zero", minutes.MinutePriorArtifact.model_validate, changed)
    changed = copy.deepcopy(body)
    vector = list(changed["minute_priors"]["GK"]["BENCH"])
    vector[0], vector[1] = vector[1], vector[0]
    changed["minute_priors"]["GK"]["BENCH"] = tuple(vector)
    _raises("semantic identity", minutes.MinutePriorArtifact.model_validate, changed)
    assert minutes.MinutePriorArtifact.coerce_vectors(object()) is not None


def test_minute_history_validation_paths(
    training: dict[str, object], history: dict[str, object]
) -> None:
    rows = history["rows"]
    assert isinstance(rows, list) and rows
    source = copy.deepcopy(rows[0])
    _raises("rows sequence", minutes._history_rows_checked, {"rows": "bad"})
    direct = HistoryRow.model_validate(source)
    assert minutes._history_rows_checked({"rows": [direct]})[0].example_id == str(direct.example_id)

    mutations = (
        (lambda row: row.pop("team_key"), "missing a required field"),
        (lambda row: row.__setitem__("unknown", 1), "unknown fields"),
        (lambda row: row.__setitem__("evidence_type", "OTHER"), "evidence type"),
        (lambda row: row.__setitem__("position", "SWEEPER"), "position or role"),
        (lambda row: row.__setitem__("minutes_label", True), "minute or sequence"),
        (
            lambda row: (
                row.__setitem__("role_label", "START"),
                row.__setitem__("minutes_label", 0),
            ),
            "positive minutes",
        ),
        (
            lambda row: (row.__setitem__("role_label", "OUT"), row.__setitem__("minutes_label", 1)),
            "OUT requires zero",
        ),
        (lambda row: row.__setitem__("player_id", 7), "UUID string"),
        (lambda row: row.__setitem__("player_id", "not-a-uuid"), "UUID string"),
        (lambda row: row.__setitem__("team_key", ""), "team_key"),
        (lambda row: row.__setitem__("example_id", ""), "example_id"),
        (lambda row: row.__setitem__("feature_cutoff", "not-a-time"), "history row is invalid"),
    )
    for mutate, message in mutations:
        changed = copy.deepcopy(source)
        mutate(changed)
        _raises(message, minutes._history_rows_checked, {"rows": [changed]})
    _raises("rows must be mappings", minutes._history_rows_checked, {"rows": [object()]})
    duplicate = copy.deepcopy(source)
    second = copy.deepcopy(source)
    second["example_id"] = str(uuid5(NAMESPACE_URL, "different-example"))
    _raises(
        "duplicate player-fixture", minutes._history_rows_checked, {"rows": [duplicate, second]}
    )
    _raises("frozen MIN-007B", minutes._training_rows_checked, {"rows": []})
    _raises("frozen minutes policy", minutes._policy_checked, {})
    _raises("prediction context", minutes._context_checked, {})
    assert isinstance(training["rows"], list)


def test_minute_prediction_validation_and_preseason_weighting(
    minute_artifact: minutes.MinutePriorArtifact,
    history: dict[str, object],
    policy: dict[str, object],
) -> None:
    rows = history["rows"]
    assert isinstance(rows, list)
    source = next(row for row in rows if row["role_label"] == "START")
    context = {
        "as_of": "2026-09-01T12:00:00Z",
        "cutoff_sequence_index": 999,
        "manager_regime_id": source["manager_regime_id"],
        "team_id": source["team_id"],
        "team_key": source["team_key"],
    }
    for player_id, position, role, message in (
        (7, "MID", "START", "UUID string"),
        ("not-a-uuid", "MID", "START", "UUID string"),
        (source["player_id"], "SWEEPER", "START", "position"),
        (source["player_id"], "MID", "OUT", "START or BENCH"),
    ):
        _raises(
            message,
            minutes.predict_conditional_minutes,
            history,
            minute_artifact,
            context=context,
            player_id=player_id,
            position=position,
            role=role,
            policy=policy,
        )
    baseline = minutes.predict_conditional_minutes(
        history,
        minute_artifact,
        context=context,
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    preseason_history = copy.deepcopy(history)
    for row in preseason_history["rows"]:
        if row["player_id"] == source["player_id"] and row["role_label"] == "START":
            row["evidence_type"] = "PRESEASON"
            break
    preseason = minutes.predict_conditional_minutes(
        preseason_history,
        minute_artifact,
        context=context,
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    assert preseason.minute_pmf != baseline.minute_pmf
    invalid_prediction = baseline.model_dump(mode="python")
    invalid_prediction["player_id"] = "not-a-uuid"
    _raises("UUID string", minutes.MinuteConditionalPrediction.model_validate, invalid_prediction)
    invalid_prediction = baseline.model_dump(mode="python")
    invalid_prediction["matching_role_history_count"] = (
        invalid_prediction["eligible_history_count"] + 1
    )
    _raises(
        "matching history count",
        minutes.MinuteConditionalPrediction.model_validate,
        invalid_prediction,
    )
    assert baseline.model_copy() == baseline
    _raises(
        "matching history count",
        baseline.model_copy,
        update={"matching_role_history_count": baseline.eligible_history_count + 1},
    )
    _raises("schema validation", minutes._artifact_mapping, {"bad": "artifact"})
    _raises("mapping or validated", minutes._artifact_mapping, object())


def test_minute_supported_edge_paths_fail_closed(
    minute_artifact: minutes.MinutePriorArtifact,
    history: dict[str, object],
    policy: dict[str, object],
) -> None:
    unsupported = copy.deepcopy(history["rows"][0])
    unsupported["evidence_type"] = "OTHER"
    strict = HistoryRow.model_validate(unsupported)
    _raises("evidence type", minutes._history_rows_checked, {"rows": [strict]})
    reduced = copy.deepcopy(unsupported)
    reduced.pop("fixture_key")
    reduced.pop("player_key")
    reduced.pop("split")
    _raises("evidence type", minutes._history_rows_checked, {"rows": [reduced]})
    changed_policy = dict(policy)
    changed_policy["minute_prior_strength"] = "0.000000"
    _raises("frozen minutes policy", minutes._policy_checked, changed_policy)


def test_lineup_scalar_candidate_and_invalid_result_classification(
    policy: dict[str, object],
) -> None:
    assert (
        lineup._choose(
            (),
            fixture_id="fixture",
            seed_suffix="",
            scenario_index=0,
            phase="X",
            count=0,
            field="start_weight",
        )
        == ()
    )
    for value, message in (
        (True, "Decimal-compatible"),
        (object(), "not a Decimal"),
        ("NaN", "finite"),
    ):
        _raises(message, lineup._decimal, value, label="weight")
    _raises("UUID string", lineup._uuid_text, 1, label="id")
    _raises("UUID string", lineup._uuid_text, "bad", label="id")
    _raises("non-empty string", lineup._validate_text, "", label="fixture")

    candidates = _candidates()
    cases: list[tuple[object, str]] = [
        ("bad", "INVALID_CANDIDATES"),
        ([{**candidates[0], "extra": 1}], "INVALID_CANDIDATES"),
        ([{**candidates[0], "position": "SWEEPER"}], "INVALID_POSITION"),
        ([{**candidates[0], "player_key": ""}], "INVALID_CANDIDATES"),
        ([{**candidates[0], "hard_ineligible": 1}], "INVALID_CANDIDATES"),
        ([{**candidates[0], "start_weight": "0.8", "bench_weight": "0.8"}], "INVALID_ROLE_WEIGHTS"),
        ([{**candidates[0], "hard_ineligible": True}], "CONTRADICTORY_INELIGIBLE_WEIGHTS"),
    ]
    for value, code in cases:
        result = lineup.sample_coherent_lineups(
            value,
            fixture_id="fixture",
            team_id="team",
            seed_suffix="",
            bench_size=9,
            bench_goalkeeper_slots=1,
            policy=policy,
        )
        assert isinstance(result, lineup.InvalidLineupResult) and result.error_code == code
    duplicate_key = copy.deepcopy(candidates[:2])
    duplicate_key[1]["player_key"] = duplicate_key[0]["player_key"]
    assert (
        lineup.sample_coherent_lineups(
            duplicate_key,
            fixture_id="f",
            team_id="t",
            seed_suffix="",
            bench_size=0,
            bench_goalkeeper_slots=0,
            policy=policy,
        ).error_code
        == "DUPLICATE_PLAYER_KEY"
    )
    for kwargs, code in (
        ({"seed_suffix": 1}, "INVALID_SEED_SUFFIX"),
        ({"bench_size": True}, "INVALID_BENCH_CONFIGURATION"),
        ({"bench_goalkeeper_slots": 10}, "INVALID_BENCH_CONFIGURATION"),
    ):
        options = {"seed_suffix": "", "bench_size": 9, "bench_goalkeeper_slots": 1, **kwargs}
        result = lineup.sample_coherent_lineups(
            candidates, fixture_id="f", team_id="t", policy=policy, **options
        )
        assert isinstance(result, lineup.InvalidLineupResult) and result.error_code == code
    assert lineup.BlockedLineupResult(
        status="BLOCKED",
        error_code="INSUFFICIENT_ELIGIBLE_SQUAD",
        fixture_id="f",
        team_id="t",
        sample_count=256,
    ).semantic_sha256
    assert lineup.InvalidLineupResult(status="INVALID", error_code="X").semantic_sha256


def test_lineup_role_marginal_and_result_invariants(
    lineup_result: lineup.ProjectedLineupResult,
) -> None:
    marginal = lineup_result.role_marginals[0]
    for update, message in (
        ({"p_start": Decimal("-0.1")}, "finite and non-negative"),
        ({"p_start": Decimal(0), "p_bench": Decimal(0), "p_out": Decimal(0)}, "sum to one"),
        ({"player_key": ""}, "non-empty"),
    ):
        _raises(message, marginal.model_copy, update=update)
    assert lineup_result.semantic_sha256
    assert lineup_result.model_copy() == lineup_result

    cases = (
        ({"scenarios": lineup_result.scenarios[:-1]}, "wrong scenario count"),
        ({"bench_goalkeeper_slots": 10}, "exceed bench size"),
        ({"role_marginals": (*lineup_result.role_marginals, marginal)}, "duplicate player_id"),
        ({"role_marginals": ()}, "no roster marginals"),
        ({"sum_p_start": Decimal(10)}, "advertised marginal sums"),
    )
    for update, message in cases:
        _raises(message, lineup_result.model_copy, update=update)
    changed = list(lineup_result.role_marginals)
    changed[0] = changed[0].model_copy(
        update={
            "p_start": changed[0].p_start + Decimal("0.1"),
            "p_out": changed[0].p_out - Decimal("0.1"),
        }
    )
    _raises(
        "does not match scenario counts",
        lineup_result.model_copy,
        update={"role_marginals": tuple(changed)},
    )
    changed = list(lineup_result.role_marginals)
    changed[1] = changed[1].model_copy(update={"player_key": changed[0].player_key})
    _raises(
        "duplicate player_key", lineup_result.model_copy, update={"role_marginals": tuple(changed)}
    )
    scenarios = list(lineup_result.scenarios)
    scenarios[1] = scenarios[1].model_copy(update={"scenario_index": 0})
    _raises("indexes", lineup_result.model_copy, update={"scenarios": tuple(scenarios)})
    first = list(lineup_result.first_scenarios)
    first[0] = first[0].model_copy(update={"starters": first[0].starters[::-1]})
    _raises("diagnostics", lineup_result.model_copy, update={"first_scenarios": tuple(first)})


def test_lineup_scenario_integrity_failures(lineup_result: lineup.ProjectedLineupResult) -> None:
    base = lineup_result.scenarios[0]
    marginal_by_id = {row.player_id: row for row in lineup_result.role_marginals}

    def reject(update: Mapping[str, object], message: str) -> None:
        scenario = base.model_copy(update=update)
        counts = {player_id: {"START": 0, "BENCH": 0, "OUT": 0} for player_id in marginal_by_id}
        _raises(
            message,
            lineup._validate_projected_scenario,
            scenario,
            lineup_result,
            marginal_by_id,
            counts,
        )

    reject({"starters": base.starters[:-1]}, "eleven unique starters")
    reject({"bench": (*base.bench[:-1], base.bench[0])}, "bench size or uniqueness")
    reject({"starters": base.starters[::-1]}, "roster lists must be sorted")
    reject({"bench": tuple(sorted((*base.bench[:-1], base.starters[0])))}, "roles overlap")
    reject(
        {"starters": tuple(sorted((*base.starters[:-1], str(uuid5(NAMESPACE_URL, "unknown")))))},
        "unknown player",
    )
    gk = next(
        row.player_id
        for row in lineup_result.role_marginals
        if row.position == "GK"
        and row.player_id not in base.starters
        and row.player_id not in base.bench
    )
    outfield_start = next(
        player_id for player_id in base.starters if marginal_by_id[player_id].position != "GK"
    )
    reject(
        {"starters": tuple(sorted((set(base.starters) - {outfield_start}) | {gk}))},
        "one starting goalkeeper",
    )
    bench_gk = next(
        player_id for player_id in base.bench if marginal_by_id[player_id].position == "GK"
    )
    outfield_out = next(
        row.player_id
        for row in lineup_result.role_marginals
        if row.position != "GK"
        and row.player_id not in base.starters
        and row.player_id not in base.bench
    )
    reject(
        {"bench": tuple(sorted((set(base.bench) - {bench_gk}) | {outfield_out}))},
        "bench goalkeeper count",
    )
    member = base.members[0]
    members = list(base.members)
    members[0] = member.model_copy(update={"role": "OUT" if member.role != "OUT" else "START"})
    reject({"members": tuple(members)}, "role or position is incoherent")
    reject({"members": base.members[:-1]}, "each roster player exactly once")
    reject({"members": base.members[::-1]}, "sorted by player_id")
    members = list(base.members)
    bench_member = next(index for index, member in enumerate(members) if member.role == "BENCH")
    members[bench_member] = members[bench_member].model_copy(update={"role": "OUT"})
    reject({"members": tuple(members)}, "role or position is incoherent")
    reject({"scenario_sha256": "0" * 64}, "hash does not match")


def test_lineup_remaining_supported_input_boundaries(
    policy: dict[str, object], lineup_result: lineup.ProjectedLineupResult
) -> None:
    class Dumpable:
        def model_dump(self, *, mode: str) -> object:
            assert mode == "json"
            return {"ok": True}

    class BadDumpable:
        def model_dump(self, *, mode: str) -> object:
            return []

    assert lineup._mapping(Dumpable(), label="value") == {"ok": True}
    _raises("must be a mapping", lineup._mapping, BadDumpable(), label="value")
    _raises("must be a mapping", lineup._mapping, object(), label="value")
    _raises(
        "canonical UUID spelling",
        lineup._canonical_result_player_id,
        lineup_result.role_marginals[0].player_id.upper(),
        label="id",
    )
    _raises("UUID string", lineup._canonical_result_player_id, 1, label="id")
    _raises("UUID string", lineup._canonical_result_player_id, "bad", label="id")

    candidates = _candidates()
    candidates[0]["hard_ineligible"] = True
    candidates[0]["start_weight"] = "0"
    candidates[0]["bench_weight"] = "0"
    blocked = lineup.sample_coherent_lineups(
        candidates,
        fixture_id="f",
        team_id="t",
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert isinstance(blocked, lineup.ProjectedLineupResult)
    rows = lineup._candidate_rows(candidates)
    selected = lineup._choose(
        rows,
        fixture_id="f",
        seed_suffix="",
        scenario_index=0,
        phase="TEST",
        count=1,
        field="start_weight",
    )
    assert selected[0].hard_ineligible is False
    zero_weight = copy.deepcopy(_candidates())
    for row in zero_weight:
        row["start_weight"] = "0"
        row["bench_weight"] = "0"
    blocked = lineup.sample_coherent_lineups(
        zero_weight,
        fixture_id="f",
        team_id="t",
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert isinstance(blocked, lineup.BlockedLineupResult)
    changed_policy = dict(policy)
    changed_policy["lineup_sample_count"] = 1
    invalid = lineup.sample_coherent_lineups(
        _candidates(),
        fixture_id="f",
        team_id="t",
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=changed_policy,
    )
    assert isinstance(invalid, lineup.InvalidLineupResult)


def test_projection_scalar_and_player_validation(
    pipeline_fixture: tuple[object, projection.MinutesPredictionResult, dict[str, object]],
) -> None:
    _, result, _ = pipeline_fixture
    assert result.projection is not None
    player = result.projection.players[0]
    for value, message in (
        (True, "exact decimal"),
        (object(), "must be decimal"),
        ("NaN", "finite"),
    ):
        _raises(message, projection._decimal, value, label="value")
    _raises(r"in \[0,1\]", projection._probability, "2", label="value")

    class Dumpable:
        def model_dump(self, *, mode: str) -> object:
            assert mode == "python"
            return {"ok": True}

    class BadDumpable:
        def model_dump(self, *, mode: str) -> object:
            return []

    assert projection._mapping(Dumpable(), label="value") == {"ok": True}
    _raises("mapping or model", projection._mapping, BadDumpable(), label="value")
    _raises("mapping or model", projection._mapping, object(), label="value")
    assert projection.PlayerMinutesProjection.coerce_sequences(object()) is not None
    coerced = projection.PlayerMinutesProjection.coerce_sequences(
        {"minute_pmf": [], "confidence_reasons": []}
    )
    assert coerced == {"minute_pmf": (), "confidence_reasons": ()}
    assert player.model_copy() == player

    body = player.model_dump(mode="python")
    mutations = (
        ("player_id", "bad", "UUID"),
        ("minute_pmf", body["minute_pmf"][:-1], "91 bins"),
        ("minute_pmf", ("bad", *body["minute_pmf"][1:]), "12-decimal strings"),
        ("minute_pmf", ("0.000000000000",) * 91, "sum exactly"),
        ("p_start", "0.000000000000", "role probabilities"),
        ("p_appearance", "0.000000000000", "appearance probabilities"),
        ("p_60_plus", "0.000000000000", "p_60_plus"),
        ("expected_minutes", "0.000000", "expected_minutes"),
        ("confidence_reasons", ("BASELINE_MODEL_CAP_B", "BASELINE_MODEL_CAP_B"), "unique"),
        ("projection_sha256", "0" * 64, "does not match"),
    )
    for key, value, message in mutations:
        changed = copy.deepcopy(body)
        changed[key] = value
        _raises(message, projection.PlayerMinutesProjection.model_validate, changed)


def test_team_and_outer_projection_validation(
    pipeline_fixture: tuple[
        pipeline.MinutesModelArtifact, projection.MinutesPredictionResult, dict[str, object]
    ],
) -> None:
    _, result, _ = pipeline_fixture
    team = result.projection
    assert team is not None
    assert projection.TeamMinutesProjection.coerce_players(object()) is not None
    assert projection.TeamMinutesProjection.coerce_players({"players": []}) == {"players": ()}
    body = team.model_dump(mode="python")
    cases = (
        ("fixture_id", "bad", "fixture_id must be a UUID"),
        ("as_of", "bad", "RFC3339"),
        ("as_of", "2026-01-01T00:00:00", "timezone-aware UTC"),
        ("bench_goalkeeper_slots", 10, "exceed bench size"),
        ("players", (body["players"][0],) * 11, "unique canonical IDs"),
        ("players", tuple(reversed(body["players"])), "sorted"),
        ("sum_p_start", "0.000000000000", "does not match player rows"),
        ("result_sha256", "0" * 64, "does not match public fields"),
    )
    for key, value, message in cases:
        changed = copy.deepcopy(body)
        changed[key] = value
        _raises(message, projection.TeamMinutesProjection.model_validate, changed)

    outer = result.model_dump(mode="python")
    for changes, message in (
        ({"fixture_id": "bad"}, "identifiers/timestamp"),
        ({"as_of": "2026-01-01T00:00:00"}, "as_of must be UTC"),
        ({"status": "PROJECTED", "projection": None}, "require a projection"),
        ({"status": "BLOCKED", "projection": team, "error_code": "X"}, "error and no projection"),
        ({"fixture_id": str(uuid5(NAMESPACE_URL, "other"))}, "outer prediction identity"),
    ):
        changed = copy.deepcopy(outer)
        changed.update(changes)
        _raises(message, projection.MinutesPredictionResult.model_validate, changed)
    with localcontext() as decimal_context:
        decimal_context.traps[InvalidOperation] = False
        _raises("rounded PMF", projection._rounded_pmf, (Decimal("Infinity"), Decimal(0)))
    _raises(
        "91 bins",
        projection.compose_player_minutes_projection,
        {
            "player_id": str(uuid5(NAMESPACE_URL, "p")),
            "position": "MID",
            "p_start": "1",
            "p_bench": "0",
            "p_out": "0",
        },
        {"minute_pmf": (Decimal(1),)},
        {"minute_pmf": (Decimal(1),)},
        confidence_grade="B",
        confidence_reasons=("BASELINE_MODEL_CAP_B",),
    )


def test_pipeline_models_helpers_and_oracle_fail_closed(
    pipeline_fixture: tuple[
        pipeline.MinutesModelArtifact, projection.MinutesPredictionResult, dict[str, object]
    ],
) -> None:
    artifact, result, context = pipeline_fixture
    assert pipeline.MinutesModelArtifact.coerce_vectors(object()) is not None
    assert pipeline.MinutesModelArtifact.coerce_vectors({"minute_priors": []}) == {
        "minute_priors": []
    }
    assert artifact.model_copy() == artifact
    assert (
        artifact.model_copy(update={"training_fixture_count": artifact.training_fixture_count})
        == artifact
    )
    body = artifact.model_dump(mode="python")
    for key, value, message in (("artifact_sha256", "0" * 64, "identity"),):
        changed = copy.deepcopy(body)
        changed[key] = value
        _raises(message, pipeline.MinutesModelArtifact.model_validate, changed)
    changed = copy.deepcopy(body)
    changed["config"]["history_window"] = 11
    _raises("hash is inconsistent", pipeline.MinutesModelArtifact.model_validate, changed)

    evaluation = _read(Path("fixtures/availability/MIN-007G/evaluation.json"))
    for key, value, message in (
        ("evaluation_sha256", "0" * 64, "evaluation identity"),
        ("role_log_loss", "0.000000", "evaluation hash"),
    ):
        changed = copy.deepcopy(evaluation)
        changed[key] = value
        _raises(message, pipeline.MinutesModelEvaluation.model_validate, changed)

    class Dumpable:
        def model_dump(self, *, mode: str) -> object:
            return {"mode": mode}

    class BadDumpable:
        def model_dump(self, *, mode: str) -> object:
            return []

    assert pipeline._mapping(Dumpable(), label="value") == {"mode": "python"}
    assert pipeline._mapping({"value": 1}, label="value") == {"value": 1}
    _raises("mapping or model", pipeline._mapping, BadDumpable(), label="value")
    _raises("mapping or model", pipeline._mapping, object(), label="value")
    assert pipeline._model_dump(Dumpable(), mode="json") == {"mode": "json"}
    assert pipeline._model_dump({"value": 1}) == {"value": 1}
    _raises("Pydantic model", pipeline._model_dump, BadDumpable())
    _raises("Pydantic model", pipeline._model_dump, object())

    missing_focus = result.model_copy(update={"player_keys": ()})
    _raises(
        "focus player cannot be resolved",
        pipeline.summarize_prediction_for_oracle,
        missing_focus,
        context,
    )


def test_pipeline_prediction_input_guards(
    pipeline_fixture: tuple[
        pipeline.MinutesModelArtifact, projection.MinutesPredictionResult, dict[str, object]
    ],
    history: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact, _, context = pipeline_fixture
    _raises(
        "roster/context team",
        pipeline.predict_minutes_baseline,
        {"rows": history["rows"]},
        artifact,
        context=context,
        policy=policy,
    )
    bad_history = copy.deepcopy(history)
    bad_history["rosters"][context["team_key"]] = "bad"
    _raises(
        "target roster",
        pipeline.predict_minutes_baseline,
        bad_history,
        artifact,
        context=context,
        policy=policy,
    )
    bad_history = copy.deepcopy(history)
    bad_history["rosters"][context["team_key"]][0]["player_key"] = 1
    _raises(
        "roster player key",
        pipeline.predict_minutes_baseline,
        bad_history,
        artifact,
        context=context,
        policy=policy,
    )
    duplicate = copy.deepcopy(history)
    duplicate["rosters"][context["team_key"]][1]["player_id"] = duplicate["rosters"][
        context["team_key"]
    ][0]["player_id"]
    _raises(
        "lineup sampler returned an invalid result",
        pipeline.predict_minutes_baseline,
        duplicate,
        artifact,
        context=context,
        policy=policy,
    )


def test_evaluation_rejects_a_supported_blocked_fixture(
    repository_root: Path,
    pipeline_fixture: tuple[
        pipeline.MinutesModelArtifact, projection.MinutesPredictionResult, dict[str, object]
    ],
    history: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact, _, _ = pipeline_fixture
    evaluation = _read(repository_root / "fixtures/availability/MIN-007G/evaluation_dataset.json")
    rows = evaluation["rows"]
    assert isinstance(rows, list) and rows
    target_team = rows[0]["team_key"]
    changed_history = copy.deepcopy(history)
    changed_history["rosters"][target_team] = changed_history["rosters"][target_team][:1]
    _raises(
        "evaluation fixture unexpectedly blocked",
        pipeline.evaluate_minutes_baseline,
        changed_history,
        artifact,
        {"rows": [rows[0]]},
        policy=policy,
    )
