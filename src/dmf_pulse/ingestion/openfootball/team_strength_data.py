"""Authenticated, market-free individual-match evidence for shadow team strength.

Dates remain dates: OpenFootball's unzoned time strings are not UTC kickoffs.
Both accepted dataset modes enforce D+2; reconstructed provenance never claims
that today's source bytes were received at a historical forecast origin.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.openfootball.config import (
    load_rights_profiles,
    rights_config_sha256,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    TEAM_STRENGTH_RIGHTS_PROFILE_ID,
    SourceFreshnessState,
    classify_source_freshness,
    eligibility_not_before,
    load_current_team_strength_governance,
    load_historical_team_identity,
    resolve_openfootball_team,
)

SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
COMMIT = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
SEASON = Annotated[str, Field(pattern=r"^20\d{2}/\d{2}$")]
MODE = Literal["LIVE_OBSERVED", "RECONSTRUCTED"]
RIGHTS_HASH = "b90075563647a69a87e201aa70fe6f44034828afd9ad3926decf5c45bb53b17c"
MAX_BYTES = 131072


class StrengthEvidenceError(ValueError):
    """Finite, sanitized source/identity/temporal integrity failure."""


class FrozenEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
    )

    @field_validator("*", mode="after")
    @classmethod
    def utc_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("evidence timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return value

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        del deep
        payload = self.model_dump(mode="python")
        payload.update(update or {})
        return type(self).model_validate(payload)


class SealedEvidence(FrozenEvidence):
    semantic_sha256: SHA

    @model_validator(mode="after")
    def check_hash(self) -> Self:
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"semantic_sha256"}))
            != self.semantic_sha256
        ):
            raise ValueError("evidence semantic hash mismatch")
        return self


def seal[T: SealedEvidence](model: type[T], /, **values: Any) -> T:
    """Construct only after computing the hash; all validators still run."""
    # Hash the same UTC instants that validation serializes, not an input
    # timezone spelling. Naive timestamps still fail before sealing.
    values = {key: FrozenEvidence.utc_datetimes(value) for key, value in values.items()}
    draft = model.model_construct(**values, semantic_sha256="0" * 64)
    values["semantic_sha256"] = canonical_sha256(
        draft.model_dump(mode="json", exclude={"semantic_sha256"})
    )
    return model.model_validate(values)


def authenticate[T: SealedEvidence](value: T, expected: str | None = None) -> T:
    validated = type(value).model_validate_json(value.model_dump_json())
    if expected is not None and validated.semantic_sha256 != expected:
        raise StrengthEvidenceError("evidence differs from the expected immutable identity")
    return validated


def require_team_strength_rights(profile: RightsProfile | None = None) -> None:
    approved = load_rights_profiles()[TEAM_STRENGTH_RIGHTS_PROFILE_ID]
    if rights_config_sha256() != RIGHTS_HASH:
        raise StrengthEvidenceError("team-strength rights authority differs from approval")
    if profile is not None and profile != approved:
        raise StrengthEvidenceError("team-strength rights purpose or capabilities differ")
    load_current_team_strength_governance()


class SourceResource(FrozenEvidence):
    repository: Literal["openfootball/football.json"] = "openfootball/football.json"
    commit: COMMIT
    path: str = Field(pattern=r"^20\d{2}-\d{2}/en\.1\.json$")
    season: SEASON
    git_blob_sha1: COMMIT
    content_sha256: SHA
    byte_length: int = Field(gt=0, le=MAX_BYTES)
    licence_identity: Literal["CC0-1.0"] = "CC0-1.0"
    licence_blob_sha1: Literal["670154e3538863b2d9891fd5483160fbdfc89164"] = (
        "670154e3538863b2d9891fd5483160fbdfc89164"
    )
    licence_content_sha256: Literal[
        "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673"
    ] = "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673"

    @model_validator(mode="after")
    def check_path(self) -> Self:
        if self.path != self.season.replace("/", "-") + "/en.1.json":
            raise ValueError("source season and EPL path differ")
        return self


@lru_cache(maxsize=1)
def _approval_timestamp() -> datetime:
    return load_current_team_strength_governance().human_approval.approved_at


class SourceLineage(SealedEvidence):
    resource: SourceResource
    retrieval_started_at: datetime
    received_at: datetime
    validated_at: datetime
    usable_at: datetime
    acquisition: Literal["COMMIT_PINNED_HTTPS", "LOCAL_IMMUTABLE_IMPORT"]
    rights_profile_id: Literal["openfootball_football_json_team_strength_v1"] = (
        "openfootball_football_json_team_strength_v1"
    )
    rights_profile_version: Literal["1.0.0"] = "1.0.0"
    rights_config_sha256: Literal[
        "b90075563647a69a87e201aa70fe6f44034828afd9ad3926decf5c45bb53b17c"
    ] = "b90075563647a69a87e201aa70fe6f44034828afd9ad3926decf5c45bb53b17c"
    human_approval_id: Literal[
        "CURRENT-TEAM-STRENGTH-001A#openfootball_football_json_team_strength_v1"
    ] = "CURRENT-TEAM-STRENGTH-001A#openfootball_football_json_team_strength_v1"
    predecessor_snapshot_sha256: SHA | None = None

    @model_validator(mode="after")
    def check_times(self) -> Self:
        approval = _approval_timestamp()
        if not (
            approval
            <= self.retrieval_started_at
            <= self.received_at
            <= self.validated_at
            <= self.usable_at
        ):
            raise ValueError("source receipt, validation, usable or approval order is invalid")
        return self


class FixtureRegistration(FrozenEvidence):
    fixture_id: UUID
    competition_id: UUID
    season: SEASON
    home_team_id: UUID
    away_team_id: UUID

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        if any(
            value.version != 7
            for value in (
                self.fixture_id,
                self.competition_id,
                self.home_team_id,
                self.away_team_id,
            )
        ):
            raise ValueError("canonical fixture, competition and clubs require UUIDv7")
        if self.home_team_id == self.away_team_id:
            raise ValueError("a club cannot play itself")
        return self


class FixtureRegistry(SealedEvidence):
    schema_version: Literal["team-strength-fixture-registry-v1"] = (
        "team-strength-fixture-registry-v1"
    )
    competition: Literal["English Premier League"] = "English Premier League"
    competition_id: UUID
    registration_authority: str = Field(min_length=1, max_length=160)
    registered_at: datetime
    fixtures: tuple[FixtureRegistration, ...] = Field(min_length=1)
    identity_registry_sha256: Literal[
        "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    ] = "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"

    @model_validator(mode="after")
    def check_registry(self) -> Self:
        identity = load_historical_team_identity()
        membership = {
            club.canonical_team_id: club.season_membership for club in identity.canonical_clubs
        }
        ids = [row.fixture_id for row in self.fixtures]
        if ids != sorted(set(ids)):
            raise ValueError("fixture registrations must be unique and canonically ordered")
        keys = [(row.season, row.home_team_id, row.away_team_id) for row in self.fixtures]
        if len(set(keys)) != len(keys):
            raise ValueError("ambiguous canonical season fixture")
        for row in self.fixtures:
            if row.competition_id != self.competition_id:
                raise ValueError("fixture competition differs from registry")
            for team in (row.home_team_id, row.away_team_id):
                if row.season not in membership.get(team, ()):
                    raise ValueError("fixture club or season is outside the P0 registry")
        return self


class ParsedMatch(SealedEvidence):
    fixture: FixtureRegistration
    source_match_date: date
    kickoff_utc: None = None
    time_precision: Literal["DATE_ONLY"] = "DATE_ONLY"
    source_round: int = Field(ge=1, le=38)
    home_goals: int | None = Field(default=None, ge=0, le=99)
    away_goals: int | None = Field(default=None, ge=0, le=99)
    finality: Literal["FULL_TIME", "NOT_FINAL", "UNKNOWN_STATUS", "NO_SCORE"]
    source_row_sha256: SHA
    source_snapshot_sha256: SHA

    @model_validator(mode="after")
    def check_score(self) -> Self:
        if (self.home_goals is None) != (self.away_goals is None):
            raise ValueError("partial full-time score is invalid")
        if self.finality == "FULL_TIME" and self.home_goals is None:
            raise ValueError("full-time classification requires a full-time score")
        return self


class ParsedSnapshot(SealedEvidence):
    lineage: SourceLineage
    fixture_registry_sha256: SHA
    matches: tuple[ParsedMatch, ...] = Field(min_length=1, max_length=380)

    @model_validator(mode="after")
    def check_rows(self) -> Self:
        keys = [row.fixture.fixture_id for row in self.matches]
        if keys != sorted(set(keys)):
            raise ValueError("snapshot fixtures are duplicated or unordered")
        if any(
            row.source_snapshot_sha256 != self.lineage.semantic_sha256
            or row.fixture.season != self.lineage.resource.season
            for row in self.matches
        ):
            raise ValueError("snapshot match lineage differs")
        return self


class TeamStrengthHistoricalMatchV1(SealedEvidence):
    observation: ParsedMatch
    source: SourceLineage
    dataset_mode: MODE
    identity_registry_sha256: Literal[
        "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    ] = "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"

    @model_validator(mode="after")
    def check_lineage(self) -> Self:
        if (
            self.observation.finality != "FULL_TIME"
            or self.observation.source_snapshot_sha256 != self.source.semantic_sha256
        ):
            raise ValueError("training row is not an authenticated full-time result")
        return self


class TeamStrengthHistoricalDatasetV1(SealedEvidence):
    schema_version: Literal["team-strength-historical-dataset-v1"] = (
        "team-strength-historical-dataset-v1"
    )
    competition: Literal["English Premier League"] = "English Premier League"
    competition_id: UUID
    dataset_mode: MODE
    information_cutoff: datetime
    training_cutoff: datetime
    forecast_season: SEASON
    fixture_registry: FixtureRegistry
    sources: tuple[ParsedSnapshot, ...] = Field(min_length=1, max_length=17)
    matches: tuple[TeamStrengthHistoricalMatchV1, ...]
    missing_due: int = Field(ge=0)
    freshness: SourceFreshnessState
    policy_sha256: Literal["e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"] = (
        "e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"
    )
    identity_registry_sha256: Literal[
        "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    ] = "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"

    @model_validator(mode="after")
    def check_dataset(self) -> Self:
        if self.training_cutoff > self.information_cutoff:
            raise ValueError("training cutoff exceeds the information cutoff")
        if self.dataset_mode == "LIVE_OBSERVED" and self.training_cutoff != self.information_cutoff:
            raise ValueError("live training and information cutoffs must agree")
        if self.competition_id != self.fixture_registry.competition_id:
            raise ValueError("dataset competition differs from fixture registry")
        seasons = tuple(source.lineage.resource.season for source in self.sources)
        if seasons != tuple(sorted(set(seasons))):
            raise ValueError("sources must contain one canonical snapshot per season")
        if self.forecast_season not in load_historical_team_identity().seasons_covered:
            raise ValueError("forecast season is outside the approved identity registry")
        required_seasons = {
            row.season
            for row in self.fixture_registry.fixtures
            if row.season <= self.forecast_season
        }
        if self.forecast_season not in required_seasons or set(seasons) != required_seasons:
            raise StrengthEvidenceError(
                "source season coverage is incomplete or outside forecast scope"
            )
        expected, missing, freshness = _eligible(
            self.sources, self.training_cutoff, self.information_cutoff, self.dataset_mode
        )
        if self.matches != expected or self.missing_due != missing or self.freshness != freshness:
            raise ValueError("dataset eligibility or freshness disagrees with source evidence")
        registered = {row.fixture_id: row for row in self.fixture_registry.fixtures}
        for source in self.sources:
            if source.fixture_registry_sha256 != self.fixture_registry.semantic_sha256:
                raise ValueError("source fixture registry binding differs")
            for row in source.matches:
                if registered.get(row.fixture.fixture_id) != row.fixture:
                    raise ValueError("source row differs from canonical fixture registration")
            expected_ids = {
                row.fixture_id
                for row in self.fixture_registry.fixtures
                if row.season == source.lineage.resource.season
            }
            if {row.fixture.fixture_id for row in source.matches} != expected_ids:
                raise ValueError("source omits governed scheduled fixtures")
        return self


def _eligible(
    sources: tuple[ParsedSnapshot, ...],
    training_cutoff: datetime,
    information_cutoff: datetime,
    mode: MODE,
) -> tuple[tuple[TeamStrengthHistoricalMatchV1, ...], int, SourceFreshnessState]:
    eligible: list[TeamStrengthHistoricalMatchV1] = []
    missing = 0
    unambiguous = True
    for source in sources:
        if source.lineage.usable_at > information_cutoff:
            raise StrengthEvidenceError("post-cutoff source evidence is not allowed")
        if source.lineage.validated_at >= information_cutoff and mode == "LIVE_OBSERVED":
            raise StrengthEvidenceError("live source must be validated strictly before cutoff")
        for row in source.matches:
            unambiguous &= row.finality != "UNKNOWN_STATUS"
            if eligibility_not_before(row.source_match_date) > training_cutoff:
                continue
            if row.finality != "FULL_TIME":
                missing += 1
                continue
            eligible.append(
                seal(
                    TeamStrengthHistoricalMatchV1,
                    observation=row,
                    source=source.lineage,
                    dataset_mode=mode,
                )
            )
    result = tuple(sorted(eligible, key=lambda row: row.observation.fixture.fixture_id))
    freshness = classify_source_freshness(
        cutoff=information_cutoff,
        latest_successful_usable_retrieval=max(source.lineage.received_at for source in sources),
        missing_due=missing,
        canonical_mapping_valid=True,
        status_unambiguous=unambiguous,
        schema_valid=True,
        source_lineage_valid=True,
    )
    return result, missing, freshness


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StrengthEvidenceError("duplicate source JSON key")
        result[key] = value
    return result


def _reject_numeric(value: str) -> object:
    del value
    raise StrengthEvidenceError("source numeric representation is invalid")


def _score(value: object, *, leaf: bool = False) -> tuple[int, int] | None:
    if value is None and not leaf:
        return None
    if isinstance(value, dict) and not leaf:
        if set(value) not in ({"ft"}, {"ft", "ht"}):
            raise StrengthEvidenceError("source score shape is invalid")
        full = _score(value["ft"], leaf=True)
        if "ht" in value:
            half = _score(value["ht"], leaf=True)
            if full is None or half is None or any(a > b for a, b in zip(half, full, strict=True)):
                raise StrengthEvidenceError("half-time score exceeds full time")
        return full
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(goal) is not int or not 0 <= goal <= 99 for goal in value)
    ):
        raise StrengthEvidenceError("full-time score is invalid")
    return value[0], value[1]


def parse_snapshot(
    body: bytes,
    *,
    lineage: SourceLineage,
    fixtures: FixtureRegistry,
    expected_fixture_registry_sha256: str,
    profile: RightsProfile | None = None,
) -> ParsedSnapshot:
    require_team_strength_rights(profile)
    lineage = authenticate(lineage)
    fixtures = authenticate(fixtures, expected_fixture_registry_sha256)
    resource = lineage.resource
    if (
        len(body) != resource.byte_length
        or hashlib.sha256(body).hexdigest() != resource.content_sha256
    ):
        raise StrengthEvidenceError("source bytes fail their declared identity")
    if (
        hashlib.sha1(f"blob {len(body)}\0".encode() + body, usedforsecurity=False).hexdigest()
        != resource.git_blob_sha1
    ):
        raise StrengthEvidenceError("source Git blob identity differs")
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_numeric,
            parse_constant=_reject_numeric,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise StrengthEvidenceError("source JSON is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != {"name", "matches"}:
        raise StrengthEvidenceError("source season schema is invalid")
    stack: list[tuple[object, int]] = [(payload, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > 12:
            raise StrengthEvidenceError("source JSON exceeds its depth limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    if payload["name"] != f"English Premier League {resource.season}":
        raise StrengthEvidenceError("source competition or season is outside approved scope")
    raw_rows = payload["matches"]
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= 380:
        raise StrengthEvidenceError("source match count is invalid")
    identity = load_historical_team_identity()
    registrations = {
        (row.season, row.home_team_id, row.away_team_id): row for row in fixtures.fixtures
    }
    observations = []
    for raw in raw_rows:
        if (
            not isinstance(raw, dict)
            or not {"team1", "team2", "date", "round"} <= raw.keys()
            or raw.keys() - {"team1", "team2", "date", "round", "time", "score", "status"}
        ):
            raise StrengthEvidenceError("source match schema is invalid")
        if any(
            not isinstance(raw[key], str) or len(raw[key]) > 120
            for key in ("team1", "team2", "date", "round")
        ):
            raise StrengthEvidenceError("source match text is invalid")
        try:
            home = resolve_openfootball_team(
                identity, season_code=resource.season, source_team_name=raw["team1"]
            )
            away = resolve_openfootball_team(
                identity, season_code=resource.season, source_team_name=raw["team2"]
            )
        except IngestionError as exc:
            raise StrengthEvidenceError("source club or season mapping is unresolved") from exc
        fixture = registrations.get((resource.season, home, away))
        if fixture is None:
            raise StrengthEvidenceError("source has no exact canonical fixture mapping")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw["date"]) is None:
            raise StrengthEvidenceError("source date precision is invalid")
        try:
            played = date.fromisoformat(raw["date"])
        except ValueError as exc:
            raise StrengthEvidenceError("source match date is invalid") from exc
        round_match = re.fullmatch(r"Matchday ([1-9]|[12]\d|3[0-8])", raw["round"])
        if round_match is None:
            raise StrengthEvidenceError("source round is invalid")
        if "time" in raw and (
            not isinstance(raw["time"], str)
            or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw["time"]) is None
        ):
            raise StrengthEvidenceError("source unzoned time is invalid")
        score = _score(raw.get("score"))
        status = raw.get("status", "")
        if not isinstance(status, str) or len(status) > 80:
            raise StrengthEvidenceError("source status schema is invalid")
        finality: Literal["FULL_TIME", "NOT_FINAL", "UNKNOWN_STATUS", "NO_SCORE"]
        if status in {"postponed", "abandoned", "cancelled", "suspended"}:
            finality = "NOT_FINAL"
        elif status:
            finality = "UNKNOWN_STATUS"
        else:
            finality = "FULL_TIME" if score is not None else "NO_SCORE"
        observations.append(
            seal(
                ParsedMatch,
                fixture=fixture,
                source_match_date=played,
                source_round=int(round_match[1]),
                home_goals=None if score is None else score[0],
                away_goals=None if score is None else score[1],
                finality=finality,
                source_row_sha256=canonical_sha256(raw),
                source_snapshot_sha256=lineage.semantic_sha256,
            )
        )
    return seal(
        ParsedSnapshot,
        lineage=lineage,
        fixture_registry_sha256=fixtures.semantic_sha256,
        matches=tuple(sorted(observations, key=lambda row: row.fixture.fixture_id)),
    )


def build_dataset(
    *,
    sources: tuple[ParsedSnapshot, ...],
    fixtures: FixtureRegistry,
    expected_fixture_registry_sha256: str,
    information_cutoff: datetime,
    training_cutoff: datetime,
    forecast_season: str,
    mode: MODE,
) -> TeamStrengthHistoricalDatasetV1:
    require_team_strength_rights()
    fixtures = authenticate(fixtures, expected_fixture_registry_sha256)
    sources = tuple(
        sorted(
            (authenticate(source) for source in sources),
            key=lambda source: source.lineage.resource.season,
        )
    )
    if not sources:
        raise StrengthEvidenceError("source evidence is unavailable")
    for value in (information_cutoff, training_cutoff):
        if value.tzinfo is None or value.utcoffset() is None:
            raise StrengthEvidenceError("cutoffs must be timezone-aware")
    rows, missing, freshness = _eligible(sources, training_cutoff, information_cutoff, mode)
    return seal(
        TeamStrengthHistoricalDatasetV1,
        competition_id=fixtures.competition_id,
        dataset_mode=mode,
        information_cutoff=information_cutoff,
        training_cutoff=training_cutoff,
        forecast_season=forecast_season,
        fixture_registry=fixtures,
        sources=sources,
        matches=rows,
        missing_due=missing,
        freshness=freshness,
    )
