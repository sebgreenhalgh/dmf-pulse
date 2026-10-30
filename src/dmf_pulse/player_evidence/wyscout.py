"""Offline formation adapter candidate, admitted only for pinned owned bytes.

Public native entry points reject every real source before parsing. Native
substitution clock minutes never become FPL played minutes or inferred starts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictInt, model_validator

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.player_evidence.contracts import (
    EvidenceError,
    EvidenceFeatureSet,
    EvidenceFixture,
    EvidenceSource,
    FeatureRequest,
    Identifier,
    IdentityMapping,
    Participation,
    ParticipationDataset,
    PlayerScope,
    Role,
    RosterMembership,
    Season,
)
from dmf_pulse.player_evidence.features import build_features
from dmf_pulse.player_evidence.qualification import (
    MAX_BODY_BYTES,
    OWNED_WYSCOUT_BINDINGS_SHA256,
    authenticate_wyscout_native,
    owned_wyscout_bindings_body,
    owned_wyscout_native_body,
    owned_wyscout_native_source,
    owned_wyscout_source,
)
from dmf_pulse.player_lab.contracts import LabModel, Sha

PositiveID = Annotated[StrictInt, Field(ge=1)]


class _Native(LabModel):
    # Native row statistics/labels are deliberately unretained. Every consumed
    # identity, status and role field is typed; the entire owned body is pinned.
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)


class _Player(_Native):
    playerId: PositiveID


class _Substitution(_Native):
    playerIn: PositiveID
    playerOut: PositiveID
    minute: Annotated[StrictInt, Field(ge=0, le=150)]


class _Formation(_Native):
    lineup: Annotated[tuple[_Player, ...], Field(max_length=30)]
    bench: Annotated[tuple[_Player, ...], Field(max_length=30)]
    substitutions: Annotated[tuple[_Substitution, ...], Field(max_length=10)] | None

    @model_validator(mode="after")
    def direct_roles(self) -> Self:
        starters = [row.playerId for row in self.lineup]
        bench = [row.playerId for row in self.bench]
        if len(set(starters + bench)) != len(starters + bench):
            raise ValueError("native matchday roles are duplicated or overlap")
        active = set(starters)
        entered: set[int] = set()
        last_minute = 0
        for row in self.substitutions or ():
            if (
                row.playerIn not in bench
                or row.playerIn in entered
                or row.playerOut not in active
                or row.minute < last_minute
            ):
                raise ValueError("substitution identity or chronology differs from matchday roles")
            active.remove(row.playerOut)
            active.add(row.playerIn)
            entered.add(row.playerIn)
            last_minute = row.minute
        return self


class _Team(_Native):
    teamId: PositiveID
    side: Literal["home", "away"]
    hasFormation: Annotated[StrictInt, Field(ge=0, le=1)]
    formation: _Formation | None

    @model_validator(mode="after")
    def explicit_formation(self) -> Self:
        if self.hasFormation == 1 and (self.formation is None or not self.formation.lineup):
            raise ValueError("reported native formation lacks a starting lineup")
        if (
            self.hasFormation == 0
            and self.formation is not None
            and (self.formation.lineup or self.formation.bench or self.formation.substitutions)
        ):
            raise ValueError("unreported formation cannot supply role facts")
        return self


class _Match(_Native):
    wyId: PositiveID
    competitionId: PositiveID
    seasonId: PositiveID
    dateutc: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")]
    status: Literal["Played"]
    duration: Literal["Regular"]
    teamsData: Annotated[dict[str, _Team], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def exact_teams(self) -> Self:
        if {row.side for row in self.teamsData.values()} != {"home", "away"} or any(
            key != str(row.teamId) for key, row in self.teamsData.items()
        ):
            raise ValueError("native fixture team identity or side differs")
        return self


class _Envelope(LabModel):
    schema_version: Literal["dmf-owned-wyscout-native-v1"]
    classification: Literal["OWNED_SYNTHETIC"]
    matches: Annotated[tuple[_Match, ...], Field(min_length=1, max_length=100)]


class _Bindings(LabModel):
    schema_version: Literal["dmf-owned-wyscout-bindings-v1"]
    classification: Literal["OWNED_SYNTHETIC"]
    source_id: Identifier
    competition_id: PositiveID
    provider_season_id: PositiveID
    season: Season
    observed_at: datetime
    usable_at: datetime
    mappings: tuple[IdentityMapping, ...]
    fixtures: tuple[EvidenceFixture, ...]
    players: tuple[PlayerScope, ...]

    @model_validator(mode="after")
    def authentic_clock_scope(self) -> Self:
        temporal_rows: tuple[IdentityMapping | EvidenceFixture, ...] = (
            *self.mappings,
            *self.fixtures,
        )
        if (
            self.observed_at > self.usable_at
            or not self.fixtures
            or any(
                row.season != self.season
                or row.observed_at > self.observed_at
                or row.usable_at > self.usable_at
                for row in temporal_rows
            )
        ):
            raise ValueError("native binding source vintage or season differs")
        return self


def _strict_json(body: bytes) -> object:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate native JSON field")
            result[key] = value
        return result

    def reject(_value: str) -> None:
        raise ValueError("noninteger native JSON number")

    value: object = json.loads(
        body, object_pairs_hook=unique, parse_float=reject, parse_constant=reject
    )
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 20:
            raise ValueError("native JSON depth exceeds bound")
        if isinstance(item, dict):
            pending.extend((row, depth + 1) for row in item.values())
        elif isinstance(item, list):
            pending.extend((row, depth + 1) for row in item)
    return value


def _adapt_schema(body: bytes, bindings_body: bytes) -> ParticipationDataset:
    """Internal schema transformation; this alone grants no feature qualification."""
    if (
        not isinstance(body, bytes)
        or not isinstance(bindings_body, bytes)
        or max(len(body), len(bindings_body)) > MAX_BODY_BYTES
    ):
        raise ValueError("native source exceeds byte bound")
    _strict_json(body)
    _strict_json(bindings_body)
    native = _Envelope.model_validate_json(body)
    bindings = _Bindings.model_validate_json(bindings_body)
    fixtures = {row.provider_fixture_id: row for row in bindings.fixtures}
    if (
        len(fixtures) != len(bindings.fixtures)
        or len({row.wyId for row in native.matches}) != len(native.matches)
        or {str(row.wyId) for row in native.matches} != set(fixtures)
    ):
        raise ValueError("native fixture mapping is not an exact unique population")
    memberships, observations = [], []
    for match in native.matches:
        fixture = fixtures[str(match.wyId)]
        kickoff = datetime.strptime(match.dateutc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        sides = {row.side: str(row.teamId) for row in match.teamsData.values()}
        if (
            match.competitionId != bindings.competition_id
            or match.seasonId != bindings.provider_season_id
            or kickoff != fixture.kickoff_at
            or fixture.status != "FINAL"
            or sides
            != {"home": fixture.home_provider_team_id, "away": fixture.away_provider_team_id}
        ):
            raise ValueError("native competition/season/fixture/side binding differs")
        seen_players: set[int] = set()
        for team in match.teamsData.values():
            if not team.hasFormation or team.formation is None:
                continue
            roles: tuple[tuple[Role, tuple[_Player, ...]], ...] = (
                ("START", team.formation.lineup),
                ("BENCH", team.formation.bench),
            )
            for role, players in roles:
                for player in players:
                    if player.playerId in seen_players:
                        raise ValueError("player belongs to both fixture teams")
                    seen_players.add(player.playerId)
                    memberships.append(
                        RosterMembership(
                            season=bindings.season,
                            provider_fixture_id=str(match.wyId),
                            provider_player_id=str(player.playerId),
                            provider_team_id=str(team.teamId),
                            status="VERIFIED_ELIGIBLE",
                            observed_at=bindings.observed_at,
                            usable_at=bindings.usable_at,
                        )
                    )
                    observations.append(
                        Participation(
                            season=bindings.season,
                            provider_fixture_id=str(match.wyId),
                            provider_player_id=str(player.playerId),
                            provider_team_id=str(team.teamId),
                            revision=0,
                            supersedes_sha256=None,
                            role=role,
                            role_missing_reason=None,
                            minutes=None,
                            minutes_missing_reason="NOT_SUPPORTED",
                            minute_convention="UNSUPPORTED",
                            observed_at=bindings.observed_at,
                            usable_at=bindings.usable_at,
                        )
                    )
    # Every consumed native player/team needs exactly one temporal canonical map.
    canonical_players: set[tuple[str, object]] = set()
    for row in memberships:
        fixture = fixtures[row.provider_fixture_id]
        for kind, provider_id in (
            ("PLAYER", row.provider_player_id),
            ("TEAM", row.provider_team_id),
        ):
            candidates = [
                item
                for item in bindings.mappings
                if item.kind == kind
                and item.provider_id == provider_id
                and item.season == fixture.season
                and item.effective_from <= fixture.kickoff_at < item.effective_until
                and item.usable_at <= bindings.usable_at
            ]
            if len(candidates) != 1:
                raise ValueError("native canonical identity is missing or ambiguous")
            if kind == "PLAYER":
                identity = (row.provider_fixture_id, candidates[0].canonical_id)
                if identity in canonical_players:
                    raise ValueError("native player aliases collide in one canonical fixture")
                canonical_players.add(identity)
    for fixture in bindings.fixtures:
        canonical_teams = []
        for provider_id in (fixture.home_provider_team_id, fixture.away_provider_team_id):
            candidates = [
                item
                for item in bindings.mappings
                if item.kind == "TEAM"
                and item.provider_id == provider_id
                and item.season == fixture.season
                and item.effective_from <= fixture.kickoff_at < item.effective_until
                and item.usable_at <= bindings.usable_at
            ]
            if len(candidates) != 1:
                raise ValueError("native fixture team canonical identity is missing or ambiguous")
            canonical_teams.append(candidates[0].canonical_id)
        if len(set(canonical_teams)) != 2:
            raise ValueError("native fixture home/away canonical identities collide")
    return ParticipationDataset(
        schema_version="fixture-participation-evidence-v1",
        source_id=bindings.source_id,
        mode="SYNTHETIC",
        mappings=bindings.mappings,
        fixtures=bindings.fixtures,
        memberships=tuple(memberships),
        observations=tuple(observations),
    )


def adapt_owned_wyscout(body: bytes, *, source: EvidenceSource) -> ParticipationDataset:
    """Authenticate exact owned native bytes and mapping vintage before parsing."""
    authenticate_wyscout_native(body, source)
    bindings = owned_wyscout_bindings_body()
    if hashlib.sha256(bindings).hexdigest() != OWNED_WYSCOUT_BINDINGS_SHA256:
        raise EvidenceError("NATIVE_BINDINGS_NOT_AUTHENTICATED")
    result = _adapt_scope(body, bindings)
    if result is None:
        raise EvidenceError("NATIVE_FORMATION_SCHEMA_INVALID")
    return result


def _adapt_scope(body: bytes, bindings: bytes) -> ParticipationDataset | None:
    try:
        return _adapt_schema(body, bindings)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None


class WyscoutDemo(LabModel):
    schema_version: Literal["owned-native-formation-demo-v1"] = "owned-native-formation-demo-v1"
    mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    native_payload_sha256: Sha
    bindings_sha256: Sha
    native_fixture_count: Annotated[StrictInt, Field(ge=1)]
    unreported_formation_team_fixture_count: Annotated[StrictInt, Field(ge=0)]
    reported_matchday_membership_count: Annotated[StrictInt, Field(ge=0)]
    denominator_scope: Literal["REPORTED_MATCHDAY_SQUAD_ONLY_NOT_FULL_CLUB_ROSTER"] = (
        "REPORTED_MATCHDAY_SQUAD_ONLY_NOT_FULL_CLUB_ROSTER"
    )
    minute_semantics: Literal["NOT_SUPPORTED_NO_FPL_MINUTES_INFERRED"] = (
        "NOT_SUPPORTED_NO_FPL_MINUTES_INFERRED"
    )
    real_release_qualification: Literal["CLOSED_NOT_ACQUIRED"] = "CLOSED_NOT_ACQUIRED"
    source_compatibility: Literal["DOCUMENTED_SUBSET_OWNED_ACCEPTANCE_ONLY"] = (
        "DOCUMENTED_SUBSET_OWNED_ACCEPTANCE_ONLY"
    )
    features: EvidenceFeatureSet

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def owned_wyscout_demo(*, cutoff: datetime | None = None) -> WyscoutDemo:
    """Complete byte-authenticated adapter -> temporal features, synthetic only."""
    native_source = owned_wyscout_native_source()
    dataset = adapt_owned_wyscout(owned_wyscout_native_body(), source=native_source)
    bindings = _Bindings.model_validate_json(owned_wyscout_bindings_body())
    native = _Envelope.model_validate_json(owned_wyscout_native_body())
    request = FeatureRequest(
        season="2017/18",
        cutoff=cutoff or datetime(2019, 3, 1, tzinfo=UTC),
        history_start=datetime(2017, 7, 1, tzinfo=UTC),
        target_kickoff=datetime(2019, 4, 1, tzinfo=UTC),
        players=bindings.players,
    )
    features = build_features(
        canonical_json_bytes(dataset), source=owned_wyscout_source(), request=request
    )
    return WyscoutDemo(
        native_payload_sha256=native_source.payload_sha256,
        bindings_sha256=OWNED_WYSCOUT_BINDINGS_SHA256,
        native_fixture_count=len(native.matches),
        unreported_formation_team_fixture_count=sum(
            not team.hasFormation for match in native.matches for team in match.teamsData.values()
        ),
        reported_matchday_membership_count=len(dataset.memberships),
        features=features,
    )
