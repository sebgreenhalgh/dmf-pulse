"""Exact, transient future-fixture market evidence from one complete Odds response.

This is an R8B binding layer, not a second odds parser or consensus formula.  It
reuses the accepted current-market fixture kernel and keeps every derived future
result bound to the original complete provider response held by the root current
state.  No response subset is represented as a provider response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.market_constraints import MarketConstraint
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateBundle,
    current_unified_state_semantic_sha256,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplFixture, CurrentFplTeam
from dmf_pulse.ingestion.odds.automatic_mapping import _resolve_team
from dmf_pulse.ingestion.odds.current import CurrentOddsEvent
from dmf_pulse.ingestion.odds.identity import current_odds_identity_semantic_sha256
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalFixture,
    CurrentMarketCanonicalIdentityView,
    CurrentMarketCanonicalOperator,
    CurrentMarketConstraintError,
    CurrentMarketReadiness,
    build_exact_fixture_market_constraints,
    current_market_identity_view_sha256,
)
from dmf_pulse.markets.policy import load_market_normalisation_policy

_NAMESPACE = UUID("b2cf8340-e82f-58b6-9d32-1bf69f4bf32e")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HorizonFutureMarketEvidence(_Frozen):
    """One future official fixture's exact classification from the full response."""

    schema_version: Literal["r8b-horizon-future-market-evidence-v1"] = (
        "r8b-horizon-future-market-evidence-v1"
    )
    classification: Literal["MARKET_BACKED", "NO_EVENT", "H2H_UNAVAILABLE"]
    official_fpl_fixture_id: int = Field(gt=0)
    official_fpl_fixture_lookup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gameweek: int = Field(gt=0)
    canonical_fixture_id: UUID
    home_official_fpl_team_id: int = Field(gt=0)
    away_official_fpl_team_id: int = Field(gt=0)
    kickoff_at: datetime
    information_cutoff: datetime
    provider_event_id: str | None = Field(default=None, min_length=1, max_length=500)
    provider_event_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fixture_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_unified_state_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_odds_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    constraints: tuple[MarketConstraint, ...]
    warnings: tuple[str, ...]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def sealed_and_coherent(self) -> Self:
        if self.kickoff_at.tzinfo is None or self.kickoff_at.utcoffset() is None:
            raise ValueError("future market kickoff must be aware")
        if self.information_cutoff.tzinfo is None or self.information_cutoff.utcoffset() is None:
            raise ValueError("future market cutoff must be aware")
        if self.kickoff_at.astimezone(UTC) <= self.information_cutoff.astimezone(UTC):
            raise ValueError("future market fixture must be after cutoff")
        if self.home_official_fpl_team_id == self.away_official_fpl_team_id:
            raise ValueError("future market teams must differ")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("future market warnings must be sorted and unique")
        if self.classification == "MARKET_BACKED":
            if (
                not self.constraints
                or not self.provider_event_id
                or not self.provider_event_identity_sha256
            ):
                raise ValueError("market-backed future evidence needs event and constraints")
        elif self.constraints or (
            self.classification == "NO_EVENT" and self.provider_event_id is not None
        ):
            raise ValueError("future unavailable evidence contradicts its classification")
        if any(item.usable_at > self.information_cutoff for item in self.constraints):
            raise ValueError("future market evidence is post-cutoff")
        if self.semantic_sha256 != horizon_future_market_evidence_sha256(self):
            raise ValueError("future market evidence hash is inconsistent")
        return self


def horizon_future_market_evidence_sha256(value: HorizonFutureMarketEvidence) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _seal(value: HorizonFutureMarketEvidence) -> HorizonFutureMarketEvidence:
    return value.model_copy(
        update={"semantic_sha256": horizon_future_market_evidence_sha256(value)}
    )


def _gameweek(fixture: CurrentFplFixture) -> int:
    if fixture.event_identity is None or not fixture.event_identity.external_id_text.isdecimal():
        raise IngestionError(
            "ROLLING_FUTURE_IDENTITY_UNRESOLVED", "future official gameweek is absent"
        )
    return int(fixture.event_identity.external_id_text)


