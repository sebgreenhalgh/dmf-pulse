"""Offline, aggregate-only calibration of the GW1 Wyscout role-prior candidate.

The public Pappalardo/Wyscout release is deliberately used only to estimate
league-era role pools.  This module never maps a Wyscout identity to a current
DMF/FPL identity and never performs a network request.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from json import loads
from math import lgamma, log, sqrt
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import BpsAuxiliaryRates, PlayerPosition
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.models import (
    EmpiricalBayesParameters,
    EvidenceSourceLevel,
    HistorySensitivityWorld,
    RolePooledPrior,
    TacticalRole,
    candidate_eb_parameters,
)


class _CandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MappingQuality(StrEnum):
    DIRECTLY_MAPPED = "DIRECTLY_MAPPED"
    DERIVED_WITH_DOCUMENTED_TRANSFORM = "DERIVED_WITH_DOCUMENTED_TRANSFORM"
    ROLE_POOLED_PROXY = "ROLE_POOLED_PROXY"
    GENERIC_FALLBACK = "GENERIC_FALLBACK"
    UNSUPPORTED_BY_SOURCE = "UNSUPPORTED_BY_SOURCE"


class SupportLevel(StrEnum):
    TACTICAL_ROLE = "TACTICAL_ROLE"
    FPL_POSITION = "FPL_POSITION"
    LEAGUE_GENERIC = "LEAGUE_GENERIC"
    FALLBACK_TO_LEAGUE_GENERIC = "FALLBACK_TO_LEAGUE_GENERIC"
    UNSUPPORTED = "UNSUPPORTED"


class WyscoutSourceFile(_CandidateModel):
    item_id: int = Field(gt=0)
    item_version: int = Field(gt=0)
    file_id: int = Field(gt=0)
    file_name: str = Field(min_length=1)
    download_url: str = Field(min_length=1)
    supplied_md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    download_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    used_member: str = Field(min_length=1)
    member_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WyscoutSourceGovernance(_CandidateModel):
    dataset_owner: Literal["Pappalardo / Wyscout Soccer Match Event Dataset"]
    paper: str = Field(min_length=1)
    figshare_collection: str = Field(min_length=1)
    figshare_collection_version: int = Field(gt=0)
    licence: Literal["CC BY 4.0"]
    licence_url: Literal["https://creativecommons.org/licenses/by/4.0/"]
    attribution: str = Field(min_length=1)
    retrieved_at: datetime
    files: tuple[WyscoutSourceFile, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def files_are_unique_and_timestamp_is_utc(self) -> WyscoutSourceGovernance:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        file_names = [row.file_name for row in self.files]
        if file_names != sorted(file_names) or len(file_names) != len(set(file_names)):
            raise ValueError("source files must be sorted and unique")
        return self


class CalibrationSummary(_CandidateModel):
    competition: Literal["English Premier League"]
    season: Literal["2017/18"]
    match_count: int = Field(gt=0)
    player_count: int = Field(gt=0)
    total_minutes: float = Field(gt=0.0)
    role_mapping_version: Literal["WYSCOUNT_BROAD_ROLE_TO_FPL_POSITION_V1"]
    excluded_non_regular_match_count: int = Field(ge=0)
    excluded_events_without_exposure: int = Field(ge=0)
    excluded_non_goalkeeper_save_events: int = Field(ge=0)


class RolePriorCell(_CandidateModel):
    field: str = Field(min_length=1)
    shrinkage_group_id: str = Field(min_length=1)
    position: PlayerPosition | None = None
    tactical_role: TacticalRole | None = None
    estimator: str = Field(min_length=1)
    player_count: int = Field(ge=0)
    exposure_minutes: float = Field(ge=0.0)
    event_count: int | None = Field(default=None, ge=0)
    raw_pooled_rate: float | None = Field(default=None, ge=0.0)
    prior_mean: float = Field(ge=0.0)
    prior_variance: float | None = Field(default=None, ge=0.0)
    interval_low: float | None = Field(default=None, ge=0.0)
    interval_high: float | None = Field(default=None, ge=0.0)
    support_level: SupportLevel
    minimum_support_met: bool
    mapping_quality: MappingQuality
    source_definition_reference: str = Field(min_length=1)
    fallback_level: str = Field(min_length=1)


class KappaAttempt(_CandidateModel):
    field: str = Field(min_length=1)
    player_count: int = Field(ge=0)
    moment_estimate_full_match_equivalents: float | None = Field(default=None, gt=0.0)
    reliable: bool
    reason: str = Field(min_length=1)


class KappaPolicy(_CandidateModel):
    role_mean_calibrated: Literal[True]
    shrinkage_strength_calibrated: Literal[False]
    status: Literal["TEMPORARY_CANDIDATE_PARAMETERS"]
    method: str = Field(min_length=1)
    central_world: Mapping[str, float]
    low_world: Mapping[str, float]
    high_world: Mapping[str, float]
    attempts: tuple[KappaAttempt, ...]


class CalibrationDiagnostic(_CandidateModel):
    name: str = Field(min_length=1)
    status: Literal["PASS", "LIMITATION", "INFO"]
    value: float | None = None
    detail: str = Field(min_length=1)


class RolePriorCandidateArtifact(_CandidateModel):
    schema_version: Literal["gw1-player-role-prior-candidate-v1"] = (
        "gw1-player-role-prior-candidate-v1"
    )
    status: Literal["CANDIDATE_NOT_ACCEPTED"] = "CANDIDATE_NOT_ACCEPTED"
    source: WyscoutSourceGovernance
    calibration: CalibrationSummary
    cells: tuple[RolePriorCell, ...] = Field(min_length=1)
    role_priors: tuple[RolePooledPrior, ...] = Field(min_length=1)
    kappa_policy: KappaPolicy
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transformation_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: tuple[CalibrationDiagnostic, ...]
    limitations: tuple[str, ...]
    human_acceptance: None = None
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def deterministic_ordering_is_preserved(self) -> RolePriorCandidateArtifact:
        keys = [(cell.shrinkage_group_id, cell.field) for cell in self.cells]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("role-prior cells must be sorted and unique")
        prior_keys = [row.shrinkage_group_id for row in self.role_priors]
        if prior_keys != sorted(prior_keys) or len(prior_keys) != len(set(prior_keys)):
            raise ValueError("role priors must be sorted and unique")
        return self


@dataclass(frozen=True)
class WyscoutInputPaths:
    """Explicit local paths only; downloading is intentionally outside this module."""

    players: Path
    matches: Path
    events: Path


@dataclass(frozen=True)
class _Group:
    shrinkage_group_id: str
    position: PlayerPosition | None
    tactical_role: TacticalRole | None
    source_level: EvidenceSourceLevel
    source_roles: tuple[str, ...] | None


_ROLE_TO_POSITION: Mapping[str, PlayerPosition] = {
    "Goalkeeper": PlayerPosition.GK,
    "Defender": PlayerPosition.DEF,
    "Midfielder": PlayerPosition.MID,
    "Forward": PlayerPosition.FWD,
}

_MINIMUM_PLAYER_COUNT = 20
_MINIMUM_EXPOSURE_MINUTES = 9_000.0
_JEFFREYS_SHAPE = 0.5
_GOAL_POSITION_TAGS = frozenset(range(1201, 1210))
_OUT_POSITION_TAGS = frozenset(range(1210, 1217))
_REQUIRED_PLAYER_KEYS = frozenset({"wyId", "role"})
_REQUIRED_MATCH_KEYS = frozenset({"wyId", "duration", "teamsData"})
_REQUIRED_EVENT_KEYS = frozenset(
    {
        "eventName",
        "eventSec",
        "matchId",
        "matchPeriod",
        "playerId",
        "subEventName",
        "tags",
    }
)

_DIRECT_COUNT_FIELDS: Mapping[str, tuple[MappingQuality, str]] = {
    "goal_rate_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Wyscout score events: tag 101 on Shot/Free Kick; excludes tag 102 own goals and "
        "Free Kick/Penalty.",
    ),
    "assist_rate_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout tag 301 (assist); broad source creation propensity only, not FPL assist replay.",
    ),
    "yellow_rate_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout tag 1702 (yellow card).",
    ),
    "red_rate_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Wyscout tags 1701 (red card) or 1703 (second yellow card).",
    ),
    "save_rate_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Wyscout Save attempt events excluding tag 101 goals and non-goalkeeper source roles.",
    ),
    "own_goal_weight": (
        MappingQuality.ROLE_POOLED_PROXY,
        "Wyscout tag 102 own-goal event rate; used only as a Stage-9 allocation weight.",
    ),
    "clearances_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout Others on the ball/Clearance subevent.",
    ),
    "interceptions_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout tag 1401 (interception).",
    ),
    "tackles_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Won Ground defending duel (subevent plus tag 703); not an assertion of exact Opta tackle semantics.",
    ),
    "fouls_conceded_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout Foul events attributed to the event player.",
    ),
    "key_passes_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout tag 302 (key pass).",
    ),
    "offsides_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout Offside events.",
    ),
    "pass_attempts_per90": (
        MappingQuality.DIRECTLY_MAPPED,
        "Wyscout Pass events.",
    ),
    "shots_off_target_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Shot events with an out/post position tag (1210-1216), excluding goals.",
    ),
    "shots_on_target_non_goal_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Shot events with a goal-mouth position tag (1201-1209), excluding goals.",
    ),
    "successful_dribbles_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Won Ground attacking duel (subevent plus tag 703), a documented dribble proxy.",
    ),
    "successful_open_play_crosses_per90": (
        MappingQuality.DERIVED_WITH_DOCUMENTED_TRANSFORM,
        "Accurate Pass/Cross events; Free Kick/Cross events are excluded by event type.",
    ),
}

_UNSUPPORTED_FIELDS: Mapping[str, tuple[float, str]] = {
    "saves_inside_box_fraction": (
        0.5,
        "No reliable save-location/inside-box denominator is exposed by the selected release; "
        "neutral compatibility fallback, not a measurement.",
    ),
    "blocks_per90": (
        0.0,
        "Tag 2101 labels a blocked actor event and cannot safely be assigned as a defender block.",
    ),
    "ball_recoveries_per90": (
        0.0,
        "No source event is definition-compatible with the Stage-9 ball-recovery field.",
    ),
    "big_chances_created_per90": (
        0.0,
        "Wyscout opportunity tag is not asserted to be the current FPL/Opta big-chance definition.",
    ),
    "big_chances_missed_per90": (
        0.0,
        "Wyscout opportunity tag is not asserted to be the current FPL/Opta big-chance definition.",
    ),
    "errors_leading_attempt_per90": (
        0.0,
        "No causal error-to-attempt linkage is available in this source subset.",
    ),
    "errors_leading_goal_per90": (
        0.0,
        "No causal error-to-goal linkage is available in this source subset.",
    ),
    "fouls_won_per90": (
        0.0,
        "Foul events identify the event actor, not a definition-compatible fouled player.",
    ),
    "goal_line_clearances_per90": (
        0.0,
        "No goal-line-clearance event is present in the published event taxonomy.",
    ),
    "times_tackled_per90": (
        0.0,
        "The current rules coefficient is zero and the source has no exact being-tackled field.",
    ),
}

_STRUCTURAL_FALLBACKS: Mapping[str, tuple[float, MappingQuality, str]] = {
    "goal_role_adjustment": (
        1.0,
        MappingQuality.ROLE_POOLED_PROXY,
        "The empirically calibrated rate is already role/position pooled; multiplying it again would double count role.",
    ),
    "assist_role_adjustment": (
        1.0,
        MappingQuality.ROLE_POOLED_PROXY,
        "The empirically calibrated rate is already role/position pooled; multiplying it again would double count role.",
    ),
    "penalty_weight": (
        1.0,
        MappingQuality.GENERIC_FALLBACK,
        "Uniform current-team fallback: historical 2017/18 identities do not establish a 2026/27 penalty taker.",
    ),
}


def _canonical_hash(model: BaseModel, *, excluded: set[str]) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude=excluded))


def _sha256_path(path: Path) -> str:
    if not path.is_file():
        raise IngestionError(
            "SOURCE_FILE_MISSING", f"required role-prior source file is missing: {path}"
        )
    return sha256(path.read_bytes()).hexdigest()


def _load_json_array(path: Path, *, expected_sha256: str, label: str) -> list[dict[str, Any]]:
    actual_sha256 = _sha256_path(path)
    if actual_sha256 != expected_sha256:
        raise IngestionError(
            "SOURCE_HASH_MISMATCH", f"{label} hash does not match governed metadata"
        )
    try:
        parsed = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IngestionError("SOURCE_SCHEMA_INVALID", f"{label} is not valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(row, dict) for row in parsed):
        raise IngestionError("SOURCE_SCHEMA_INVALID", f"{label} must be a JSON array of objects")
    return parsed


def _assert_no_current_fpl_material(rows: Sequence[Mapping[str, Any]], *, label: str) -> None:
    prohibited = {"fpl", "fantasy", "element", "current_price"}
    for row in rows:
        keys = {str(key).lower() for key in row}
        if keys & prohibited:
            raise IngestionError(
                "CURRENT_FPL_MATERIAL_FORBIDDEN",
                f"{label} contains a prohibited current-FPL-shaped field",
            )


def _require_keys(
    rows: Sequence[Mapping[str, Any]], required: frozenset[str], *, label: str
) -> None:
    if not rows or any(not required <= set(row) for row in rows):
        raise IngestionError(
            "SOURCE_SCHEMA_INVALID", f"{label} does not satisfy the required schema"
        )


def load_verified_wyscout_source(
    *, paths: WyscoutInputPaths, source: WyscoutSourceGovernance
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load only the three hash-bound, local source members used for calibration."""

    files = {item.used_member: item for item in source.files}
    required_members = {
        "players.json": paths.players,
        "matches_England.json": paths.matches,
        "events_England.json": paths.events,
    }
    if set(required_members) - set(files):
        raise IngestionError("SOURCE_METADATA_INCOMPLETE", "required Figshare members are absent")
    loaded = {
        member: _load_json_array(path, expected_sha256=files[member].member_sha256, label=member)
        for member, path in required_members.items()
    }
    _assert_no_current_fpl_material(loaded["players.json"], label="players")
    _assert_no_current_fpl_material(loaded["matches_England.json"], label="matches")
    _assert_no_current_fpl_material(loaded["events_England.json"], label="events")
    _require_keys(loaded["players.json"], _REQUIRED_PLAYER_KEYS, label="players")
    _require_keys(loaded["matches_England.json"], _REQUIRED_MATCH_KEYS, label="matches")
    _require_keys(loaded["events_England.json"], _REQUIRED_EVENT_KEYS, label="events")
    return (
        loaded["players.json"],
        loaded["matches_England.json"],
        loaded["events_England.json"],
    )


