"""Transient adapter from the accepted Stage-7 model to private-V1 scenarios."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from functools import cache, lru_cache
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
from dmf_pulse.availability.resources import availability_resource_json

CURRENT_MODEL_FAMILY: Literal["REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"] = (
    "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
)
CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_WARNING = "CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_V1"
_CURRENT_TEAM_PATH_POLICY_RESOURCE = "current_team_path_policy_2026_27.json"


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


class CurrentTeamPathPolicy(_FrozenModel):
    """Current-season competition constraints for the transient joint-team adapter."""

    schema_version: Literal["current-team-path-policy-v1"]
    policy_id: Literal["CURRENT-STAGE7-TEAM-PATH-RECONCILIATION-2026-27-V1"]
    competition_code: Literal["PL"]
    season_code: Literal["2026/27"]
    match_minutes: Literal[90]
    players_on_pitch: Literal[11]
    goalkeepers_on_pitch: Literal[1]
    maximum_standard_substitutions: Literal[5]
    exceptional_substitutions_modelled: Literal[False]
    source_url: Literal[
        "https://resources.premierleague.pulselive.com/premierleague/document/2026/07/31/8a890ff9-176c-4364-a8ff-e08f995e2c86/TM2040_PL-Handbook-and-Collateral-2026-27_Digital_31.07.pdf"
    ]
    source_locator: Literal["Premier League Handbook 2026/27, Rule L.29, page 237"]
    source_published_date: Literal["2026-07-31"]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def policy_is_sealed(self) -> Self:
        if self.semantic_sha256 != current_team_path_policy_sha256(self):
            raise ValueError("current team-path policy semantic hash does not match")
        return self


def current_team_path_policy_sha256(value: CurrentTeamPathPolicy) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


@lru_cache(maxsize=1)
def load_current_team_path_policy() -> CurrentTeamPathPolicy:
    """Load the wheel-contained 2026/27 Premier League team-path constraints."""

    return CurrentTeamPathPolicy.model_validate(
        availability_resource_json(_CURRENT_TEAM_PATH_POLICY_RESOURCE)
    )


class CurrentTeamMinuteReconciliation(_FrozenModel):
    """Safe aggregate distortion evidence for one reconciled team scenario."""

    schema_version: Literal["current-team-minute-reconciliation-v1"] = (
        "current-team-minute-reconciliation-v1"
    )
    scenario_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,63}$")
    original_team_minutes: Annotated[int, Field(ge=0)]
    reconciled_team_minutes: Literal[990] = 990
    adjusted_player_count: Annotated[int, Field(ge=0, le=40)]
    total_absolute_minute_adjustment: Annotated[int, Field(ge=0)]
    maximum_absolute_player_adjustment: Annotated[int, Field(ge=0, le=90)]
    substitution_count: Annotated[int, Field(ge=0, le=5)]
    original_player_minutes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciled_player_minutes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def metrics_are_coherent_and_sealed(self) -> Self:
        if self.adjusted_player_count == 0:
            if (
                self.total_absolute_minute_adjustment != 0
                or self.maximum_absolute_player_adjustment != 0
            ):
                raise ValueError("zero adjusted players require zero minute distortion")
        elif (
            self.total_absolute_minute_adjustment <= 0
            or self.maximum_absolute_player_adjustment <= 0
            or self.maximum_absolute_player_adjustment > self.total_absolute_minute_adjustment
        ):
            raise ValueError("positive adjusted players require coherent minute distortion")
        if self.semantic_sha256 != current_team_minute_reconciliation_sha256(self):
            raise ValueError("team-minute reconciliation semantic hash does not match")
        return self


def current_team_minute_reconciliation_sha256(
    value: CurrentTeamMinuteReconciliation,
) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _scenario_minutes_sha256(value: ManualWeightedScenario) -> str:
    return canonical_sha256(
        {
            "scenario_id": value.scenario_id,
            "players": [
                {
                    "official_minutes": item.official_minutes,
                    "player_id": item.player_id,
                    "position": item.position,
                    "role": item.role,
                }
                for item in value.players
            ],
        }
    )


def validate_current_team_path(
    scenario: ManualWeightedScenario,
    policy: CurrentTeamPathPolicy | None = None,
) -> None:
    """Reject a vector that cannot describe one continuous legal 90-minute team path."""

    policy = policy or load_current_team_path_policy()
    starters = tuple(item for item in scenario.players if item.role == "START")
    bench = tuple(item for item in scenario.players if item.role == "BENCH")
    if len(starters) != policy.players_on_pitch:
        raise ValueError("current team path must have exactly 11 kickoff starters")
    if len(bench) != 9 or sum(item.position == "GK" for item in bench) != 1:
        raise ValueError("current team path must retain the configured nine-player bench")
    if sum(item.position == "GK" for item in starters) != policy.goalkeepers_on_pitch:
        raise ValueError("current team path must have exactly one kickoff goalkeeper")
    if any(item.role == "OUT" and item.official_minutes != 0 for item in scenario.players):
        raise ValueError("OUT players cannot enter the current team path")

    entrants = tuple(item for item in bench if item.official_minutes > 0)
    exits = tuple(item for item in starters if item.official_minutes < policy.match_minutes)
    if len(entrants) > policy.maximum_standard_substitutions:
        raise ValueError("current team path exceeds the governed substitution limit")
    if any(item.official_minutes >= policy.match_minutes for item in entrants):
        raise ValueError("appearing bench players must enter strictly after kickoff")

    goalkeeper_exits = sorted(item.official_minutes for item in exits if item.position == "GK")
    goalkeeper_entries = sorted(
        policy.match_minutes - item.official_minutes for item in entrants if item.position == "GK"
    )
    if goalkeeper_exits != goalkeeper_entries:
        raise ValueError("goalkeeper exit must be paired with the bench goalkeeper")
    outfield_exits = sorted(item.official_minutes for item in exits if item.position != "GK")
    outfield_entries = sorted(
        policy.match_minutes - item.official_minutes for item in entrants if item.position != "GK"
    )
    if outfield_exits != outfield_entries:
        raise ValueError("starter exits and bench entries must be paired at the same minute")
    if sum(item.official_minutes for item in scenario.players) != (
        policy.players_on_pitch * policy.match_minutes
    ):
        raise ValueError("current team path must contain exactly 990 pre-dismissal team-minutes")


def _best_pair_time(starter_target: int, bench_target: int) -> tuple[int, int]:
    return min(
        (
            abs(minute - starter_target) + abs((90 - minute) - bench_target),
            minute,
        )
        for minute in range(1, 90)
    )


def reconcile_current_team_scenario(
    scenario: ManualWeightedScenario,
    policy: CurrentTeamPathPolicy | None = None,
) -> tuple[ManualWeightedScenario, CurrentTeamMinuteReconciliation]:
    """Find the deterministic minimum-L1 legal team path nearest independent draws."""

    policy = policy or load_current_team_path_policy()
    starters = tuple(item for item in scenario.players if item.role == "START")
    bench = tuple(item for item in scenario.players if item.role == "BENCH")
    if len(starters) != policy.players_on_pitch or len(bench) != 9:
        raise ValueError("raw current scenario has an invalid role allocation")
    raw_minutes = {item.player_id: item.official_minutes for item in scenario.players}
    baseline_cost = sum(
        abs((policy.match_minutes if item.role == "START" else 0) - item.official_minutes)
        for item in scenario.players
    )
    pair_options: dict[tuple[int, int], tuple[int, int]] = {}
    for bench_index, entrant in enumerate(bench):
        for starter_index, outgoing in enumerate(starters):
            if (entrant.position == "GK") != (outgoing.position == "GK"):
                continue
            pair_cost, minute = _best_pair_time(outgoing.official_minutes, entrant.official_minutes)
            unpaired_cost = abs(policy.match_minutes - outgoing.official_minutes) + abs(
                entrant.official_minutes
            )
            pair_options[(bench_index, starter_index)] = (
                pair_cost - unpaired_cost,
                minute,
            )

    Pair = tuple[str, str, int]
    SearchResult = tuple[int, tuple[Pair, ...]]

    @cache
    def search(bench_index: int, used_starters: int) -> SearchResult:
        if bench_index == len(bench):
            return 0, ()
        best = search(bench_index + 1, used_starters)
        if used_starters.bit_count() >= policy.maximum_standard_substitutions:
            return best
        entrant = bench[bench_index]
        for starter_index, outgoing in enumerate(starters):
            if used_starters & (1 << starter_index):
                continue
            option = pair_options.get((bench_index, starter_index))
            if option is None:
                continue
            delta, minute = option
            tail_delta, tail_pairs = search(bench_index + 1, used_starters | (1 << starter_index))
            candidate: SearchResult = (
                delta + tail_delta,
                ((entrant.player_id, outgoing.player_id, minute), *tail_pairs),
            )
            if (candidate[0], len(candidate[1]), candidate[1]) < (
                best[0],
                len(best[1]),
                best[1],
            ):
                best = candidate
        return best

    total_delta, pairs = search(0, 0)
    legal_minutes = {
        item.player_id: policy.match_minutes if item.role == "START" else 0
        for item in scenario.players
    }
    for entrant_id, outgoing_id, minute in pairs:
        legal_minutes[outgoing_id] = minute
        legal_minutes[entrant_id] = policy.match_minutes - minute
    reconciled = ManualWeightedScenario(
        scenario_id=scenario.scenario_id,
        count=scenario.count,
        players=tuple(
            item.model_copy(update={"official_minutes": legal_minutes[item.player_id]})
            for item in scenario.players
        ),
    )
    validate_current_team_path(reconciled, policy)
    adjustments = tuple(
        abs(legal_minutes[item.player_id] - item.official_minutes) for item in scenario.players
    )
    body: dict[str, object] = {
        "scenario_id": scenario.scenario_id,
        "original_team_minutes": sum(raw_minutes.values()),
        "reconciled_team_minutes": policy.players_on_pitch * policy.match_minutes,
        "adjusted_player_count": sum(item > 0 for item in adjustments),
        "total_absolute_minute_adjustment": baseline_cost + total_delta,
        "maximum_absolute_player_adjustment": max(adjustments, default=0),
        "substitution_count": len(pairs),
        "original_player_minutes_sha256": _scenario_minutes_sha256(scenario),
        "reconciled_player_minutes_sha256": _scenario_minutes_sha256(reconciled),
        "semantic_sha256": "0" * 64,
    }
    provisional = CurrentTeamMinuteReconciliation.model_construct(**cast(Any, body))
    body["semantic_sha256"] = current_team_minute_reconciliation_sha256(provisional)
    metrics = CurrentTeamMinuteReconciliation.model_validate(body)
    if metrics.total_absolute_minute_adjustment != sum(adjustments):
        raise ValueError("team-minute reconciliation objective accounting differs")
    return reconciled, metrics


class CurrentModelTeamScenarios(_FrozenModel):
    team_id: str
    bench_size: Literal[9] = 9
    bench_goalkeeper_slots: Literal[1] = 1
    team_path_policy: CurrentTeamPathPolicy
    scenarios: Annotated[tuple[ManualWeightedScenario, ...], Field(min_length=256, max_length=256)]
    reconciliations: Annotated[
        tuple[CurrentTeamMinuteReconciliation, ...],
        Field(min_length=256, max_length=256),
    ]
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
        if tuple(item.scenario_id for item in self.reconciliations) != expected_ids:
            raise ValueError("model reconciliation indices must match the 256-sample sequence")
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
        for scenario, reconciliation in zip(self.scenarios, self.reconciliations, strict=True):
            validate_current_team_path(scenario, self.team_path_policy)
            if reconciliation.reconciled_player_minutes_sha256 != _scenario_minutes_sha256(
                scenario
            ) or reconciliation.substitution_count != sum(
                item.role == "BENCH" and item.official_minutes > 0 for item in scenario.players
            ):
                raise ValueError("model reconciliation does not bind the coherent team path")
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
    policy = load_current_team_path_policy()
    scenarios: list[ManualWeightedScenario] = []
    reconciliations: list[CurrentTeamMinuteReconciliation] = []
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
        raw_scenario = ManualWeightedScenario(
            scenario_id=f"S{index:03d}",
            count=1,
            players=tuple(sorted(players, key=lambda item: item.player_id)),
        )
        scenario, reconciliation = reconcile_current_team_scenario(raw_scenario, policy)
        scenarios.append(scenario)
        reconciliations.append(reconciliation)
    hard = tuple(sorted(str(item["player_id"]) for item in result.core_hard_eligibility))
    return CurrentModelTeamScenarios(
        team_id=result.team_id,
        team_path_policy=policy,
        scenarios=tuple(scenarios),
        reconciliations=tuple(reconciliations),
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
        "warnings": tuple(sorted({*warnings, CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_WARNING})),
        "semantic_sha256": "0" * 64,
    }
    provisional = CurrentModelFixtureMinutesInput.model_construct(**cast(Any, body))
    body["semantic_sha256"] = current_model_fixture_sha256(provisional)
    return CurrentModelFixtureMinutesInput.model_validate(body)


__all__ = [
    "CURRENT_MODEL_FAMILY",
    "CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_WARNING",
    "CurrentModelFixtureMinutesInput",
    "CurrentModelTeamScenarios",
    "CurrentTeamMinuteReconciliation",
    "CurrentTeamPathPolicy",
    "build_current_model_fixture_minutes",
    "current_model_fixture_sha256",
    "current_team_minute_reconciliation_sha256",
    "current_team_path_policy_sha256",
    "load_current_team_path_policy",
    "reconcile_current_team_scenario",
    "validate_current_team_path",
]
