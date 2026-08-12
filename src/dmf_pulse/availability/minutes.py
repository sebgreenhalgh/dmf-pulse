"""Conditional Decimal minute distributions for MIN-007D.

The module deliberately keeps the numerical PMF separate from the role model:
it fits position/role minute priors and then conditions those priors on a
single player's cutoff-safe history.  Probabilistic arithmetic remains
``Decimal`` at the frozen precision, while stored-PMF invariants use exact
coefficient/exponent arithmetic; JSON is only a twelve-decimal diagnostic
projection.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Literal, Self, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    model_validator,
)

from dmf_pulse.availability.decimal_integrity import (
    exact_decimal_sum,
    exact_one_minus,
    exact_sum_equals_one,
)
from dmf_pulse.availability.models import HistoryRow, Position, parse_utc
from dmf_pulse.availability.role_model import (
    FROZEN_POLICY_SHA256,
    TRAINING_DATASET_SHA256,
    RoleModelValidationError,
    _context_mapping,
    _policy_mapping,
    _training_rows,
)

POSITION_ORDER: tuple[Position, ...] = ("GK", "DEF", "MID", "FWD")
MINUTE_ROLE_ORDER: tuple[Literal["START", "BENCH"], ...] = ("START", "BENCH")
MINUTE_COUNT = 91
DECIMAL_PRECISION = 60
ROUNDING_MODE = ROUND_HALF_EVEN
SERIAL_SCALE = Decimal("0.000000000001")
MINUTE_ARTIFACT_SHA256 = "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422"


class MinuteModelValidationError(ValueError):
    """A policy, artifact, history, context, or prediction is invalid."""


@dataclass(frozen=True)
class _MinuteHistoryRow:
    """The identity/temporal subset needed by conditional minutes.

    Canonical MIN-007 history is parsed through :class:`HistoryRow`.  Small
    synthetic weighting fixtures intentionally omit presentation-only fields
    and use readable example IDs, so they are accepted by this narrower,
    fail-closed parser as well.
    """

    evidence_type: str
    example_id: str
    fixture_id: str
    feature_cutoff: datetime
    label_usable_at: datetime
    manager_regime_id: str
    minutes_label: int
    player_id: str
    position: Position
    role_label: Literal["START", "BENCH", "OUT"]
    sequence_index: int
    team_id: str
    team_key: str


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decimal(value: object, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise MinuteModelValidationError(f"{label} must not be a float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        try:
            return Decimal(value)
        except Exception as exc:
            raise MinuteModelValidationError(f"{label} must be a decimal") from exc
    raise MinuteModelValidationError(f"{label} must be a decimal")


def _serial_decimal(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        return format(value.quantize(SERIAL_SCALE), ".12f")


def _public_vector(values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Round for JSON and put the exact residual on the largest raw bin."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        quantized = [value.quantize(SERIAL_SCALE) for value in values]
        residual = Decimal(1) - sum(quantized, Decimal(0))
        if residual:
            index = max(range(len(values)), key=lambda item: (values[item], -item))
            quantized[index] += residual
        if sum(quantized, Decimal(0)) != Decimal(1):
            raise MinuteModelValidationError("minute-vector residual correction failed")
        return tuple(quantized)


def _validate_stored_pmf(values: Sequence[Decimal], *, role: str) -> None:
    """Validate the exact stored Decimal PMF invariant."""

    if len(values) != MINUTE_COUNT:
        raise MinuteModelValidationError("minute_pmf must contain 91 Decimal bins")
    for value in values:
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise MinuteModelValidationError("minute_pmf must contain finite non-negative Decimals")
    if role == "START" and values[0] != Decimal(0):
        raise MinuteModelValidationError("START minute zero must be zero")
    if not exact_sum_equals_one(values):
        raise MinuteModelValidationError("minute_pmf does not sum exactly to one")


def _correct_stored_pmf(values: Sequence[Decimal], *, role: str) -> tuple[Decimal, ...]:
    """Apply an internal high-precision residual without public rounding."""

    if len(values) != MINUTE_COUNT:
        raise MinuteModelValidationError("minute_pmf must contain 91 Decimal bins")
    for value in values:
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise MinuteModelValidationError("minute_pmf must contain finite non-negative Decimals")
    correction_index = max(range(MINUTE_COUNT), key=lambda index: (values[index], -index))
    if role == "START" and correction_index == 0:
        raise MinuteModelValidationError("START minute zero cannot receive simplex correction")
    corrected = list(values)
    other_sum = exact_decimal_sum(
        value for index, value in enumerate(values) if index != correction_index
    )
    corrected[correction_index] = exact_one_minus(other_sum)
    _validate_stored_pmf(tuple(corrected), role=role)
    return tuple(corrected)


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise MinuteModelValidationError(f"{label} must be a mapping or validated model")


def _coerce_priors(value: object) -> dict[str, dict[str, tuple[Decimal, ...]]]:
    if not isinstance(value, Mapping):
        raise MinuteModelValidationError("minute_priors must be a mapping")
    result: dict[str, dict[str, tuple[Decimal, ...]]] = {}
    for position, raw_roles in value.items():
        if not isinstance(position, str) or not isinstance(raw_roles, Mapping):
            raise MinuteModelValidationError("minute_priors positions are invalid")
        roles: dict[str, tuple[Decimal, ...]] = {}
        for role, raw_values in raw_roles.items():
            if (
                not isinstance(role, str)
                or not isinstance(raw_values, Sequence)
                or isinstance(raw_values, (str, bytes, bytearray))
            ):
                raise MinuteModelValidationError("minute_priors role vectors are invalid")
            roles[role] = tuple(
                _decimal(item, label=f"minute_priors.{position}.{role}[{index}]")
                for index, item in enumerate(raw_values)
            )
        result[position] = roles
    return result


class MinutePriorArtifact(_FrozenModel):
    """Immutable position/role minute prior artifact."""

    schema_version: Literal["minute-prior-artifact-v1"]
    model_family: str
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_example_count: int = Field(ge=0)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    minute_prior_strength: str
    minute_bin_alpha: str
    probability_decimal_places: int = Field(ge=1)
    rounding_mode: Literal["ROUND_HALF_EVEN"]
    minute_priors: dict[str, dict[str, tuple[Decimal, ...]]]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def coerce_vectors(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if "minute_priors" in data:
            data["minute_priors"] = _coerce_priors(data["minute_priors"])
        return data

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.artifact_sha256 != MINUTE_ARTIFACT_SHA256:
            raise MinuteModelValidationError("minute artifact identity is not frozen")
        if self.policy_sha256 != FROZEN_POLICY_SHA256:
            raise MinuteModelValidationError("minute artifact policy lineage is not frozen")
        if self.training_dataset_sha256 != TRAINING_DATASET_SHA256:
            raise MinuteModelValidationError("minute artifact training lineage is not frozen")
        if self.training_example_count != 368:
            raise MinuteModelValidationError("minute artifact training count is not frozen")
        if self.probability_decimal_places != 12:
            raise MinuteModelValidationError("minute artifact precision is not frozen")
        if self.minute_prior_strength != "3.000000" or self.minute_bin_alpha != "0.050000":
            raise MinuteModelValidationError("minute artifact prior constants are not frozen")
        if set(self.minute_priors) != set(POSITION_ORDER):
            raise MinuteModelValidationError("minute artifact positions are incomplete or unknown")
        for position in POSITION_ORDER:
            roles = self.minute_priors[position]
            if set(roles) != set(MINUTE_ROLE_ORDER):
                raise MinuteModelValidationError("minute artifact roles are incomplete or unknown")
            for role in MINUTE_ROLE_ORDER:
                vector = roles[role]
                if len(vector) != MINUTE_COUNT or any(value < 0 for value in vector):
                    raise MinuteModelValidationError("minute artifact vectors are invalid")
                if not exact_sum_equals_one(vector):
                    raise MinuteModelValidationError("minute artifact vector does not sum to one")
                if role == "START" and vector[0] != Decimal(0):
                    raise MinuteModelValidationError("START minute zero must be zero")
        body = self._body_json()
        if _canonical_sha256(body) != self.artifact_sha256:
            raise MinuteModelValidationError("minute artifact semantic identity is invalid")
        return self

    def _body_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_family": self.model_family,
            "training_dataset_sha256": self.training_dataset_sha256,
            "training_example_count": self.training_example_count,
            "policy_sha256": self.policy_sha256,
            "minute_prior_strength": self.minute_prior_strength,
            "minute_bin_alpha": self.minute_bin_alpha,
            "probability_decimal_places": self.probability_decimal_places,
            "rounding_mode": self.rounding_mode,
            "minute_priors": {
                position: {
                    role: [_serial_decimal(value) for value in self.minute_priors[position][role]]
                    for role in MINUTE_ROLE_ORDER
                }
                for position in POSITION_ORDER
            },
        }

    @field_serializer("minute_priors", when_used="json")
    def serialize_priors(
        self, value: dict[str, dict[str, tuple[Decimal, ...]]]
    ) -> dict[str, dict[str, list[str]]]:
        return {
            position: {
                role: [_serial_decimal(item) for item in value[position][role]]
                for role in MINUTE_ROLE_ORDER
            }
            for position in POSITION_ORDER
        }


class MinuteConditionalPrediction(_FrozenModel):
    """A conditional 91-bin minute PMF for one player and requested role."""

    player_id: str = Field(min_length=1)
    position: Position
    role: Literal["START", "BENCH"]
    eligible_history_count: int = Field(ge=0)
    matching_role_history_count: int = Field(ge=0)
    minute_pmf: tuple[Decimal, ...]

    @model_validator(mode="after")
    def validate_prediction(self) -> Self:
        try:
            UUID(self.player_id)
        except ValueError as exc:
            raise MinuteModelValidationError("player_id must be a UUID string") from exc
        _validate_stored_pmf(self.minute_pmf, role=self.role)
        if self.matching_role_history_count > self.eligible_history_count:
            raise MinuteModelValidationError("matching history count exceeds eligible history")
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Revalidate merged updates instead of using Pydantic's unsafe copy path."""

        del deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(dict(update))
        return type(self).model_validate(data)

    @field_serializer("minute_pmf", when_used="json")
    def serialize_pmf(self, value: tuple[Decimal, ...]) -> list[str]:
        return [_serial_decimal(item) for item in _public_vector(value)]