def map_wyscout_broad_role(role_name: str) -> PlayerPosition:
    """Map only the explicit four-category taxonomy published in ``players.json``."""

    try:
        return _ROLE_TO_POSITION[role_name]
    except KeyError as exc:
        raise IngestionError(
            "ROLE_TAXONOMY_UNSUPPORTED", f"unsupported Wyscout role: {role_name}"
        ) from exc


def _tag_ids(event: Mapping[str, Any]) -> set[int]:
    raw_tags = event["tags"]
    if not isinstance(raw_tags, list) or not all(isinstance(tag, dict) for tag in raw_tags):
        raise IngestionError("SOURCE_SCHEMA_INVALID", "event tags must be a list of objects")
    values = {tag.get("id") for tag in raw_tags}
    if not all(isinstance(value, int) for value in values):
        raise IngestionError("SOURCE_SCHEMA_INVALID", "event tag ids must be integers")
    return {value for value in values if isinstance(value, int)}


def _regulation_minute(event: Mapping[str, Any]) -> float:
    period = event["matchPeriod"]
    seconds = event["eventSec"]
    if not isinstance(period, str) or not isinstance(seconds, (int, float)):
        raise IngestionError("SOURCE_SCHEMA_INVALID", "event period and seconds must be valid")
    if period == "1H":
        minute = float(seconds) / 60.0
    elif period == "2H":
        minute = 45.0 + float(seconds) / 60.0
    else:
        return 90.0
    return min(90.0, max(0.0, minute))


