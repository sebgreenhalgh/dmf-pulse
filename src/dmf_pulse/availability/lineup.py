"""Deterministic coherent XI/bench scenario sampling for MIN-007E.

The sampler is intentionally independent of the role and minute fitting
stages.  It consumes explicit START/BENCH weights and uses only Decimal
arithmetic plus SHA-256-derived race keys, so repeated calls are reproducible
without a random-number generator or ambient state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    model_validator,
)

from dmf_pulse.availability.role_model import (
    RoleModelValidationError,
    _policy_mapping,
)

DECIMAL_PRECISION = 60
ROUNDING_MODE = ROUND_HALF_EVEN
SAMPLER_ID = "DETERMINISTIC_EXPONENTIAL_RACE_V1"
COHERENCE_MODEL = "COHERENCE_MODEL_V1"
POLICY_SEED = "MIN-007-COHERENCE-V1"
SAMPLE_COUNT: Literal[256] = 256
PHASES: tuple[str, ...] = (
    "START_GK",
    "START_OUTFIELD",
    "BENCH_GK",
    "BENCH_OUTFIELD",
)
POSITION_ORDER = ("GK", "DEF", "MID", "FWD")


class LineupModelValidationError(ValueError):
    """An input or generated lineup result violates the frozen contract."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


@dataclass(frozen=True)
class _Candidate:
    player_id: str
    player_key: str
    position: str
    start_weight: Decimal
    bench_weight: Decimal
    hard_ineligible: bool


class ScenarioMember(_FrozenModel):
    player_id: str
    role: Literal["START", "BENCH", "OUT"]
    position: Literal["GK", "DEF", "MID", "FWD"]