def _artifact_mapping(artifact: object) -> MinutePriorArtifact:
    try:
        return MinutePriorArtifact.model_validate(_mapping(artifact, label="artifact"))
    except (ValidationError, MinuteModelValidationError) as exc:
        if isinstance(exc, MinuteModelValidationError):
            raise
        raise MinuteModelValidationError("minute artifact failed schema validation") from exc


def _training_rows_checked(training_dataset: object) -> tuple[HistoryRow, ...]:
    try:
        return _training_rows(training_dataset)
    except (RoleModelValidationError, ValidationError, ValueError) as exc:
        raise MinuteModelValidationError(
            "training dataset is not the frozen MIN-007B dataset"
        ) from exc


def _history_rows_checked(history: object) -> tuple[_MinuteHistoryRow, ...]:
    value = _mapping(history, label="history")
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes, bytearray)):
        raise MinuteModelValidationError("history must contain a rows sequence")
    rows: list[_MinuteHistoryRow] = []
    seen_examples: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    for raw in raw_rows:
        if isinstance(raw, HistoryRow):
            row = raw
            parsed = _MinuteHistoryRow(
                evidence_type=row.evidence_type,
                example_id=str(row.example_id),
                fixture_id=str(row.fixture_id),
                feature_cutoff=row.feature_cutoff,
                label_usable_at=row.label_usable_at,
                manager_regime_id=str(row.manager_regime_id),
                minutes_label=row.minutes_label,
                player_id=str(row.player_id),
                position=row.position,
                role_label=row.role_label,
                sequence_index=row.sequence_index,
                team_id=str(row.team_id),
                team_key=row.team_key,
            )
        elif isinstance(raw, Mapping):
            try:
                try:
                    strict = HistoryRow.model_validate(raw)
                except (ValidationError, ValueError):
                    # The frozen mixed-weight fixture is intentionally a
                    # reduced history shape.  Validate every field used by
                    # the minutes contract without inventing missing labels.
                    required = (
                        "evidence_type",
                        "feature_cutoff",
                        "label_usable_at",
                        "manager_regime_id",
                        "minutes_label",
                        "player_id",
                        "position",
                        "role_label",
                        "sequence_index",
                        "team_id",
                        "team_key",
                    )
                    allowed = set(required) | {
                        "example_id",
                        "fixture_id",
                        "fixture_key",
                        "player_key",
                        "split",
                    }
                    if any(name not in raw for name in required):
                        raise MinuteModelValidationError(
                            "history row is missing a required field"
                        ) from None
                    if set(raw) - allowed:
                        raise MinuteModelValidationError(
                            "history row contains unknown fields"
                        ) from None
                    evidence = raw["evidence_type"]
                    if not isinstance(evidence, str) or evidence not in {
                        "COMPETITIVE",
                        "PRESEASON",
                    }:
                        raise MinuteModelValidationError(
                            "history evidence type is not supported"
                        ) from None
                    position = raw["position"]
                    role = raw["role_label"]
                    if (
                        not isinstance(position, str)
                        or position not in POSITION_ORDER
                        or not isinstance(role, str)
                        or role not in {"START", "BENCH", "OUT"}
                    ):
                        raise MinuteModelValidationError(
                            "history position or role is invalid"
                        ) from None
                    minutes = raw["minutes_label"]
                    sequence = raw["sequence_index"]
                    if (
                        isinstance(minutes, bool)
                        or not isinstance(minutes, int)
                        or not 0 <= minutes <= 90
                        or isinstance(sequence, bool)
                        or not isinstance(sequence, int)
                        or sequence < 1
                    ):
                        raise MinuteModelValidationError(
                            "history minute or sequence is invalid"
                        ) from None
                    if role == "START" and minutes == 0:
                        raise MinuteModelValidationError(
                            "START requires positive minutes"
                        ) from None
                    if role == "OUT" and minutes != 0:
                        raise MinuteModelValidationError("OUT requires zero minutes") from None

                    def uuid_text(item: object, label: str) -> str:
                        if not isinstance(item, str):
                            raise MinuteModelValidationError(f"{label} must be a UUID string")
                        try:
                            return str(UUID(item))
                        except ValueError as exc:
                            raise MinuteModelValidationError(
                                f"{label} must be a UUID string"
                            ) from exc

                    player = uuid_text(raw["player_id"], "history.player_id")
                    team = uuid_text(raw["team_id"], "history.team_id")
                    manager = uuid_text(raw["manager_regime_id"], "history.manager_regime_id")
                    if not isinstance(raw["team_key"], str) or not raw["team_key"]:
                        raise MinuteModelValidationError(
                            "history.team_key must be non-empty"
                        ) from None
                    example = raw.get("example_id")
                    if not isinstance(example, str) or not example:
                        raise MinuteModelValidationError(
                            "history.example_id must be non-empty"
                        ) from None
                    feature = parse_utc(raw["feature_cutoff"], field_name="feature_cutoff")
                    usable = parse_utc(raw["label_usable_at"], field_name="label_usable_at")
                    parsed = _MinuteHistoryRow(
                        evidence_type=evidence,
                        example_id=example,
                        fixture_id=(
                            uuid_text(raw["fixture_id"], "history.fixture_id")
                            if "fixture_id" in raw
                            else example
                        ),
                        feature_cutoff=feature,
                        label_usable_at=usable,
                        manager_regime_id=manager,
                        minutes_label=minutes,
                        player_id=player,
                        position=position,
                        role_label=cast(Literal["START", "BENCH", "OUT"], role),
                        sequence_index=sequence,
                        team_id=team,
                        team_key=raw["team_key"],
                    )
                else:
                    parsed = _MinuteHistoryRow(
                        evidence_type=str(strict.evidence_type),
                        example_id=str(strict.example_id),
                        fixture_id=str(strict.fixture_id),
                        feature_cutoff=strict.feature_cutoff,
                        label_usable_at=strict.label_usable_at,
                        manager_regime_id=str(strict.manager_regime_id),
                        minutes_label=strict.minutes_label,
                        player_id=str(strict.player_id),
                        position=strict.position,
                        role_label=strict.role_label,
                        sequence_index=strict.sequence_index,
                        team_id=str(strict.team_id),
                        team_key=strict.team_key,
                    )
            except (ValidationError, ValueError, TypeError) as exc:
                if isinstance(exc, MinuteModelValidationError):
                    raise
                raise MinuteModelValidationError("history row is invalid") from exc
        else:
            raise MinuteModelValidationError("history rows must be mappings")
        if parsed.evidence_type not in {"COMPETITIVE", "PRESEASON"}:
            raise MinuteModelValidationError("history evidence type is not supported")
        try:
            example_identity = str(UUID(parsed.example_id))
        except ValueError:
            example_identity = parsed.example_id
        if example_identity in seen_examples:
            raise MinuteModelValidationError("history contains duplicate example_id")
        target = (parsed.player_id, parsed.fixture_id)
        if target in seen_targets:
            raise MinuteModelValidationError("history contains duplicate player-fixture target")
        seen_examples.add(example_identity)
        seen_targets.add(target)
        rows.append(parsed)
    return tuple(rows)