def reconstruct_regulation_minutes(
    *, matches: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]
) -> tuple[dict[int, float], int]:
    """Reconstruct regulation exposure from XI, substitutions, and dismissals.

    Stoppage time is clipped at 90 by design.  Extra-time/suspended matches are
    excluded instead of pretending that an appearance is a full match.
    """

    red_exits: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for event in events:
        tags = _tag_ids(event)
        if not tags.intersection({1701, 1703}):
            continue
        match_id = event["matchId"]
        player_id = event["playerId"]
        if not isinstance(match_id, int) or not isinstance(player_id, int):
            raise IngestionError(
                "SOURCE_SCHEMA_INVALID", "red-card event identifiers must be integers"
            )
        red_exits[match_id].append((player_id, _regulation_minute(event)))

    minutes: defaultdict[int, float] = defaultdict(float)
    excluded_matches = 0
    for match in matches:
        if match["duration"] != "Regular":
            excluded_matches += 1
            continue
        match_id = match["wyId"]
        teams_data = match["teamsData"]
        if not isinstance(match_id, int) or not isinstance(teams_data, dict):
            raise IngestionError("SOURCE_SCHEMA_INVALID", "match identifiers/teamsData are invalid")
        active_by_team: list[dict[int, list[float]]] = []
        for team in teams_data.values():
            if not isinstance(team, dict):
                raise IngestionError("SOURCE_SCHEMA_INVALID", "teamsData entries must be objects")
            formation = team.get("formation")
            if not isinstance(formation, dict):
                raise IngestionError(
                    "MINUTES_UNAVAILABLE", "a regular match has no usable formation"
                )
            lineup = formation.get("lineup")
            substitutions = formation.get("substitutions")
            if not isinstance(lineup, list):
                raise IngestionError("MINUTES_UNAVAILABLE", "a regular match has no usable lineup")
            if substitutions == "null":
                substitutions = []
            if not isinstance(substitutions, list):
                raise IngestionError("MINUTES_UNAVAILABLE", "substitutions are invalid")
            active: dict[int, list[float]] = {}
            for row in lineup:
                if not isinstance(row, dict) or not isinstance(row.get("playerId"), int):
                    raise IngestionError("MINUTES_UNAVAILABLE", "lineup player ids are invalid")
                player_id = row["playerId"]
                if player_id in active:
                    raise IngestionError("MINUTES_UNAVAILABLE", "duplicate starting player")
                active[player_id] = [0.0, 90.0]
            if len(active) != 11:
                raise IngestionError("MINUTES_UNAVAILABLE", "a usable team must contain an XI")
            for substitution in substitutions:
                if not isinstance(substitution, dict):
                    raise IngestionError("MINUTES_UNAVAILABLE", "substitution must be an object")
                player_in = substitution.get("playerIn")
                player_out = substitution.get("playerOut")
                minute = substitution.get("minute")
                if (
                    not isinstance(player_in, int)
                    or not isinstance(player_out, int)
                    or not isinstance(minute, (int, float))
                ):
                    raise IngestionError("MINUTES_UNAVAILABLE", "substitution fields are invalid")
                if player_out not in active or player_in in active:
                    raise IngestionError(
                        "MINUTES_UNAVAILABLE", "substitution does not describe an active XI"
                    )
                clipped = min(90.0, max(0.0, float(minute)))
                active[player_out][1] = min(active[player_out][1], clipped)
                active[player_in] = [clipped, 90.0]
            active_by_team.append(active)
        active_by_player = {
            player_id: interval for team in active_by_team for player_id, interval in team.items()
        }
        if len(active_by_player) != sum(len(team) for team in active_by_team):
            raise IngestionError("MINUTES_UNAVAILABLE", "player appears for both teams")
        for player_id, minute in red_exits.get(match_id, []):
            interval = active_by_player.get(player_id)
            if interval is not None:
                interval[1] = min(interval[1], minute)
        for player_id, (start, end) in active_by_player.items():
            if end > start:
                minutes[player_id] += end - start
    if not minutes:
        raise IngestionError(
            "MINUTES_UNAVAILABLE", "no usable regulation minutes were reconstructed"
        )
    return dict(minutes), excluded_matches