def _binding_hash(
    source: CurrentUnifiedStateBundle,
    fixture: CurrentFplFixture,
    canonical_fixture_id: UUID,
    provider_event_id: str | None,
    provider_event_identity_sha256: str | None,
) -> str:
    return canonical_sha256(
        {
            "canonical_fixture_id": str(canonical_fixture_id),
            "full_odds_identity_semantic_sha256": current_odds_identity_semantic_sha256(
                source.odds_input
            ),
            "full_odds_market_semantic_sha256": source.odds_input.market_semantic_sha256,
            "information_cutoff": source.information_cutoff.isoformat(),
            "official_fpl_fixture_id": fixture.provider_fixture_id,
            "official_fpl_fixture_lookup_sha256": fixture.identity.canonical_lookup_sha256,
            "provider_event_id": provider_event_id,
            "provider_event_identity_sha256": provider_event_identity_sha256,
        }
    )


def _event_identity(event: CurrentOddsEvent) -> str:
    from dmf_pulse.markets.current import _provider_event_identity_sha256

    return _provider_event_identity_sha256(event)


def _resolve_future_team(source: CurrentUnifiedStateBundle, provider_text: str) -> CurrentFplTeam:
    """Use an accepted root alias first, then the reviewed direct alias policy."""

    resolved_matches = tuple(
        item
        for item in source.identity_map.team_mappings
        if item.provider_team_text == provider_text
    )
    if not resolved_matches:
        return _resolve_team(provider_text, source.fpl_input.teams)
    if len(resolved_matches) != 1:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED",
            "future provider team identity is ambiguous in the current source",
        )
    resolved = resolved_matches[0]
    matches = tuple(
        team
        for team in source.fpl_input.teams
        if team.provider_team_id == resolved.official_fpl_team_id
        and team.identity == resolved.official_fpl_team_identity
    )
    if len(matches) != 1:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED",
            "accepted future team alias contradicts the official FPL source",
        )
    return matches[0]


def _is_other_official_fixture(
    source: CurrentUnifiedStateBundle,
    *,
    home: CurrentFplTeam,
    away: CurrentFplTeam,
    kickoff_at: datetime,
    target_fixture_id: int,
) -> bool:
    return any(
        item.provider_fixture_id != target_fixture_id
        and item.home_team_identity == home.identity
        and item.away_team_identity == away.identity
        and item.kickoff_at == kickoff_at
        for item in source.fpl_input.fixtures
    )


def _exact_event(
    source: CurrentUnifiedStateBundle, fixture: CurrentFplFixture
) -> CurrentOddsEvent | None:
    if fixture.kickoff_at is None:
        raise IngestionError("ROLLING_FUTURE_FIXTURE_UNSCHEDULED", "future fixture has no kickoff")
    exact: list[CurrentOddsEvent] = []
    unresolved_at_exact_kickoff = False
    paired_wrong_time = False
    for event in source.odds_input.events:
        if event.commence_time != fixture.kickoff_at:
            # Another officially scheduled horizon fixture can legitimately
            # involve the same pair. Any unassigned duplicate pairing remains
            # a material reschedule conflict, never ordinary absence.
            try:
                home = _resolve_future_team(source, event.provider_home_team)
                away = _resolve_future_team(source, event.provider_away_team)
            except IngestionError:
                continue
            if {home.identity, away.identity} == {
                fixture.home_team_identity,
                fixture.away_team_identity,
            } and not _is_other_official_fixture(
                source,
                home=home,
                away=away,
                kickoff_at=event.commence_time,
                target_fixture_id=fixture.provider_fixture_id,
            ):
                paired_wrong_time = True
            continue
        try:
            home = _resolve_future_team(source, event.provider_home_team)
            away = _resolve_future_team(source, event.provider_away_team)
        except IngestionError:
            # Preserve benign extra events when the official target is already
            # resolved below.  If no exact target resolves, however, an
            # unresolvable event at this fixture's kickoff is ambiguous target
            # evidence and must never be re-labelled as ordinary absence.
            unresolved_at_exact_kickoff = True
            continue
        if (
            home.identity == fixture.home_team_identity
            and away.identity == fixture.away_team_identity
        ):
            exact.append(event)
        elif (
            {home.identity, away.identity}
            == {
                fixture.home_team_identity,
                fixture.away_team_identity,
            }
            or fixture.home_team_identity in {home.identity, away.identity}
            or fixture.away_team_identity
            in {
                home.identity,
                away.identity,
            }
        ):
            raise IngestionError(
                "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED",
                "potential future provider event contradicts official orientation",
            )
    if paired_wrong_time:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED",
            "provider future event kickoff contradicts official fixture",
        )
    if len(exact) > 1:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED",
            "future official fixture has ambiguous provider events",
        )
    if not exact and unresolved_at_exact_kickoff:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED",
            "unresolvable provider event at future official fixture kickoff",
        )
    return exact[0] if exact else None


