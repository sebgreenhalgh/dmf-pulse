"""Owned MQ002 match-time evidence resolver; never infer a former club from today's.

This complete research slice admits wholly owned synthetic inputs only. Real
membership acquisition/retention requires separately qualified source authority.
No production adapter, provider, database, model fit or activation is invoked.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.player_lab.contracts import LabModel, Sha

CONTRACT_VERSION = "MQ002_OWNED_MATCH_TIME_MEMBERSHIP_V1"
Positive = Annotated[int, Field(gt=0)]
Week = Annotated[int, Field(ge=1, le=38)]
Season = Annotated[str, Field(pattern=r"^20\d{2}/\d{2}$")]


class EvidenceTime(LabModel):
    evidence_sha256: Sha
    observed_at: datetime
    usable_at: datetime

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.observed_at > self.usable_at:
            raise ValueError("EVIDENCE_USABLE_BEFORE_OBSERVATION")
        return self


class PlayerGameweek(LabModel):
    season: Season
    gameweek: Week
    player_id: UUID

    def identity(self) -> tuple[str, int, UUID]:
        return self.season, self.gameweek, self.player_id


class Aggregate(PlayerGameweek):
    minutes: Annotated[int, Field(ge=0)]
    starts: Annotated[int, Field(ge=0)]


class MembershipWindow(PlayerGameweek):
    fixture_ids: tuple[UUID, ...]
    evidence: EvidenceTime

    @model_validator(mode="after")
    def unique_fixtures(self) -> Self:
        if self.fixture_ids != tuple(sorted(set(self.fixture_ids), key=str)):
            raise ValueError("EXACT_CANONICAL_MATCH_TIME_FIXTURE_POPULATION_REQUIRED")
        return self


class Fixture(LabModel):
    season: Season
    gameweek: Week
    fixture_id: UUID
    home_team_id: Positive
    away_team_id: Positive
    status: Literal["FINISHED", "SCHEDULED", "POSTPONED"]
    evidence: EvidenceTime

    @model_validator(mode="after")
    def distinct_clubs(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("FIXTURE_CLUBS_MUST_DIFFER")
        return self


class Participation(PlayerGameweek):
    fixture_id: UUID
    team_id: Positive
    minutes: Annotated[int, Field(ge=0, le=90)]
    starts: Annotated[int, Field(ge=0, le=1)]
    evidence: EvidenceTime


class Exclusion(PlayerGameweek):
    reason: str


class OwnedHistoryBatch(LabModel):
    dataset_mode: Literal["OWNED_SYNTHETIC"] = "OWNED_SYNTHETIC"
    cutoff: datetime
    aggregates: tuple[Aggregate, ...]
    membership: tuple[MembershipWindow, ...]
    fixtures: tuple[Fixture, ...]
    participation: tuple[Participation, ...]

    @model_validator(mode="after")
    def unique_aggregates(self) -> Self:
        keys = [item.identity() for item in self.aggregates]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_PLAYER_GAMEWEEK_AGGREGATE")
        return self


class OwnedHistoryResult(LabModel):
    contract_version: Literal["MQ002_OWNED_MATCH_TIME_MEMBERSHIP_V1"] = CONTRACT_VERSION
    dataset_mode: Literal["OWNED_SYNTHETIC"] = "OWNED_SYNTHETIC"
    accepted: tuple[Participation, ...]
    excluded: tuple[Exclusion, ...]
    known_blank: tuple[PlayerGameweek, ...]
    input_aggregate_count: int
    accepted_aggregate_count: int
    unreferenced_participation_count: int


def resolve_history(batch: OwnedHistoryBatch) -> OwnedHistoryResult:
    """Accept only complete explicit fixture records reconciling the GW aggregate.

    Ambiguity/missingness excludes the entire player/GW. Doubles are never split
    from a GW aggregate. An explicitly evidenced blank yields no training row;
    it is not an OUT/zero-minute competitive appearance. Current club is absent
    from the input contract. Valid zero-minute starts retain their original fact.
    """
    batch = OwnedHistoryBatch.model_validate_json(batch.model_dump_json())
    windows = defaultdict(list)
    fixtures = defaultdict(list)
    participation = defaultdict(list)
    facts_by_gameweek = defaultdict(list)
    aggregate_keys = {row.identity() for row in batch.aggregates}
    for row in batch.membership:
        windows[row.identity()].append(row)
    for row in batch.fixtures:
        fixtures[row.fixture_id].append(row)
    for row in batch.participation:
        participation[(row.player_id, row.fixture_id)].append(row)
        facts_by_gameweek[row.identity()].append(row)
    accepted, excluded, blank = [], [], []
    for aggregate in sorted(
        batch.aggregates, key=lambda x: (x.season, x.gameweek, str(x.player_id))
    ):
        key = aggregate.identity()
        candidates = windows[key]
        reason = None
        rows = []
        if len(candidates) != 1:
            reason = "MISSING_MEMBERSHIP" if not candidates else "AMBIGUOUS_MEMBERSHIP"
        else:
            window = candidates[0]
            if window.evidence.usable_at > batch.cutoff:
                reason = "MEMBERSHIP_AFTER_CUTOFF"
            elif any(
                row.identity() == key and row.fixture_id not in window.fixture_ids
                for row in facts_by_gameweek[key]
            ):
                reason = "PARTICIPATION_OUTSIDE_EXACT_MEMBERSHIP_WINDOW"
            elif not window.fixture_ids:
                if aggregate.minutes or aggregate.starts:
                    reason = "AGGREGATE_CONFLICTS_WITH_EVIDENCED_BLANK"
                else:
                    blank.append(PlayerGameweek(season=key[0], gameweek=key[1], player_id=key[2]))
                    continue
            else:
                for fixture_id in window.fixture_ids:
                    matches = fixtures[fixture_id]
                    facts = participation[(aggregate.player_id, fixture_id)]
                    if len(matches) != 1 or len(facts) != 1:
                        reason = "MISSING_OR_AMBIGUOUS_FIXTURE_PARTICIPATION"
                        break
                    fixture, fact = matches[0], facts[0]
                    if (fixture.season, fixture.gameweek) != key[:2] or fact.identity() != key:
                        reason = "SEASON_OR_PLAYED_GAMEWEEK_MISMATCH"
                    elif fixture.status != "FINISHED":
                        reason = "FIXTURE_NOT_FINISHED_OR_POSTPONED"
                    elif fact.team_id not in {fixture.home_team_id, fixture.away_team_id}:
                        reason = "MATCH_TIME_TEAM_NOT_IN_FIXTURE"
                    elif max(fixture.evidence.usable_at, fact.evidence.usable_at) > batch.cutoff:
                        reason = "PARTICIPATION_AFTER_CUTOFF"
                    if reason:
                        break
                    rows.append(fact)
                if reason is None and (
                    sum(x.minutes for x in rows) != aggregate.minutes
                    or sum(x.starts for x in rows) != aggregate.starts
                ):
                    reason = "PER_FIXTURE_AGGREGATE_RECONCILIATION_FAILED"
        if reason is not None:
            excluded.append(
                Exclusion(season=key[0], gameweek=key[1], player_id=key[2], reason=reason)
            )
        else:
            accepted.extend(rows)
    return OwnedHistoryResult(
        accepted=tuple(accepted),
        excluded=tuple(excluded),
        known_blank=tuple(blank),
        input_aggregate_count=len(batch.aggregates),
        accepted_aggregate_count=len(batch.aggregates) - len(excluded) - len(blank),
        unreferenced_participation_count=sum(
            row.identity() not in aggregate_keys for row in batch.participation
        ),
    )