def _event_counts(
    *,
    events: Sequence[Mapping[str, Any]],
    exposure_minutes: Mapping[int, float],
    source_roles: Mapping[int, str],
) -> tuple[dict[int, Counter[str]], int, int]:
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    excluded_without_exposure = 0
    excluded_non_goalkeeper_saves = 0
    for event in events:
        player_id = event["playerId"]
        if not isinstance(player_id, int):
            raise IngestionError("SOURCE_SCHEMA_INVALID", "event player id must be an integer")
        if player_id not in exposure_minutes or player_id not in source_roles:
            excluded_without_exposure += 1
            continue
        tags = _tag_ids(event)
        name = event["eventName"]
        sub_name = event["subEventName"]
        if not isinstance(name, str) or not isinstance(sub_name, str):
            raise IngestionError("SOURCE_SCHEMA_INVALID", "event names must be strings")
        row = counts[player_id]
        is_goal = 101 in tags and 102 not in tags and name in {"Shot", "Free Kick"}
        if is_goal:
            row["all_goals"] += 1
            if sub_name != "Penalty":
                row["non_penalty_goals"] += 1
        if 102 in tags:
            row["own_goals"] += 1
        if 301 in tags:
            row["assists"] += 1
        if 1702 in tags:
            row["yellow_cards"] += 1
        if tags.intersection({1701, 1703}):
            row["red_cards"] += 1
        if name == "Save attempt" and 101 not in tags:
            if source_roles[player_id] == "Goalkeeper":
                row["saves"] += 1
            else:
                excluded_non_goalkeeper_saves += 1
        if name == "Others on the ball" and sub_name == "Clearance":
            row["clearances"] += 1
        if 1401 in tags:
            row["interceptions"] += 1
        if name == "Duel" and sub_name == "Ground defending duel" and 703 in tags:
            row["tackles"] += 1
        if name == "Foul":
            row["fouls_conceded"] += 1
        if 302 in tags:
            row["key_passes"] += 1
        if name == "Offside":
            row["offsides"] += 1
        if name == "Pass":
            row["pass_attempts"] += 1
            if 1801 in tags:
                row["pass_completions"] += 1
        if name == "Shot" and 101 not in tags and tags.intersection(_OUT_POSITION_TAGS):
            row["shots_off_target"] += 1
        if name == "Shot" and 101 not in tags and tags.intersection(_GOAL_POSITION_TAGS):
            row["shots_on_target_non_goal"] += 1
        if name == "Duel" and sub_name == "Ground attacking duel" and 703 in tags:
            row["successful_dribbles"] += 1
        if name == "Pass" and sub_name == "Cross" and 1801 in tags:
            row["successful_open_play_crosses"] += 1
    return counts, excluded_without_exposure, excluded_non_goalkeeper_saves


def _groups() -> tuple[_Group, ...]:
    return (
        _Group(
            "wyscout-epl-2017-18-fpl-def",
            PlayerPosition.DEF,
            None,
            EvidenceSourceLevel.FPL_POSITION,
            ("Defender",),
        ),
        _Group(
            "wyscout-epl-2017-18-fpl-fwd",
            PlayerPosition.FWD,
            None,
            EvidenceSourceLevel.FPL_POSITION,
            ("Forward",),
        ),
        _Group(
            "wyscout-epl-2017-18-fpl-gk",
            PlayerPosition.GK,
            None,
            EvidenceSourceLevel.FPL_POSITION,
            ("Goalkeeper",),
        ),
        _Group(
            "wyscout-epl-2017-18-fpl-mid",
            PlayerPosition.MID,
            None,
            EvidenceSourceLevel.FPL_POSITION,
            ("Midfielder",),
        ),
        _Group(
            "wyscout-epl-2017-18-league-generic",
            None,
            None,
            EvidenceSourceLevel.LEAGUE_GENERIC,
            None,
        ),
        _Group(
            "wyscout-epl-2017-18-tactical-gk",
            PlayerPosition.GK,
            TacticalRole.GK,
            EvidenceSourceLevel.TACTICAL_ROLE,
            ("Goalkeeper",),
        ),
    )


def _normal_interval(mean: float, variance: float) -> tuple[float, float]:
    spread = 1.96 * sqrt(variance)
    return max(0.0, mean - spread), mean + spread


def _support(
    *, player_count: int, exposure_minutes: float, source_level: EvidenceSourceLevel
) -> tuple[bool, SupportLevel]:
    supported = (
        player_count >= _MINIMUM_PLAYER_COUNT and exposure_minutes >= _MINIMUM_EXPOSURE_MINUTES
    )
    if supported:
        return (
            True,
            SupportLevel.TACTICAL_ROLE
            if source_level is EvidenceSourceLevel.TACTICAL_ROLE
            else SupportLevel.FPL_POSITION
            if source_level is EvidenceSourceLevel.FPL_POSITION
            else SupportLevel.LEAGUE_GENERIC,
        )
    return False, SupportLevel.FALLBACK_TO_LEAGUE_GENERIC


def _count_cell(
    *,
    field: str,
    group: _Group,
    player_ids: set[int],
    minutes: Mapping[int, float],
    counts: Mapping[int, Counter[str]],
    event_key: str,
    fallback: RolePriorCell | None,
) -> RolePriorCell:
    exposure = sum(minutes[player_id] for player_id in player_ids) / 90.0
    total_minutes = exposure * 90.0
    player_count = len(player_ids)
    event_count = sum(counts[player_id][event_key] for player_id in player_ids)
    minimum_support_met, level = _support(
        player_count=player_count,
        exposure_minutes=total_minutes,
        source_level=group.source_level,
    )
    if not minimum_support_met and fallback is not None:
        return RolePriorCell(
            field=field,
            shrinkage_group_id=group.shrinkage_group_id,
            position=group.position,
            tactical_role=group.tactical_role,
            estimator="LEAGUE_GENERIC_FALLBACK_V1",
            player_count=player_count,
            exposure_minutes=total_minutes,
            event_count=event_count,
            raw_pooled_rate=event_count / exposure if exposure else None,
            prior_mean=fallback.prior_mean,
            prior_variance=fallback.prior_variance,
            interval_low=fallback.interval_low,
            interval_high=fallback.interval_high,
            support_level=level,
            minimum_support_met=False,
            mapping_quality=fallback.mapping_quality,
            source_definition_reference=fallback.source_definition_reference,
            fallback_level="LEAGUE_GENERIC",
        )
    if exposure <= 0.0:
        raise IngestionError(
            "MINUTES_UNAVAILABLE", "a calibrated group has zero regulation exposure"
        )
    shape = event_count + _JEFFREYS_SHAPE
    mean = shape / exposure
    variance = shape / (exposure * exposure)
    low, high = _normal_interval(mean, variance)
    quality, reference = _DIRECT_COUNT_FIELDS[field]
    return RolePriorCell(
        field=field,
        shrinkage_group_id=group.shrinkage_group_id,
        position=group.position,
        tactical_role=group.tactical_role,
        estimator="JEFFREYS_GAMMA_POISSON_POOLED_PER90_V1",
        player_count=player_count,
        exposure_minutes=total_minutes,
        event_count=event_count,
        raw_pooled_rate=event_count / exposure,
        prior_mean=mean,
        prior_variance=variance,
        interval_low=low,
        interval_high=high,
        support_level=level,
        minimum_support_met=minimum_support_met,
        mapping_quality=quality,
        source_definition_reference=reference,
        fallback_level="NONE" if minimum_support_met else "LEAGUE_GENERIC",
    )