class LineupScenario(_FrozenModel):
    scenario_index: int = Field(ge=0, lt=SAMPLE_COUNT)
    starters: tuple[str, ...]
    bench: tuple[str, ...]
    members: tuple[ScenarioMember, ...]
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FirstScenario(_FrozenModel):
    scenario_index: int = Field(ge=0, lt=SAMPLE_COUNT)
    starters: tuple[str, ...]
    bench: tuple[str, ...]
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RoleMarginal(_FrozenModel):
    player_id: str
    player_key: str
    position: Literal["GK", "DEF", "MID", "FWD"]
    p_start: Decimal
    p_bench: Decimal
    p_out: Decimal

    @model_validator(mode="after")
    def validate_vector(self) -> Self:
        values = (self.p_start, self.p_bench, self.p_out)
        if any(value < 0 for value in values) or sum(values, Decimal(0)) != Decimal(1):
            raise LineupModelValidationError("role marginal must be non-negative and sum to one")
        return self

    @field_serializer("p_start", "p_bench", "p_out", when_used="json")
    def serialize_probability(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.000000000001"), rounding=ROUNDING_MODE), ".12f")


class ProjectedLineupResult(_FrozenModel):
    status: Literal["PROJECTED"]
    fixture_id: str
    team_id: str
    sample_count: Literal[256]
    bench_size: int = Field(ge=0)
    bench_goalkeeper_slots: int = Field(ge=0)
    scenarios: tuple[LineupScenario, ...]
    first_scenarios: tuple[FirstScenario, ...]
    scenario_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role_marginals: tuple[RoleMarginal, ...]
    sum_p_start: Decimal
    sum_p_bench: Decimal
    sum_p_out: Decimal

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if len(self.scenarios) != SAMPLE_COUNT or len(self.first_scenarios) != 3:
            raise LineupModelValidationError("projected result has the wrong scenario count")
        if self.sum_p_start != Decimal(11):
            raise LineupModelValidationError("starting marginal sum is not eleven")
        if self.sum_p_bench != Decimal(self.bench_size):
            raise LineupModelValidationError("bench marginal sum is not configured bench size")
        expected_out = len(self.role_marginals) - 11 - self.bench_size
        if self.sum_p_out != Decimal(expected_out):
            raise LineupModelValidationError("OUT marginal sum is inconsistent")
        return self

    @field_serializer("sum_p_start", "sum_p_bench", "sum_p_out", when_used="json")
    def serialize_sum(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.000000000001"), rounding=ROUNDING_MODE), ".12f")

    @property
    def semantic_sha256(self) -> str:
        """Hash the compact projected output, excluding full scenario detail."""

        body = self.model_dump(mode="json")
        body.pop("scenarios", None)
        return _canonical_sha256(body)


class BlockedLineupResult(_FrozenModel):
    status: Literal["BLOCKED"]
    error_code: Literal["INSUFFICIENT_ELIGIBLE_SQUAD"]
    fixture_id: str
    team_id: str
    sample_count: Literal[256]

    @property
    def semantic_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class InvalidLineupResult(_FrozenModel):
    status: Literal["INVALID"]
    error_code: str

    @property
    def semantic_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


LineupResult = ProjectedLineupResult | BlockedLineupResult | InvalidLineupResult


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
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
    raise LineupModelValidationError(f"{label} must be a mapping")


def _decimal(value: object, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise LineupModelValidationError(f"{label} must be a Decimal-compatible string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (str, int)):
        try:
            result = Decimal(value)
        except Exception as exc:  # pragma: no cover - Decimal exception types vary
            raise LineupModelValidationError(f"{label} is not a Decimal") from exc
    else:
        raise LineupModelValidationError(f"{label} is not a Decimal")
    if not result.is_finite():
        raise LineupModelValidationError(f"{label} must be finite")
    return result


def _uuid_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise LineupModelValidationError(f"{label} must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise LineupModelValidationError(f"{label} must be a UUID string") from exc


def _candidate_rows(candidates: object) -> tuple[_Candidate, ...]:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        raise LineupModelValidationError("candidates must be a sequence")
    rows: list[_Candidate] = []
    seen: set[str] = set()
    allowed = {
        "player_id",
        "player_key",
        "position",
        "start_weight",
        "bench_weight",
        "hard_ineligible",
    }
    for raw in candidates:
        value = _mapping(raw, label="candidate")
        if set(value) != allowed:
            raise LineupModelValidationError("candidate fields are incomplete or unknown")
        player_id = _uuid_text(value["player_id"], label="candidate.player_id")
        if player_id in seen:
            raise LineupModelValidationError("duplicate player ID")
        position = value["position"]
        if not isinstance(position, str) or position not in POSITION_ORDER:
            raise LineupModelValidationError("invalid position")
        player_key = value["player_key"]
        if not isinstance(player_key, str) or not player_key:
            raise LineupModelValidationError("invalid player key")
        start = _decimal(value["start_weight"], label="candidate.start_weight")
        bench = _decimal(value["bench_weight"], label="candidate.bench_weight")
        hard = value["hard_ineligible"]
        if not isinstance(hard, bool):
            raise LineupModelValidationError("hard_ineligible must be boolean")
        if start < 0 or bench < 0 or start + bench > Decimal(1):
            raise LineupModelValidationError("invalid role weights")
        if hard and (start != 0 or bench != 0):
            raise LineupModelValidationError("contradictory ineligible weights")
        rows.append(_Candidate(player_id, player_key, position, start, bench, hard))
        seen.add(player_id)
    return tuple(sorted(rows, key=lambda row: row.player_id))


def _validate_policy(policy: object) -> dict[str, Any]:
    try:
        value = _policy_mapping(policy)
    except (RoleModelValidationError, ValidationError, ValueError) as exc:
        raise LineupModelValidationError("policy does not match the frozen sampler policy") from exc
    if (
        value["lineup_sampler"] != SAMPLER_ID
        or value["coherence_model"] != COHERENCE_MODEL
        or value["lineup_sample_count"] != SAMPLE_COUNT
        or value["seed"] != POLICY_SEED
    ):
        raise LineupModelValidationError("policy sampler identity is not frozen")
    return value


def _validate_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LineupModelValidationError(f"{label} must be a non-empty string")
    return value


def _choose(
    candidates: Sequence[_Candidate],
    *,
    fixture_id: str,
    seed_suffix: str,
    scenario_index: int,
    phase: str,
    count: int,
    field: Literal["start_weight", "bench_weight"],
) -> tuple[_Candidate, ...]:
    if count == 0:
        return ()
    ranked: list[tuple[Decimal, str, _Candidate]] = []
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        denominator = Decimal(2**128 + 1)
        for candidate in candidates:
            if candidate.hard_ineligible:
                continue
            weight = candidate.start_weight if field == "start_weight" else candidate.bench_weight
            if weight <= 0:
                continue
            raw = (
                f"{POLICY_SEED}|{fixture_id}|{seed_suffix}|{scenario_index}|{phase}|{candidate.player_id}"
            ).encode()
            digest = hashlib.sha256(raw).digest()
            number = int.from_bytes(digest[:16], "big") + 1
            u = Decimal(number) / denominator
            key = -u.ln() / weight
            ranked.append((key, candidate.player_id, candidate))
    ranked.sort(key=lambda item: (item[0], item[1]))
    if len(ranked) < count:
        raise LineupModelValidationError("insufficient positive-weight capacity")
    return tuple(item[2] for item in ranked[:count])


def _scenario_hash(
    scenario_index: int,
    starters: set[str],
    bench: set[str],
    candidates: Sequence[_Candidate],
) -> tuple[str, tuple[ScenarioMember, ...]]:
    members = tuple(
        ScenarioMember(
            player_id=candidate.player_id,
            role=(
                "START"
                if candidate.player_id in starters
                else "BENCH"
                if candidate.player_id in bench
                else "OUT"
            ),
            position=candidate.position,  # type: ignore[arg-type]
        )
        for candidate in candidates
    )
    body = {
        "scenario_index": scenario_index,
        "starters": sorted(starters),
        "bench": sorted(bench),
        "members": [member.model_dump(mode="json") for member in members],
    }
    return _canonical_sha256(body), members


def sample_coherent_lineups(
    candidates: object,
    *,
    fixture_id: str,
    team_id: str,
    seed_suffix: str,
    bench_size: int,
    bench_goalkeeper_slots: int,
    policy: object,
) -> LineupResult:
    """Sample exactly 256 coherent lineups or return a typed blocked result."""

    try:
        fixture = _validate_text(fixture_id, label="fixture_id")
        team = _validate_text(team_id, label="team_id")
        suffix = _validate_text(seed_suffix, label="seed_suffix") if seed_suffix else ""
        if isinstance(bench_size, bool) or not isinstance(bench_size, int) or bench_size < 0:
            raise LineupModelValidationError("invalid bench configuration")
        if (
            isinstance(bench_goalkeeper_slots, bool)
            or not isinstance(bench_goalkeeper_slots, int)
            or bench_goalkeeper_slots < 0
            or bench_goalkeeper_slots > bench_size
        ):
            raise LineupModelValidationError("invalid bench configuration")
        _validate_policy(policy)
        rows = _candidate_rows(candidates)
    except LineupModelValidationError as exc:
        message = str(exc)
        if "duplicate player" in message:
            code = "DUPLICATE_PLAYER_ID"
        elif "invalid position" in message:
            code = "INVALID_POSITION"
        elif "contradictory" in message:
            code = "CONTRADICTORY_INELIGIBLE_WEIGHTS"
        elif "weights" in message:
            code = "INVALID_ROLE_WEIGHTS"
        elif "bench" in message:
            code = "INVALID_BENCH_CONFIGURATION"
        else:
            code = "INVALID_CANDIDATES"
        return InvalidLineupResult(status="INVALID", error_code=code)

    eligible = tuple(candidate for candidate in rows if not candidate.hard_ineligible)
    goalkeepers = tuple(candidate for candidate in eligible if candidate.position == "GK")
    outfield = tuple(candidate for candidate in eligible if candidate.position != "GK")
    if (
        len(goalkeepers) < 1 + bench_goalkeeper_slots
        or len(outfield) < 10 + bench_size - bench_goalkeeper_slots
    ):
        return BlockedLineupResult(
            status="BLOCKED",
            error_code="INSUFFICIENT_ELIGIBLE_SQUAD",
            fixture_id=fixture,
            team_id=team,
            sample_count=SAMPLE_COUNT,
        )

    counts: dict[str, dict[str, int]] = {
        candidate.player_id: {"START": 0, "BENCH": 0, "OUT": 0} for candidate in rows
    }
    scenarios: list[LineupScenario] = []
    scenario_hashes: list[str] = []
    try:
        for scenario_index in range(SAMPLE_COUNT):
            starting_gk = _choose(
                goalkeepers,
                fixture_id=fixture,
                seed_suffix=suffix,
                scenario_index=scenario_index,
                phase="START_GK",
                count=1,
                field="start_weight",
            )
            starting_outfield = _choose(
                outfield,
                fixture_id=fixture,
                seed_suffix=suffix,
                scenario_index=scenario_index,
                phase="START_OUTFIELD",
                count=10,
                field="start_weight",
            )
            starters = {candidate.player_id for candidate in starting_gk + starting_outfield}
            remaining_gk = tuple(
                candidate for candidate in goalkeepers if candidate.player_id not in starters
            )
            remaining_outfield = tuple(
                candidate for candidate in outfield if candidate.player_id not in starters
            )
            bench_gk = _choose(
                remaining_gk,
                fixture_id=fixture,
                seed_suffix=suffix,
                scenario_index=scenario_index,
                phase="BENCH_GK",
                count=bench_goalkeeper_slots,
                field="bench_weight",
            )
            bench_outfield = _choose(
                remaining_outfield,
                fixture_id=fixture,
                seed_suffix=suffix,
                scenario_index=scenario_index,
                phase="BENCH_OUTFIELD",
                count=bench_size - bench_goalkeeper_slots,
                field="bench_weight",
            )
            bench = {candidate.player_id for candidate in bench_gk + bench_outfield}
            scenario_hash, members = _scenario_hash(scenario_index, starters, bench, rows)
            scenarios.append(
                LineupScenario(
                    scenario_index=scenario_index,
                    starters=tuple(sorted(starters)),
                    bench=tuple(sorted(bench)),
                    members=members,
                    scenario_sha256=scenario_hash,
                )
            )
            scenario_hashes.append(scenario_hash)
            for player_id in counts:
                role = (
                    "START" if player_id in starters else "BENCH" if player_id in bench else "OUT"
                )
                counts[player_id][role] += 1
    except LineupModelValidationError:
        return BlockedLineupResult(
            status="BLOCKED",
            error_code="INSUFFICIENT_ELIGIBLE_SQUAD",
            fixture_id=fixture,
            team_id=team,
            sample_count=SAMPLE_COUNT,
        )

    marginals: list[RoleMarginal] = []
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUNDING_MODE
        denominator = Decimal(SAMPLE_COUNT)
        for candidate in rows:
            values = {
                role: Decimal(counts[candidate.player_id][role]) / denominator
                for role in ("START", "BENCH", "OUT")
            }
            marginals.append(
                RoleMarginal(
                    player_id=candidate.player_id,
                    player_key=candidate.player_key,
                    position=candidate.position,  # type: ignore[arg-type]
                    p_start=values["START"],
                    p_bench=values["BENCH"],
                    p_out=values["OUT"],
                )
            )
        sum_start = sum((item.p_start for item in marginals), Decimal(0))
        sum_bench = sum((item.p_bench for item in marginals), Decimal(0))
        sum_out = sum((item.p_out for item in marginals), Decimal(0))
    first = tuple(
        FirstScenario(
            scenario_index=item.scenario_index,
            starters=item.starters,
            bench=item.bench,
            scenario_sha256=item.scenario_sha256,
        )
        for item in scenarios[:3]
    )
    try:
        return ProjectedLineupResult(
            status="PROJECTED",
            fixture_id=fixture,
            team_id=team,
            sample_count=SAMPLE_COUNT,
            bench_size=bench_size,
            bench_goalkeeper_slots=bench_goalkeeper_slots,
            scenarios=tuple(scenarios),
            first_scenarios=first,
            scenario_set_sha256=hashlib.sha256(
                "".join(scenario_hashes).encode("utf-8")
            ).hexdigest(),
            role_marginals=tuple(marginals),
            sum_p_start=sum_start,
            sum_p_bench=sum_bench,
            sum_p_out=sum_out,
        )
    except (ValidationError, LineupModelValidationError) as exc:
        if isinstance(exc, LineupModelValidationError):
            raise
        raise LineupModelValidationError(
            "projected lineup result failed schema validation"
        ) from exc


__all__ = [
    "COHERENCE_MODEL",
    "DECIMAL_PRECISION",
    "PHASES",
    "POLICY_SEED",
    "SAMPLER_ID",
    "SAMPLE_COUNT",
    "BlockedLineupResult",
    "FirstScenario",
    "InvalidLineupResult",
    "LineupModelValidationError",
    "LineupResult",
    "LineupScenario",
    "ProjectedLineupResult",
    "RoleMarginal",
    "ScenarioMember",
    "sample_coherent_lineups",
]
