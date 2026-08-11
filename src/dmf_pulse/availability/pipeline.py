"""Pure MIN-007G projection, evaluation, and compatibility-artifact pipeline."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.availability.dataset import semantic_dataset_hash
from dmf_pulse.availability.lineup import (
    BlockedLineupResult,
    ProjectedLineupResult,
    sample_coherent_lineups,
)
from dmf_pulse.availability.minutes import (
    MinutePriorArtifact,
    fit_minute_priors,
    predict_conditional_minutes,
)
from dmf_pulse.availability.projection import (
    DECIMAL_PRECISION,
    MinutesPredictionResult,
    PlayerMinutesProjection,
    canonical_sha256,
    compose_player_minutes_projection,
    compose_team_minutes_projection,
)
from dmf_pulse.availability.role_model import (
    RoleBaselineArtifact,
    RoleUtilityPrediction,
    fit_role_baseline,
    predict_role_utilities,
)

ARTIFACT_SHA256 = "80d1aa4cfd4a80eb7f7b291899fd9cf6173b017e308ea3b41d450a7bc87e2aeb"
EVALUATION_SHA256 = "f2d075a9497331b73bf896be4610b684f8a3ed41eb17248a27284c79556cd748"
ROLE_ARTIFACT_SHA256 = "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96"
MINUTE_ARTIFACT_SHA256 = "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422"
POLICY_SHA256 = "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994"
DATASET_SHA256 = "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3"
ROUNDING_MODE = ROUND_HALF_EVEN


class _FrozenValidatedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> _FrozenValidatedModel:
        del deep
        data = self.model_dump(mode="python")
        if update:
            data.update(dict(update))
        return type(self).model_validate(data)


class MinutesModelArtifact(_FrozenValidatedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["minutes-model-artifact-v1"]
    model_family: Literal["REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"]
    training_split: Literal["TRAIN"]
    training_example_count: int = Field(ge=1)
    training_fixture_count: int = Field(ge=1)
    config: dict[str, Any]
    role_priors: dict[str, dict[str, str]]
    minute_priors: dict[str, dict[str, tuple[str, ...]]]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def coerce_vectors(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        priors = data.get("minute_priors")
        if isinstance(priors, Mapping):
            data["minute_priors"] = {
                str(position): {
                    str(role): tuple(values)
                    if isinstance(values, Sequence)
                    and not isinstance(values, (str, bytes, bytearray))
                    else values
                    for role, values in roles.items()
                }
                for position, roles in priors.items()
                if isinstance(roles, Mapping)
            }
        return data

    @model_validator(mode="after")
    def validate_identity(self) -> MinutesModelArtifact:
        if self.artifact_sha256 != ARTIFACT_SHA256:
            raise ValueError("model artifact identity is not frozen")
        body = self.model_dump(mode="json")
        supplied = body.pop("artifact_sha256")
        if canonical_sha256(body) != supplied:
            raise ValueError("model artifact hash is inconsistent")
        if self.dataset_sha256 != DATASET_SHA256:
            raise ValueError("model artifact dataset lineage is not frozen")
        return self


class MinutesModelEvaluation(_FrozenValidatedModel):
    schema_version: Literal["minutes-model-evaluation-v1"]
    evaluation_kind: Literal["SYNTHETIC_CONTRACT_EVALUATION"]
    n_examples: int = Field(ge=1)
    role_log_loss: str
    persistence_role_log_loss: str
    role_multiclass_brier: str
    persistence_role_multiclass_brier: str
    p_zero_brier: str
    persistence_p_zero_brier: str
    p_60_plus_brier: str
    persistence_p_60_plus_brier: str
    expected_minutes_mae: str
    baseline_decision: Literal["PROMOTE_BASELINE", "RETAIN_EQUAL_BASELINE"]
    production_calibration_claim: Literal[False]
    evaluation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> MinutesModelEvaluation:
        if self.evaluation_sha256 != EVALUATION_SHA256:
            raise ValueError("evaluation identity is not frozen")
        body = self.model_dump(mode="json")
        supplied = body.pop("evaluation_sha256")
        if canonical_sha256(body) != supplied:
            raise ValueError("evaluation hash is inconsistent")
        return self


class ModelEvaluationPublication(_FrozenValidatedModel):
    """Internal persistence envelope binding public metrics to one model artifact."""

    evaluation: MinutesModelEvaluation
    model_version_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_family: str = Field(min_length=1)


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="python")
        if isinstance(result, Mapping):
            return dict(result)
    raise TypeError(f"{label} must be a mapping or model")


def _model_dump(value: object, *, mode: Literal["json", "python"] = "python") -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode=mode)
        if isinstance(result, Mapping):
            return dict(result)
    raise TypeError("value must be a mapping or Pydantic model")


def _as_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _artifact_parts(artifact: object) -> tuple[RoleBaselineArtifact, MinutePriorArtifact]:
    value = _mapping(artifact, label="artifact")
    role_body = {
        "artifact_sha256": ROLE_ARTIFACT_SHA256,
        "history_window": value["config"]["history_window"],
        "model_family": value["model_family"],
        "old_manager_multiplier": value["config"]["old_manager_multiplier"],
        "other_team_multiplier": value["config"]["other_team_multiplier"],
        "policy_sha256": POLICY_SHA256,
        "preseason_multiplier": value["config"]["preseason_multiplier"],
        "probability_decimal_places": value["config"]["probability_decimal_places"],
        "recency_decay": value["config"]["recency_decay"],
        "role_prior_strength": value["config"]["role_prior_strength"],
        "role_priors": value["role_priors"],
        "rounding_mode": value["config"]["rounding_mode"],
        "schema_version": "role-baseline-artifact-v1",
        "training_dataset_sha256": value["dataset_sha256"],
        "training_example_count": value["training_example_count"],
    }
    minute_body = {
        "schema_version": "minute-prior-artifact-v1",
        "model_family": value["model_family"],
        "training_dataset_sha256": value["dataset_sha256"],
        "training_example_count": value["training_example_count"],
        "policy_sha256": POLICY_SHA256,
        "minute_prior_strength": value["config"]["minute_prior_strength"],
        "minute_bin_alpha": value["config"]["minute_bin_alpha"],
        "probability_decimal_places": value["config"]["probability_decimal_places"],
        "rounding_mode": value["config"]["rounding_mode"],
        "minute_priors": value["minute_priors"],
        "artifact_sha256": MINUTE_ARTIFACT_SHA256,
    }
    return RoleBaselineArtifact.model_validate(role_body), MinutePriorArtifact.model_validate(
        minute_body
    )


def fit_projection_artifact(training_dataset: object, *, policy: object) -> MinutesModelArtifact:
    """Fit the compatibility artifact by delegating all priors to accepted C and D."""

    role = fit_role_baseline(training_dataset, policy=policy)
    minute = fit_minute_priors(training_dataset, policy=policy)
    role_json = role.model_dump(mode="json")
    minute_json = minute.model_dump(mode="json")
    policy_value = _mapping(policy, label="policy")
    dataset_hash = semantic_dataset_hash(training_dataset)
    rows = _mapping(training_dataset, label="training_dataset").get("rows", ())
    fixtures = {str(_mapping(row, label="training row").get("fixture_id")) for row in rows}
    body: dict[str, Any] = {
        "schema_version": "minutes-model-artifact-v1",
        "model_family": policy_value["model_family"],
        "training_split": "TRAIN",
        "training_example_count": len(rows),
        "training_fixture_count": len(fixtures),
        "config": policy_value,
        "role_priors": role_json["role_priors"],
        "minute_priors": minute_json["minute_priors"],
        "dataset_sha256": dataset_hash,
    }
    body["artifact_sha256"] = canonical_sha256(body)
    return MinutesModelArtifact.model_validate(body)


def _context_for_eval(
    history: Mapping[str, Any], team_key: str, sequence: int, row: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "minutes-prediction-context-v1",
        "scenario": "eval",
        "fixture_id": str(
            uuid5(NAMESPACE_URL, f"dmf-pulse:min007:fixture:{team_key}:target:eval:{sequence}")
        ),
        "team_key": team_key,
        "team_id": row["team_id"],
        "as_of": "2026-08-14T17:30:00Z",
        "cutoff_sequence_index": sequence,
        "manager_regime_id": row["manager_regime_id"],
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "current_manager_team_lineups": 8,
        "target_league_team_lineups": 8,
        "promoted_team": False,
        "new_manager": False,
        "player_overrides": {},
    }


def predict_minutes_baseline(
    history: object,
    artifact: object,
    *,
    context: object,
    policy: object,
) -> MinutesPredictionResult:
    """Run accepted C/D/E and compose a deterministic public prediction."""

    history_value = _mapping(history, label="history")
    context_value = _mapping(context, label="context")
    artifact_value = _mapping(artifact, label="artifact")
    role_artifact, minute_artifact = _artifact_parts(artifact_value)
    rosters = history_value.get("rosters")
    team_key = context_value.get("team_key")
    if not isinstance(rosters, Mapping) or not isinstance(team_key, str):
        raise ValueError("history roster/context team is invalid")
    roster = rosters.get(team_key)
    if not isinstance(roster, Sequence) or isinstance(roster, (str, bytes, bytearray)):
        raise ValueError("target roster is missing")
    role_predictions: dict[str, RoleUtilityPrediction] = {}
    candidates: list[dict[str, Any]] = []
    for raw in roster:
        player = _mapping(raw, label="roster player")
        player_key = player.get("player_key")
        if not isinstance(player_key, str):
            raise ValueError("roster player key is invalid")
        with localcontext() as decimal_context:
            decimal_context.prec = DECIMAL_PRECISION
            decimal_context.rounding = ROUND_HALF_EVEN
            role_prediction = predict_role_utilities(
                history_value,
                role_artifact,
                context=context_value,
                player_key=player_key,
                policy=policy,
            )
        role_predictions[player_key] = role_prediction
        override = _mapping(
            context_value.get("player_overrides", {}).get(player_key, {}), label="override"
        )
        player_id = str(override.get("player_id", player["player_id"]))
        candidates.append(
            {
                "player_id": player_id,
                "player_key": player_key,
                "position": player["position"],
                "start_weight": role_prediction.role_utilities["START"],
                "bench_weight": role_prediction.role_utilities["BENCH"],
                "hard_ineligible": bool(
                    override.get("hard_ineligible", player.get("hard_ineligible", False))
                ),
            }
        )
    bench_size = int(context_value.get("bench_size", 9))
    bench_gk = int(context_value.get("bench_goalkeeper_slots", 1))
    with localcontext() as decimal_context:
        decimal_context.prec = DECIMAL_PRECISION
        decimal_context.rounding = ROUND_HALF_EVEN
        lineup = sample_coherent_lineups(
            candidates,
            fixture_id=str(context_value["fixture_id"]),
            team_id=str(context_value["team_id"]),
            seed_suffix="",
            bench_size=bench_size,
            bench_goalkeeper_slots=bench_gk,
            policy=policy,
        )
    if isinstance(lineup, BlockedLineupResult):
        return MinutesPredictionResult(
            status="BLOCKED",
            fixture_id=str(context_value["fixture_id"]),
            team_id=str(context_value["team_id"]),
            as_of=str(context_value["as_of"]),
            projection=None,
            error_code=lineup.error_code,
        )
    if not isinstance(lineup, ProjectedLineupResult):
        raise ValueError("lineup sampler returned an invalid result")
    by_key = {str(item["player_key"]): item for item in candidates}
    players: list[PlayerMinutesProjection] = []
    core_pmfs: list[dict[str, Any]] = []
    for marginal in lineup.role_marginals:
        candidate = by_key[
            next(
                key for key, item in by_key.items() if str(item["player_id"]) == marginal.player_id
            )
        ]
        role_prediction = role_predictions[candidate["player_key"]]
        with localcontext() as decimal_context:
            decimal_context.prec = DECIMAL_PRECISION
            decimal_context.rounding = ROUND_HALF_EVEN
            start = predict_conditional_minutes(
                history_value,
                minute_artifact,
                context=context_value,
                player_id=marginal.player_id,
                position=marginal.position,
                role="START",
                policy=policy,
            )
            bench = predict_conditional_minutes(
                history_value,
                minute_artifact,
                context=context_value,
                player_id=marginal.player_id,
                position=marginal.position,
                role="BENCH",
                policy=policy,
            )
        core_pmfs.extend(
            (
                start.model_dump(mode="json"),
                bench.model_dump(mode="json"),
            )
        )
        players.append(
            compose_player_minutes_projection(
                marginal,
                start,
                bench,
                confidence_grade=role_prediction.confidence_grade,
                confidence_reasons=(
                    ("HARD_INELIGIBLE_OVERRIDE", "BASELINE_MODEL_CAP_B")
                    if "HARD_INELIGIBLE_OVERRIDE" in role_prediction.confidence_reasons
                    else role_prediction.confidence_reasons
                ),
            )
        )
    projection = compose_team_minutes_projection(
        lineup,
        players,
        as_of=str(context_value["as_of"]),
        model_family=str(artifact_value["model_family"]),
        dataset_sha256=str(artifact_value["dataset_sha256"]),
        model_artifact_sha256=str(artifact_value["artifact_sha256"]),
    )
    first = tuple(item.model_dump(mode="json") for item in lineup.first_scenarios)
    core_scenarios = tuple(item.model_dump(mode="json") for item in lineup.scenarios)
    core_hard = tuple(
        {
            "player_id": str(item["player_id"]),
            "reason": "HARD_INELIGIBLE_OVERRIDE",
            "hard_ineligible": True,
        }
        for item in candidates
        if item["hard_ineligible"]
    )
    return MinutesPredictionResult(
        status="PROJECTED",
        fixture_id=projection.fixture_id,
        team_id=projection.team_id,
        as_of=projection.as_of,
        projection=projection,
        error_code=None,
        first_scenarios=first,
        player_keys=tuple((str(item["player_id"]), key) for key, item in by_key.items()),
        core_role_marginals=tuple(item.model_dump(mode="json") for item in lineup.role_marginals),
        core_minute_pmfs=tuple(core_pmfs),
        core_scenarios=core_scenarios,
        core_hard_eligibility=core_hard,
    )


def summarize_prediction_for_oracle(
    result: MinutesPredictionResult, context: object
) -> dict[str, Any]:
    """Return the compact registry view used by the frozen oracle."""

    context_value = _mapping(context, label="context")
    if result.status == "BLOCKED":
        return {
            "status": result.status,
            "fixture_id": result.fixture_id,
            "team_id": result.team_id,
            "as_of": result.as_of,
            "error_code": result.error_code,
        }
    assert result.projection is not None
    projection = result.projection
    focus_key = context_value["focus_player_key"]
    # The public schema intentionally excludes player_key; registry diagnostics use the
    # accepted roster key only to select the requested focus row.
    focus_id = next((player_id for player_id, key in result.player_keys if key == focus_key), None)
    if focus_id is None:
        raise ValueError("focus player cannot be resolved without context roster mapping")
    focus = next(item for item in projection.players if item.player_id == focus_id)
    return {
        "status": "PROJECTED",
        "fixture_id": projection.fixture_id,
        "team_id": projection.team_id,
        "as_of": projection.as_of,
        "focus_player_key": focus_key,
        "focus_player": focus.model_dump(mode="json"),
        "scenario_set_sha256": projection.scenario_set_sha256,
        "team_result_sha256": projection.result_sha256,
        "all_player_projection_hashes": sorted(
            item.projection_sha256 for item in projection.players
        ),
        "sum_p_start": projection.sum_p_start,
        "sum_p_bench": projection.sum_p_bench,
        "sum_p_out": projection.sum_p_out,
        "first_scenarios": list(result.first_scenarios),
    }


def _public_metric(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(Decimal("0.000001")), ".6f")


def _previous_row(
    rows: Sequence[Mapping[str, Any]], team: str, player_id: str, sequence: int
) -> Mapping[str, Any] | None:
    prior = [
        row
        for row in rows
        if row["team_key"] == team
        and row["player_id"] == player_id
        and int(row["sequence_index"]) < sequence
    ]
    return max(prior, key=lambda row: int(row["sequence_index"])) if prior else None


def _persistence_role(previous: str | None) -> dict[str, Decimal]:
    baselines: dict[str | None, dict[str, Decimal]] = {
        "START": {"START": Decimal(".80"), "BENCH": Decimal(".15"), "OUT": Decimal(".05")},
        "BENCH": {"START": Decimal(".20"), "BENCH": Decimal(".70"), "OUT": Decimal(".10")},
        "OUT": {"START": Decimal(".10"), "BENCH": Decimal(".20"), "OUT": Decimal(".70")},
        None: {"START": Decimal(".45"), "BENCH": Decimal(".40"), "OUT": Decimal(".15")},
    }
    return baselines[previous]


def evaluate_minutes_baseline(
    history: object,
    artifact: object,
    evaluation_dataset: object,
    *,
    policy: object,
) -> MinutesModelEvaluation:
    """Evaluate exactly the frozen 92-row synthetic evaluation set."""

    history_value = _mapping(history, label="history")
    evaluation_rows = _mapping(evaluation_dataset, label="evaluation_dataset").get("rows", ())
    rows = [_mapping(row, label="evaluation row") for row in evaluation_rows]
    grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["team_key"]), int(row["sequence_index"]))].append(row)
    metrics = {
        key: Decimal(0)
        for key in (
            "model_log",
            "base_log",
            "model_brier",
            "base_brier",
            "model_p0",
            "base_p0",
            "model_p60",
            "base_p60",
            "mae",
        )
    }
    epsilon = Decimal("0.000000000001")
    for (team, sequence), group in sorted(grouped.items()):
        context = _context_for_eval(history_value, team, sequence, group[0])
        prediction = predict_minutes_baseline(
            history_value, artifact, context=context, policy=policy
        )
        if prediction.projection is None:
            raise ValueError("evaluation fixture unexpectedly blocked")
        by_player = {player.player_id: player for player in prediction.projection.players}
        for eval_row in group:
            player = by_player[str(eval_row["player_id"])]
            role = str(eval_row["role_label"])
            key = {"START": "p_start", "BENCH": "p_bench", "OUT": "p_out_of_squad"}[role]
            model_probability = max(_as_decimal(getattr(player, key)), epsilon)
            previous = _previous_row(
                _mapping(history_value, label="history")["rows"],
                team,
                str(eval_row["player_id"]),
                sequence,
            )
            previous_role = str(previous["role_label"]) if previous else None
            baseline = _persistence_role(previous_role)
            metrics["model_log"] += -model_probability.ln()
            metrics["base_log"] += -baseline[role].ln()
            for candidate_role, field in (
                ("START", "p_start"),
                ("BENCH", "p_bench"),
                ("OUT", "p_out_of_squad"),
            ):
                truth = Decimal(1) if role == candidate_role else Decimal(0)
                metrics["model_brier"] += (
                    _as_decimal(getattr(player, field)) - truth
                ) ** 2 / Decimal(3)
                metrics["base_brier"] += (baseline[candidate_role] - truth) ** 2 / Decimal(3)
            truth_zero = Decimal(1) if int(eval_row["minutes_label"]) == 0 else Decimal(0)
            truth_sixty = Decimal(1) if int(eval_row["minutes_label"]) >= 60 else Decimal(0)
            previous_minutes = int(previous["minutes_label"]) if previous else 0
            baseline_zero = Decimal(".80") if previous_minutes == 0 else Decimal(".20")
            baseline_sixty = Decimal(".80") if previous_minutes >= 60 else Decimal(".20")
            metrics["model_p0"] += (_as_decimal(player.p_zero_minutes) - truth_zero) ** 2
            metrics["base_p0"] += (baseline_zero - truth_zero) ** 2
            metrics["model_p60"] += (_as_decimal(player.p_60_plus) - truth_sixty) ** 2
            metrics["base_p60"] += (baseline_sixty - truth_sixty) ** 2
            metrics["mae"] += abs(
                _as_decimal(player.expected_minutes) - Decimal(int(eval_row["minutes_label"]))
            )
    count = Decimal(len(rows))
    body: dict[str, Any] = {
        "schema_version": "minutes-model-evaluation-v1",
        "evaluation_kind": "SYNTHETIC_CONTRACT_EVALUATION",
        "n_examples": len(rows),
        "role_log_loss": _public_metric(metrics["model_log"] / count),
        "persistence_role_log_loss": _public_metric(metrics["base_log"] / count),
        "role_multiclass_brier": _public_metric(metrics["model_brier"] / count),
        "persistence_role_multiclass_brier": _public_metric(metrics["base_brier"] / count),
        "p_zero_brier": _public_metric(metrics["model_p0"] / count),
        "persistence_p_zero_brier": _public_metric(metrics["base_p0"] / count),
        "p_60_plus_brier": _public_metric(metrics["model_p60"] / count),
        "persistence_p_60_plus_brier": _public_metric(metrics["base_p60"] / count),
        "expected_minutes_mae": _public_metric(metrics["mae"] / count),
        "baseline_decision": "PROMOTE_BASELINE"
        if metrics["model_log"] / count <= metrics["base_log"] / count
        and metrics["model_brier"] / count <= metrics["base_brier"] / count
        else "RETAIN_EQUAL_BASELINE",
        "production_calibration_claim": False,
    }
    body["evaluation_sha256"] = canonical_sha256(body)
    return MinutesModelEvaluation.model_validate(body)


__all__ = [
    "ARTIFACT_SHA256",
    "EVALUATION_SHA256",
    "MinutesModelArtifact",
    "MinutesModelEvaluation",
    "ModelEvaluationPublication",
    "evaluate_minutes_baseline",
    "fit_projection_artifact",
    "predict_minutes_baseline",
    "summarize_prediction_for_oracle",
]
