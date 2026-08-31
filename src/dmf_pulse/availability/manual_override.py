"""Private, transient, operator-authored Stage-7 minutes projections.

This adapter treats the supplied scenario mixture as the complete uncertainty
distribution.  It does not read history, fit a model, smooth probabilities, or
perform provider/network/database access.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticSerializationError

from dmf_pulse.availability.lineup import (
    FirstScenario,
    LineupScenario,
    ProjectedLineupResult,
    RoleMarginal,
    ScenarioMember,
)
from dmf_pulse.availability.models import Position, format_utc, parse_utc
from dmf_pulse.availability.projection import (
    PlayerMinutesProjection,
    TeamMinutesProjection,
    canonical_sha256,
    compose_player_minutes_projection,
    compose_team_minutes_projection,
)

MANUAL_MODEL_FAMILY: Literal["PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"] = (
    "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"
)
MANUAL_CONFIDENCE_REASON: Literal["MANUAL_TRANSIENT_OVERRIDE"] = "MANUAL_TRANSIENT_OVERRIDE"
MANUAL_SAMPLE_COUNT: Literal[256] = 256
MANUAL_BENCH_SIZE: Literal[9] = 9
MANUAL_BENCH_GOALKEEPER_SLOTS: Literal[1] = 1
MAXIMUM_INPUT_BYTES = 4 * 1024 * 1024

_MANUAL_POLICY_ARTIFACT: dict[str, object] = {
    "bench_goalkeeper_slots": MANUAL_BENCH_GOALKEEPER_SLOTS,
    "bench_size": MANUAL_BENCH_SIZE,
    "confidence_grade": "D",
    "confidence_reason": MANUAL_CONFIDENCE_REASON,
    "exact_expansion_count": MANUAL_SAMPLE_COUNT,
    "minute_bins": 91,
    "minute_range": [0, 90],
    "model_derived": False,
    "model_family": MANUAL_MODEL_FAMILY,
    "policy_id": "CURRENT-AVAILABILITY-001B-MANUAL-TRANSFORM-V1",
    "probability_decimal_places": 12,
    "production_suitable": False,
    "rounding_mode": "ROUND_HALF_EVEN",
    "schema_version": "manual-transient-minutes-policy-v1",
}
MANUAL_POLICY_SHA256 = canonical_sha256(_MANUAL_POLICY_ARTIFACT)

HardOverrideType = Literal[
    "OFFICIAL_SUSPENSION",
    "FORMAL_INELIGIBILITY",
    "OFFICIAL_LINEUP_NON_FPL_CUTOFF",
]


class ManualOverrideError(ValueError):
    """Stable, disclosure-minimized manual-override failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Revalidate hostile copies through the complete typed boundary."""

        del deep
        body = self.model_dump(mode="python", exclude_none=False)
        if update:
            body.update(dict(update))
        return type(self).model_validate(body)


def _canonical_uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUID string")
    try:
        canonical = str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{label} must be a canonical UUID string") from exc
    if canonical != value:
        raise ValueError(f"{label} must use canonical UUID spelling")
    return canonical


def _utc(value: object, *, label: str) -> datetime:
    return parse_utc(value, field_name=label)


class ManualOverrideProvenance(_FrozenModel):
    """Fixture-scoped provenance for the soft operator-authored scenario mixture."""

    supplier_type: Literal["PRIVATE_OPERATOR"]
    operator_ref: str = Field(min_length=1, max_length=120)
    evidence_type: Literal["ANALYST_SCENARIO_JUDGEMENT"]
    source_ref: str = Field(min_length=1, max_length=240)
    source_timestamp: datetime
    entered_at: datetime
    usable_at: datetime
    adjustment_type: Literal["SOFT_SCENARIO_MIXTURE"]
    reason: str = Field(min_length=1, max_length=500)
    expires_at: datetime
    fixture_scope_id: str
    classification: Literal["PRIVATE_TRANSIENT"]
    persistence_class: Literal["TRANSIENT_PRIVATE"]
    model_derived: Literal[False]
    production_suitable: Literal[False]

    @field_validator("fixture_scope_id", mode="before")
    @classmethod
    def validate_fixture_scope(cls, value: object) -> str:
        return _canonical_uuid(value, label="fixture_scope_id")

    @field_validator("source_timestamp", "entered_at", "usable_at", "expires_at", mode="before")
    @classmethod
    def validate_timestamp(cls, value: object, info: Any) -> datetime:
        return _utc(value, label=str(info.field_name))

    @field_serializer("source_timestamp", "entered_at", "usable_at", "expires_at")
    def serialize_timestamp(self, value: datetime) -> str:
        return format_utc(value)

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        if self.usable_at < max(self.source_timestamp, self.entered_at):
            raise ValueError("manual evidence is usable before its source/entry time")
        if self.expires_at <= self.usable_at:
            raise ValueError("manual evidence expires before it is usable")
        return self


class ManualHardRoleOverride(_FrozenModel):
    """One authoritative, fixture-scoped deterministic role assertion."""

    player_id: str
    team_id: str
    fixture_id: str
    override_type: HardOverrideType
    asserted_role: Literal["START", "BENCH", "OUT"]
    supplier_type: Literal["PRIVATE_OPERATOR"]
    operator_ref: str = Field(min_length=1, max_length=120)
    source_ref: str = Field(min_length=1, max_length=240)
    source_timestamp: datetime
    entered_at: datetime
    usable_at: datetime
    expires_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    classification: Literal["PRIVATE_TRANSIENT"]
    persistence_class: Literal["TRANSIENT_PRIVATE"]
    model_derived: Literal[False]
    production_suitable: Literal[False]

    @field_validator("player_id", "team_id", "fixture_id", mode="before")
    @classmethod
    def validate_identity(cls, value: object, info: Any) -> str:
        return _canonical_uuid(value, label=str(info.field_name))

    @field_validator("source_timestamp", "entered_at", "usable_at", "expires_at", mode="before")
    @classmethod
    def validate_timestamp(cls, value: object, info: Any) -> datetime:
        return _utc(value, label=str(info.field_name))

    @field_serializer("source_timestamp", "entered_at", "usable_at", "expires_at")
    def serialize_timestamp(self, value: datetime) -> str:
        return format_utc(value)

    @model_validator(mode="after")
    def validate_override(self) -> Self:
        if self.usable_at < max(self.source_timestamp, self.entered_at):
            raise ValueError("hard override is usable before its source/entry time")
        if self.expires_at <= self.usable_at:
            raise ValueError("hard override expires before it is usable")
        if self.override_type in {"OFFICIAL_SUSPENSION", "FORMAL_INELIGIBILITY"} and (
            self.asserted_role != "OUT"
        ):
            raise ValueError("suspension/ineligibility hard overrides must assert OUT")
        return self


class ManualScenarioPlayer(_FrozenModel):
    player_id: str
    position: Position
    role: Literal["START", "BENCH", "OUT"]
    official_minutes: Annotated[int, Field(ge=0, le=90)]

    @field_validator("player_id", mode="before")
    @classmethod
    def validate_player_id(cls, value: object) -> str:
        return _canonical_uuid(value, label="player_id")

    @model_validator(mode="after")
    def validate_role_minutes(self) -> Self:
        if self.role == "START" and self.official_minutes == 0:
            raise ValueError("START requires official_minutes in 1..90")
        if self.role == "OUT" and self.official_minutes != 0:
            raise ValueError("OUT requires zero official_minutes")
        return self


class ManualWeightedScenario(_FrozenModel):
    scenario_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,63}$")
    count: Annotated[int, Field(ge=1, le=MANUAL_SAMPLE_COUNT)]
    players: Annotated[tuple[ManualScenarioPlayer, ...], Field(min_length=20, max_length=40)]

    @model_validator(mode="before")
    @classmethod
    def coerce_players(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        body = dict(value)
        if isinstance(body.get("players"), list):
            body["players"] = tuple(body["players"])
        return body

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        ids = [player.player_id for player in self.players]
        if ids != sorted(ids):
            raise ValueError("scenario players must be sorted by canonical player_id")
        if len(ids) != len(set(ids)):
            raise ValueError("scenario contains a duplicate player")
        starters = tuple(player for player in self.players if player.role == "START")
        if len(starters) != 11:
            raise ValueError("scenario must contain exactly 11 START players")
        if sum(player.position == "GK" for player in starters) != 1:
            raise ValueError("scenario must contain exactly one starting GK")
        return self


class ManualTeamScenarios(_FrozenModel):
    team_id: str
    bench_size: Literal[9]
    bench_goalkeeper_slots: Literal[1]
    scenarios: Annotated[
        tuple[ManualWeightedScenario, ...],
        Field(min_length=1, max_length=MANUAL_SAMPLE_COUNT),
    ]
    hard_overrides: tuple[ManualHardRoleOverride, ...]

    @field_validator("team_id", mode="before")
    @classmethod
    def validate_team_id(cls, value: object) -> str:
        return _canonical_uuid(value, label="team_id")

    @model_validator(mode="before")
    @classmethod
    def coerce_sequences(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        body = dict(value)
        for key in ("scenarios", "hard_overrides"):
            if isinstance(body.get(key), list):
                body[key] = tuple(body[key])
        return body

    @model_validator(mode="after")
    def validate_team(self) -> Self:
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if scenario_ids != sorted(scenario_ids) or len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("team scenarios must have unique canonically ordered scenario_id")
        if sum(scenario.count for scenario in self.scenarios) != MANUAL_SAMPLE_COUNT:
            raise ValueError("team scenario counts must sum exactly to 256")

        roster = tuple((player.player_id, player.position) for player in self.scenarios[0].players)
        for scenario in self.scenarios:
            candidate = tuple((player.player_id, player.position) for player in scenario.players)
            if candidate != roster:
                raise ValueError("every team scenario must contain the identical player roster")
            bench = tuple(player for player in scenario.players if player.role == "BENCH")
            if len(bench) != self.bench_size:
                raise ValueError("scenario BENCH count does not match bench_size")
            if sum(player.position == "GK" for player in bench) != self.bench_goalkeeper_slots:
                raise ValueError("scenario bench goalkeeper count is invalid")

        override_ids = [override.player_id for override in self.hard_overrides]
        if override_ids != sorted(override_ids) or len(override_ids) != len(set(override_ids)):
            raise ValueError("hard overrides must have unique canonically ordered player_id")
        roster_ids = {player_id for player_id, _ in roster}
        for override in self.hard_overrides:
            if override.player_id not in roster_ids:
                raise ValueError("hard override references a player outside the team roster")
            roles = {
                next(
                    player.role
                    for player in scenario.players
                    if player.player_id == override.player_id
                )
                for scenario in self.scenarios
            }
            if roles != {override.asserted_role}:
                raise ValueError("hard override does not match every supplied scenario")
        return self


class ManualFixtureMinutesInput(_FrozenModel):
    schema_version: Literal["private-manual-transient-minutes-v1"]
    fixture_id: str
    home_team_id: str
    away_team_id: str
    as_of: datetime
    information_cutoff: datetime
    provenance: ManualOverrideProvenance
    home: ManualTeamScenarios
    away: ManualTeamScenarios

    @field_validator("fixture_id", "home_team_id", "away_team_id", mode="before")
    @classmethod
    def validate_identity(cls, value: object, info: Any) -> str:
        return _canonical_uuid(value, label=str(info.field_name))

    @field_validator("as_of", "information_cutoff", mode="before")
    @classmethod
    def validate_timestamp(cls, value: object, info: Any) -> datetime:
        return _utc(value, label=str(info.field_name))

    @field_serializer("as_of", "information_cutoff")
    def serialize_timestamp(self, value: datetime) -> str:
        return format_utc(value)

    @model_validator(mode="after")
    def validate_fixture(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("home and away teams must be distinct")
        if self.home.team_id != self.home_team_id or self.away.team_id != self.away_team_id:
            raise ValueError("team scenario identity does not match the requested fixture side")
        if self.as_of > self.information_cutoff:
            raise ValueError("as_of must not be after information_cutoff")
        if self.provenance.fixture_scope_id != self.fixture_id:
            raise ValueError("manual provenance fixture scope does not match fixture_id")
        if self.provenance.usable_at > self.as_of:
            raise ValueError("manual evidence is not usable at as_of")
        if self.provenance.expires_at <= self.as_of:
            raise ValueError("manual evidence is expired at as_of")

        home_ids = {player.player_id for player in self.home.scenarios[0].players}
        away_ids = {player.player_id for player in self.away.scenarios[0].players}
        if home_ids & away_ids:
            raise ValueError("one canonical player cannot be represented by both teams")
        for team in (self.home, self.away):
            for override in team.hard_overrides:
                if override.fixture_id != self.fixture_id or override.team_id != team.team_id:
                    raise ValueError("hard override fixture/team scope is inconsistent")
                if override.usable_at > self.as_of:
                    raise ValueError("hard override is not usable at as_of")
                if override.expires_at <= self.as_of:
                    raise ValueError("hard override is expired at as_of")
        return self


def manual_fixture_input_sha256(value: ManualFixtureMinutesInput) -> str:
    """Hash the complete canonical validated manual input body."""

    return canonical_sha256(value.model_dump(mode="json"))


def manual_provenance_sha256(value: ManualFixtureMinutesInput) -> str:
    return canonical_sha256(
        {
            "fixture_provenance": value.provenance.model_dump(mode="json"),
            "home_hard_overrides": [
                item.model_dump(mode="json") for item in value.home.hard_overrides
            ],
            "away_hard_overrides": [
                item.model_dump(mode="json") for item in value.away.hard_overrides
            ],
        }
    )


class ManualMinutesProjectionBundle(_FrozenModel):
    schema_version: Literal["private-manual-transient-minutes-bundle-v1"]
    fixture_id: str
    as_of: datetime
    model_family: Literal["PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"]
    classification: Literal["PRIVATE_TRANSIENT"]
    persistence_class: Literal["TRANSIENT_PRIVATE"]
    model_derived: Literal[False]
    production_suitable: Literal[False]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transformation_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    home: TeamMinutesProjection
    away: TeamMinutesProjection
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("fixture_id", mode="before")
    @classmethod
    def validate_fixture_id(cls, value: object) -> str:
        return _canonical_uuid(value, label="fixture_id")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of(cls, value: object) -> datetime:
        return _utc(value, label="as_of")

    @field_serializer("as_of")
    def serialize_as_of(self, value: datetime) -> str:
        return format_utc(value)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        expected_as_of = format_utc(self.as_of)
        if (
            self.home.fixture_id != self.fixture_id
            or self.away.fixture_id != self.fixture_id
            or self.home.team_id == self.away.team_id
            or self.home.as_of != expected_as_of
            or self.away.as_of != expected_as_of
            or self.home.model_family != self.model_family
            or self.away.model_family != self.model_family
            or self.home.dataset_sha256 != self.dataset_sha256
            or self.away.dataset_sha256 != self.dataset_sha256
            or self.home.model_artifact_sha256 != self.transformation_policy_sha256
            or self.away.model_artifact_sha256 != self.transformation_policy_sha256
        ):
            raise ValueError("manual projection bundle identities are inconsistent")
        body = self.model_dump(mode="json")
        supplied = body.pop("semantic_sha256")
        if canonical_sha256(body) != supplied:
            raise ValueError("manual projection bundle semantic identity is invalid")
        return self


def _role_scenario_hash(
    *,
    scenario_index: int,
    starters: tuple[str, ...],
    bench: tuple[str, ...],
    members: tuple[ScenarioMember, ...],
) -> str:
    return canonical_sha256(
        {
            "scenario_index": scenario_index,
            "starters": list(starters),
            "bench": list(bench),
            "members": [member.model_dump(mode="json") for member in members],
        }
    )


def _expand_team(
    fixture_id: str,
    team: ManualTeamScenarios,
) -> tuple[ProjectedLineupResult, tuple[tuple[ManualScenarioPlayer, ...], ...], str]:
    role_scenarios: list[LineupScenario] = []
    minute_scenarios: list[tuple[ManualScenarioPlayer, ...]] = []
    source_ids: list[str] = []
    for scenario in team.scenarios:
        for _ in range(scenario.count):
            index = len(role_scenarios)
            starters = tuple(
                player.player_id for player in scenario.players if player.role == "START"
            )
            bench = tuple(player.player_id for player in scenario.players if player.role == "BENCH")
            members = tuple(
                ScenarioMember(
                    player_id=player.player_id,
                    role=player.role,
                    position=player.position,
                )
                for player in scenario.players
            )
            scenario_hash = _role_scenario_hash(
                scenario_index=index,
                starters=starters,
                bench=bench,
                members=members,
            )
            role_scenarios.append(
                LineupScenario(
                    scenario_index=index,
                    starters=starters,
                    bench=bench,
                    members=members,
                    scenario_sha256=scenario_hash,
                )
            )
            minute_scenarios.append(scenario.players)
            source_ids.append(scenario.scenario_id)

    role_hash = hashlib.sha256(
        "".join(scenario.scenario_sha256 for scenario in role_scenarios).encode("utf-8")
    ).hexdigest()
    roster = team.scenarios[0].players
    role_counts: dict[str, Counter[str]] = {player.player_id: Counter() for player in roster}
    for expanded_players in minute_scenarios:
        for player in expanded_players:
            role_counts[player.player_id][player.role] += 1
    with localcontext() as context:
        context.prec = 256
        denominator = Decimal(MANUAL_SAMPLE_COUNT)
        marginals = tuple(
            RoleMarginal(
                player_id=player.player_id,
                player_key=player.player_id,
                position=player.position,
                p_start=Decimal(role_counts[player.player_id]["START"]) / denominator,
                p_bench=Decimal(role_counts[player.player_id]["BENCH"]) / denominator,
                p_out=Decimal(role_counts[player.player_id]["OUT"]) / denominator,
            )
            for player in roster
        )
    lineup = ProjectedLineupResult(
        status="PROJECTED",
        fixture_id=fixture_id,
        team_id=team.team_id,
        sample_count=MANUAL_SAMPLE_COUNT,
        bench_size=team.bench_size,
        bench_goalkeeper_slots=team.bench_goalkeeper_slots,
        scenarios=tuple(role_scenarios),
        first_scenarios=tuple(
            FirstScenario(
                scenario_index=scenario.scenario_index,
                starters=scenario.starters,
                bench=scenario.bench,
                scenario_sha256=scenario.scenario_sha256,
            )
            for scenario in role_scenarios[:3]
        ),
        scenario_set_sha256=role_hash,
        role_marginals=marginals,
        sum_p_start=sum((item.p_start for item in marginals), Decimal(0)),
        sum_p_bench=sum((item.p_bench for item in marginals), Decimal(0)),
        sum_p_out=sum((item.p_out for item in marginals), Decimal(0)),
    )
    minute_sensitive_hash = canonical_sha256(
        {
            "contract": "PRIVATE_MANUAL_TRANSIENT_SCENARIO_SET",
            "fixture_id": fixture_id,
            "policy_sha256": MANUAL_POLICY_SHA256,
            "scenarios": [
                {
                    "expanded_index": index,
                    "source_scenario_id": source_ids[index],
                    "players": [player.model_dump(mode="json") for player in scenario],
                }
                for index, scenario in enumerate(minute_scenarios)
            ],
            "team_id": team.team_id,
            "version": "1.0.0",
        }
    )
    return lineup, tuple(minute_scenarios), minute_sensitive_hash


def _conditional_minute_pmf(
    rows: Sequence[ManualScenarioPlayer], role: Literal["START", "BENCH"]
) -> tuple[Decimal, ...]:
    selected = tuple(row.official_minutes for row in rows if row.role == role)
    if not selected:
        return (Decimal(1), *(Decimal(0) for _ in range(90)))
    counts = Counter(selected)
    denominator = Decimal(len(selected))
    return tuple(Decimal(counts[index]) / denominator for index in range(91))


def _team_projection(
    fixture: ManualFixtureMinutesInput,
    team: ManualTeamScenarios,
    *,
    dataset_sha256: str,
) -> TeamMinutesProjection:
    lineup, scenarios, minute_sensitive_hash = _expand_team(fixture.fixture_id, team)
    hard_by_player = {item.player_id: item for item in team.hard_overrides}
    players: list[PlayerMinutesProjection] = []
    marginal_by_player = {item.player_id: item for item in lineup.role_marginals}
    for roster_player in team.scenarios[0].players:
        player_rows = tuple(
            next(item for item in scenario if item.player_id == roster_player.player_id)
            for scenario in scenarios
        )
        marginal = marginal_by_player[roster_player.player_id]
        hard = hard_by_player.get(roster_player.player_id)
        if marginal.p_start == Decimal(1) and (
            hard is None
            or hard.override_type != "OFFICIAL_LINEUP_NON_FPL_CUTOFF"
            or hard.asserted_role != "START"
        ):
            raise ManualOverrideError(
                "SOFT_DEGENERATE_ROLE",
                "p_start=1 requires an aligned allowed hard override",
            )
        if marginal.p_out == Decimal(1) and (hard is None or hard.asserted_role != "OUT"):
            raise ManualOverrideError(
                "SOFT_DEGENERATE_ROLE",
                "p_out=1 requires an aligned allowed hard override",
            )
        reasons: tuple[str, ...] = (
            (MANUAL_CONFIDENCE_REASON, "HARD_INELIGIBLE_OVERRIDE")
            if hard is not None and hard.asserted_role == "OUT"
            else (MANUAL_CONFIDENCE_REASON,)
        )
        players.append(
            compose_player_minutes_projection(
                marginal,
                {"minute_pmf": _conditional_minute_pmf(player_rows, "START")},
                {"minute_pmf": _conditional_minute_pmf(player_rows, "BENCH")},
                confidence_grade="D",
                confidence_reasons=reasons,
            )
        )
    lineup_identity = {
        "fixture_id": fixture.fixture_id,
        "team_id": team.team_id,
        "sample_count": MANUAL_SAMPLE_COUNT,
        "bench_size": team.bench_size,
        "bench_goalkeeper_slots": team.bench_goalkeeper_slots,
        "scenario_set_sha256": minute_sensitive_hash,
    }
    return compose_team_minutes_projection(
        lineup_identity,
        players,
        as_of=format_utc(fixture.as_of),
        model_family=MANUAL_MODEL_FAMILY,
        dataset_sha256=dataset_sha256,
        model_artifact_sha256=MANUAL_POLICY_SHA256,
    )


def build_manual_minutes_override(
    value: ManualFixtureMinutesInput,
) -> ManualMinutesProjectionBundle:
    """Build two exact manual Stage-7 projections with no stochastic approximation."""

    try:
        checked = ManualFixtureMinutesInput.model_validate(value.model_dump(mode="python"))
    except (ValidationError, PydanticSerializationError) as exc:
        raise ManualOverrideError(
            "MANUAL_OVERRIDE_INVALID", "manual fixture input failed validation"
        ) from exc
    dataset_sha256 = manual_fixture_input_sha256(checked)
    home = _team_projection(checked, checked.home, dataset_sha256=dataset_sha256)
    away = _team_projection(checked, checked.away, dataset_sha256=dataset_sha256)
    body: dict[str, object] = {
        "schema_version": "private-manual-transient-minutes-bundle-v1",
        "fixture_id": checked.fixture_id,
        "as_of": checked.as_of,
        "model_family": MANUAL_MODEL_FAMILY,
        "classification": "PRIVATE_TRANSIENT",
        "persistence_class": "TRANSIENT_PRIVATE",
        "model_derived": False,
        "production_suitable": False,
        "dataset_sha256": dataset_sha256,
        "transformation_policy_sha256": MANUAL_POLICY_SHA256,
        "provenance_sha256": manual_provenance_sha256(checked),
        "home": home,
        "away": away,
    }
    hash_body = {
        **body,
        "as_of": format_utc(checked.as_of),
        "home": home.model_dump(mode="json"),
        "away": away.model_dump(mode="json"),
    }
    body["semantic_sha256"] = canonical_sha256(hash_body)
    return ManualMinutesProjectionBundle.model_validate(body)


def manual_transient_policy_artifact() -> dict[str, object]:
    """Return a mutation-independent copy of the governed transformation policy."""

    return deepcopy(_MANUAL_POLICY_ARTIFACT)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> object:
    raise ValueError(f"binary/JSON float is forbidden: {value}")


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def load_manual_fixture_minutes(path: Path) -> ManualFixtureMinutesInput:
    """Read one bounded nonsymlink JSON input and validate it strictly."""

    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("manual input must be a nonsymlink regular file")
        with path.open("rb") as handle:
            raw = handle.read(MAXIMUM_INPUT_BYTES + 1)
        if len(raw) > MAXIMUM_INPUT_BYTES:
            raise OSError("manual input exceeds the bounded size limit")
        text = raw.decode("utf-8")
        json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
        return ManualFixtureMinutesInput.model_validate_json(raw)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        raise ManualOverrideError(
            "MANUAL_OVERRIDE_INPUT_INVALID", "manual override input is invalid"
        ) from exc


__all__ = [
    "MANUAL_BENCH_GOALKEEPER_SLOTS",
    "MANUAL_BENCH_SIZE",
    "MANUAL_CONFIDENCE_REASON",
    "MANUAL_MODEL_FAMILY",
    "MANUAL_POLICY_SHA256",
    "MANUAL_SAMPLE_COUNT",
    "ManualFixtureMinutesInput",
    "ManualHardRoleOverride",
    "ManualMinutesProjectionBundle",
    "ManualOverrideError",
    "ManualOverrideProvenance",
    "ManualScenarioPlayer",
    "ManualTeamScenarios",
    "ManualWeightedScenario",
    "build_manual_minutes_override",
    "load_manual_fixture_minutes",
    "manual_fixture_input_sha256",
    "manual_provenance_sha256",
    "manual_transient_policy_artifact",
]