def _identity_view(
    source: CurrentUnifiedStateBundle,
    fixture: CurrentFplFixture,
    canonical_fixture_id: UUID,
    event: CurrentOddsEvent,
    binding: str,
) -> CurrentMarketCanonicalIdentityView:
    if not event.bookmakers:
        raise IngestionError("ROLLING_FUTURE_MARKET_UNAVAILABLE", "future event has no bookmakers")
    identity = _event_identity(event)
    fixture_view = CurrentMarketCanonicalFixture(
        official_fpl_fixture_id=fixture.provider_fixture_id,
        official_fpl_fixture_lookup_sha256=fixture.identity.canonical_lookup_sha256,
        provider_event_id=event.provider_event_id,
        provider_event_identity_sha256=identity,
        canonical_fixture_id=canonical_fixture_id,
        official_fpl_external_mapping_id=uuid5(
            _NAMESPACE, "fpl:" + fixture.identity.canonical_lookup_sha256
        ),
        odds_event_external_mapping_id=uuid5(_NAMESPACE, "event:" + identity),
        fixture_binding_sha256=binding,
    )
    operators = tuple(
        CurrentMarketCanonicalOperator(
            bookmaker_key=book.bookmaker_key,
            bookmaker_title=book.bookmaker_title,
            canonical_operator_id=uuid5(_NAMESPACE, "operator:" + book.bookmaker_key),
            canonical_operator_key="transient:" + book.bookmaker_key,
            external_mapping_id=uuid5(_NAMESPACE, "operator-map:" + book.bookmaker_key),
            target_occurrence_times_sha256=canonical_sha256(
                {
                    "bookmaker_key": book.bookmaker_key,
                    "target_occurrence_times": [event.commence_time.isoformat()],
                }
            ),
        )
        for book in event.bookmakers
    )
    provisional = CurrentMarketCanonicalIdentityView.model_construct(
        authority="OPERATOR_INITIATED_DETERMINISTIC",
        resolved_at=source.identity_map.mapping_decided_at,
        resolution_cutoff=source.information_cutoff,
        database_read_performed=False,
        provider_id=uuid5(_NAMESPACE, "provider:the-odds-api"),
        fixtures=(fixture_view,),
        operators=operators,
        semantic_sha256="0" * 64,
    )
    return CurrentMarketCanonicalIdentityView.model_validate(
        provisional.model_dump(mode="python")
        | {"semantic_sha256": current_market_identity_view_sha256(provisional)}
    )