def _pass_completion_cell(
    *,
    group: _Group,
    player_ids: set[int],
    minutes: Mapping[int, float],
    counts: Mapping[int, Counter[str]],
    fallback: RolePriorCell | None,
) -> RolePriorCell:
    total_minutes = sum(minutes[player_id] for player_id in player_ids)
    player_count = len(player_ids)
    attempts = sum(counts[player_id]["pass_attempts"] for player_id in player_ids)
    successes = sum(counts[player_id]["pass_completions"] for player_id in player_ids)
    minimum_support_met, level = _support(
        player_count=player_count,
        exposure_minutes=total_minutes,
        source_level=group.source_level,
    )
    if not minimum_support_met and fallback is not None:
        return RolePriorCell(
            field="pass_completion_probability",
            shrinkage_group_id=group.shrinkage_group_id,
            position=group.position,
            tactical_role=group.tactical_role,
            estimator="LEAGUE_GENERIC_FALLBACK_V1",
            player_count=player_count,
            exposure_minutes=total_minutes,
            event_count=successes,
            raw_pooled_rate=successes / attempts if attempts else None,
            prior_mean=fallback.prior_mean,
            prior_variance=fallback.prior_variance,
            interval_low=fallback.interval_low,
            interval_high=fallback.interval_high,
            support_level=level,
            minimum_support_met=False,
            mapping_quality=fallback.mapping_quality,
            source_definition_reference=fallback.source_definition_reference,
            fallback_level="LEAGUE_GENERIC",
        )
    if attempts <= 0:
        raise IngestionError("SOURCE_SCHEMA_INVALID", "a supported group has no pass attempts")
    alpha = successes + _JEFFREYS_SHAPE
    beta = attempts - successes + _JEFFREYS_SHAPE
    mean = alpha / (alpha + beta)
    variance = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1.0))
    low, high = _normal_interval(mean, variance)
    return RolePriorCell(
        field="pass_completion_probability",
        shrinkage_group_id=group.shrinkage_group_id,
        position=group.position,
        tactical_role=group.tactical_role,
        estimator="JEFFREYS_BETA_BINOMIAL_POOLED_V1",
        player_count=player_count,
        exposure_minutes=total_minutes,
        event_count=successes,
        raw_pooled_rate=successes / attempts,
        prior_mean=mean,
        prior_variance=variance,
        interval_low=low,
        interval_high=high,
        support_level=level,
        minimum_support_met=minimum_support_met,
        mapping_quality=MappingQuality.DIRECTLY_MAPPED,
        source_definition_reference="Wyscout Pass events with tag 1801 (accurate) over all Pass events.",
        fallback_level="NONE" if minimum_support_met else "LEAGUE_GENERIC",
    )


def _fallback_cell(
    *, field: str, group: _Group, player_ids: set[int], minutes: Mapping[int, float]
) -> RolePriorCell:
    total_minutes = sum(minutes[player_id] for player_id in player_ids)
    player_count = len(player_ids)
    if field in _UNSUPPORTED_FIELDS:
        value, reference = _UNSUPPORTED_FIELDS[field]
        quality = MappingQuality.UNSUPPORTED_BY_SOURCE
        level = SupportLevel.UNSUPPORTED
        estimator = "EXPLICIT_UNSUPPORTED_COMPATIBILITY_FALLBACK_V1"
    else:
        value, quality, reference = _STRUCTURAL_FALLBACKS[field]
        level = SupportLevel.LEAGUE_GENERIC
        estimator = "EXPLICIT_STRUCTURAL_FALLBACK_V1"
    return RolePriorCell(
        field=field,
        shrinkage_group_id=group.shrinkage_group_id,
        position=group.position,
        tactical_role=group.tactical_role,
        estimator=estimator,
        player_count=player_count,
        exposure_minutes=total_minutes,
        event_count=None,
        raw_pooled_rate=None,
        prior_mean=value,
        prior_variance=None,
        interval_low=None,
        interval_high=None,
        support_level=level,
        minimum_support_met=False,
        mapping_quality=quality,
        source_definition_reference=reference,
        fallback_level="EXPLICIT_NEUTRAL_OR_ZERO_COMPATIBILITY_FALLBACK",
    )


def _moment_kappa(
    *, event_key: str, minutes: Mapping[int, float], counts: Mapping[int, Counter[str]]
) -> KappaAttempt:
    eligible = [player_id for player_id, value in minutes.items() if value >= 450.0]
    exposures = [minutes[player_id] / 90.0 for player_id in eligible]
    values = [counts[player_id][event_key] for player_id in eligible]
    if len(eligible) < 100 or not exposures:
        return KappaAttempt(
            field=event_key,
            player_count=len(eligible),
            moment_estimate_full_match_equivalents=None,
            reliable=False,
            reason="insufficient eligible players for a stable moment estimate",
        )
    mean = sum(values) / sum(exposures)
    rates = [value / exposure for value, exposure in zip(values, exposures, strict=True)]
    sample_variance = sum((rate - mean) ** 2 for rate in rates) / (len(rates) - 1)
    poisson_component = mean * sum(1.0 / exposure for exposure in exposures) / len(exposures)
    latent_variance = sample_variance - poisson_component
    estimate = mean / latent_variance if latent_variance > 0.0 and mean > 0.0 else None
    return KappaAttempt(
        field=event_key,
        player_count=len(eligible),
        moment_estimate_full_match_equivalents=estimate,
        reliable=False,
        reason=(
            "attempted moment estimate is retained only diagnostically: one historical season, "
            "coarse source taxonomy, and unmodelled club/context heterogeneity do not justify "
            "calibrating current-player shrinkage strength"
        ),
    )


def _poisson_log_likelihood(events: int, exposure: float, rate: float) -> float:
    if exposure <= 0.0 or rate <= 0.0:
        return 0.0
    expectation = rate * exposure
    return events * log(expectation) - expectation - lgamma(events + 1.0)