def _policy_checked(policy: object) -> dict[str, Any]:
    try:
        return _policy_mapping(policy)
    except (RoleModelValidationError, ValidationError, ValueError) as exc:
        raise MinuteModelValidationError("policy does not match the frozen minutes policy") from exc


def _context_checked(context: object) -> dict[str, Any]:
    try:
        return _context_mapping(context)
    except (RoleModelValidationError, ValidationError, ValueError) as exc:
        raise MinuteModelValidationError("prediction context is invalid") from exc


def fit_minute_priors(training_dataset: object, *, policy: object) -> MinutePriorArtifact:
    """Fit frozen position/role minute priors from the accepted training set."""

    policy_value = _policy_checked(policy)
    rows = _training_rows_checked(training_dataset)
    counts: dict[Position, dict[str, dict[int, Decimal]]] = {
        position: {
            role: {minute: Decimal(0) for minute in range(MINUTE_COUNT)}
            for role in MINUTE_ROLE_ORDER
        }
        for position in POSITION_ORDER
    }
    for row in rows:
        if row.role_label in MINUTE_ROLE_ORDER:
            counts[row.position][row.role_label][row.minutes_label] += Decimal(1)

    priors: dict[str, dict[str, list[str]]] = {}
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        alpha = _decimal(policy_value["minute_bin_alpha"], label="minute_bin_alpha")
        for position in POSITION_ORDER:
            priors[position] = {}
            for role in MINUTE_ROLE_ORDER:
                valid = range(1, MINUTE_COUNT) if role == "START" else range(MINUTE_COUNT)
                values = [counts[position][role][minute] + alpha for minute in valid]
                total = sum(values, Decimal(0))
                raw = [Decimal(0)] * MINUTE_COUNT
                for minute, value in zip(valid, values, strict=True):
                    raw[minute] = value / total
                priors[position][role] = [_serial_decimal(item) for item in _public_vector(raw)]
    body = {
        "schema_version": "minute-prior-artifact-v1",
        "model_family": policy_value["model_family"],
        "training_dataset_sha256": TRAINING_DATASET_SHA256,
        "training_example_count": len(rows),
        "policy_sha256": FROZEN_POLICY_SHA256,
        "minute_prior_strength": policy_value["minute_prior_strength"],
        "minute_bin_alpha": policy_value["minute_bin_alpha"],
        "probability_decimal_places": policy_value["probability_decimal_places"],
        "rounding_mode": policy_value["rounding_mode"],
        "minute_priors": priors,
    }
    artifact = dict(body)
    artifact["artifact_sha256"] = _canonical_sha256(body)
    if artifact["artifact_sha256"] != MINUTE_ARTIFACT_SHA256:
        raise MinuteModelValidationError("fitted minute artifact does not match frozen identity")
    try:
        return MinutePriorArtifact.model_validate(artifact)
    except (ValidationError, MinuteModelValidationError) as exc:
        if isinstance(exc, MinuteModelValidationError):
            raise
        raise MinuteModelValidationError("fitted minute artifact failed schema validation") from exc


