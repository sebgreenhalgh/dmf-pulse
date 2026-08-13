"""Strict public minutes projection contracts and exact Decimal composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DECIMAL_PRECISION = 60
PROBABILITY_SCALE = Decimal("0.000000000001")
MINUTES_SCALE = Decimal("0.000001")
POSITIONS = ("GK", "DEF", "MID", "FWD")
ROLES = ("START", "BENCH", "OUT")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def _decimal(value: object, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError(f"{label} must use an exact decimal representation")
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValueError(f"{label} must be decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _probability(value: object, *, label: str) -> Decimal:
    result = _decimal(value, label=label)
    if result < 0 or result > 1:
        raise ValueError(f"{label} must be in [0,1]")
    return result


def _public_probability(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(PROBABILITY_SCALE), ".12f")


def _public_minutes(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(MINUTES_SCALE), ".6f")


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="python")
        if isinstance(result, Mapping):
            return dict(result)
    raise TypeError(f"{label} must be a mapping or model")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep
        data = self.model_dump(mode="python", exclude_none=False)
        if update:
            data.update(dict(update))
        return type(self).model_validate(data)


class PlayerMinutesProjection(_FrozenModel):
    player_id: str
    position: Literal["GK", "DEF", "MID", "FWD"]
    p_start: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    p_bench: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    p_out_of_squad: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    p_appearance: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    p_zero_minutes: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    p_60_plus: str = Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")
    expected_minutes: str = Field(pattern=r"^(?:[0-8]?\d|90)\.\d{6}$")
    minute_pmf: tuple[str, ...]
    confidence_grade: Literal["A", "B", "C", "D"]
    confidence_reasons: tuple[
        Literal[
            "HARD_INELIGIBLE_OVERRIDE",
            "NO_TARGET_TEAM_COMPETITIVE_HISTORY",
            "THIN_PLAYER_HISTORY",
            "NEW_SIGNING",
            "NEW_MANAGER_REGIME",
            "PROMOTED_TEAM_EARLY_REGIME",
            "BASELINE_MODEL_CAP_B",
        ],
        ...,
    ]
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def coerce_sequences(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if isinstance(data.get("minute_pmf"), list):
            data["minute_pmf"] = tuple(data["minute_pmf"])
        if isinstance(data.get("confidence_reasons"), list):
            data["confidence_reasons"] = tuple(data["confidence_reasons"])
        return data

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        try:
            UUID(self.player_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("player_id must be a UUID") from exc
        if len(self.minute_pmf) != 91:
            raise ValueError("minute_pmf must contain 91 bins")
        if any(
            not isinstance(item, str) or len(item) != 14 or item[1] != "."
            for item in self.minute_pmf
        ):
            raise ValueError("minute_pmf values must be 12-decimal strings")
        probabilities = tuple(_probability(v, label="minute_pmf") for v in self.minute_pmf)
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            if sum(probabilities, Decimal(0)) != Decimal(1):
                raise ValueError("minute_pmf must sum exactly to one")
            p_start = _probability(self.p_start, label="p_start")
            p_bench = _probability(self.p_bench, label="p_bench")
            p_out = _probability(self.p_out_of_squad, label="p_out_of_squad")
            p_zero = _probability(self.p_zero_minutes, label="p_zero_minutes")
            p_appearance = _probability(self.p_appearance, label="p_appearance")
            p_60 = _probability(self.p_60_plus, label="p_60_plus")
            if p_start + p_bench + p_out != Decimal(1):
                raise ValueError("role probabilities must sum exactly to one")
            if p_zero != probabilities[0] or p_appearance != Decimal(1) - p_zero:
                raise ValueError("derived appearance probabilities are inconsistent")
            if p_60 != sum(probabilities[60:], Decimal(0)):
                raise ValueError("derived p_60_plus is inconsistent")
            expected = sum(
                (Decimal(i) * value for i, value in enumerate(probabilities)), Decimal(0)
            )
            if _public_minutes(expected) != self.expected_minutes:
                raise ValueError("derived expected_minutes is inconsistent")
        if len(set(self.confidence_reasons)) != len(self.confidence_reasons):
            raise ValueError("confidence_reasons must be unique")
        body = self.model_dump(mode="json")
        supplied = body.pop("projection_sha256")
        if canonical_sha256(body) != supplied:
            raise ValueError("projection_sha256 does not match public fields")
        return self


class TeamMinutesProjection(_FrozenModel):
    schema_version: Literal["team-minutes-projection-v1"]
    fixture_id: str
    team_id: str
    as_of: str
    model_family: Literal["REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: Literal[256]
    bench_size: int = Field(ge=0)
    bench_goalkeeper_slots: int = Field(ge=0)
    players: tuple[PlayerMinutesProjection, ...]
    scenario_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sum_p_start: str = Field(pattern=r"^\d+\.\d{12}$")
    sum_p_bench: str = Field(pattern=r"^\d+\.\d{12}$")
    sum_p_out: str = Field(pattern=r"^\d+\.\d{12}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def coerce_players(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if isinstance(data.get("players"), list):
            data["players"] = tuple(data["players"])
        return data

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        for label, value in (("fixture_id", self.fixture_id), ("team_id", self.team_id)):
            try:
                UUID(value)
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"{label} must be a UUID") from exc
        try:
            parsed = datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("as_of must be an RFC3339 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("as_of must be timezone-aware UTC")
        if self.bench_goalkeeper_slots > self.bench_size:
            raise ValueError("bench goalkeeper slots exceed bench size")
        ids = [player.player_id for player in self.players]
        if len(ids) < 11 or len(ids) != len(set(ids)):
            raise ValueError("players must contain unique canonical IDs")
        if ids != sorted(ids):
            raise ValueError("players must be sorted by canonical player_id")
        for label, expected in (
            (
                "sum_p_start",
                sum((_decimal(p.p_start, label="p_start") for p in self.players), Decimal(0)),
            ),
            (
                "sum_p_bench",
                sum((_decimal(p.p_bench, label="p_bench") for p in self.players), Decimal(0)),
            ),
            (
                "sum_p_out",
                sum((_decimal(p.p_out_of_squad, label="p_out") for p in self.players), Decimal(0)),
            ),
        ):
            if _public_probability(expected) != getattr(self, label):
                raise ValueError(f"{label} does not match player rows")
        body = self.model_dump(mode="json")
        supplied = body.pop("result_sha256")
        if canonical_sha256(body) != supplied:
            raise ValueError("result_sha256 does not match public fields")
        return self


class MinutesPredictionResult(_FrozenModel):
    status: Literal["PROJECTED", "BLOCKED"]
    fixture_id: str
    team_id: str
    as_of: str
    projection: TeamMinutesProjection | None
    error_code: str | None
    first_scenarios: tuple[dict[str, Any], ...] = Field(default=(), exclude=True)
    player_keys: tuple[tuple[str, str], ...] = Field(default=(), exclude=True)
    core_role_marginals: tuple[dict[str, Any], ...] = Field(default=(), exclude=True)
    core_minute_pmfs: tuple[dict[str, Any], ...] = Field(default=(), exclude=True)
    core_scenarios: tuple[dict[str, Any], ...] = Field(default=(), exclude=True)
    core_hard_eligibility: tuple[dict[str, Any], ...] = Field(default=(), exclude=True)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        try:
            UUID(self.fixture_id)
            UUID(self.team_id)
            parsed = datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("prediction result identifiers/timestamp are invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("prediction result as_of must be UTC")
        if self.status == "PROJECTED" and (self.projection is None or self.error_code is not None):
            raise ValueError("projected results require a projection and no error")
        if self.status == "BLOCKED" and (self.projection is not None or not self.error_code):
            raise ValueError("blocked results require an error and no projection")
        if (
            self.status == "PROJECTED"
            and self.projection is not None
            and (
                self.fixture_id != self.projection.fixture_id
                or self.team_id != self.projection.team_id
                or self.as_of != self.projection.as_of
            )
        ):
            raise ValueError("outer prediction identity does not match nested projection")
        return self


def _rounded_pmf(values: Sequence[Decimal]) -> tuple[str, ...]:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        rounded = [value.quantize(PROBABILITY_SCALE) for value in values]
        residual = Decimal(1) - sum(rounded, Decimal(0))
        if residual:
            index = max(range(len(values)), key=lambda item: (values[item], -item))
            rounded[index] += residual
        if sum(rounded, Decimal(0)) != Decimal(1):
            raise ValueError("rounded PMF does not sum to one")
        return tuple(format(value, ".12f") for value in rounded)


def _field(value: object, name: str) -> Any:
    if hasattr(value, name):
        return getattr(value, name)
    return _mapping(value, label=name).get(name)


def compose_player_minutes_projection(
    role_marginal: object,
    start_prediction: object,
    bench_prediction: object,
    *,
    confidence_grade: str,
    confidence_reasons: Sequence[str],
) -> PlayerMinutesProjection:
    """Compose exact role marginals and accepted conditional PMFs into public fields."""

    p_start = _decimal(_field(role_marginal, "p_start"), label="p_start")
    p_bench = _decimal(_field(role_marginal, "p_bench"), label="p_bench")
    p_out = _decimal(_field(role_marginal, "p_out"), label="p_out")
    start_pmf = tuple(
        _decimal(item, label="start minute PMF") for item in _field(start_prediction, "minute_pmf")
    )
    bench_pmf = tuple(
        _decimal(item, label="bench minute PMF") for item in _field(bench_prediction, "minute_pmf")
    )
    if len(start_pmf) != 91 or len(bench_pmf) != 91:
        raise ValueError("conditional minute PMFs must have 91 bins")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        overall = tuple(
            p_start * start_pmf[index]
            + p_bench * bench_pmf[index]
            + (p_out if index == 0 else Decimal(0))
            for index in range(91)
        )
        public_pmf = _rounded_pmf(overall)
        p_zero = _decimal(public_pmf[0], label="p_zero")
        p_appearance = Decimal(1) - p_zero
        p_60 = sum((_decimal(item, label="public PMF") for item in public_pmf[60:]), Decimal(0))
        expected = sum(
            (
                Decimal(index) * _decimal(item, label="public PMF")
                for index, item in enumerate(public_pmf)
            ),
            Decimal(0),
        )
    body: dict[str, Any] = {
        "player_id": str(_field(role_marginal, "player_id")),
        "position": _field(role_marginal, "position"),
        "p_start": _public_probability(p_start),
        "p_bench": _public_probability(p_bench),
        "p_out_of_squad": _public_probability(p_out),
        "p_appearance": _public_probability(p_appearance),
        "p_zero_minutes": _public_probability(p_zero),
        "p_60_plus": _public_probability(p_60),
        "expected_minutes": _public_minutes(expected),
        "minute_pmf": public_pmf,
        "confidence_grade": confidence_grade,
        "confidence_reasons": tuple(confidence_reasons),
    }
    body["projection_sha256"] = canonical_sha256(body)
    return PlayerMinutesProjection.model_validate(body)


def compose_team_minutes_projection(
    lineup_result: object,
    players: Sequence[PlayerMinutesProjection],
    *,
    as_of: str,
    model_family: str,
    dataset_sha256: str,
    model_artifact_sha256: str,
) -> TeamMinutesProjection:
    """Build the public team projection from accepted E scenarios and player rows."""

    player_rows = tuple(sorted(players, key=lambda item: item.player_id))
    scenario_hash = str(_field(lineup_result, "scenario_set_sha256"))
    body: dict[str, Any] = {
        "schema_version": "team-minutes-projection-v1",
        "fixture_id": str(_field(lineup_result, "fixture_id")),
        "team_id": str(_field(lineup_result, "team_id")),
        "as_of": as_of,
        "model_family": model_family,
        "dataset_sha256": dataset_sha256,
        "model_artifact_sha256": model_artifact_sha256,
        "sample_count": int(_field(lineup_result, "sample_count")),
        "bench_size": int(_field(lineup_result, "bench_size")),
        "bench_goalkeeper_slots": int(_field(lineup_result, "bench_goalkeeper_slots")),
        "players": player_rows,
        "scenario_set_sha256": scenario_hash,
        "sum_p_start": _public_probability(
            sum((_decimal(p.p_start, label="p_start") for p in player_rows), Decimal(0))
        ),
        "sum_p_bench": _public_probability(
            sum((_decimal(p.p_bench, label="p_bench") for p in player_rows), Decimal(0))
        ),
        "sum_p_out": _public_probability(
            sum((_decimal(p.p_out_of_squad, label="p_out") for p in player_rows), Decimal(0))
        ),
    }
    hash_body = dict(body)
    hash_body["players"] = [item.model_dump(mode="json") for item in player_rows]
    body["result_sha256"] = canonical_sha256(hash_body)
    return TeamMinutesProjection.model_validate(body)


__all__ = [
    "MinutesPredictionResult",
    "PlayerMinutesProjection",
    "TeamMinutesProjection",
    "canonical_sha256",
    "compose_player_minutes_projection",
    "compose_team_minutes_projection",
]