def _position_vs_generic_diagnostic(
    *,
    event_key: str,
    minutes: Mapping[int, float],
    counts: Mapping[int, Counter[str]],
    positions: Mapping[int, PlayerPosition],
) -> CalibrationDiagnostic:
    total_events = sum(counts[player_id][event_key] for player_id in minutes)
    total_exposure = sum(minutes.values()) / 90.0
    by_position_events: Counter[PlayerPosition] = Counter()
    by_position_exposure: defaultdict[PlayerPosition, float] = defaultdict(float)
    for player_id, minute in minutes.items():
        position = positions[player_id]
        by_position_events[position] += counts[player_id][event_key]
        by_position_exposure[position] += minute / 90.0
    delta = 0.0
    for player_id, minute in minutes.items():
        exposure = minute / 90.0
        events = counts[player_id][event_key]
        position = positions[player_id]
        position_exposure_after_holdout = by_position_exposure[position] - exposure
        if position_exposure_after_holdout <= 0.0:
            continue
        generic_rate = (total_events - events + _JEFFREYS_SHAPE) / (total_exposure - exposure)
        position_rate = (
            by_position_events[position] - events + _JEFFREYS_SHAPE
        ) / position_exposure_after_holdout
        delta += _poisson_log_likelihood(events, exposure, position_rate) - _poisson_log_likelihood(
            events, exposure, generic_rate
        )
    return CalibrationDiagnostic(
        name=f"leave_player_out_position_vs_generic_{event_key}",
        status="INFO",
        value=delta,
        detail="Positive values favour coarse source-role/FPL-position pooling over a league-generic rate.",
    )


def _prior_from_cells(group: _Group, cells: Mapping[str, RolePriorCell]) -> RolePooledPrior:
    def value(field: str) -> float:
        return cells[field].prior_mean

    return RolePooledPrior(
        shrinkage_group_id=group.shrinkage_group_id,
        position=group.position,
        tactical_role=group.tactical_role,
        source_level=group.source_level,
        fallback_reason=(
            "WYSCOUNT_BROAD_ROLE_ONLY: GK is the sole fine tactical role; DEF/MID/FWD are "
            "FPL-position fallbacks and all remaining requested tactical roles resolve through them."
        ),
        prior_version="GW1_WYSCOUNT_EPL_2017_18_ROLE_PRIOR_CANDIDATE_V1",
        source_reference="Pappalardo/Massucco Figshare CC-BY EPL 2017/18 aggregate-only calibration",
        goal_rate_per90=value("goal_rate_per90"),
        assist_rate_per90=value("assist_rate_per90"),
        yellow_rate_per90=value("yellow_rate_per90"),
        red_rate_per90=value("red_rate_per90"),
        save_rate_per90=value("save_rate_per90"),
        goal_role_adjustment=value("goal_role_adjustment"),
        assist_role_adjustment=value("assist_role_adjustment"),
        penalty_weight=value("penalty_weight"),
        own_goal_weight=value("own_goal_weight"),
        saves_inside_box_fraction=value("saves_inside_box_fraction"),
        clearances_per90=value("clearances_per90"),
        blocks_per90=value("blocks_per90"),
        interceptions_per90=value("interceptions_per90"),
        tackles_per90=value("tackles_per90"),
        ball_recoveries_per90=value("ball_recoveries_per90"),
        bps_auxiliary=BpsAuxiliaryRates(
            big_chances_created_per90=value("big_chances_created_per90"),
            big_chances_missed_per90=value("big_chances_missed_per90"),
            errors_leading_attempt_per90=value("errors_leading_attempt_per90"),
            errors_leading_goal_per90=value("errors_leading_goal_per90"),
            fouls_conceded_per90=value("fouls_conceded_per90"),
            fouls_won_per90=value("fouls_won_per90"),
            goal_line_clearances_per90=value("goal_line_clearances_per90"),
            key_passes_per90=value("key_passes_per90"),
            offsides_per90=value("offsides_per90"),
            pass_attempts_per90=value("pass_attempts_per90"),
            pass_completion_probability=value("pass_completion_probability"),
            recoveries_per90=value("ball_recoveries_per90"),
            shots_off_target_per90=value("shots_off_target_per90"),
            shots_on_target_non_goal_per90=value("shots_on_target_non_goal_per90"),
            successful_dribbles_per90=value("successful_dribbles_per90"),
            successful_open_play_crosses_per90=value("successful_open_play_crosses_per90"),
            times_tackled_per90=value("times_tackled_per90"),
        ),
    )


def _kappa_world(world: HistorySensitivityWorld) -> dict[str, float]:
    parameters = candidate_eb_parameters(world)
    return {
        "goal": parameters.goal_kappa_full_match_equivalents,
        "assist": parameters.assist_kappa_full_match_equivalents,
        "yellow": parameters.yellow_kappa_full_match_equivalents,
        "red": parameters.red_kappa_full_match_equivalents,
        "save": parameters.save_kappa_full_match_equivalents,
    }


def _build_policy(cells: Sequence[RolePriorCell]) -> KappaPolicy:
    policy_payload = {
        "minimum_player_count": _MINIMUM_PLAYER_COUNT,
        "minimum_exposure_minutes": _MINIMUM_EXPOSURE_MINUTES,
        "count_estimator": "JEFFREYS_GAMMA_POISSON_POOLED_PER90_V1",
        "pass_estimator": "JEFFREYS_BETA_BINOMIAL_POOLED_V1",
        "unsupported_fields": sorted(_UNSUPPORTED_FIELDS),
        "cell_count": len(cells),
    }
    _ = canonical_sha256(policy_payload)
    return KappaPolicy(
        role_mean_calibrated=True,
        shrinkage_strength_calibrated=False,
        status="TEMPORARY_CANDIDATE_PARAMETERS",
        method=(
            "Moment estimates are attempted for transparency but not adopted: the single-season, "
            "coarse-role historical source is not adequate to fit current-player shrinkage strength."
        ),
        central_world=_kappa_world(HistorySensitivityWorld.CENTRAL_TEMPORARY),
        low_world=_kappa_world(HistorySensitivityWorld.LOW_SHRINKAGE),
        high_world=_kappa_world(HistorySensitivityWorld.HIGH_SHRINKAGE),
        attempts=(),
    )


