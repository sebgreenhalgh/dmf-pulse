"""Offline, candidate-only calibration for the GW1 league-wide score support prior.

The module deliberately knows nothing about current teams, players, providers, or
market retrieval.  It parses a pinned historical source supplied by the caller,
derives one league-wide independent-Poisson regulariser, and exercises the
accepted Stage-8 score grid and soft-KL projection for offline diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any, Literal

from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    SHA256_PATTERN,
    canonical_decimal_text,
    canonical_json_sha256,
    format_utc,
    parse_utc,
    positive_decimal,
    public_measure_text,
    public_probability_text,
    quantize_measure,
)
from dmf_pulse.football_events.market_constraints import MarketConstraintSet
from dmf_pulse.football_events.score_prior import ScorePrior, build_score_prior
from dmf_pulse.football_events.score_projection import project_to_markets
from dmf_pulse.football_events.service import ScoreBaselinePolicy, ScorePriorRequest

SOURCE_REPOSITORY_URL = "https://github.com/openfootball/england"
SOURCE_OWNER = "openfootball"
SOURCE_COMMIT = "10fa650c5d0f137f0d71d6b9fc723076060fe80e"
SOURCE_LICENCE = "CC0-1.0"
PARSER_VERSION = "OPENFOOTBALL_TEXT_RESULTS_V1"
MODEL_FAMILY = "INDEPENDENT_POISSON_V1"
ARTIFACT_SCHEMA_VERSION = "gw1-support-prior-candidate-v1"
WEIGHT_METHOD = "EXPONENTIAL_HALF_LIFE_SEASONS_V1"
HALF_LIFE_SEASONS = Decimal("2")
RATE_SCALE = Decimal("0.0000000001")


@dataclass(frozen=True, slots=True)
class SeasonSource:
    """One deliberately fixed source file in chronological calibration order."""

    season: str
    relative_path: str
    age_seasons: int


SEASON_SOURCES: tuple[SeasonSource, ...] = (
    SeasonSource("2021/22", "2021-22/1-premierleague.txt", 4),
    SeasonSource("2022/23", "2022-23/1-premierleague.txt", 3),
    SeasonSource("2023/24", "2023-24/1-premierleague.txt", 2),
    SeasonSource("2024/25", "2024-25/1-premierleague.txt", 1),
    SeasonSource("2025/26", "2025-26/1-premierleague.txt", 0),
)


class SupportPriorError(ValueError):
    """Typed, fail-closed source/calibration error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedFixture:
    """A completed full-time fixture parsed from one source line."""

    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    line_number: int


@dataclass(frozen=True, slots=True)
class SeasonSummary:
    """One source file's validated league-wide completed-match summary."""

    source: SeasonSource
    source_sha256: str
    match_count: int
    home_goal_total: int
    away_goal_total: int
    home_goal_rate: Decimal
    away_goal_rate: Decimal
    weight: Decimal

    def public_dict(self) -> dict[str, Any]:
        return {
            "age_seasons": self.source.age_seasons,
            "away_goal_rate": canonical_decimal_text(self.away_goal_rate),
            "away_goal_total": self.away_goal_total,
            "home_goal_rate": canonical_decimal_text(self.home_goal_rate),
            "home_goal_total": self.home_goal_total,
            "match_count": self.match_count,
            "path": self.source.relative_path,
            "season": self.source.season,
            "sha256": self.source_sha256,
            "weight": canonical_decimal_text(self.weight),
        }


@dataclass(frozen=True, slots=True)
class SupportPriorCalibration:
    """Derived, team-agnostic support-prior calibration before acceptance."""

    seasons: tuple[SeasonSummary, ...]
    home_goal_rate: Decimal
    away_goal_rate: Decimal
    dataset_sha256: str

    @property
    def match_count(self) -> int:
        return sum(item.match_count for item in self.seasons)

    @property
    def central_home_goal_rate(self) -> Decimal:
        return _round_rate(self.home_goal_rate)

    @property
    def central_away_goal_rate(self) -> Decimal:
        return _round_rate(self.away_goal_rate)

    def score_prior_request(self) -> ScorePriorRequest:
        """Use the existing public Stage-8 prior input precision and model family."""

        return ScorePriorRequest(
            home_goal_rate=quantize_measure(self.central_home_goal_rate),
            away_goal_rate=quantize_measure(self.central_away_goal_rate),
        )


