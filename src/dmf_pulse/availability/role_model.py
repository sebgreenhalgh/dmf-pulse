"""Internal regularised START/BENCH/OUT role utilities for MIN-007C.

The values returned here are sampling weights for the later coherent lineup
sampler.  They are deliberately not public player role probabilities.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.availability.models import HistoryRow, Position, RoleLabel, parse_utc

ROLE_ORDER: tuple[RoleLabel, ...] = ("START", "BENCH", "OUT")
POSITION_ORDER: tuple[Position, ...] = ("GK", "DEF", "MID", "FWD")
DECIMAL_PRECISION = 60
ROUNDING_MODE = ROUND_HALF_EVEN
SERIAL_SCALE = Decimal("0.000000000001")
TRAINING_DATASET_SHA256 = "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3"
CANONICAL_HISTORY_SHA256 = "23cc133b26beba0455ca50e66cbd4fca5bde8b1b38a4b946b197d53039982096"
FROZEN_POLICY_SHA256 = "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994"
ROLE_ARTIFACT_SHA256 = "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96"


class RoleModelValidationError(ValueError):
    """A role policy, artifact, history or context violates the frozen contract."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RoleBaselineArtifact(_FrozenModel):
    """Immutable position-prior artifact consumed by internal role utilities."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_window: int = Field(ge=1)
    model_family: str
    old_manager_multiplier: str
    other_team_multiplier: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preseason_multiplier: str
    probability_decimal_places: int = Field(ge=1)
    recency_decay: str
    role_prior_strength: str
    role_priors: dict[str, dict[str, str]]
    rounding_mode: Literal["ROUND_HALF_EVEN"]
    schema_version: Literal["role-baseline-artifact-v1"]
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_example_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.artifact_sha256 != ROLE_ARTIFACT_SHA256:
            raise RoleModelValidationError("role artifact identity is not the frozen artifact")
        if self.policy_sha256 != FROZEN_POLICY_SHA256:
            raise RoleModelValidationError("role artifact policy lineage is not frozen")
        if self.training_dataset_sha256 != TRAINING_DATASET_SHA256:
            raise RoleModelValidationError("role artifact training lineage is not frozen")
        return self


class RoleUtilityPrediction(_FrozenModel):
    """Internal role sampling weights plus uncertainty metadata."""

    schema_version: Literal["role-utility-prediction-v1"]
    player_key: str = Field(min_length=1)
    position: Position
    role_utilities: dict[RoleLabel, str]
    target_team_competitive_history_count: int = Field(ge=0)
    confidence_grade: Literal["B", "C", "D"]
    confidence_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        if set(self.role_utilities) != set(ROLE_ORDER):
            raise RoleModelValidationError("role utility roles are incomplete or unknown")
        if tuple(sorted(self.confidence_reasons)) != self.confidence_reasons:
            raise RoleModelValidationError("confidence reasons must be lexicographically sorted")
        if len(set(self.confidence_reasons)) != len(self.confidence_reasons):
            raise RoleModelValidationError("confidence reasons must be unique")
        if "BASELINE_MODEL_CAP_B" not in self.confidence_reasons:
            raise RoleModelValidationError("baseline confidence cap reason is required")
        return self


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise RoleModelValidationError(f"{label} must be a mapping or validated model")


def _strict_int(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RoleModelValidationError(f"{label} must be an integer >= {minimum}")
    return value


def _strict_bool(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise RoleModelValidationError(f"{label} must be a boolean")
    return value


def _uuid_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise RoleModelValidationError(f"{label} must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise RoleModelValidationError(f"{label} must be a UUID string") from exc


def _policy_mapping(policy: object) -> dict[str, Any]:
    value = _mapping(policy, label="policy")
    expected = {
        "baseline_confidence_cap": "B",
        "coherence_model": "COHERENCE_MODEL_V1",
        "cold_start_min_competitive_observations": 3,
        "default_bench_goalkeeper_slots": 1,
        "default_bench_size": 9,
        "expected_minutes_decimal_places": 6,
        "history_window": 12,
        "lineup_sample_count": 256,
        "lineup_sampler": "DETERMINISTIC_EXPONENTIAL_RACE_V1",
        "minute_bin_alpha": "0.050000",
        "minute_prior_strength": "3.000000",
        "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        "new_manager_min_team_lineups": 3,
        "old_manager_multiplier": "0.350000",
        "other_team_multiplier": "0.000000",
        "policy_id": "minutes-baseline-v1",
        "preseason_multiplier": "0.250000",
        "probability_decimal_places": 12,
        "promoted_team_min_target_league_lineups": 3,
        "recency_decay": "0.850000",
        "role_prior_strength": "2.000000",
        "rounding_mode": "ROUND_HALF_EVEN",
        "schema_version": "minutes-baseline-policy-v1",
        "seed": "MIN-007-COHERENCE-V1",
    }
    if value != expected:
        raise RoleModelValidationError("policy does not match the frozen minutes baseline policy")
    if _canonical_sha256(value) != FROZEN_POLICY_SHA256:
        raise RoleModelValidationError("policy semantic hash is not frozen")
    return value


def _as_history_rows(history: object) -> tuple[HistoryRow, ...]:
    value = _mapping(history, label="history")
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes, bytearray)):
        raise RoleModelValidationError("history must contain a rows sequence")
    rows: list[HistoryRow] = []
    seen_examples: set[str] = set()
    try:
        for raw in raw_rows:
            if isinstance(raw, HistoryRow):
                row = raw
            elif isinstance(raw, Mapping):
                row = HistoryRow.model_validate(raw)
            else:
                raise RoleModelValidationError("history rows must be mappings")
            if row.evidence_type not in {"COMPETITIVE", "PRESEASON"}:
                raise RoleModelValidationError("history evidence type is not supported")
            example_id = str(row.example_id)
            if example_id in seen_examples:
                raise RoleModelValidationError("history contains duplicate example_id")
            seen_examples.add(example_id)
            rows.append(row)
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, RoleModelValidationError):
            raise
        raise RoleModelValidationError("history contains an invalid role row") from exc
    return tuple(rows)


def _training_rows(training_dataset: object) -> tuple[HistoryRow, ...]:
    value = _mapping(training_dataset, label="training_dataset")
    rows = _as_history_rows(value)
    if len(rows) != 368 or any(row.split != "TRAIN" for row in rows):
        raise RoleModelValidationError("training dataset is not the frozen 368-row TRAIN dataset")
    canonical = dict(value)
    canonical["rows"] = [row.model_dump(mode="json") for row in sorted(rows, key=_training_row_key)]
    if _canonical_sha256(canonical) != TRAINING_DATASET_SHA256:
        raise RoleModelValidationError(
            "training dataset semantic hash is not the accepted MIN-007B hash"
        )
    return rows


def _training_row_key(row: HistoryRow) -> tuple[str, datetime, int, str, str]:
    position_rank = {position: index for index, position in enumerate(POSITION_ORDER)}
    return (
        row.team_key,
        row.feature_cutoff,
        position_rank[row.position],
        row.player_key,
        str(row.example_id),
    )


def _serialized_decimal(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        return format(value.quantize(SERIAL_SCALE), ".12f")


def _public_vector(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        quantized = [value.quantize(SERIAL_SCALE) for value in values]
        residual = Decimal(1) - sum(quantized, Decimal(0))
        if residual:
            index = max(range(len(values)), key=lambda item: (values[item], -item))
            quantized[index] += residual
        if sum(quantized, Decimal(0)) != Decimal(1):
            raise RoleModelValidationError("role prior residual correction failed")
        return tuple(quantized)


def _artifact_body(
    policy: Mapping[str, Any], priors: dict[str, dict[str, str]], count: int
) -> dict[str, Any]:
    return {
        "schema_version": "role-baseline-artifact-v1",
        "model_family": policy["model_family"],
        "training_dataset_sha256": TRAINING_DATASET_SHA256,
        "training_example_count": count,
        "policy_sha256": FROZEN_POLICY_SHA256,
        "role_prior_strength": policy["role_prior_strength"],
        "recency_decay": policy["recency_decay"],
        "old_manager_multiplier": policy["old_manager_multiplier"],
        "preseason_multiplier": policy["preseason_multiplier"],
        "other_team_multiplier": policy["other_team_multiplier"],
        "history_window": policy["history_window"],
        "probability_decimal_places": policy["probability_decimal_places"],
        "rounding_mode": policy["rounding_mode"],
        "role_priors": priors,
    }


def fit_role_baseline(training_dataset: object, *, policy: object) -> RoleBaselineArtifact:
    """Fit immutable position priors from the accepted MIN-007B TRAIN dataset."""

    policy_value = _policy_mapping(policy)
    rows = _training_rows(training_dataset)
    counts: dict[Position, dict[RoleLabel, Decimal]] = {
        position: {role: Decimal(0) for role in ROLE_ORDER} for position in POSITION_ORDER
    }
    for row in rows:
        counts[row.position][row.role_label] += Decimal(1)
    priors: dict[str, dict[str, str]] = {}
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        for position in POSITION_ORDER:
            total = sum(counts[position].values(), Decimal(0))
            values = tuple(
                (counts[position][role] + Decimal(1)) / (total + Decimal(3)) for role in ROLE_ORDER
            )
            corrected = _public_vector(values)
            priors[position] = {
                role: format(value, ".12f")
                for role, value in zip(ROLE_ORDER, corrected, strict=True)
            }
    body = _artifact_body(policy_value, priors, len(rows))
    artifact = dict(body)
    artifact["artifact_sha256"] = _canonical_sha256(body)
    try:
        return RoleBaselineArtifact.model_validate(artifact)
    except ValidationError as exc:
        raise RoleModelValidationError("role artifact failed schema validation") from exc


def _artifact_mapping(artifact: object) -> dict[str, Any]:
    value = _mapping(artifact, label="artifact")
    try:
        validated = RoleBaselineArtifact.model_validate(value)
    except ValidationError as exc:
        raise RoleModelValidationError("role artifact failed schema validation") from exc
    body = validated.model_dump(mode="json")
    identity = dict(body)
    supplied = identity.pop("artifact_sha256")
    if supplied != _canonical_sha256(identity):
        raise RoleModelValidationError("role artifact semantic identity is invalid")
    if set(validated.role_priors) != set(POSITION_ORDER):
        raise RoleModelValidationError("role artifact positions are incomplete or unknown")
    for position in POSITION_ORDER:
        if set(validated.role_priors[position]) != set(ROLE_ORDER):
            raise RoleModelValidationError("role artifact roles are incomplete or unknown")
    return body


def _context_mapping(context: object) -> dict[str, Any]:
    value = _mapping(context, label="context")
    required = ("as_of", "cutoff_sequence_index", "manager_regime_id", "team_id", "team_key")
    if any(name not in value for name in required):
        raise RoleModelValidationError("prediction context is missing a required field")
    value["as_of"] = parse_utc(value["as_of"], field_name="as_of")
    value["cutoff_sequence_index"] = _strict_int(
        value["cutoff_sequence_index"], label="cutoff_sequence_index", minimum=1
    )
    value["team_id"] = _uuid_text(value["team_id"], label="context.team_id")
    value["manager_regime_id"] = _uuid_text(
        value["manager_regime_id"], label="context.manager_regime_id"
    )
    if not isinstance(value["team_key"], str) or not value["team_key"]:
        raise RoleModelValidationError("context.team_key must be non-empty")
    for name in ("new_manager", "promoted_team"):
        if name in value:
            value[name] = _strict_bool(value[name], label=f"context.{name}")
    for name in ("current_manager_team_lineups", "target_league_team_lineups"):
        value[name] = _strict_int(value.get(name, 0), label=f"context.{name}")
    overrides = value.get("player_overrides", {})
    if not isinstance(overrides, Mapping):
        raise RoleModelValidationError("context.player_overrides must be a mapping")
    value["player_overrides"] = dict(overrides)
    return value


def _player(history: object, context: Mapping[str, Any], player_key: str) -> dict[str, Any]:
    value = _mapping(history, label="history")
    rosters = value.get("rosters")
    if not isinstance(rosters, Mapping):
        raise RoleModelValidationError("history must contain rosters")
    roster = rosters.get(context["team_key"])
    if not isinstance(roster, Sequence) or isinstance(roster, (str, bytes, bytearray)):
        raise RoleModelValidationError("target team roster is missing")
    selected: dict[str, Any] | None = None
    for raw in roster:
        if not isinstance(raw, Mapping):
            raise RoleModelValidationError("roster players must be mappings")
        if raw.get("player_key") == player_key:
            selected = dict(raw)
            break
    if selected is None:
        raise RoleModelValidationError("player is not present on target team roster")
    for key in ("player_id", "team_id"):
        selected[key] = _uuid_text(selected.get(key), label=f"player.{key}")
    for key in ("player_key", "team_key"):
        if not isinstance(selected.get(key), str) or not selected[key]:
            raise RoleModelValidationError(f"player.{key} must be non-empty")
    if selected["team_key"] != context["team_key"] or selected["team_id"] != context["team_id"]:
        raise RoleModelValidationError("player does not belong to the target team")
    if selected.get("position") not in POSITION_ORDER:
        raise RoleModelValidationError("player position is invalid")
    overrides = context["player_overrides"].get(player_key, {})
    if not isinstance(overrides, Mapping):
        raise RoleModelValidationError("player override must be a mapping")
    allowed = {"hard_ineligible", "new_signing", "player_id"}
    if set(overrides) - allowed:
        raise RoleModelValidationError("player override contains unresolved eligibility fields")
    for key in ("hard_ineligible", "new_signing"):
        if key in overrides:
            selected[key] = _strict_bool(overrides[key], label=f"player override {key}")
    if "player_id" in overrides:
        selected["player_id"] = _uuid_text(
            overrides["player_id"], label="player override player_id"
        )
    return selected


def _eligible_rows(
    rows: Sequence[HistoryRow], player: Mapping[str, Any], context: Mapping[str, Any], window: int
) -> tuple[HistoryRow, ...]:
    as_of = context["as_of"]
    eligible = [
        row
        for row in rows
        if str(row.player_id) == player["player_id"]
        and str(row.team_id) == context["team_id"]
        and row.team_key == context["team_key"]
        and row.sequence_index < context["cutoff_sequence_index"]
        and row.feature_cutoff < as_of
        and row.label_usable_at <= as_of
    ]
    eligible.sort(key=lambda row: (-row.sequence_index, str(row.example_id)))
    return tuple(eligible[:window])


def _confidence(
    player: Mapping[str, Any], context: Mapping[str, Any], competitive_count: int
) -> tuple[Literal["B", "C", "D"], tuple[str, ...]]:
    if player.get("hard_ineligible", False):
        return "B", ("BASELINE_MODEL_CAP_B", "HARD_INELIGIBLE_OVERRIDE")
    reasons: set[str] = set()
    if competitive_count == 0:
        grade: Literal["B", "C", "D"] = "D"
        reasons.add("NO_TARGET_TEAM_COMPETITIVE_HISTORY")
    elif competitive_count < 3:
        grade = "C"
        reasons.add("THIN_PLAYER_HISTORY")
    else:
        grade = "B"
    if player.get("new_signing", False):
        grade = "D" if competitive_count == 0 else "C"
        reasons.add("NEW_SIGNING")
    if context.get("new_manager", False) and context["current_manager_team_lineups"] < 3:
        if grade == "B":
            grade = "C"
        reasons.add("NEW_MANAGER_REGIME")
    if context.get("promoted_team", False) and context["target_league_team_lineups"] < 3:
        if grade == "B":
            grade = "C"
        reasons.add("PROMOTED_TEAM_EARLY_REGIME")
    reasons.add("BASELINE_MODEL_CAP_B")
    return grade, tuple(sorted(reasons))


def predict_role_utilities(
    history: object,
    artifact: object,
    *,
    context: object,
    player_key: str,
    policy: object,
) -> RoleUtilityPrediction:
    """Produce cutoff-safe internal role sampling weights for one player."""

    policy_value = _policy_mapping(policy)
    artifact_value = _artifact_mapping(artifact)
    history_value = _mapping(history, label="history")
    rows = _as_history_rows(history_value)
    context_value = _context_mapping(context)
    if not isinstance(player_key, str) or not player_key:
        raise RoleModelValidationError("player_key must be non-empty")
    player = _player(history_value, context_value, player_key)
    if player.get("hard_ineligible", False):
        utilities = {"START": Decimal(0), "BENCH": Decimal(0), "OUT": Decimal(1)}
        retained: tuple[HistoryRow, ...] = ()
    else:
        priors = artifact_value["role_priors"][player["position"]]
        retained = _eligible_rows(rows, player, context_value, int(policy_value["history_window"]))
        with localcontext() as decimal_context:
            decimal_context.prec = DECIMAL_PRECISION
            decimal_context.rounding = ROUNDING_MODE
            scores = {
                role: Decimal(policy_value["role_prior_strength"]) * Decimal(priors[role])
                for role in ROLE_ORDER
            }
            for age, row in enumerate(retained):
                multiplier = Decimal(1)
                if str(row.manager_regime_id) != context_value["manager_regime_id"]:
                    multiplier *= Decimal(policy_value["old_manager_multiplier"])
                if row.evidence_type == "PRESEASON":
                    multiplier *= Decimal(policy_value["preseason_multiplier"])
                scores[row.role_label] += (
                    Decimal(policy_value["recency_decay"]) ** age
                ) * multiplier
            total = sum(scores.values(), Decimal(0))
            if total <= 0:
                raise RoleModelValidationError("role utility normalisation has no positive mass")
            utilities = {role: scores[role] / total for role in ROLE_ORDER}
    competitive_count = sum(row.evidence_type == "COMPETITIVE" for row in retained)
    grade, reasons = _confidence(player, context_value, competitive_count)
    result = {
        "schema_version": "role-utility-prediction-v1",
        "player_key": player_key,
        "position": player["position"],
        "role_utilities": {role: _serialized_decimal(utilities[role]) for role in ROLE_ORDER},
        "target_team_competitive_history_count": competitive_count,
        "confidence_grade": grade,
        "confidence_reasons": reasons,
    }
    try:
        return RoleUtilityPrediction.model_validate(result)
    except ValidationError as exc:
        raise RoleModelValidationError("role utility prediction failed schema validation") from exc


__all__ = [
    "CANONICAL_HISTORY_SHA256",
    "FROZEN_POLICY_SHA256",
    "ROLE_ARTIFACT_SHA256",
    "TRAINING_DATASET_SHA256",
    "RoleBaselineArtifact",
    "RoleModelValidationError",
    "RoleUtilityPrediction",
    "fit_role_baseline",
    "predict_role_utilities",
]