def build_role_prior_candidate(
    *,
    paths: WyscoutInputPaths,
    source: WyscoutSourceGovernance,
    transformation_code_commit: str,
) -> RolePriorCandidateArtifact:
    """Build the immutable aggregate candidate from hash-verified local Wyscout files."""

    if len(transformation_code_commit) != 40 or any(
        value not in "0123456789abcdef" for value in transformation_code_commit
    ):
        raise IngestionError(
            "CODE_COMMIT_INVALID", "transformation code commit must be a lowercase SHA-1"
        )
    players, matches, events = load_verified_wyscout_source(paths=paths, source=source)
    source_roles: dict[int, str] = {}
    positions: dict[int, PlayerPosition] = {}
    for player in players:
        player_id = player.get("wyId")
        role = player.get("role")
        if (
            not isinstance(player_id, int)
            or not isinstance(role, dict)
            or not isinstance(role.get("name"), str)
        ):
            raise IngestionError("SOURCE_SCHEMA_INVALID", "player role taxonomy is invalid")
        if player_id in source_roles:
            raise IngestionError("SOURCE_SCHEMA_INVALID", "duplicate source player id")
        role_name = role["name"]
        source_roles[player_id] = role_name
        positions[player_id] = map_wyscout_broad_role(role_name)
    minutes, excluded_non_regular = reconstruct_regulation_minutes(matches=matches, events=events)
    missing_roles = set(minutes) - set(source_roles)
    if missing_roles:
        raise IngestionError(
            "ROLE_TAXONOMY_UNSUPPORTED", "exposed source player lacks a declared role"
        )
    counts, excluded_events, excluded_non_goalkeeper_saves = _event_counts(
        events=events,
        exposure_minutes=minutes,
        source_roles=source_roles,
    )
    groups = _groups()
    group_players: dict[str, set[int]] = {}
    for group in groups:
        group_players[group.shrinkage_group_id] = {
            player_id
            for player_id in minutes
            if group.source_roles is None or source_roles[player_id] in group.source_roles
        }
    generic_group = next(group for group in groups if group.source_roles is None)
    generic_players = group_players[generic_group.shrinkage_group_id]
    generic_cells: dict[str, RolePriorCell] = {}
    for field, event_key in (
        ("goal_rate_per90", "non_penalty_goals"),
        ("assist_rate_per90", "assists"),
        ("yellow_rate_per90", "yellow_cards"),
        ("red_rate_per90", "red_cards"),
        ("save_rate_per90", "saves"),
        ("own_goal_weight", "own_goals"),
        ("clearances_per90", "clearances"),
        ("interceptions_per90", "interceptions"),
        ("tackles_per90", "tackles"),
        ("fouls_conceded_per90", "fouls_conceded"),
        ("key_passes_per90", "key_passes"),
        ("offsides_per90", "offsides"),
        ("pass_attempts_per90", "pass_attempts"),
        ("shots_off_target_per90", "shots_off_target"),
        ("shots_on_target_non_goal_per90", "shots_on_target_non_goal"),
        ("successful_dribbles_per90", "successful_dribbles"),
        ("successful_open_play_crosses_per90", "successful_open_play_crosses"),
    ):
        generic_cells[field] = _count_cell(
            field=field,
            group=generic_group,
            player_ids=generic_players,
            minutes=minutes,
            counts=counts,
            event_key=event_key,
            fallback=None,
        )
    generic_cells["pass_completion_probability"] = _pass_completion_cell(
        group=generic_group,
        player_ids=generic_players,
        minutes=minutes,
        counts=counts,
        fallback=None,
    )
    for field in sorted({*_UNSUPPORTED_FIELDS, *_STRUCTURAL_FALLBACKS}):
        generic_cells[field] = _fallback_cell(
            field=field,
            group=generic_group,
            player_ids=generic_players,
            minutes=minutes,
        )
    cell_maps: dict[str, dict[str, RolePriorCell]] = {
        generic_group.shrinkage_group_id: generic_cells
    }
    for group in groups:
        if group is generic_group:
            continue
        player_ids = group_players[group.shrinkage_group_id]
        group_cells: dict[str, RolePriorCell] = {}
        for field, event_key in (
            ("goal_rate_per90", "non_penalty_goals"),
            ("assist_rate_per90", "assists"),
            ("yellow_rate_per90", "yellow_cards"),
            ("red_rate_per90", "red_cards"),
            ("save_rate_per90", "saves"),
            ("own_goal_weight", "own_goals"),
            ("clearances_per90", "clearances"),
            ("interceptions_per90", "interceptions"),
            ("tackles_per90", "tackles"),
            ("fouls_conceded_per90", "fouls_conceded"),
            ("key_passes_per90", "key_passes"),
            ("offsides_per90", "offsides"),
            ("pass_attempts_per90", "pass_attempts"),
            ("shots_off_target_per90", "shots_off_target"),
            ("shots_on_target_non_goal_per90", "shots_on_target_non_goal"),
            ("successful_dribbles_per90", "successful_dribbles"),
            ("successful_open_play_crosses_per90", "successful_open_play_crosses"),
        ):
            group_cells[field] = _count_cell(
                field=field,
                group=group,
                player_ids=player_ids,
                minutes=minutes,
                counts=counts,
                event_key=event_key,
                fallback=generic_cells[field],
            )
        group_cells["pass_completion_probability"] = _pass_completion_cell(
            group=group,
            player_ids=player_ids,
            minutes=minutes,
            counts=counts,
            fallback=generic_cells["pass_completion_probability"],
        )
        for field in sorted({*_UNSUPPORTED_FIELDS, *_STRUCTURAL_FALLBACKS}):
            group_cells[field] = _fallback_cell(
                field=field,
                group=group,
                player_ids=player_ids,
                minutes=minutes,
            )
        cell_maps[group.shrinkage_group_id] = group_cells
    all_cells = tuple(
        sorted(
            (cell for group_cells in cell_maps.values() for cell in group_cells.values()),
            key=lambda cell: (cell.shrinkage_group_id, cell.field),
        )
    )
    priors = tuple(
        sorted(
            (_prior_from_cells(group, cell_maps[group.shrinkage_group_id]) for group in groups),
            key=lambda row: row.shrinkage_group_id,
        )
    )
    attempts = tuple(
        _moment_kappa(event_key=key, minutes=minutes, counts=counts)
        for key in ("non_penalty_goals", "assists", "yellow_cards", "red_cards", "saves")
    )
    initial_policy = _build_policy(all_cells)
    policy = initial_policy.model_copy(update={"attempts": attempts})
    policy_hash = _canonical_hash(policy, excluded=set())
    fwd_goal = cell_maps["wyscout-epl-2017-18-fpl-fwd"]["goal_rate_per90"].prior_mean
    def_goal = cell_maps["wyscout-epl-2017-18-fpl-def"]["goal_rate_per90"].prior_mean
    mid_assist = cell_maps["wyscout-epl-2017-18-fpl-mid"]["assist_rate_per90"].prior_mean
    def_assist = cell_maps["wyscout-epl-2017-18-fpl-def"]["assist_rate_per90"].prior_mean
    def_clearances = cell_maps["wyscout-epl-2017-18-fpl-def"]["clearances_per90"].prior_mean
    fwd_clearances = cell_maps["wyscout-epl-2017-18-fpl-fwd"]["clearances_per90"].prior_mean
    diagnostics = (
        _position_vs_generic_diagnostic(
            event_key="non_penalty_goals", minutes=minutes, counts=counts, positions=positions
        ),
        _position_vs_generic_diagnostic(
            event_key="assists", minutes=minutes, counts=counts, positions=positions
        ),
        CalibrationDiagnostic(
            name="fine_tactical_role_pooling",
            status="LIMITATION",
            detail=(
                "The selected players.json taxonomy supplies Goalkeeper, Defender, Midfielder, and "
                "Forward only. CB, FB_WB, DM, CM, AM, WINGER, and CF are deliberately unresolved "
                "to FPL-position fallbacks."
            ),
        ),
        CalibrationDiagnostic(
            name="fwd_non_penalty_goal_rate_exceeds_def",
            status="PASS" if fwd_goal > def_goal else "LIMITATION",
            value=fwd_goal - def_goal,
            detail="Sanity check of the supported Forward versus Defender coarse pools.",
        ),
        CalibrationDiagnostic(
            name="mid_assist_rate_exceeds_def",
            status="PASS" if mid_assist > def_assist else "LIMITATION",
            value=mid_assist - def_assist,
            detail="Sanity check of broad source assist propensity, not FPL assist eligibility.",
        ),
        CalibrationDiagnostic(
            name="def_clearance_rate_exceeds_fwd",
            status="PASS" if def_clearances > fwd_clearances else "LIMITATION",
            value=def_clearances - fwd_clearances,
            detail="Sanity check of direct Wyscout clearance frequencies in coarse pools.",
        ),
        CalibrationDiagnostic(
            name="goalkeeper_save_location",
            status="LIMITATION",
            detail="Save attempts support a GK save-rate candidate after goal/non-GK exclusions; "
            "inside-box save fraction remains unsupported and uses a visible neutral fallback.",
        ),
    )
    dataset_sha256 = canonical_sha256(
        {
            "files": [item.model_dump(mode="json") for item in source.files],
            "members_used": ["events_England.json", "matches_England.json", "players.json"],
        }
    )
    provisional = RolePriorCandidateArtifact.model_construct(
        source=source,
        calibration=CalibrationSummary(
            competition="English Premier League",
            season="2017/18",
            match_count=len(matches) - excluded_non_regular,
            player_count=len(minutes),
            total_minutes=sum(minutes.values()),
            role_mapping_version="WYSCOUNT_BROAD_ROLE_TO_FPL_POSITION_V1",
            excluded_non_regular_match_count=excluded_non_regular,
            excluded_events_without_exposure=excluded_events,
            excluded_non_goalkeeper_save_events=excluded_non_goalkeeper_saves,
        ),
        cells=all_cells,
        role_priors=priors,
        kappa_policy=policy,
        policy_sha256=policy_hash,
        transformation_code_commit=transformation_code_commit,
        dataset_sha256=dataset_sha256,
        diagnostics=diagnostics,
        limitations=(
            "CANDIDATE_NOT_HUMAN_ACCEPTED",
            "OPEN_DATA_IS_BROAD_HISTORICAL_POOL_NOT_CURRENT_PLAYER_EVIDENCE",
            "NO_WYSCOUT_IDENTITY_IS_RETAINED_OR_JOINED_TO_CURRENT_DMF_PLAYERS",
            "STAGE7_PARTICIPATION_OWNS_CURRENT_MINUTES_AND_ON_PITCH_ELIGIBILITY",
            "WYSCOUNT_ASSIST_IS_BROAD_PROPENSITY_ONLY_FPL_ASSIST_RULES_REMAIN_STAGE9",
            "PENALTY_WEIGHT_IS_UNIFORM_CURRENT_TEAM_FALLBACK_NOT_HISTORICAL_IDENTITY_INFERENCE",
            "BPS_RATES_ARE_EVENT_FREQUENCY_BASELINES_NOT_2017_18_FPL_COEFFICIENTS",
            "UNSUPPORTED_FIELDS_ARE_EXPLICIT_AND_NEVER_PRESENTED_AS_CALIBRATED",
        ),
        artifact_sha256="0" * 64,
    )
    return RolePriorCandidateArtifact(
        source=source,
        calibration=provisional.calibration,
        cells=all_cells,
        role_priors=priors,
        kappa_policy=policy,
        policy_sha256=policy_hash,
        transformation_code_commit=transformation_code_commit,
        dataset_sha256=dataset_sha256,
        diagnostics=diagnostics,
        limitations=provisional.limitations,
        artifact_sha256=_canonical_hash(provisional, excluded={"artifact_sha256"}),
    )