@dataclass(frozen=True, slots=True)
class SupportPriorWorld:
    """One explicit epistemic sensitivity world, not a posterior ensemble member."""

    availability: Literal["H2H_TOTALS", "H2H_ONLY"]
    home_multiplier: Decimal
    away_multiplier: Decimal
    home_goal_rate: Decimal
    away_goal_rate: Decimal
    world_sha256: str

    def public_dict(self) -> dict[str, str]:
        return {
            "availability": self.availability,
            "away_goal_rate": canonical_decimal_text(self.away_goal_rate),
            "away_multiplier": canonical_decimal_text(self.away_multiplier),
            "home_goal_rate": canonical_decimal_text(self.home_goal_rate),
            "home_multiplier": canonical_decimal_text(self.home_multiplier),
            "world_sha256": self.world_sha256,
        }


_V_FIXTURE = re.compile(
    r"^(?P<home>.+?)\s+v\s+(?P<away>.+?)\s+"
    r"(?P<home_goals>-?\d+)\s*-\s*(?P<away_goals>-?\d+)"
    r"(?:\s+\(-?\d+\s*-\s*-?\d+\))?\s*$"
)
_LEGACY_FIXTURE = re.compile(
    r"^(?P<home>.+?)\s+(?P<home_goals>-?\d+)\s*-\s*(?P<away_goals>-?\d+)"
    r"(?:\s+\(-?\d+\s*-\s*-?\d+\))?\s+(?P<away>.+?)\s*$"
)
_TIME_PREFIX = re.compile(r"^\s*(?:\d{1,2}:\d{2}(?::\d{2})?\s+)")
_SCORE_TOKEN = re.compile(r"-?\d+\s*-\s*-?\d+")


