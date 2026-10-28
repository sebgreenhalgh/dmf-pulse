"""OpenLigaDB final-fact projection and exact-ten P01 outcome admission."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.p01_fallback_context import (
    ROUTES,
    P01FallbackContext,
    strict_json,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FixtureRegistration,
    FrozenEvidence,
    SealedEvidence,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import eligibility_not_before
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    DiagnosticProgress,
    FailureReason,
    ReasonFailure,
    RouteClass,
)
from dmf_pulse.ingestion.p01_match_metadata import require_match_metadata


class SourceReceipt(FrozenEvidence):
    source_url: str
    request_started_at: datetime
    received_at: datetime
    response_sha256: SHA
    response_bytes: int = Field(gt=0, le=524288)
    status_code: Literal[200] = 200

    @model_validator(mode="after")
    def valid_receipt(self) -> Self:
        if self.source_url not in ROUTES or self.received_at < self.request_started_at:
            raise ValueError("source receipt route/time differs")
        return self


class RegulationResultType(FrozenEvidence):
    league_result_type_id: int = Field(gt=0)
    global_result_type_id: int = Field(gt=0)
    kind: Literal["After90Minutes"] = "After90Minutes"


class ProjectedFinalFact(FrozenEvidence):
    """Minimal retained factual extraction; never the raw match response."""

    provider_match_id: int = Field(gt=0)
    provider_home_id: int = Field(gt=0)
    provider_away_id: int = Field(gt=0)
    home_name: str = Field(min_length=1, max_length=100)
    away_name: str = Field(min_length=1, max_length=100)
    league_id: Literal[5996] = 5996
    league_shortcut: Literal["pl"] = "pl"
    league_season: Literal[2026] = 2026
    league_name: Literal["Premier League"] = "Premier League"
    matchday: Literal[6] = 6
    played_at: datetime
    match_is_finished: Literal[True] = True
    result_id: int = Field(gt=0)
    result_type_id: int = Field(gt=0)
    result_type_kind: Literal["After90Minutes"] = "After90Minutes"
    home_goals: int = Field(ge=0, le=36)
    away_goals: int = Field(ge=0, le=36)

    @model_validator(mode="after")
    def distinct_clubs(self) -> Self:
        if self.provider_home_id == self.provider_away_id or self.home_name == self.away_name:
            raise ValueError("source clubs are not distinct")
        return self


class AdmittedP01Outcome(FrozenEvidence):
    fixture: FixtureRegistration
    frozen_scheduled_date: date
    actual_played_date: date
    finality: Literal["FULL_TIME"] = "FULL_TIME"
    label_class: Literal["FINAL_OUTCOME"] = "FINAL_OUTCOME"
    home_goals: int = Field(ge=0, le=36)
    away_goals: int = Field(ge=0, le=36)
    source_fact: ProjectedFinalFact
    mapping_method: Literal["EXACT_ORIENTED_FROZEN_CLUB_ALIASES"] = (
        "EXACT_ORIENTED_FROZEN_CLUB_ALIASES"
    )
    mapping_context_sha256: SHA


class PublicP01FallbackOutcomesV1(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-outcomes-v1"] = (
        "public-team-strength-p01-fallback-outcomes-v1"
    )
    context: P01FallbackContext
    independent_review_sha256: SHA
    independently_reviewed_at: datetime
    provenance: Literal["PUBLIC_FALLBACK_OUTCOME_SOURCE"] = "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    source: Literal["OpenLigaDB"] = "OpenLigaDB"
    source_role: Literal["CANONICAL_FINAL_OUTCOME_LABEL"] = "CANONICAL_FINAL_OUTCOME_LABEL"
    label_class: Literal["FINAL_OUTCOME"] = "FINAL_OUTCOME"
    retrievals: tuple[SourceReceipt, ...] = Field(min_length=3, max_length=3)
    retrieved_at: datetime
    validated_at: datetime
    usable_at: datetime
    regulation_result_type: RegulationResultType
    extract_sha256: SHA
    outcomes: tuple[AdmittedP01Outcome, ...] = Field(min_length=10, max_length=10)
    attribution: str = Field(min_length=1)
    redistribution_permitted: Literal[False] = False
    reconciliation_status: Literal["OPENFOOTBALL_RECONCILIATION_PENDING"] = (
        "OPENFOOTBALL_RECONCILIATION_PENDING"
    )

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        context = authenticate(self.context)
        if tuple(row.source_url for row in self.retrievals) != context.allowed_routes:
            raise ValueError("fallback source routes differ")
        if not (
            context.amended_at
            <= self.independently_reviewed_at
            <= self.retrievals[0].request_started_at
            and all(
                a.received_at <= b.request_started_at
                for a, b in zip(self.retrievals, self.retrievals[1:], strict=False)
            )
            and self.retrievals[-1].received_at == self.retrieved_at
            and self.retrieved_at <= self.validated_at <= self.usable_at
        ):
            raise ValueError("fallback source availability chronology differs")
        expected = {row.fixture.fixture_id: row for row in context.fixtures}
        ids = tuple(row.fixture.fixture_id for row in self.outcomes)
        source_ids = [row.source_fact.provider_match_id for row in self.outcomes]
        result_ids = [row.source_fact.result_id for row in self.outcomes]
        if (
            ids != tuple(expected)
            or len(set(source_ids)) != 10
            or len(set(result_ids)) != 10
            or canonical_sha256([row.source_fact.model_dump(mode="json") for row in self.outcomes])
            != self.extract_sha256
        ):
            raise ValueError("fallback cohort, uniqueness or extract identity differs")
        provider_clubs: dict[int, UUID] = {}
        canonical_clubs: dict[UUID, int] = {}
        for row in self.outcomes:
            frozen = expected[row.fixture.fixture_id]
            fact = row.source_fact
            for provider_id, canonical_id in (
                (fact.provider_home_id, row.fixture.home_team_id),
                (fact.provider_away_id, row.fixture.away_team_id),
            ):
                if provider_clubs.get(provider_id, canonical_id) != canonical_id or (
                    canonical_clubs.get(canonical_id, provider_id) != provider_id
                ):
                    raise ValueError("ambiguous provider club identity")
                provider_clubs[provider_id] = canonical_id
                canonical_clubs[canonical_id] = provider_id
            if (
                row.fixture != frozen.fixture
                or row.frozen_scheduled_date != frozen.scheduled_date
                or fact.home_name not in frozen.home_aliases
                or fact.away_name not in frozen.away_aliases
                or fact.result_type_id != self.regulation_result_type.league_result_type_id
                or row.mapping_context_sha256 != context.semantic_sha256
                or row.actual_played_date != fact.played_at.date()
                or (row.home_goals, row.away_goals) != (fact.home_goals, fact.away_goals)
                or fact.played_at <= context.frozen_at
                or fact.played_at > self.retrieved_at
                or row.actual_played_date <= context.frozen_at.date()
            ):
                raise ValueError("fallback oriented mapping, result or played date differs")
        return self


def require_d_plus_2(value: PublicP01FallbackOutcomesV1, *, as_of: datetime) -> None:
    as_of = FrozenEvidence.utc_datetimes(as_of)
    if value.usable_at > as_of or any(
        eligibility_not_before(row.actual_played_date) > as_of for row in value.outcomes
    ):
        raise ReasonFailure(FailureReason.D_PLUS_2_NOT_COMPLETE)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReasonFailure(FailureReason.PROVIDER_FIELD_TYPE_INVALID)
    return value


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ReasonFailure(FailureReason.PROVIDER_FIELD_TYPE_INVALID)
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ReasonFailure(FailureReason.PROVIDER_FIELD_TYPE_INVALID)
    return value


def _provider_json(
    body: bytes, route: RouteClass, diagnostics: DiagnosticProgress | None
) -> object:
    try:
        value = strict_json(body)
    except (ValueError, UnicodeError):
        if diagnostics is not None:
            diagnostics.json_valid(route, False)
        raise ReasonFailure(FailureReason.PROVIDER_JSON_INVALID) from None
    if diagnostics is not None:
        diagnostics.json_valid(route, True)
    return value


def regulation_type(
    global_body: bytes, league_body: bytes, *, diagnostics: DiagnosticProgress | None = None
) -> RegulationResultType:
    globals_ = [
        _object(row)
        for row in _array(_provider_json(global_body, RouteClass.GLOBAL_RESULT_TYPES, diagnostics))
    ]
    leagues = [
        _object(row)
        for row in _array(_provider_json(league_body, RouteClass.LEAGUE_RESULT_INFO, diagnostics))
    ]
    candidates = [row for row in globals_ if row.get("kind") == "After90Minutes"]
    finals = [
        row
        for row in leagues
        if _object(row.get("globalResultInfo")).get("kind") == "After90Minutes"
    ]
    if diagnostics is not None:
        diagnostics.update(
            regulation_global_candidate_count=len(candidates),
            regulation_league_candidate_count=len(finals),
        )
    if len(candidates) != 1 or len(finals) != 1:
        raise ReasonFailure(FailureReason.REGULATION_METADATA_AMBIGUOUS)
    global_row, league_row = candidates[0], finals[0]
    linked = _object(league_row["globalResultInfo"])
    if linked.get("id") != global_row.get("id"):
        raise ReasonFailure(FailureReason.REGULATION_METADATA_DISAGREEMENT)
    try:
        result = RegulationResultType(
            league_result_type_id=_integer(league_row.get("id")),
            global_result_type_id=_integer(global_row.get("id")),
        )
    except ReasonFailure:
        raise
    except ValueError:
        raise ReasonFailure(FailureReason.PROVIDER_FIELD_TYPE_INVALID) from None
    if diagnostics is not None:
        diagnostics.update(regulation_metadata_resolved=True)
    return result


def project_final_facts(
    body: bytes,
    *,
    context: P01FallbackContext,
    result_type: RegulationResultType,
    diagnostics: DiagnosticProgress | None = None,
) -> tuple[ProjectedFinalFact, ...]:
    """Process response transiently; retain neither raw JSON nor unrelated fields."""
    value = _provider_json(body, RouteClass.MATCHDAY_DATA, diagnostics)
    if not isinstance(value, list):
        raise ReasonFailure(FailureReason.MATCHDAY_RESPONSE_INVALID)
    matches = value
    if diagnostics is not None:
        diagnostics.update(provider_match_rows=len(matches))
    if len(matches) != 10:
        raise ReasonFailure(FailureReason.MATCHDAY_FIXTURE_COUNT_INVALID)
    projected: list[ProjectedFinalFact] = []
    for item in matches:
        row = _object(item)
        require_match_metadata(row, context=context, diagnostics=diagnostics)
        if row.get("matchIsFinished") is not True:
            raise ReasonFailure(FailureReason.MATCH_NOT_FINISHED)
        if diagnostics is not None:
            diagnostics.update(finished_match_rows=diagnostics.safe.finished_match_rows + 1)
        results = [_object(value) for value in _array(row.get("matchResults"))]
        finals = [
            value
            for value in results
            if value.get("resultTypeKind") == "After90Minutes"
            or value.get("resultTypeID") == result_type.league_result_type_id
        ]
        if diagnostics is not None:
            diagnostics.update(
                regulation_result_rows=diagnostics.safe.regulation_result_rows + len(finals)
            )
        if len(finals) != 1:
            raise ReasonFailure(FailureReason.REGULATION_RESULT_MISSING_OR_AMBIGUOUS)
        final = finals[0]
        if (
            final.get("resultTypeKind") != "After90Minutes"
            or final.get("resultTypeID") != result_type.league_result_type_id
            or type(final.get("resultTypeID")) is not int
        ):
            raise ReasonFailure(FailureReason.REGULATION_RESULT_TYPE_MISMATCH)
        description = " ".join(
            str(final.get(name) or "") for name in ("resultName", "resultDescription")
        ).casefold()
        if any(
            word in description
            for word in (
                "abandon",
                "abbruch",
                "award",
                "annul",
                "penalt",
                "extra time",
                "verlänger",
                "elfmeter",
            )
        ):
            raise ReasonFailure(FailureReason.EXCEPTIONAL_RESULT_REFUSED)
        home, away = _object(row.get("team1")), _object(row.get("team2"))
        played = row.get("matchDateTimeUTC")
        try:
            if not isinstance(played, str):
                raise ValueError
            played_at = datetime.fromisoformat(played)
            if played_at.utcoffset() is None:
                raise ValueError
        except ValueError:
            raise ReasonFailure(FailureReason.PLAYED_TIMESTAMP_MISSING_OR_INVALID) from None
        try:
            projected.append(
                ProjectedFinalFact(
                    provider_match_id=_integer(row.get("matchID")),
                    provider_home_id=_integer(home.get("teamId")),
                    provider_away_id=_integer(away.get("teamId")),
                    home_name=home.get("teamName"),  # type: ignore[arg-type]
                    away_name=away.get("teamName"),  # type: ignore[arg-type]
                    played_at=played_at,
                    result_id=_integer(final.get("resultID")),
                    result_type_id=_integer(final.get("resultTypeID")),
                    home_goals=_integer(final.get("pointsTeam1")),
                    away_goals=_integer(final.get("pointsTeam2")),
                )
            )
        except ReasonFailure:
            raise
        except (ValueError, TypeError):
            raise ReasonFailure(FailureReason.PROVIDER_FIELD_TYPE_INVALID) from None
        if diagnostics is not None:
            diagnostics.update(projected_fact_count=len(projected))
    return tuple(projected)


def admit_final_facts(
    facts: tuple[ProjectedFinalFact, ...],
    *,
    context: P01FallbackContext,
    retrievals: tuple[SourceReceipt, ...],
    result_type: RegulationResultType,
    validated_at: datetime,
    usable_at: datetime,
    attribution: str,
    independent_review_sha256: str,
    independently_reviewed_at: datetime,
    diagnostics: DiagnosticProgress | None = None,
) -> PublicP01FallbackOutcomesV1:
    context = authenticate(context)
    outcomes: list[AdmittedP01Outcome] = []
    for frozen in context.fixtures:
        candidates = [
            fact
            for fact in facts
            if fact.home_name in frozen.home_aliases and fact.away_name in frozen.away_aliases
        ]
        if len(candidates) != 1:
            reason = (
                FailureReason.EXACT_TEN_INCOMPLETE
                if not candidates
                else FailureReason.ORIENTED_MAPPING_AMBIGUOUS
            )
            raise ReasonFailure(reason)
        if diagnostics is not None:
            diagnostics.update(uniquely_mapped_fixture_count=len(outcomes) + 1)
        fact = candidates[0]
        outcomes.append(
            AdmittedP01Outcome(
                fixture=frozen.fixture,
                frozen_scheduled_date=frozen.scheduled_date,
                actual_played_date=fact.played_at.date(),
                home_goals=fact.home_goals,
                away_goals=fact.away_goals,
                source_fact=fact,
                mapping_context_sha256=context.semantic_sha256,
            )
        )
    if len(facts) != 10:
        raise ReasonFailure(FailureReason.EXACT_TEN_INCOMPLETE)
    provider_clubs: dict[int, UUID] = {}
    canonical_clubs: dict[UUID, int] = {}
    for row in outcomes:
        for provider_id, canonical_id in (
            (row.source_fact.provider_home_id, row.fixture.home_team_id),
            (row.source_fact.provider_away_id, row.fixture.away_team_id),
        ):
            if (
                provider_clubs.get(provider_id, canonical_id) != canonical_id
                or canonical_clubs.get(canonical_id, provider_id) != provider_id
            ):
                raise ReasonFailure(FailureReason.PROVIDER_CLUB_IDENTITY_AMBIGUOUS)
            provider_clubs[provider_id] = canonical_id
            canonical_clubs[canonical_id] = provider_id
    admitted = seal(
        PublicP01FallbackOutcomesV1,
        context=context,
        independent_review_sha256=independent_review_sha256,
        independently_reviewed_at=independently_reviewed_at,
        retrievals=retrievals,
        retrieved_at=retrievals[-1].received_at,
        validated_at=validated_at,
        usable_at=usable_at,
        regulation_result_type=result_type,
        extract_sha256=canonical_sha256(
            [row.source_fact.model_dump(mode="json") for row in outcomes]
        ),
        outcomes=tuple(outcomes),
        attribution=attribution,
    )
    if diagnostics is not None:
        diagnostics.update(admitted_outcome_count=len(admitted.outcomes))
    return admitted


def source_receipt(
    url: str, body: bytes, *, started: datetime, received: datetime
) -> SourceReceipt:
    return SourceReceipt(
        source_url=url,
        request_started_at=started,
        received_at=received,
        response_sha256=hashlib.sha256(body).hexdigest(),
        response_bytes=len(body),
    )
