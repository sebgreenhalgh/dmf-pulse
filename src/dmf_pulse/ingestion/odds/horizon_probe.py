"""R8A transient observation only: no consensus, projections or recommendation.

The complete original response is parsed on every classification/verification.
Returned records contain identities and categories, never prices or source bodies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import TypeAdapter

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplFixture,
    CurrentFplIdentity,
    CurrentFplInputBundle,
)
from dmf_pulse.ingestion.odds.automatic_mapping import _resolve_team
from dmf_pulse.ingestion.odds.client import OddsFetchResult, OddsRetrievalAttempt, build_request
from dmf_pulse.ingestion.odds.config import (
    load_provider_config,
    load_rights_profiles,
    provider_config_sha256,
    rights_config_sha256,
)
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsTotalsOutcome,
    _canonical_outcome,
    _canonical_totals_outcome,
    _contains_secret_like_extra,
)
from dmf_pulse.ingestion.odds.identity import current_fpl_identity_view_sha256
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import (
    OddsBookmaker,
    OddsEvent,
    ParsedOddsPayload,
    parse_odds_payload,
)
from dmf_pulse.markets.models import canonical_decimal_text
from dmf_pulse.markets.policy import load_market_normalisation_policy

PROFILE_ID = "the_odds_api_private_analytics_v1"
CONTRACT = "horizon-market-observation-r8a-v1"


@dataclass(frozen=True)
class BookObservation:
    bookmaker_sha256: str
    h2h: Literal["ABSENT", "COMPLETE", "INVALID"]
    h2h_observed_at: datetime | None
    h2h_timestamp_source: Literal["MARKET", "BOOKMAKER"] | None
    h2h_temporally_eligible: bool
    h2h_stale: bool
    totals: Literal["MISSING", "PAIRED_HALF_GOAL", "UNSUPPORTED", "INVALID"]
    paired_lines: tuple[str, ...]
    totals_observed_at: datetime | None
    totals_timestamp_source: Literal["MARKET", "BOOKMAKER"] | None
    totals_temporally_eligible: bool
    totals_stale: bool
    ignored_h2h_lay: bool
    blockers: tuple[str, ...]
    degradations: tuple[str, ...]


@dataclass(frozen=True)
class FixtureObservation:
    gameweek: int
    fixture_identity_sha256: str
    status: Literal["MATCHED", "NOT_RETURNED", "BLOCKED"]
    event_sha256: str | None
    books: tuple[BookObservation, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class EventObservation:
    event_sha256: str
    status: Literal["MATCHED", "OUTSIDE_HORIZON", "BLOCKED"]
    books: tuple[BookObservation, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class HorizonObservation:
    body_sha256: str
    parsed_semantic_sha256: str
    request_fingerprint: str
    commence_from: datetime
    commence_to: datetime
    request_started_at: datetime
    received_at: datetime
    assessed_at: datetime
    usable_at: datetime
    fpl_input_sha256: str
    fpl_identity_sha256: str
    fpl_bootstrap_sha256: str
    fpl_fixtures_sha256: str
    fpl_rights_config_sha256: str
    fpl_provider_config_sha256: str
    odds_rights_config_sha256: str
    odds_profile_sha256: str
    odds_provider_config_sha256: str
    freshness_policy_sha256: str
    quota: QuotaState
    nominal_cost: int
    transport_attempts: int
    attempts_sha256: str
    fixtures: tuple[FixtureObservation, ...]
    events: tuple[EventObservation, ...]
    outside_horizon_events: int
    status: Literal["OBSERVATION_ONLY"] = "OBSERVATION_ONLY"
    consensus: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    stage8_acceptance: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    model_stage_invocations: Literal[0] = 0
    persistence_performed: Literal[False] = False

    def safe_summary(self) -> dict[str, object]:
        """Exclusive mapping states reconcile; all market counts overlap by fixture."""
        counts: list[dict[str, int]] = []
        for gw in sorted({row.gameweek for row in self.fixtures}):
            rows = tuple(row for row in self.fixtures if row.gameweek == gw)
            counts.append(
                {
                    "gameweek": gw,
                    "official_fixtures": len(rows),
                    "matched": sum(row.status == "MATCHED" for row in rows),
                    "not_returned": sum(row.status == "NOT_RETURNED" for row in rows),
                    "blocked": sum(row.status == "BLOCKED" for row in rows),
                    "event_no_books": sum(
                        row.event_sha256 is not None and not row.books for row in rows
                    ),
                    "bookmaker_present": sum(bool(row.books) for row in rows),
                    "complete_h2h": sum(
                        any(b.h2h == "COMPLETE" for b in row.books) for row in rows
                    ),
                    "temporally_eligible_h2h": sum(
                        row.status == "MATCHED"
                        and any(b.h2h_temporally_eligible for b in row.books)
                        for row in rows
                    ),
                    "paired_supported_totals": sum(
                        any(b.totals == "PAIRED_HALF_GOAL" for b in row.books) for row in rows
                    ),
                    "temporally_eligible_totals": sum(
                        row.status == "MATCHED"
                        and any(b.totals_temporally_eligible for b in row.books)
                        for row in rows
                    ),
                    "missing_totals": sum(
                        any(b.totals == "MISSING" for b in row.books) for row in rows
                    ),
                    "unsupported_totals": sum(
                        any(b.totals == "UNSUPPORTED" for b in row.books) for row in rows
                    ),
                    "invalid_totals": sum(
                        any(b.totals == "INVALID" for b in row.books) for row in rows
                    ),
                    "no_h2h": sum(any(b.h2h == "ABSENT" for b in row.books) for row in rows),
                    "totals_only": sum(
                        any(b.h2h == "ABSENT" and b.totals != "MISSING" for b in row.books)
                        for row in rows
                    ),
                    "stale": sum(
                        any(b.h2h_stale or b.totals_stale for b in row.books) for row in rows
                    ),
                }
            )
        return {
            "contract": CONTRACT,
            "status": self.status,
            "consensus": self.consensus,
            "stage8_acceptance": self.stage8_acceptance,
            "information_cutoff": self.commence_from.isoformat(),
            "commence_from": self.commence_from.isoformat(),
            "commence_to": self.commence_to.isoformat(),
            "request_started_at": self.request_started_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "assessed_at": self.assessed_at.isoformat(),
            "usable_at": self.usable_at.isoformat(),
            "body_sha256": self.body_sha256,
            "request_fingerprint": self.request_fingerprint,
            "fpl_input_sha256": self.fpl_input_sha256,
            "fpl_identity_sha256": self.fpl_identity_sha256,
            "fpl_bootstrap_sha256": self.fpl_bootstrap_sha256,
            "fpl_fixtures_sha256": self.fpl_fixtures_sha256,
            "fpl_rights_config_sha256": self.fpl_rights_config_sha256,
            "fpl_provider_config_sha256": self.fpl_provider_config_sha256,
            "odds_rights_config_sha256": self.odds_rights_config_sha256,
            "odds_profile_sha256": self.odds_profile_sha256,
            "odds_provider_config_sha256": self.odds_provider_config_sha256,
            "freshness_policy_sha256": self.freshness_policy_sha256,
            "by_gameweek": counts,
            "exclusive_counts": "matched + not_returned + blocked = official_fixtures",
            "overlapping_counts": "all market/book/stale counts are fixture-level and may overlap",
            "outside_horizon_events": self.outside_horizon_events,
            "blocked_events": sum(e.status == "BLOCKED" for e in self.events),
            "integrity_blocked_books": sum(bool(b.blockers) for e in self.events for b in e.books),
            "nominal_request_cost": self.nominal_cost,
            "x_requests_remaining": self.quota.remaining,
            "x_requests_used": self.quota.used,
            "x_requests_last": self.quota.last_cost,
            "transport_attempts": self.transport_attempts,
            "attempts_sha256": self.attempts_sha256,
            "model_stage_invocations": 0,
            "persistence_performed": False,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IngestionError("VALIDATION_FAILED", "probe timestamps must be aware")
    return value.astimezone(UTC)


def _horizon(fpl: CurrentFplInputBundle) -> tuple[tuple[int, CurrentFplFixture], ...]:
    # Revalidate copied/constructed Pydantic input rather than trusting frozen=True.
    fpl = CurrentFplInputBundle.model_validate(fpl.model_dump(mode="python"))
    cutoff = fpl.provenance.information_cutoff
    if cutoff.microsecond or fpl.target_event.deadline_at <= cutoff:
        raise IngestionError(
            "VALIDATION_FAILED", "probe cutoff must be whole-second and predeadline"
        )
    result: list[tuple[int, CurrentFplFixture]] = []
    ids: set[str] = set()
    for gw in range(fpl.target_gameweek, fpl.target_gameweek + 3):
        events = tuple(e for e in fpl.events if e.provider_event_id == gw)
        if len(events) != 1 or events[0].finished:
            raise IngestionError(
                "ROLLING_FUTURE_FIXTURES_UNAVAILABLE", "horizon event is unavailable"
            )
        rows = tuple(f for f in fpl.fixtures if f.event_identity == events[0].identity)
        if not rows:
            raise IngestionError(
                "ROLLING_FUTURE_FIXTURES_UNAVAILABLE", "horizon fixtures are absent"
            )
        for row in sorted(rows, key=lambda f: f.provider_fixture_id):
            key = row.identity.canonical_lookup_sha256
            if key in ids:
                raise IngestionError("MAPPING_CONFLICT", "duplicate official horizon fixture")
            ids.add(key)
            if row.kickoff_at is None:
                raise IngestionError(
                    "ROLLING_FUTURE_FIXTURE_UNSCHEDULED", "horizon fixture has no kickoff"
                )
            if row.started or row.finished or row.finished_provisional or row.kickoff_at <= cutoff:
                raise IngestionError(
                    "QUALITY_BLOCKED", "horizon fixtures must be scheduled and unstarted"
                )
            result.append((gw, row))
    return tuple(result)


def horizon_window(fpl: CurrentFplInputBundle) -> tuple[datetime, datetime]:
    rows = _horizon(fpl)
    latest = max(f.kickoff_at for _, f in rows if f.kickoff_at is not None)
    if latest.microsecond:
        raise IngestionError(
            "VALIDATION_FAILED", "official kickoff must have whole-second precision"
        )
    return fpl.provenance.information_cutoff, latest + timedelta(seconds=1)


def _book(
    event: OddsEvent,
    book: OddsBookmaker,
    parsed: ParsedOddsPayload,
    received: datetime,
    assessed: datetime,
    stale_after: int,
) -> BookObservation:
    blockers: set[str] = set()
    degradations: set[str] = set()
    markets = {m.key: m for m in book.markets}
    h2h = markets.get("h2h")
    totals = markets.get("totals")
    if book.last_update > received:
        blockers.add("BOOKMAKER_TIMESTAMP_AFTER_RECEIPT")
    htime = None if h2h is None else h2h.last_update or book.last_update
    hsource: Literal["MARKET", "BOOKMAKER"] | None = (
        None if h2h is None else "MARKET" if h2h.last_update is not None else "BOOKMAKER"
    )
    hstate: Literal["ABSENT", "COMPLETE", "INVALID"] = "ABSENT"
    duplicate_markets = {
        d.market_key
        for d in parsed.duplicate_outcomes
        if d.event_external_id_sha256 == canonical_sha256(event.id) and d.bookmaker_key == book.key
    }
    if h2h is not None:
        outcomes = [_canonical_outcome(event, o.name) for o in h2h.outcomes]
        if len(outcomes) != 3 or set(outcomes) != {"HOME", "DRAW", "AWAY"}:
            blockers.add("H2H_INCOMPLETE")
        if None in outcomes or any(o.point is not None for o in h2h.outcomes):
            blockers.add("H2H_MALFORMED")
        if "h2h" in duplicate_markets or len(set(outcomes)) != len(outcomes):
            blockers.add("H2H_DUPLICATE_OUTCOME")
        if htime is not None and (htime > received or htime > book.last_update):
            blockers.add("H2H_TIMESTAMP_INVALID")
        hstate = "INVALID" if blockers else "COMPLETE"
    tstate: Literal["MISSING", "PAIRED_HALF_GOAL", "UNSUPPORTED", "INVALID"] = "MISSING"
    lines: list[str] = []
    ttime = None if totals is None else totals.last_update or book.last_update
    tsource: Literal["MARKET", "BOOKMAKER"] | None = (
        None if totals is None else "MARKET" if totals.last_update is not None else "BOOKMAKER"
    )
    if totals is not None:
        by_line: dict[Decimal, set[str]] = {}
        if ttime is not None and (ttime > received or ttime > book.last_update):
            degradations.add("TOTALS_TIMESTAMP_INVALID")
        if "totals" in duplicate_markets:
            degradations.add("TOTALS_DUPLICATE_OUTCOME")
        for outcome in totals.outcomes:
            side = _canonical_totals_outcome(outcome.name)
            if side is None or outcome.point is None:
                degradations.add("TOTALS_MALFORMED_OUTCOME")
                continue
            try:
                CurrentOddsTotalsOutcome(
                    provider_name=outcome.name,
                    outcome=side,
                    decimal_price=outcome.price,
                    point=outcome.point,
                )
            except ValueError:
                degradations.add("TOTALS_UNSUPPORTED_LINE")
                continue
            sides = by_line.setdefault(outcome.point, set())
            if side in sides:
                degradations.add("TOTALS_DUPLICATE_OUTCOME")
            sides.add(side)
        for line, sides in sorted(by_line.items()):
            if sides == {"OVER", "UNDER"}:
                lines.append(canonical_decimal_text(line))
            else:
                degradations.add("TOTALS_INCOMPLETE_LINE")
        if not totals.outcomes:
            degradations.add("TOTALS_EMPTY")
        tstate = (
            "INVALID"
            if degradations - {"TOTALS_UNSUPPORTED_LINE"}
            else "UNSUPPORTED"
            if degradations
            else "PAIRED_HALF_GOAL"
        )
    hstale = htime is not None and (assessed - htime).total_seconds() > stale_after
    tstale = ttime is not None and (assessed - ttime).total_seconds() > stale_after
    return BookObservation(
        canonical_sha256(book.key),
        hstate,
        htime,
        hsource,
        hstate == "COMPLETE" and not hstale and not blockers,
        hstale,
        tstate,
        tuple(lines),
        ttime,
        tsource,
        tstate == "PAIRED_HALF_GOAL" and not tstale and not blockers,
        tstale,
        "h2h_lay" in markets,
        tuple(sorted(blockers)),
        tuple(sorted(degradations)),
    )


def _classify(
    fetched: OddsFetchResult, fpl: CurrentFplInputBundle, assessed_at: datetime, usable_at: datetime
) -> HorizonObservation:
    start, end = horizon_window(fpl)
    assessed, usable = _utc(assessed_at), _utc(usable_at)
    expected = build_request("synthetic-fingerprint-only", commence_from=start, commence_to=end)
    config = load_provider_config()
    attempts = fetched.attempts
    if not 1 <= len(attempts) <= config.retry.max_attempts or fetched.transport_call_count != len(
        attempts
    ):
        raise IngestionError("VALIDATION_FAILED", "probe retrieval attempts are inconsistent")
    if (
        fetched.request_fingerprint != expected.request_fingerprint
        or fetched.sanitized_target != expected.sanitized_target
    ):
        raise IngestionError("MAPPING_CONFLICT", "probe request does not bind the exact horizon")
    previous = attempts[0].request_started_at
    for index, attempt in enumerate(attempts, 1):
        if (
            attempt.attempt_number != index
            or attempt.request_fingerprint != expected.request_fingerprint
            or attempt.sanitized_target != expected.sanitized_target
            or attempt.transport_id != fetched.transport_id
            or not _utc(previous) <= _utc(attempt.request_started_at) <= _utc(attempt.received_at)
            or attempt.attempt_outcome
            != ("SUCCESS" if index == len(attempts) else "RETRY_SCHEDULED")
        ):
            raise IngestionError("VALIDATION_FAILED", "probe retrieval history is inconsistent")
        previous = attempt.received_at
    last = attempts[-1]
    if (
        not last.received_at <= assessed <= usable <= start
        or fpl.provenance.usable_at > attempts[0].request_started_at
    ):
        raise IngestionError("POST_CUTOFF", "probe temporal order or cutoff is invalid")
    parsed = parse_odds_payload(fetched.body)
    if (
        last.body_capture_state != "COMPLETE"
        or last.body_sha256 != parsed.body_sha256
        or last.body_size != len(fetched.body)
        or last.http_status != 200
        or last.failure_code is not None
        or last.quota_header_state != "VALID"
        or fetched.quota != last.quota
        or fetched.quota.observed_at != last.received_at
        or fetched.quota.source != QuotaSource.RESPONSE_HEADERS
        or fetched.quota.last_cost != (config.request_cost if parsed.events else 0)
    ):
        raise IngestionError(
            "VALIDATION_FAILED", "probe source hash, quota or success evidence is invalid"
        )
    if _contains_secret_like_extra(parsed.events):
        raise IngestionError("QUALITY_BLOCKED", "secret-like provider fields are forbidden")
    policy = load_market_normalisation_policy()
    rows = _horizon(fpl)
    matched: dict[str, list[EventObservation]] = {}
    blocked: dict[str, set[str]] = {}
    event_results: list[EventObservation] = []
    for event in sorted(parsed.events, key=lambda e: e.id):
        books = tuple(
            _book(
                event, b, parsed, last.received_at, assessed, policy.freshness.stale_after_seconds
            )
            for b in sorted(event.bookmakers, key=lambda b: b.key)
        )
        blockers = {b for book in books for b in book.blockers}
        if event.commence_time <= start:
            blockers.add("EVENT_NOT_PREMATCH")
        home: CurrentFplIdentity | None
        away: CurrentFplIdentity | None
        try:
            home, away = (
                _resolve_team(name, fpl.teams).identity
                for name in (event.home_team, event.away_team)
            )
        except IngestionError:
            # Unknown aliases cannot establish irrelevance; conservatively block the horizon.
            home = away = None
            blockers.add("UNKNOWN_OR_AMBIGUOUS_TEAM_ALIAS")
        exact = tuple(
            f
            for f in fpl.fixtures
            if home is not None
            and home != away
            and f.home_team_identity == home
            and f.away_team_identity == away
            and f.kickoff_at == event.commence_time
        )
        target = tuple(f for _, f in rows if f in exact)
        if len(exact) == 1 and not target:
            status: Literal["MATCHED", "OUTSIDE_HORIZON", "BLOCKED"] = "OUTSIDE_HORIZON"
        elif len(exact) == 1 and len(target) == 1:
            status = "BLOCKED" if blockers else "MATCHED"
        else:
            status = "BLOCKED"
            blockers.add("NO_UNIQUE_EXACT_ORIENTED_FIXTURE")
            possible = tuple(
                f
                for _, f in rows
                if home is None
                or away is None
                or {home, away} == {f.home_team_identity, f.away_team_identity}
            )
            # Unproven outside-horizon events are not grounds for absence, even if
            # the known pair has no matching assigned horizon fixture.
            for fixture in possible or tuple(f for _, f in rows):
                blocked.setdefault(fixture.identity.canonical_lookup_sha256, set()).update(blockers)
        result = EventObservation(
            canonical_sha256(event.id), status, books, tuple(sorted(blockers))
        )
        event_results.append(result)
        if len(target) == 1:
            matched.setdefault(target[0].identity.canonical_lookup_sha256, []).append(result)
    duplicated = {e.event_sha256 for values in matched.values() if len(values) > 1 for e in values}
    event_results = [
        replace(
            e,
            status="BLOCKED",
            blockers=tuple(sorted(set(e.blockers) | {"MULTIPLE_EVENTS_FOR_FIXTURE"})),
        )
        if e.event_sha256 in duplicated
        else e
        for e in event_results
    ]
    fixtures: list[FixtureObservation] = []
    for gw, fixture in rows:
        key = fixture.identity.canonical_lookup_sha256
        events = matched.get(key, [])
        reasons = set(blocked.get(key, set()))
        if len(events) > 1:
            reasons.add("MULTIPLE_EVENTS_FOR_FIXTURE")
        reasons.update(b for e in events for b in e.blockers)
        state: Literal["MATCHED", "NOT_RETURNED", "BLOCKED"] = (
            "BLOCKED" if reasons else "MATCHED" if events else "NOT_RETURNED"
        )
        fixtures.append(
            FixtureObservation(
                gw,
                key,
                state,
                events[0].event_sha256 if len(events) == 1 else None,
                tuple(b for e in events for b in e.books),
                tuple(sorted(reasons)),
            )
        )
    profile = load_rights_profiles()[PROFILE_ID]
    return HorizonObservation(
        parsed.body_sha256,
        parsed.semantic_sha256,
        expected.request_fingerprint,
        start,
        end,
        attempts[0].request_started_at,
        last.received_at,
        assessed,
        usable,
        fpl.semantic_sha256,
        current_fpl_identity_view_sha256(fpl),
        fpl.provenance.bootstrap_payload_sha256,
        fpl.provenance.fixtures_payload_sha256,
        fpl.provenance.rights_config_sha256,
        fpl.provenance.provider_config_sha256,
        rights_config_sha256(),
        canonical_sha256(
            {
                **profile.model_dump(mode="json", exclude={"capabilities"}),
                "capabilities": {k.value: v.value for k, v in profile.capabilities.items()},
            }
        ),
        provider_config_sha256(),
        policy.sha256,
        fetched.quota,
        config.request_cost,
        len(attempts),
        canonical_sha256(
            TypeAdapter(tuple[OddsRetrievalAttempt, ...]).dump_python(attempts, mode="json")
        ),
        tuple(fixtures),
        tuple(event_results),
        sum(e.status == "OUTSIDE_HORIZON" for e in event_results),
    )


def classify_horizon(
    fetched: OddsFetchResult,
    fpl: CurrentFplInputBundle,
    *,
    assessed_at: datetime,
    usable_at: datetime,
) -> HorizonObservation:
    """Detached failure boundary: no source-bearing frame or provider message escapes."""
    result = None
    code = "VALIDATION_FAILED"
    try:
        result = _classify(fetched, fpl, assessed_at, usable_at)
    except IngestionError as exc:
        code = exc.code
    except (ValueError, TypeError, AttributeError, KeyError):
        code = "VALIDATION_FAILED"
    del fetched, fpl
    if result is None:
        raise IngestionError(code, "horizon observation failed integrity validation") from None
    return result


def verify_observation(
    observation: HorizonObservation, fetched: OddsFetchResult, fpl: CurrentFplInputBundle
) -> None:
    """Reconstruct all membership/categories from the original complete in-memory source."""
    expected = classify_horizon(
        fetched, fpl, assessed_at=observation.assessed_at, usable_at=observation.usable_at
    )
    del fetched, fpl
    if observation != expected:
        raise IngestionError("MAPPING_CONFLICT", "observation differs from its complete source")