def verify_role_prior_candidate(
    candidate: RolePriorCandidateArtifact,
) -> RolePriorCandidateArtifact:
    """Verify the candidate's immutable digest before it reaches the compiler."""

    expected = _canonical_hash(candidate, excluded={"artifact_sha256"})
    if candidate.artifact_sha256 != expected:
        raise IngestionError("ARTIFACT_HASH_MISMATCH", "role-prior candidate digest is invalid")
    return candidate


def role_priors_from_candidate(
    candidate: RolePriorCandidateArtifact,
) -> tuple[RolePooledPrior, ...]:
    """Return only immutable aggregate priors; no Wyscout identity leaves the artifact."""

    verified = verify_role_prior_candidate(candidate)
    if verified.status != "CANDIDATE_NOT_ACCEPTED":
        raise IngestionError("ARTIFACT_STATUS_INVALID", "unexpected role-prior artifact status")
    return verified.role_priors


def candidate_eb_parameters_from_role_prior(
    candidate: RolePriorCandidateArtifact, *, world: HistorySensitivityWorld
) -> EmpiricalBayesParameters:
    """Expose the declared temporary worlds alongside calibrated group means."""

    verified = verify_role_prior_candidate(candidate)
    if verified.kappa_policy.shrinkage_strength_calibrated:
        raise IngestionError(
            "KAPPA_POLICY_INVALID", "candidate must not claim fitted shrinkage strength"
        )
    return candidate_eb_parameters(world)


def load_role_prior_candidate(path: Path) -> RolePriorCandidateArtifact:
    """Explicit offline file load for an operator-selected immutable artifact."""

    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise IngestionError("ARTIFACT_READ_FAILED", "role-prior candidate cannot be read") from exc
    try:
        candidate = RolePriorCandidateArtifact.model_validate_json(payload)
    except ValueError as exc:
        raise IngestionError(
            "ARTIFACT_READ_FAILED", "role-prior candidate schema is invalid"
        ) from exc
    return verify_role_prior_candidate(candidate)


__all__ = [
    "CalibrationDiagnostic",
    "CalibrationSummary",
    "KappaAttempt",
    "KappaPolicy",
    "MappingQuality",
    "RolePriorCandidateArtifact",
    "RolePriorCell",
    "SupportLevel",
    "WyscoutInputPaths",
    "WyscoutSourceFile",
    "WyscoutSourceGovernance",
    "build_role_prior_candidate",
    "candidate_eb_parameters_from_role_prior",
    "load_role_prior_candidate",
    "map_wyscout_broad_role",
    "reconstruct_regulation_minutes",
    "role_priors_from_candidate",
    "verify_role_prior_candidate",
]