def build_future_market_evidence(
    source: CurrentUnifiedStateBundle,
    *,
    fixture: CurrentFplFixture,
    canonical_fixture_id: UUID,
) -> HorizonFutureMarketEvidence:
    """Classify one official future fixture from the original complete response."""

    try:
        checked = CurrentUnifiedStateBundle.model_validate(source.model_dump(mode="python"))
    except ValidationError as exc:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_SOURCE_INVALID", "future market source invalid"
        ) from exc
    if checked.semantic_sha256 != current_unified_state_semantic_sha256(checked):
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_SOURCE_INVALID", "future market source hash invalid"
        )
    source_fixtures = tuple(
        item
        for item in checked.fpl_input.fixtures
        if item.provider_fixture_id == fixture.provider_fixture_id
    )
    if len(source_fixtures) != 1 or source_fixtures[0] != fixture:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_SOURCE_INVALID",
            "future official fixture is not exactly bound to the current source",
        )
    if fixture.kickoff_at is None or fixture.kickoff_at <= checked.information_cutoff:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_IDENTITY_BLOCKED", "future fixture cutoff invalid"
        )
    gameweek = _gameweek(fixture)
    event = _exact_event(checked, fixture)
    common: dict[str, Any] = {
        "official_fpl_fixture_id": fixture.provider_fixture_id,
        "official_fpl_fixture_lookup_sha256": fixture.identity.canonical_lookup_sha256,
        "gameweek": gameweek,
        "canonical_fixture_id": canonical_fixture_id,
        "home_official_fpl_team_id": int(fixture.home_team_identity.external_id_text),
        "away_official_fpl_team_id": int(fixture.away_team_identity.external_id_text),
        "kickoff_at": fixture.kickoff_at,
        "information_cutoff": checked.information_cutoff,
        "current_unified_state_semantic_sha256": checked.semantic_sha256,
        "full_odds_market_semantic_sha256": checked.odds_input.market_semantic_sha256,
        "full_odds_identity_semantic_sha256": current_odds_identity_semantic_sha256(
            checked.odds_input
        ),
        "original_response_body_sha256": checked.odds_input.provenance.response_body_sha256,
        "original_request_fingerprint": checked.odds_input.provenance.request_fingerprint,
    }
    if event is None:
        return _seal(
            HorizonFutureMarketEvidence.model_construct(
                classification="NO_EVENT",
                provider_event_id=None,
                provider_event_identity_sha256=None,
                fixture_binding_sha256=_binding_hash(
                    checked, fixture, canonical_fixture_id, None, None
                ),
                constraints=(),
                warnings=("FUTURE_MARKET_EVENT_NOT_RETURNED",),
                semantic_sha256="0" * 64,
                **common,
            )
        )
    identity = _event_identity(event)
    binding = _binding_hash(
        checked, fixture, canonical_fixture_id, event.provider_event_id, identity
    )
    if not event.bookmakers:
        return _seal(
            HorizonFutureMarketEvidence.model_construct(
                classification="H2H_UNAVAILABLE",
                provider_event_id=event.provider_event_id,
                provider_event_identity_sha256=identity,
                fixture_binding_sha256=binding,
                constraints=(),
                warnings=("FUTURE_MARKET_H2H_UNAVAILABLE",),
                semantic_sha256="0" * 64,
                **common,
            )
        )
    try:
        view = _identity_view(checked, fixture, canonical_fixture_id, event, binding)
        result = build_exact_fixture_market_constraints(
            source=checked,
            event=event,
            fixture=view.fixtures[0],
            identity_view=view,
            mapping_cutoff=checked.identity_map.mapping_decided_at,
            policy=load_market_normalisation_policy(),
            score_policy=load_score_baseline_policy(),
            market_as_of=max(
                checked.decision_information_at, checked.identity_map.mapping_decided_at
            ),
        )
    except CurrentMarketConstraintError as exc:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_SOURCE_INVALID", "future market processing failed"
        ) from exc
    if result.readiness is CurrentMarketReadiness.BLOCKED:
        classification: Literal["MARKET_BACKED", "NO_EVENT", "H2H_UNAVAILABLE"] = "H2H_UNAVAILABLE"
        constraints: tuple[MarketConstraint, ...] = ()
        warnings = tuple(sorted(set((*result.warnings, "FUTURE_MARKET_H2H_UNAVAILABLE"))))
    else:
        classification = "MARKET_BACKED"
        constraints = result.constraint_set.constraints
        warnings = tuple(sorted(set(result.warnings)))
        if result.readiness is CurrentMarketReadiness.H2H_ONLY_DEGRADED:
            warnings = tuple(sorted(set((*warnings, "FUTURE_MARKET_TOTALS_UNAVAILABLE"))))
    return _seal(
        HorizonFutureMarketEvidence.model_construct(
            classification=classification,
            provider_event_id=event.provider_event_id,
            provider_event_identity_sha256=identity,
            fixture_binding_sha256=binding,
            constraints=constraints,
            warnings=warnings,
            semantic_sha256="0" * 64,
            **common,
        )
    )


def verify_future_market_evidence(
    value: HorizonFutureMarketEvidence,
    source: CurrentUnifiedStateBundle,
    *,
    fixture: CurrentFplFixture,
    canonical_fixture_id: UUID,
) -> HorizonFutureMarketEvidence:
    """Reject rehashed changes by reconstructing from the complete original source."""

    checked = HorizonFutureMarketEvidence.model_validate(value.model_dump(mode="python"))
    expected = build_future_market_evidence(
        source, fixture=fixture, canonical_fixture_id=canonical_fixture_id
    )
    if checked != expected:
        raise IngestionError(
            "ROLLING_FUTURE_MARKET_SOURCE_INVALID", "future evidence differs from source"
        )
    return checked


__all__ = [
    "HorizonFutureMarketEvidence",
    "build_future_market_evidence",
    "horizon_future_market_evidence_sha256",
    "verify_future_market_evidence",
]