def _canonical_team(value: str, *, label: str, line_number: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise SupportPriorError(
            "MALFORMED_FIXTURE",
            f"line {line_number} has an empty {label} team name",
        )
    return normalized


def parse_openfootball_completed_fixtures(text: str) -> tuple[ParsedFixture, ...]:
    """Parse completed Football.TXT score lines and reject malformed candidates.

    Both older ``Home 1-0 Away`` and current ``Home v Away 1-0`` layouts are
    accepted.  Lines without a result token are ignored only when they are not
    fixture-shaped; a malformed fixture is never silently treated as metadata.
    """

    fixtures: list[ParsedFixture] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _TIME_PREFIX.sub("", raw_line).strip()
        if not line:
            continue
        is_v_fixture = " v " in line
        match = _V_FIXTURE.fullmatch(line) if is_v_fixture else _LEGACY_FIXTURE.fullmatch(line)
        if match is None:
            if is_v_fixture or _SCORE_TOKEN.search(line) is not None:
                raise SupportPriorError(
                    "MALFORMED_SCORE",
                    f"line {line_number} is fixture-shaped but has no valid full-time score",
                )
            continue
        home = _canonical_team(match.group("home"), label="home", line_number=line_number)
        away = _canonical_team(match.group("away"), label="away", line_number=line_number)
        try:
            home_goals = int(match.group("home_goals"))
            away_goals = int(match.group("away_goals"))
        except (TypeError, ValueError) as exc:  # Defensive; regex has integer groups.
            raise SupportPriorError(
                "MALFORMED_SCORE", f"line {line_number} score is not an integer"
            ) from exc
        if home_goals < 0 or away_goals < 0:
            raise SupportPriorError(
                "NEGATIVE_SCORE", f"line {line_number} contains a negative score"
            )
        if home.casefold() == away.casefold():
            raise SupportPriorError(
                "MALFORMED_FIXTURE", f"line {line_number} uses the same home and away team"
            )
        fixtures.append(ParsedFixture(home, away, home_goals, away_goals, line_number))
    return tuple(fixtures)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _season_weight(age_seasons: int) -> Decimal:
    if age_seasons < 0:
        raise ValueError("age_seasons must be nonnegative")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return Decimal(2) ** (Decimal(-age_seasons) / HALF_LIFE_SEASONS)


def _round_rate(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(RATE_SCALE)


def _load_season(source_root: Path, source: SeasonSource) -> SeasonSummary:
    path = source_root / source.relative_path
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SupportPriorError(
            "SOURCE_FILE_UNAVAILABLE", f"missing required source file: {source.relative_path}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupportPriorError(
            "SOURCE_FILE_ENCODING", f"source file is not UTF-8: {source.relative_path}"
        ) from exc
    fixtures = parse_openfootball_completed_fixtures(text)
    seen: set[tuple[str, str]] = set()
    for fixture in fixtures:
        key = (fixture.home_team.casefold(), fixture.away_team.casefold())
        if key in seen:
            raise SupportPriorError(
                "DUPLICATE_FIXTURE",
                f"duplicate fixture in {source.relative_path} at line {fixture.line_number}",
            )
        seen.add(key)
    if len(fixtures) != 380:
        raise SupportPriorError(
            "INCOMPLETE_SEASON",
            f"{source.season} must contain 380 completed fixtures, found {len(fixtures)}",
        )
    home_goals = sum(item.home_goals for item in fixtures)
    away_goals = sum(item.away_goals for item in fixtures)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        match_count = Decimal(len(fixtures))
        return SeasonSummary(
            source=source,
            source_sha256=_sha256_bytes(raw),
            match_count=len(fixtures),
            home_goal_total=home_goals,
            away_goal_total=away_goals,
            home_goal_rate=Decimal(home_goals) / match_count,
            away_goal_rate=Decimal(away_goals) / match_count,
            weight=_season_weight(source.age_seasons),
        )


def calibrate_openfootball_support_prior(source_root: Path) -> SupportPriorCalibration:
    """Reproduce the five-season, league-wide candidate without retaining source rows."""

    summaries = tuple(_load_season(source_root, source) for source in SEASON_SOURCES)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        total_weight = sum((item.weight for item in summaries), Decimal(0))
        if total_weight <= 0:
            raise ArithmeticError("support-prior calibration has no positive weight")
        home_rate = (
            sum((item.weight * item.home_goal_rate for item in summaries), Decimal(0))
            / total_weight
        )
        away_rate = (
            sum((item.weight * item.away_goal_rate for item in summaries), Decimal(0))
            / total_weight
        )
    if home_rate <= 0 or away_rate <= 0:
        raise SupportPriorError("NONPOSITIVE_RATE", "derived support-prior rates must be positive")
    dataset_sha256 = canonical_json_sha256(
        {
            "parser_version": PARSER_VERSION,
            "source_commit": SOURCE_COMMIT,
            "source_files": [
                {
                    "path": item.source.relative_path,
                    "season": item.source.season,
                    "sha256": item.source_sha256,
                }
                for item in summaries
            ],
        }
    )
    return SupportPriorCalibration(
        seasons=summaries,
        home_goal_rate=home_rate,
        away_goal_rate=away_rate,
        dataset_sha256=dataset_sha256,
    )


def build_support_prior_worlds(
    calibration: SupportPriorCalibration,
    *,
    model_sha256: str,
) -> tuple[SupportPriorWorld, ...]:
    """Generate the explicit 9+9 diagnostic worlds prescribed for the candidate."""

    if SHA256_PATTERN.fullmatch(model_sha256) is None:
        raise ValueError("model_sha256 must be lowercase SHA-256")
    specifications: tuple[tuple[Literal["H2H_TOTALS", "H2H_ONLY"], tuple[Decimal, ...]], ...] = (
        ("H2H_TOTALS", (Decimal("0.85"), Decimal("1.00"), Decimal("1.15"))),
        ("H2H_ONLY", (Decimal("0.75"), Decimal("1.00"), Decimal("1.25"))),
    )
    worlds: list[SupportPriorWorld] = []
    for availability, multipliers in specifications:
        for home_multiplier in multipliers:
            for away_multiplier in multipliers:
                home_rate = _round_rate(calibration.central_home_goal_rate * home_multiplier)
                away_rate = _round_rate(calibration.central_away_goal_rate * away_multiplier)
                if home_rate <= 0 or away_rate <= 0:
                    raise SupportPriorError(
                        "NONPOSITIVE_WORLD_RATE", "support-prior world rate must be positive"
                    )
                body = {
                    "availability": availability,
                    "away_goal_rate": canonical_decimal_text(away_rate),
                    "away_multiplier": canonical_decimal_text(away_multiplier),
                    "home_goal_rate": canonical_decimal_text(home_rate),
                    "home_multiplier": canonical_decimal_text(home_multiplier),
                    "model_sha256": model_sha256,
                }
                worlds.append(
                    SupportPriorWorld(
                        availability=availability,
                        home_multiplier=home_multiplier,
                        away_multiplier=away_multiplier,
                        home_goal_rate=home_rate,
                        away_goal_rate=away_rate,
                        world_sha256=canonical_json_sha256(body),
                    )
                )
    return tuple(worlds)


def _stage8_prior(
    home_goal_rate: Decimal,
    away_goal_rate: Decimal,
    *,
    policy: ScoreBaselinePolicy,
) -> ScorePrior:
    home = positive_decimal(home_goal_rate, label="home_goal_rate")
    away = positive_decimal(away_goal_rate, label="away_goal_rate")
    return build_score_prior(
        home,
        away,
        minimum_max_goals=policy.grid.minimum_max_goals,
        maximum_max_goals=policy.grid.maximum_max_goals,
        tail_tolerance=policy.grid.tail_tolerance,
        hard_tail_limit=policy.grid.hard_tail_limit,
    )


def stage8_support_diagnostics(
    calibration: SupportPriorCalibration,
    *,
    policy: ScoreBaselinePolicy,
) -> dict[str, Any]:
    """Prove compatibility by building the accepted Stage-8 prior/grid unchanged."""

    request = calibration.score_prior_request()
    prior = _stage8_prior(
        request.home_goal_rate,
        request.away_goal_rate,
        policy=policy,
    )
    all_positive = all(value > 0 for value in prior.grid.flattened())
    return {
        "away_marginal_tail": public_probability_text(prior.grid.away_marginal_tail),
        "away_max": prior.grid.away_max,
        "central_score_prior_request": request.public_dict(),
        "finite_strictly_positive_support": all_positive,
        "home_marginal_tail": public_probability_text(prior.grid.home_marginal_tail),
        "home_max": prior.grid.home_max,
        "omitted_tail_mass": public_probability_text(prior.grid.omitted_tail_mass),
        "score_prior_sha256": prior.semantic_sha256,
        "tail_tolerance": public_probability_text(policy.grid.tail_tolerance),
    }


def _model_body(calibration: SupportPriorCalibration) -> dict[str, Any]:
    return {
        "away_goal_rate": canonical_decimal_text(calibration.central_away_goal_rate),
        "competition": "EPL",
        "dataset_sha256": calibration.dataset_sha256,
        "half_life_seasons": canonical_decimal_text(HALF_LIFE_SEASONS),
        "home_goal_rate": canonical_decimal_text(calibration.central_home_goal_rate),
        "model_family": MODEL_FAMILY,
        "weight_method": WEIGHT_METHOD,
    }


def build_candidate_artifact(
    calibration: SupportPriorCalibration,
    *,
    policy: ScoreBaselinePolicy,
    source_retrieved_at: datetime | str,
    produced_at: datetime | str,
    information_cutoff: datetime | str,
    code_commit: str,
) -> dict[str, Any]:
    """Build a self-validating, unaccepted candidate artifact from a calibration."""

    if re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
        raise ValueError("code_commit must be a lowercase Git SHA-1")
    retrieved = parse_utc(source_retrieved_at, field_name="source_retrieved_at")
    produced = parse_utc(produced_at, field_name="produced_at")
    cutoff = parse_utc(information_cutoff, field_name="information_cutoff")
    if cutoff > retrieved:
        raise ValueError("information_cutoff must not be after source retrieval")
    if produced < retrieved:
        raise ValueError("produced_at must not precede source retrieval")
    model_sha256 = canonical_json_sha256(_model_body(calibration))
    worlds = build_support_prior_worlds(calibration, model_sha256=model_sha256)
    artifact: dict[str, Any] = {
        "calibration_seasons": [item.source.season for item in calibration.seasons],
        "code_commit": code_commit,
        "competition": "EPL",
        "dataset_sha256": calibration.dataset_sha256,
        "derived_away_goal_rate": canonical_decimal_text(calibration.central_away_goal_rate),
        "derived_home_goal_rate": canonical_decimal_text(calibration.central_home_goal_rate),
        "half_life_seasons": canonical_decimal_text(HALF_LIFE_SEASONS),
        "human_acceptance": {
            "accepted": False,
            "accepted_at": None,
            "decision_reference": None,
            "reviewer": None,
        },
        "information_cutoff": format_utc(cutoff),
        "limitations": [
            "League-wide regulariser only; no fixture-specific team strength is estimated.",
            "No promoted-team, manager, lineup, player, xG, or bookmaker information enters calibration.",
            "Candidate is not activated and does not replace market evidence when H2H or totals exist.",
            "OpenFootball's public-domain assertion does not provide an independent accuracy warranty; human rights and data-quality review remains required.",
        ],
        "match_count": calibration.match_count,
        "model_family": MODEL_FAMILY,
        "model_sha256": model_sha256,
        "per_season_summaries": [item.public_dict() for item in calibration.seasons],
        "policy_sha256": policy.sha256,
        "produced_at": format_utc(produced),
        "sampling_structural_diagnostics": {
            "completed_match_counts_verified": True,
            "duplicate_fixture_rejection": "HOME_AWAY_PAIR_PER_SEASON",
            "fixture_specific_team_parameters": False,
            "market_evidence_used_in_calibration": False,
            "parser_version": PARSER_VERSION,
            "player_parameters": False,
        },
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "sensitivity_world_specification": {
            "complete_h2h_totals": [
                item.public_dict() for item in worlds if item.availability == "H2H_TOTALS"
            ],
            "h2h_only": [item.public_dict() for item in worlds if item.availability == "H2H_ONLY"],
        },
        "source": {
            "attribution_note": "OpenFootball England / football.db; source and derived candidate recorded for review.",
            "commit": SOURCE_COMMIT,
            "licence": SOURCE_LICENCE,
            "owner": SOURCE_OWNER,
            "repository_url": SOURCE_REPOSITORY_URL,
            "retention_permission": "CC0 permits retention and reuse; DMF retains only file hashes and derived aggregates.",
            "retrieved_at": format_utc(retrieved),
            "underlying_data_statement": "Repository README states that football.db schema, data and scripts are dedicated to the public domain.",
        },
        "source_file_hashes": [
            {
                "path": item.source.relative_path,
                "season": item.source.season,
                "sha256": item.source_sha256,
            }
            for item in calibration.seasons
        ],
        "stage8_compatibility": stage8_support_diagnostics(calibration, policy=policy),
        "status": "CANDIDATE_NOT_ACCEPTED",
        "validation_result": {
            "checks": [
                "FIVE_SEASONS_380_COMPLETED_MATCHES_EACH",
                "NO_DUPLICATE_HOME_AWAY_FIXTURES",
                "STRICTLY_POSITIVE_LEAGUE_WIDE_RATES",
                "EXISTING_STAGE8_ADAPTIVE_TAIL_COMPLIANT",
            ],
            "status": "PASS",
        },
        "weight_method": WEIGHT_METHOD,
    }
    artifact["artifact_sha256"] = canonical_json_sha256(artifact)
    validate_candidate_artifact(artifact)
    return artifact


def _require_exact_keys(value: object, *, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SupportPriorError("ARTIFACT_SCHEMA", f"{label} has an invalid object shape")
    return value


def _artifact_decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise SupportPriorError("ARTIFACT_SCHEMA", f"{label} must be a decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:  # Decimal can raise several implementation exceptions.
        raise SupportPriorError("ARTIFACT_SCHEMA", f"{label} must be a decimal string") from exc
    if not parsed.is_finite():
        raise SupportPriorError("ARTIFACT_SCHEMA", f"{label} must be finite")
    return parsed


def validate_candidate_artifact(value: object) -> None:
    """Fail closed when a candidate artifact differs from its declared calculation."""

    artifact = _require_exact_keys(
        value,
        label="candidate artifact",
        keys={
            "artifact_sha256",
            "calibration_seasons",
            "code_commit",
            "competition",
            "dataset_sha256",
            "derived_away_goal_rate",
            "derived_home_goal_rate",
            "half_life_seasons",
            "human_acceptance",
            "information_cutoff",
            "limitations",
            "match_count",
            "model_family",
            "model_sha256",
            "per_season_summaries",
            "policy_sha256",
            "produced_at",
            "sampling_structural_diagnostics",
            "schema_version",
            "sensitivity_world_specification",
            "source",
            "source_file_hashes",
            "stage8_compatibility",
            "status",
            "validation_result",
            "weight_method",
        },
    )
    if artifact["schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise SupportPriorError("ARTIFACT_SCHEMA", "candidate artifact schema_version is invalid")
    if artifact["status"] != "CANDIDATE_NOT_ACCEPTED":
        raise SupportPriorError("ARTIFACT_STATUS", "candidate artifact must remain unaccepted")
    if artifact["model_family"] != MODEL_FAMILY or artifact["competition"] != "EPL":
        raise SupportPriorError("ARTIFACT_SCHEMA", "candidate model identity is invalid")
    if artifact["weight_method"] != WEIGHT_METHOD:
        raise SupportPriorError("ARTIFACT_SCHEMA", "candidate weight method is invalid")
    if (
        _artifact_decimal(artifact["half_life_seasons"], label="half_life_seasons")
        != HALF_LIFE_SEASONS
    ):
        raise SupportPriorError("ARTIFACT_SCHEMA", "candidate half-life is invalid")
    if (
        not isinstance(artifact["code_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}", artifact["code_commit"]) is None
    ):
        raise SupportPriorError("ARTIFACT_SCHEMA", "code_commit is invalid")
    for field in ("dataset_sha256", "model_sha256", "policy_sha256", "artifact_sha256"):
        if (
            not isinstance(artifact[field], str)
            or SHA256_PATTERN.fullmatch(artifact[field]) is None
        ):
            raise SupportPriorError("ARTIFACT_SCHEMA", f"{field} is invalid")
    for field in ("information_cutoff", "produced_at"):
        parse_utc(artifact[field], field_name=field)
    source = _require_exact_keys(
        artifact["source"],
        label="candidate source",
        keys={
            "attribution_note",
            "commit",
            "licence",
            "owner",
            "repository_url",
            "retention_permission",
            "retrieved_at",
            "underlying_data_statement",
        },
    )
    if (
        source["owner"] != SOURCE_OWNER
        or source["repository_url"] != SOURCE_REPOSITORY_URL
        or source["commit"] != SOURCE_COMMIT
        or source["licence"] != SOURCE_LICENCE
    ):
        raise SupportPriorError("ARTIFACT_SOURCE", "candidate source identity is invalid")
    parse_utc(source["retrieved_at"], field_name="source.retrieved_at")
    source_files = artifact["source_file_hashes"]
    summaries = artifact["per_season_summaries"]
    if not isinstance(source_files, list) or not isinstance(summaries, list):
        raise SupportPriorError(
            "ARTIFACT_SCHEMA", "candidate source files or summaries are invalid"
        )
    if len(source_files) != len(SEASON_SOURCES) or len(summaries) != len(SEASON_SOURCES):
        raise SupportPriorError("ARTIFACT_COVERAGE", "candidate must contain exactly five seasons")
    total_matches = 0
    weighted_home = Decimal(0)
    weighted_away = Decimal(0)
    total_weight = Decimal(0)
    expected_source_files: list[dict[str, str]] = []
    expected_seasons: list[str] = []
    for source_spec, source_file, summary in zip(
        SEASON_SOURCES, source_files, summaries, strict=True
    ):
        file_body = _require_exact_keys(
            source_file,
            label="candidate source file",
            keys={"path", "season", "sha256"},
        )
        summary_body = _require_exact_keys(
            summary,
            label="candidate season summary",
            keys={
                "age_seasons",
                "away_goal_rate",
                "away_goal_total",
                "home_goal_rate",
                "home_goal_total",
                "match_count",
                "path",
                "season",
                "sha256",
                "weight",
            },
        )
        expected_file = {
            "path": source_spec.relative_path,
            "season": source_spec.season,
            "sha256": file_body["sha256"],
        }
        if (
            file_body["path"] != source_spec.relative_path
            or file_body["season"] != source_spec.season
        ):
            raise SupportPriorError(
                "ARTIFACT_SOURCE", "candidate source file order or path is invalid"
            )
        if (
            summary_body["path"] != source_spec.relative_path
            or summary_body["season"] != source_spec.season
        ):
            raise SupportPriorError(
                "ARTIFACT_SOURCE", "candidate season summary order or path is invalid"
            )
        if summary_body["sha256"] != file_body["sha256"] or not isinstance(
            file_body["sha256"], str
        ):
            raise SupportPriorError("ARTIFACT_SOURCE", "candidate summary/file hashes disagree")
        if SHA256_PATTERN.fullmatch(file_body["sha256"]) is None:
            raise SupportPriorError("ARTIFACT_SOURCE", "candidate source file hash is invalid")
        if summary_body["age_seasons"] != source_spec.age_seasons:
            raise SupportPriorError("ARTIFACT_SCHEMA", "candidate season age is invalid")
        if summary_body["match_count"] != 380:
            raise SupportPriorError(
                "ARTIFACT_COVERAGE", "every candidate season must have 380 matches"
            )
        if not all(
            isinstance(summary_body[field], int)
            and not isinstance(summary_body[field], bool)
            and summary_body[field] >= 0
            for field in ("home_goal_total", "away_goal_total")
        ):
            raise SupportPriorError("ARTIFACT_SCHEMA", "candidate goal totals are invalid")
        weight = _artifact_decimal(summary_body["weight"], label="season weight")
        home_rate = _artifact_decimal(summary_body["home_goal_rate"], label="season home rate")
        away_rate = _artifact_decimal(summary_body["away_goal_rate"], label="season away rate")
        expected_weight = _season_weight(source_spec.age_seasons)
        if weight != expected_weight:
            raise SupportPriorError("ARTIFACT_CALCULATION", "candidate season weight is invalid")
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            expected_home_rate = Decimal(summary_body["home_goal_total"]) / Decimal(380)
            expected_away_rate = Decimal(summary_body["away_goal_total"]) / Decimal(380)
            weighted_home = weighted_home + weight * home_rate
            weighted_away = weighted_away + weight * away_rate
            total_weight = total_weight + weight
        if home_rate != expected_home_rate:
            raise SupportPriorError("ARTIFACT_CALCULATION", "candidate home season rate is invalid")
        if away_rate != expected_away_rate:
            raise SupportPriorError("ARTIFACT_CALCULATION", "candidate away season rate is invalid")
        total_matches += 380
        expected_source_files.append(expected_file)
        expected_seasons.append(source_spec.season)
    if (
        artifact["calibration_seasons"] != expected_seasons
        or artifact["match_count"] != total_matches
    ):
        raise SupportPriorError("ARTIFACT_COVERAGE", "candidate calibration coverage is invalid")
    if artifact["dataset_sha256"] != canonical_json_sha256(
        {
            "parser_version": PARSER_VERSION,
            "source_commit": SOURCE_COMMIT,
            "source_files": expected_source_files,
        }
    ):
        raise SupportPriorError("ARTIFACT_SOURCE", "candidate dataset hash is invalid")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        home_rate = _round_rate(weighted_home / total_weight)
        away_rate = _round_rate(weighted_away / total_weight)
    if (
        _artifact_decimal(artifact["derived_home_goal_rate"], label="derived home rate")
        != home_rate
    ):
        raise SupportPriorError("ARTIFACT_CALCULATION", "candidate home rate is invalid")
    if (
        _artifact_decimal(artifact["derived_away_goal_rate"], label="derived away rate")
        != away_rate
    ):
        raise SupportPriorError("ARTIFACT_CALCULATION", "candidate away rate is invalid")
    model_body = {
        "away_goal_rate": canonical_decimal_text(away_rate),
        "competition": "EPL",
        "dataset_sha256": artifact["dataset_sha256"],
        "half_life_seasons": canonical_decimal_text(HALF_LIFE_SEASONS),
        "home_goal_rate": canonical_decimal_text(home_rate),
        "model_family": MODEL_FAMILY,
        "weight_method": WEIGHT_METHOD,
    }
    if artifact["model_sha256"] != canonical_json_sha256(model_body):
        raise SupportPriorError("ARTIFACT_CALCULATION", "candidate model hash is invalid")
    acceptance = _require_exact_keys(
        artifact["human_acceptance"],
        label="human acceptance",
        keys={"accepted", "accepted_at", "decision_reference", "reviewer"},
    )
    if acceptance != {
        "accepted": False,
        "accepted_at": None,
        "decision_reference": None,
        "reviewer": None,
    }:
        raise SupportPriorError("ARTIFACT_STATUS", "candidate must contain no human acceptance")
    without_hash = dict(artifact)
    supplied_hash = without_hash.pop("artifact_sha256")
    if supplied_hash != canonical_json_sha256(without_hash):
        raise SupportPriorError("ARTIFACT_CALCULATION", "candidate artifact hash is invalid")


def _matrix_value(matrix: tuple[tuple[Decimal, ...], ...], home: int, away: int) -> Decimal:
    if home < len(matrix) and away < len(matrix[0]):
        return matrix[home][away]
    return Decimal(0)


def _total_variation(
    left: tuple[tuple[Decimal, ...], ...], right: tuple[tuple[Decimal, ...], ...]
) -> Decimal:
    home_max = max(len(left), len(right))
    away_max = max(len(left[0]), len(right[0]))
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return sum(
            (
                abs(_matrix_value(left, home, away) - _matrix_value(right, home, away))
                for home in range(home_max)
                for away in range(away_max)
            ),
            Decimal(0),
        ) / Decimal(2)


def _matrix_metrics(matrix: tuple[tuple[Decimal, ...], ...]) -> dict[str, Any]:
    home_max = len(matrix) - 1
    away_max = len(matrix[0]) - 1
    home_pmf = tuple(sum(row, Decimal(0)) for row in matrix)
    away_pmf = tuple(
        sum((matrix[home][away] for home in range(home_max + 1)), Decimal(0))
        for away in range(away_max + 1)
    )
    home_win = sum(
        (
            matrix[home][away]
            for home in range(home_max + 1)
            for away in range(away_max + 1)
            if home > away
        ),
        Decimal(0),
    )
    draw = sum((matrix[score][score] for score in range(min(home_max, away_max) + 1)), Decimal(0))
    away_win = Decimal(1) - home_win - draw
    over_two_point_five = sum(
        (
            matrix[home][away]
            for home in range(home_max + 1)
            for away in range(away_max + 1)
            if home + away > 2
        ),
        Decimal(0),
    )
    btts = sum(
        (matrix[home][away] for home in range(1, home_max + 1) for away in range(1, away_max + 1)),
        Decimal(0),
    )
    ranked = sorted(
        (
            (matrix[home][away], home, away)
            for home in range(home_max + 1)
            for away in range(away_max + 1)
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )[:5]
    return {
        "btts_yes": public_probability_text(btts),
        "clean_sheet_probabilities": {
            "away": public_probability_text(home_pmf[0]),
            "home": public_probability_text(away_pmf[0]),
        },
        "expected_away_goals": public_measure_text(
            sum((Decimal(index) * value for index, value in enumerate(away_pmf)), Decimal(0))
        ),
        "expected_home_goals": public_measure_text(
            sum((Decimal(index) * value for index, value in enumerate(home_pmf)), Decimal(0))
        ),
        "hda": {
            "away": public_probability_text(away_win),
            "draw": public_probability_text(draw),
            "home": public_probability_text(home_win),
        },
        "over_2_5": public_probability_text(over_two_point_five),
        "top_exact_scores": [
            {
                "away_goals": away,
                "home_goals": home,
                "probability": public_probability_text(probability),
            }
            for probability, home, away in ranked
        ],
    }


def _diagnose_world(
    world: SupportPriorWorld,
    *,
    constraints: MarketConstraintSet,
    policy: ScoreBaselinePolicy,
    max_iterations: int | None,
) -> dict[str, Any]:
    prior = _stage8_prior(world.home_goal_rate, world.away_goal_rate, policy=policy)
    projection = project_to_markets(
        prior,
        constraints,
        max_iterations=policy.projection.max_iterations
        if max_iterations is None
        else max_iterations,
        gradient_tolerance=policy.projection.gradient_tolerance,
        line_search_min_step=policy.projection.line_search_min_step,
        allow_prior_fallback=policy.projection.allow_prior_fallback,
    )
    return {
        "kl_movement": public_probability_text(projection.prior_to_projected_kl),
        "metrics": _matrix_metrics(projection.probabilities),
        "prior_to_posterior_total_variation": public_probability_text(
            _total_variation(prior.grid.probabilities, projection.probabilities)
        ),
        "projection_status": projection.status,
        "solver_error_code": projection.error_code,
        "solver_iterations": projection.iterations,
        "world": world.public_dict(),
    }


def _prior_world_output_spread(records: list[dict[str, Any]]) -> dict[str, str]:
    if not records:
        return {}
    numeric_paths = {
        "away_win": ("hda", "away"),
        "draw": ("hda", "draw"),
        "expected_away_goals": ("expected_away_goals",),
        "expected_home_goals": ("expected_home_goals",),
        "home_win": ("hda", "home"),
        "over_2_5": ("over_2_5",),
    }
    result: dict[str, str] = {}
    for name, path in numeric_paths.items():
        values: list[Decimal] = []
        for record in records:
            metric: Any = record["metrics"]
            for key in path:
                metric = metric[key]
            values.append(Decimal(metric))
        spread = max(values) - min(values)
        result[name] = (
            public_measure_text(spread)
            if name.startswith("expected_")
            else public_probability_text(spread)
        )
    return result


def diagnose_market_dominance(
    calibration: SupportPriorCalibration,
    *,
    complete_constraints: MarketConstraintSet,
    h2h_only_constraints: MarketConstraintSet,
    no_market_constraints: MarketConstraintSet,
    policy: ScoreBaselinePolicy,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Run offline sensitivity diagnostics through the one accepted Stage-8 matrix.

    The returned statuses and solver warnings deliberately remain distinct from
    the frozen public confidence-grade contract.  Threshold interpretation is a
    review aid only; this function declares none as production policy.
    """

    model_sha256 = canonical_json_sha256(_model_body(calibration))
    worlds = build_support_prior_worlds(calibration, model_sha256=model_sha256)
    complete = [
        _diagnose_world(
            world,
            constraints=complete_constraints,
            policy=policy,
            max_iterations=max_iterations,
        )
        for world in worlds
        if world.availability == "H2H_TOTALS"
    ]
    h2h_only = [
        _diagnose_world(
            world,
            constraints=h2h_only_constraints,
            policy=policy,
            max_iterations=max_iterations,
        )
        for world in worlds
        if world.availability == "H2H_ONLY"
    ]
    central_world = next(
        item
        for item in worlds
        if (
            item.availability == "H2H_TOTALS"
            and item.home_multiplier == Decimal("1.00")
            and item.away_multiplier == Decimal("1.00")
        )
    )
    no_market = _diagnose_world(
        central_world,
        constraints=no_market_constraints,
        policy=policy,
        max_iterations=max_iterations,
    )
    return {
        "candidate_model_sha256": model_sha256,
        "complete_h2h_totals": complete,
        "complete_h2h_totals_prior_world_output_spread": _prior_world_output_spread(complete),
        "h2h_only": h2h_only,
        "h2h_only_prior_world_output_spread": _prior_world_output_spread(h2h_only),
        "no_market": no_market,
        "thresholds": "CANDIDATE_DIAGNOSTIC_ONLY_NO_PRODUCTION_THRESHOLD",
    }


def canonical_candidate_json(artifact: dict[str, Any]) -> str:
    """Validate then emit portable deterministic artifact bytes."""

    validate_candidate_artifact(artifact)
    return (
        json.dumps(artifact, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "HALF_LIFE_SEASONS",
    "MODEL_FAMILY",
    "PARSER_VERSION",
    "SEASON_SOURCES",
    "SOURCE_COMMIT",
    "SOURCE_LICENCE",
    "SOURCE_OWNER",
    "SOURCE_REPOSITORY_URL",
    "SeasonSource",
    "SeasonSummary",
    "SupportPriorCalibration",
    "SupportPriorError",
    "SupportPriorWorld",
    "build_candidate_artifact",
    "build_support_prior_worlds",
    "calibrate_openfootball_support_prior",
    "canonical_candidate_json",
    "diagnose_market_dominance",
    "parse_openfootball_completed_fixtures",
    "stage8_support_diagnostics",
    "validate_candidate_artifact",
]
