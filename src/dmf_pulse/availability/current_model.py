"""Transient adapter from the accepted Stage-7 model to private-V1 scenarios."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.manual_override import (
    MANUAL_SAMPLE_COUNT,
    ManualScenarioPlayer,
    ManualWeightedScenario,
)
from dmf_pulse.availability.models import format_utc, parse_utc
from dmf_pulse.availability.projection import MinutesPredictionResult, TeamMinutesProjection

CURRENT_MODEL_FAMILY: Literal["REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"] = (
    "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


def _uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUID string")
    try:
        checked = str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{label} must be a canonical UUID string") from exc
    if checked != value:
        raise ValueError(f"{label} must be a canonical UUID string")
    return checked


class CurrentModelTeamScenarios(_FrozenModel):
    team_id: str
    bench_size: Literal[9] = 9
    bench_goalkeeper_slots: Literal[1] = 1
    scenarios: Annotated[tuple[ManualWeightedScenario, ...], Field(min_length=256, max_length=256)]
    hard_ineligible_player_ids: tuple[str, ...] = ()

    @field_validator("team_id", mode="before")
    @classmethod
    def team_is_canonical(cls, value: object) -> str:
        return _uuid(value, label="team_id")

    @model_validator(mode="after")
    def scenario_set_is_exact(self) -> Self:
        expected_ids = tuple(f"S{index:03d}" for index in range(MANUAL_SAMPLE_COUNT))
        if tuple(item.scenario_id for item in self.scenarios) != expected_ids or any(
            item.count != 1 for item in self.scenarios
        ):
            raise ValueError("model scenario indices must be the exact 256-sample sequence")
        roster = tuple((item.player_id, item.position) for item in self.scenarios[0].players)
        if any(
            tuple((item.player_id, item.position) for item in scenario.players) != roster
            for scenario in self.scenarios
        ):
            raise ValueError("model scenario roster changes across samples")
        hard = tuple(sorted(set(self.hard_ineligible_player_ids)))
        if hard != self.hard_ineligible_player_ids or not set(hard) <= {item[0] for item in roster}:
            raise ValueError("model hard-ineligible identities are invalid")
        if any(
            next(item.role for item in scenario.players if item.player_id == player_id) != "OUT"
            for player_id in hard
            for scenario in self.scenarios
        ):
            raise ValueError("hard-ineligible model player is not OUT in every scenario")
        return self


class CurrentModelFixtureMinutesInput(_FrozenModel):
    schema_version: Literal["current-model-transient-minutes-v1"] = (
        "current-model-transient-minutes-v1"
    )
    fixture_id: str
    home_team_id: str
    away_team_id: str
    as_of: datetime
    information_cutoff: datetime
    source_class: Literal["PROVIDER_OBSERVED_MODEL_DERIVED"] = "PROVIDER_OBSERVED_MODEL_DERIVED"
    model_family: Literal["REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"] = CURRENT_MODEL_FAMILY
    model_derived: Literal[True] = True
    persistence_class: Literal["TRANSIENT_PRIVATE"] = "TRANSIENT_PRIVATE"
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    home: CurrentModelTeamScenarios
    away: CurrentModelTeamScenarios
    home_projection: TeamMinutesProjection
    away_projection: TeamMinutesProjection
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    warnings: tuple[str, ...]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("fixture_id", "home_team_id", "away_team_id", mode="before")
    @classmethod
    def identity_is_canonical(cls, value: object, info: Any) -> str:
        return _uuid(value, label=str(info.field_name))

    @field_validator("as_of", "information_cutoff", mode="before")
    @classmethod
    def timestamp_is_utc(cls, value: object, info: Any) -> datetime:
        return parse_utc(value, field_name=str(info.field_name))

    @model_validator(mode="after")
    def fixture_is_bound_and_sealed(self) -> Self:
        if (
            self.home_team_id == self.away_team_id
            or self.home.team_id != self.home_team_id
            or self.away.team_id != self.away_team_id
            or self.as_of > self.information_cutoff
        ):
            raise ValueError("model fixture scope is inconsistent")
        for team_id, team, projection in (
            (self.home_team_id, self.home, self.home_projection),
            (self.away_team_id, self.away, self.away_projection),
        ):
            if (
                projection.fixture_id != self.fixture_id
                or projection.team_id != team_id
                or projection.as_of != format_utc(self.as_of)
                or projection.model_family != self.model_family
                or projection.dataset_sha256 != self.training_dataset_sha256
                or projection.model_artifact_sha256 != self.model_artifact_sha256
                or {item.player_id for item in projection.players}
                != {item.player_id for item in team.scenarios[0].players}
            ):
                raise ValueError("model projection and scenario identities differ")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("model Stage-7 warnings must be unique and sorted")
        if self.semantic_sha256 != current_model_fixture_sha256(self):
            raise ValueError("model Stage-7 input semantic hash does not match")
        return self


def current_model_fixture_sha256(value: CurrentModelFixtureMinutesInput) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _minute_sample(
    pmf: Sequence[object], *, fixture_id: str, team_id: str, player_id: str, role: str, index: int
) -> int:
    values = tuple(Decimal(str(item)) for item in pmf)
    if len(values) != 91 or any(item < 0 for item in values):
        raise ValueError("accepted conditional minute PMF is invalid")
    allowed = range(1, 91) if role == "START" else range(0, 90)
    total = sum((values[item] for item in allowed), Decimal(0))
    if total <= 0:
        raise ValueError("accepted conditional minute PMF has no supported mass")
    digest = hashlib.sha256(
        f"CURRENT-STAGE7-MINUTES-V1|{fixture_id}|{team_id}|{player_id}|{role}|{index}".encode()
    ).digest()
    unit = Decimal(int.from_bytes(digest[:16], "big")) / Decimal(2**128)
    threshold = unit * total
    cumulative = Decimal(0)
    for minute in allowed:
        cumulative += values[minute]
        if threshold < cumulative:
            return minute
    return allowed[-1]


def _team_scenarios(
    result: MinutesPredictionResult,
) -> CurrentModelTeamScenarios:
    if result.status != "PROJECTED" or result.projection is None:
        raise ValueError(result.error_code or "accepted Stage-7 prediction is blocked")
    pmfs: dict[tuple[str, str], Sequence[object]] = {}
    for value in result.core_minute_pmfs:
        player_id = str(value.get("player_id"))
        role = str(value.get("role"))
        raw_pmf = value.get("minute_pmf")
        if role not in {"START", "BENCH"} or not isinstance(raw_pmf, Sequence):
            raise ValueError("accepted Stage-7 conditional PMF is malformed")
        pmfs[(player_id, role)] = raw_pmf
    scenarios: list[ManualWeightedScenario] = []
    for index, value in enumerate(result.core_scenarios):
        if value.get("scenario_index") != index:
            raise ValueError("accepted Stage-7 scenario sequence is malformed")
        members = value.get("members")
        if not isinstance(members, Sequence):
            raise ValueError("accepted Stage-7 scenario members are malformed")
        players: list[ManualScenarioPlayer] = []
        for raw in members:
            if not isinstance(raw, Mapping):
                raise ValueError("accepted Stage-7 scenario member is malformed")
            player_id = str(raw.get("player_id"))
            role = str(raw.get("role"))
            position = str(raw.get("position"))
            minute = (
                0
                if role == "OUT"
                else _minute_sample(
                    pmfs[(player_id, role)],
                    fixture_id=result.fixture_id,
                    team_id=result.team_id,
                    player_id=player_id,
                    role=role,
                    index=index,
                )
            )
            players.append(
                ManualScenarioPlayer.model_validate(
                    {
                        "player_id": player_id,
                        "position": position,
                        "role": role,
                        "official_minutes": minute,
                    }
                )
            )
        scenarios.append(
            ManualWeightedScenario(
                scenario_id=f"S{index:03d}",
                count=1,
                players=tuple(sorted(players, key=lambda item: item.player_id)),
            )
        )
    hard = tuple(sorted(str(item["player_id"]) for item in result.core_hard_eligibility))
    return CurrentModelTeamScenarios(
        team_id=result.team_id,
        scenarios=tuple(scenarios),
        hard_ineligible_player_ids=hard,
    )


def build_current_model_fixture_minutes(
    home: MinutesPredictionResult,
    away: MinutesPredictionResult,
    *,
    information_cutoff: datetime,
    observed_history_sha256: str,
    warnings: Sequence[str] = (),
) -> CurrentModelFixtureMinutesInput:
    """Bind accepted projections and their deterministic scenario adapter."""

    if home.projection is None or away.projection is None:
        raise ValueError("accepted Stage-7 prediction is blocked")
    grades = tuple(
        item.confidence_grade
        for projection in (home.projection, away.projection)
        for item in projection.players
    )
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = (
        "LOW" if "D" in grades else "MEDIUM" if "C" in grades else "HIGH"
    )
    body: dict[str, object] = {
        "fixture_id": home.fixture_id,
        "home_team_id": home.team_id,
        "away_team_id": away.team_id,
        "as_of": parse_utc(home.as_of, field_name="home.as_of"),
        "information_cutoff": information_cutoff,
        "training_dataset_sha256": home.projection.dataset_sha256,
        "model_artifact_sha256": home.projection.model_artifact_sha256,
        "observed_history_sha256": observed_history_sha256,
        "home": _team_scenarios(home),
        "away": _team_scenarios(away),
        "home_projection": home.projection,
        "away_projection": away.projection,
        "confidence": confidence,
        "warnings": tuple(sorted(set(warnings))),
        "semantic_sha256": "0" * 64,
    }
    provisional = CurrentModelFixtureMinutesInput.model_construct(**cast(Any, body))
    body["semantic_sha256"] = current_model_fixture_sha256(provisional)
    return CurrentModelFixtureMinutesInput.model_validate(body)


__all__ = [
    "CURRENT_MODEL_FAMILY",
    "CurrentModelFixtureMinutesInput",
    "CurrentModelTeamScenarios",
    "build_current_model_fixture_minutes",
    "current_model_fixture_sha256",
]