def _eligible_rows(
    rows: Sequence[_MinuteHistoryRow], player_id: str, context: Mapping[str, Any], window: int
) -> tuple[_MinuteHistoryRow, ...]:
    as_of = context["as_of"]
    eligible = [
        row
        for row in rows
        if str(row.player_id) == player_id
        and row.team_key == context["team_key"]
        and str(row.team_id) == context["team_id"]
        and row.sequence_index < context["cutoff_sequence_index"]
        and row.feature_cutoff < as_of
        and row.label_usable_at <= as_of
    ]
    eligible.sort(key=lambda row: (-row.sequence_index, str(row.example_id)))
    return tuple(eligible[:window])


def predict_conditional_minutes(
    history: object,
    artifact: object,
    *,
    context: object,
    player_id: str,
    position: Position,
    role: Literal["START", "BENCH"],
    policy: object,
) -> MinuteConditionalPrediction:
    """Return a cutoff-safe Decimal PMF conditional on one requested role."""

    policy_value = _policy_checked(policy)
    artifact_value = _artifact_mapping(artifact)
    rows = _history_rows_checked(history)
    context_value = _context_checked(context)
    if not isinstance(player_id, str):
        raise MinuteModelValidationError("player_id must be a UUID string")
    try:
        player_uuid = str(UUID(player_id))
    except ValueError as exc:
        raise MinuteModelValidationError("player_id must be a UUID string") from exc
    if not isinstance(position, str) or position not in POSITION_ORDER:
        raise MinuteModelValidationError("position is invalid")
    if not isinstance(role, str) or role not in MINUTE_ROLE_ORDER:
        raise MinuteModelValidationError("role must be START or BENCH")
    retained = _eligible_rows(rows, player_uuid, context_value, int(policy_value["history_window"]))
    with localcontext() as decimal_context:
        decimal_context.prec = DECIMAL_PRECISION
        decimal_context.rounding = ROUNDING_MODE
        prior_strength = _decimal(
            policy_value["minute_prior_strength"], label="minute_prior_strength"
        )
        counts = [prior_strength * value for value in artifact_value.minute_priors[position][role]]
        matching = 0
        recency = _decimal(policy_value["recency_decay"], label="recency_decay")
        old_manager = _decimal(
            policy_value["old_manager_multiplier"], label="old_manager_multiplier"
        )
        preseason = _decimal(policy_value["preseason_multiplier"], label="preseason_multiplier")
        for age, row in enumerate(retained):
            if row.role_label != role:
                continue
            multiplier = Decimal(1)
            if str(row.manager_regime_id) != context_value["manager_regime_id"]:
                multiplier *= old_manager
            if row.evidence_type == "PRESEASON":
                multiplier *= preseason
            counts[row.minutes_label] += (recency**age) * multiplier
            matching += 1
        total = sum(counts, Decimal(0))
        if total <= 0:
            raise MinuteModelValidationError("minute PMF has no positive mass")
        pmf = _correct_stored_pmf(tuple(value / total for value in counts), role=role)
    try:
        return MinuteConditionalPrediction.model_validate(
            {
                "player_id": player_uuid,
                "position": position,
                "role": role,
                "eligible_history_count": len(retained),
                "matching_role_history_count": matching,
                "minute_pmf": pmf,
            }
        )
    except (ValidationError, MinuteModelValidationError) as exc:
        if isinstance(exc, MinuteModelValidationError):
            raise
        raise MinuteModelValidationError(
            "conditional minute prediction failed schema validation"
        ) from exc


__all__ = [
    "DECIMAL_PRECISION",
    "MINUTE_ARTIFACT_SHA256",
    "MINUTE_COUNT",
    "MinuteConditionalPrediction",
    "MinuteModelValidationError",
    "MinutePriorArtifact",
    "fit_minute_priors",
    "predict_conditional_minutes",
]
