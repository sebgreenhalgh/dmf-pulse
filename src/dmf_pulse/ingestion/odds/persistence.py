"""Explicit mapping and append-only persistence for raw offered odds."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from psycopg.types.range import Range
from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import (
    betting_operator,
    canonical_entity,
    competition,
    data_provider,
    entity_alias,
    external_identifier,
    fixture,
    fixture_observation,
    market_definition,
    market_selection,
    odds_mapping_dependency,
    odds_observation,
    odds_publication_attestation,
    odds_publication_batch,
    operator_fixture_market,
    operator_market_observation,
    provider_market_representation,
    season,
    settlement_profile,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.mapping import OddsMappingPlan
from dmf_pulse.ingestion.odds.parser import (
    CONTRACT_VERSION,
    OddsBookmaker,
    OddsEvent,
    OddsMarket,
    ParsedOddsPayload,
)
from dmf_pulse.markets.models import MarketOutcome, MarketState, canonical_decimal_text

MARKET_DEFINITION_KEY = "MATCH_RESULT_1X2"
MARKET_DEFINITION_VERSION = "1.0.0"
SETTLEMENT_PROFILE_KEY = "SOCCER_FULL_TIME_90_MINUTES_REFERENCE_V1"
SETTLEMENT_PROFILE_VERSION = "1.0.0"


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise IngestionError("CANONICAL_INVARIANT", "database returned an invalid identifier")
    return value


def _advisory_lock(session: Session, key: str) -> None:
    try:
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": key},
        )
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate in {"40001", "40P01", "55P03"}:
            raise IngestionError(
                "DATABASE_RETRYABLE",
                "odds publication lock was not acquired in time",
                retryable=True,
            ) from None
        raise IngestionError("DATABASE_UNAVAILABLE", "odds publication lock failed") from None


def _season_valid_range(starts_on: object, ends_on: object) -> Range[datetime]:
    if not isinstance(starts_on, date) or not isinstance(ends_on, date):
        raise IngestionError("CANONICAL_INVARIANT", "season validity is unavailable")
    return Range(
        datetime.combine(starts_on, time.min, tzinfo=UTC),
        datetime.combine(ends_on + timedelta(days=1), time.min, tzinfo=UTC),
        bounds="[)",
    )


def _operator_valid_range(approved_at: datetime) -> Range[datetime]:
    return Range(require_utc(approved_at), None, bounds="[)")


def ensure_provider(
    session: Session,
    *,
    provider_key: str,
    display_name: str,
    provider_type: str,
    rights_profile_key: str | None,
) -> UUID:
    _advisory_lock(session, f"provider:{provider_key}")
    existing = (
        session.execute(select(data_provider).where(data_provider.c.provider_key == provider_key))
        .mappings()
        .one_or_none()
    )
    expected = {
        "display_name": display_name,
        "provider_type": provider_type,
        "rights_profile_key": rights_profile_key,
    }
    if existing is not None:
        if any(existing[key] != value for key, value in expected.items()):
            raise IngestionError("CANONICAL_INVARIANT", "provider identity conflicts")
        return _uuid(existing["provider_id"])
    provider_id = _uuid(
        session.execute(
            insert(canonical_entity)
            .values(entity_type="DATA_PROVIDER")
            .returning(canonical_entity.c.entity_id)
        ).scalar_one()
    )
    session.execute(
        insert(data_provider).values(
            provider_id=provider_id,
            entity_type="DATA_PROVIDER",
            provider_key=provider_key,
            display_name=display_name,
            provider_type=provider_type,
            rights_profile_key=rights_profile_key,
            active=True,
        )
    )
    return provider_id


def ensure_odds_provider(session: Session) -> UUID:
    return ensure_provider(
        session,
        provider_key="the_odds_api",
        display_name="The Odds API v4",
        provider_type="ODDS_API",
        rights_profile_key="the_odds_api_private_analytics_v1",
    )


def ensure_synthetic_odds_provider(session: Session) -> UUID:
    return ensure_provider(
        session,
        provider_key="synthetic_the_odds_api",
        display_name="Synthetic The Odds API reference provider",
        provider_type="INTERNAL",
        rights_profile_key="synthetic_the_odds_api_v1",
    )


def ensure_official_fpl_provider(session: Session) -> UUID:
    return ensure_provider(
        session,
        provider_key="official_fpl",
        display_name="Official FPL transient manual source",
        provider_type="OFFICIAL",
        rights_profile_key="fpl_official_private_manual_v1",
    )


def _current_mapping(
    session: Session,
    *,
    provider_id: UUID,
    season_id: UUID | None,
    product: str,
    namespace: str,
    entity_type: str,
    external_id: str,
    valid_at: datetime,
    system_at: datetime,
) -> dict[str, object] | None:
    row = (
        session.execute(
            select(external_identifier).where(
                external_identifier.c.provider_id == provider_id,
                external_identifier.c.season_id == season_id,
                external_identifier.c.provider_product == product,
                external_identifier.c.identifier_namespace == namespace,
                external_identifier.c.entity_type == entity_type,
                external_identifier.c.external_id_text == external_id,
                external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                external_identifier.c.valid_during.op("@>")(require_utc(valid_at)),
                external_identifier.c.system_during.op("@>")(require_utc(system_at)),
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _ensure_external_mapping(
    session: Session,
    *,
    provider_id: UUID,
    season_id: UUID | None,
    namespace: str,
    entity_type: str,
    external_id: str,
    canonical_id: UUID,
    product: str,
    snapshot_id: UUID,
    valid_during: Range[datetime],
    resolution_cutoff: datetime,
    system_known_at: datetime,
    evidence_class: str,
    reviewer: str,
) -> UUID:
    _advisory_lock(
        session,
        f"external:{provider_id}:{season_id}:{namespace}:{entity_type}:{external_id}",
    )
    valid_lower = valid_during.lower
    if not isinstance(valid_lower, datetime):
        raise IngestionError("MAPPING_CONFLICT", "mapping validity lower bound is required")
    existing = _current_mapping(
        session,
        provider_id=provider_id,
        season_id=season_id,
        product=product,
        namespace=namespace,
        entity_type=entity_type,
        external_id=external_id,
        valid_at=require_utc(valid_lower),
        system_at=resolution_cutoff,
    )
    if existing is not None:
        if existing["canonical_entity_id"] != canonical_id:
            raise IngestionError("MAPPING_CONFLICT", "provider identifier maps ambiguously")
        return _uuid(existing["external_identifier_id"])
    mapped_at = require_utc(system_known_at)
    synthetic = evidence_class == "TEST_ONLY"
    return _uuid(
        session.execute(
            insert(external_identifier)
            .values(
                canonical_entity_id=canonical_id,
                provider_id=provider_id,
                provider_product=product,
                identifier_namespace=namespace,
                entity_type=entity_type,
                external_id_text=external_id,
                valid_during=valid_during,
                system_during=Range(mapped_at, None, bounds="[)"),
                mapping_status="AUTO_MATCHED" if synthetic else "HUMAN_VERIFIED",
                mapping_method="EXACT_EXTERNAL_ID" if synthetic else "PROVIDER_MAPPING",
                match_probability=Decimal("1"),
                evidence_source_snapshot_id=snapshot_id,
                reviewed_by=reviewer,
                reviewed_at=mapped_at,
                first_seen_at=mapped_at,
                last_seen_at=mapped_at,
                is_provider_primary=True,
                season_id=season_id,
            )
            .returning(external_identifier.c.external_identifier_id)
        ).scalar_one()
    )


@dataclass(frozen=True, slots=True)
class ResolvedFixture:
    fixture_id: UUID
    season_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    fixture_mapping_id: UUID
    home_team_mapping_id: UUID
    away_team_mapping_id: UUID
    fixture_observation_id: UUID
    event_mapping_id: UUID
    kickoff_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedOperator:
    operator_id: UUID
    operator_mapping_id: UUID


@dataclass(frozen=True, slots=True)
class PreparedMappingDependency:
    representation_id: UUID
    mapping_plan_sha256: str
    fixture_lookup_mapping_id: UUID
    home_team_mapping_id: UUID
    away_team_mapping_id: UUID
    fixture_observation_id: UUID
    expected_commence_time: datetime
    dependency_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedBook:
    fixture_id: UUID
    market_id: UUID
    operator_id: UUID
    representation_id: UUID
    mapping_dependency: PreparedMappingDependency
    selections: tuple[tuple[MarketOutcome, UUID], ...]
    observed_at: datetime
    state: MarketState
    missing: tuple[str, ...]
    prices: tuple[tuple[MarketOutcome, Decimal], ...]
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedOddsPublication:
    source_semantic_sha256: str
    books: tuple[PreparedBook, ...]


@dataclass(frozen=True, slots=True)
class PublishCounts:
    operator_books_seen: int = 0
    complete_books_created: int = 0
    incomplete_books_created: int = 0
    observations_created: int = 0
    observations_reused: int = 0


def create_publication_batch(
    session: Session,
    *,
    snapshot_id: UUID,
    activation_event_id: UUID,
    mapping_cutoff: datetime,
    mapping_plan: OddsMappingPlan,
) -> UUID:
    """Create the immutable activation batch in the canonical publication transaction."""

    created = session.execute(
        insert(odds_publication_batch)
        .values(
            source_snapshot_id=snapshot_id,
            activation_event_id=activation_event_id,
            mapping_cutoff=require_utc(mapping_cutoff),
            mapping_plan_id=mapping_plan.plan_id,
            mapping_plan_sha256=mapping_plan.sha256,
            mapping_plan_approved_at=mapping_plan.approved_at,
            mapping_evidence_class=mapping_plan.evidence_class,
            mapping_reviewer=mapping_plan.reviewer,
            mapping_status=mapping_plan.status,
        )
        .returning(odds_publication_batch.c.publication_batch_id)
    ).scalar_one()
    return _uuid(created)


def attest_publication_batch(
    session: Session, *, publication_batch_id: UUID, usable_at: datetime
) -> datetime:
    """Insert one immutable post-commit attestation, safely converging concurrent repairs."""

    sampled = require_utc(usable_at)
    created = session.execute(
        postgresql_insert(odds_publication_attestation)
        .values(publication_batch_id=publication_batch_id, usable_at=sampled)
        .on_conflict_do_nothing(
            index_elements=[odds_publication_attestation.c.publication_batch_id]
        )
        .returning(odds_publication_attestation.c.usable_at)
    ).scalar_one_or_none()
    if created is not None:
        return require_utc(created)
    existing = session.scalar(
        select(odds_publication_attestation.c.usable_at).where(
            odds_publication_attestation.c.publication_batch_id == publication_batch_id
        )
    )
    if existing is None:
        raise IngestionError("DATABASE_RETRYABLE", "publication attestation raced", retryable=True)
    return require_utc(existing)


class OddsPersistence:
    def __init__(
        self,
        session: Session,
        *,
        snapshot_id: UUID,
        rights_profile_record_id: UUID,
        captured_at: datetime,
        mapping_cutoff: datetime,
        mapping_plan: OddsMappingPlan,
    ) -> None:
        self.session = session
        self.snapshot_id = snapshot_id
        self.rights_profile_record_id = rights_profile_record_id
        self.captured_at = require_utc(captured_at)
        self.mapping_cutoff = require_utc(mapping_cutoff)
        self.mapping_plan = mapping_plan
        if self.mapping_plan.approved_at > self.mapping_cutoff:
            raise IngestionError("MAPPING_CONFLICT", "mapping plan was not approved at cutoff")
        self.odds_provider_id = ensure_odds_provider(session)

    def _season_context(self) -> tuple[UUID, UUID, Range[datetime]]:
        row = (
            self.session.execute(
                select(
                    season.c.season_id,
                    competition.c.competition_id,
                    season.c.starts_on,
                    season.c.ends_on,
                )
                .join(competition, competition.c.competition_id == season.c.competition_id)
                .where(
                    competition.c.competition_key == self.mapping_plan.competition_key,
                    season.c.season_code == self.mapping_plan.season_code,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise IngestionError("MAPPING_CONFLICT", "canonical season context is unavailable")
        return (
            _uuid(row["season_id"]),
            _uuid(row["competition_id"]),
            _season_valid_range(row["starts_on"], row["ends_on"]),
        )

    def resolve_fixture(self, event: OddsEvent) -> ResolvedFixture:
        mapping = self.mapping_plan.fixture(event.id)
        season_id, competition_id, season_range = self._season_context()
        if mapping.canonical_fixture_lookup.season_code != self.mapping_plan.season_code:
            raise IngestionError("MAPPING_CONFLICT", "fixture lookup season conflicts")
        candidate_rows = list(
            self.session.execute(
                select(
                    external_identifier.c.canonical_entity_id,
                    external_identifier.c.external_identifier_id,
                    external_identifier.c.evidence_source_snapshot_id,
                    external_identifier.c.provider_id,
                    data_provider.c.provider_key,
                )
                .join(
                    data_provider,
                    data_provider.c.provider_id == external_identifier.c.provider_id,
                )
                .where(
                    data_provider.c.provider_key == mapping.canonical_fixture_lookup.provider,
                    external_identifier.c.season_id == season_id,
                    external_identifier.c.identifier_namespace
                    == mapping.canonical_fixture_lookup.namespace,
                    external_identifier.c.entity_type == "FIXTURE",
                    external_identifier.c.external_id_text
                    == mapping.canonical_fixture_lookup.external_id,
                    external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                    external_identifier.c.valid_during.op("@>")(mapping.expected_commence_time),
                    external_identifier.c.system_during.op("@>")(self.mapping_cutoff),
                )
            ).mappings()
        )
        fixture_ids = {_uuid(row["canonical_entity_id"]) for row in candidate_rows}
        if len(fixture_ids) != 1:
            raise IngestionError("MAPPING_CONFLICT", "fixture mapping is unresolved at cutoff")
        fixture_id = fixture_ids.pop()
        fixture_lookup_mapping_ids = {
            _uuid(row["external_identifier_id"]) for row in candidate_rows
        }
        fixture_lookup_provider_id: UUID | None = None
        if self.mapping_plan.evidence_class == "TEST_ONLY":
            fixture_provider_ids = {
                _uuid(row["provider_id"])
                for row in candidate_rows
                if row["provider_key"] == mapping.canonical_fixture_lookup.provider
            }
            if len(fixture_provider_ids) != 1:
                raise IngestionError("MAPPING_CONFLICT", "synthetic fixture provider is ambiguous")
            fixture_lookup_provider_id = fixture_provider_ids.pop()
            fixture_mapping_id = _ensure_external_mapping(
                self.session,
                provider_id=fixture_lookup_provider_id,
                season_id=season_id,
                namespace=mapping.canonical_fixture_lookup.namespace,
                entity_type="FIXTURE",
                external_id=mapping.canonical_fixture_lookup.external_id,
                canonical_id=fixture_id,
                product="nrm006-test-fixtures",
                snapshot_id=self.snapshot_id,
                valid_during=season_range,
                resolution_cutoff=self.mapping_cutoff,
                system_known_at=self.mapping_plan.approved_at,
                evidence_class=self.mapping_plan.evidence_class,
                reviewer=self.mapping_plan.reviewer,
            )
        else:
            if len(fixture_lookup_mapping_ids) != 1:
                raise IngestionError("MAPPING_CONFLICT", "fixture mapping lineage is ambiguous")
            fixture_mapping_id = fixture_lookup_mapping_ids.pop()
        fixture_row = (
            self.session.execute(
                select(fixture).where(
                    fixture.c.fixture_id == fixture_id,
                    fixture.c.season_id == season_id,
                    fixture.c.competition_id == competition_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if fixture_row is None:
            raise IngestionError("MAPPING_CONFLICT", "mapped fixture context conflicts")
        home_team_id = _uuid(fixture_row["home_team_id"])
        away_team_id = _uuid(fixture_row["away_team_id"])
        home_team_mapping_ids = self._validate_team_mapping(
            season_id,
            home_team_id,
            mapping.expected_home_team_external_id,
            event.home_team,
            lookup_provider=mapping.canonical_fixture_lookup.provider,
            domain_instant=mapping.expected_commence_time,
        )
        away_team_mapping_ids = self._validate_team_mapping(
            season_id,
            away_team_id,
            mapping.expected_away_team_external_id,
            event.away_team,
            lookup_provider=mapping.canonical_fixture_lookup.provider,
            domain_instant=mapping.expected_commence_time,
        )
        schedule = (
            self.session.execute(
                select(
                    fixture_observation.c.fixture_observation_id,
                    fixture_observation.c.kickoff_at,
                )
                .where(
                    fixture_observation.c.fixture_id == fixture_id,
                    fixture_observation.c.usable_at <= self.mapping_cutoff,
                )
                .order_by(
                    fixture_observation.c.usable_at.desc(),
                    fixture_observation.c.fixture_observation_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if (
            schedule is None
            or schedule["kickoff_at"] is None
            or require_utc(schedule["kickoff_at"]) != mapping.expected_commence_time
            or event.commence_time != mapping.expected_commence_time
            or self.captured_at >= require_utc(schedule["kickoff_at"])
        ):
            raise IngestionError("MAPPING_CONFLICT", "fixture commence time contradicts mapping")
        fixture_observation_id = _uuid(schedule["fixture_observation_id"])
        if fixture_lookup_provider_id is not None:
            anchored_team_mapping_ids: list[UUID] = []
            for team_id, external_id in (
                (home_team_id, mapping.expected_home_team_external_id),
                (away_team_id, mapping.expected_away_team_external_id),
            ):
                anchored_team_mapping_ids.append(
                    _ensure_external_mapping(
                        self.session,
                        provider_id=fixture_lookup_provider_id,
                        season_id=season_id,
                        namespace="fpl.team.id",
                        entity_type="TEAM",
                        external_id=external_id,
                        canonical_id=team_id,
                        product="nrm006-test-fixtures",
                        snapshot_id=self.snapshot_id,
                        valid_during=season_range,
                        resolution_cutoff=self.mapping_cutoff,
                        system_known_at=self.mapping_plan.approved_at,
                        evidence_class=self.mapping_plan.evidence_class,
                        reviewer=self.mapping_plan.reviewer,
                    )
                )
            home_team_mapping_id, away_team_mapping_id = anchored_team_mapping_ids
        else:
            if len(home_team_mapping_ids) != 1 or len(away_team_mapping_ids) != 1:
                raise IngestionError("MAPPING_CONFLICT", "team mapping lineage is ambiguous")
            home_team_mapping_id = home_team_mapping_ids[0]
            away_team_mapping_id = away_team_mapping_ids[0]
        event_mapping_id = _ensure_external_mapping(
            self.session,
            provider_id=self.odds_provider_id,
            season_id=season_id,
            namespace="the_odds_api.event.id",
            entity_type="FIXTURE",
            external_id=event.id,
            canonical_id=fixture_id,
            product="soccer_epl/odds",
            snapshot_id=self.snapshot_id,
            valid_during=season_range,
            resolution_cutoff=self.mapping_cutoff,
            system_known_at=self.mapping_plan.approved_at,
            evidence_class=self.mapping_plan.evidence_class,
            reviewer=self.mapping_plan.reviewer,
        )
        return ResolvedFixture(
            fixture_id=fixture_id,
            season_id=season_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            fixture_mapping_id=fixture_mapping_id,
            home_team_mapping_id=home_team_mapping_id,
            away_team_mapping_id=away_team_mapping_id,
            fixture_observation_id=fixture_observation_id,
            event_mapping_id=event_mapping_id,
            kickoff_at=require_utc(schedule["kickoff_at"]),
        )

    def _validate_pre_match(
        self, bookmaker: OddsBookmaker, provider_market: OddsMarket, kickoff_at: datetime
    ) -> None:
        observed_at = provider_market.last_update or bookmaker.last_update
        if (
            bookmaker.last_update > self.captured_at
            or bookmaker.last_update >= kickoff_at
            or observed_at > self.captured_at
            or observed_at >= kickoff_at
        ):
            raise IngestionError("VALIDATION_FAILED", "in-play or future-dated odds are excluded")

    def _validate_team_mapping(
        self,
        season_id: UUID,
        expected_team_id: UUID,
        external_id: str,
        raw_label: str,
        *,
        lookup_provider: str,
        domain_instant: datetime,
    ) -> tuple[UUID, ...]:
        mapping_rows = list(
            self.session.execute(
                select(
                    external_identifier.c.external_identifier_id,
                    external_identifier.c.canonical_entity_id,
                )
                .join(
                    data_provider,
                    data_provider.c.provider_id == external_identifier.c.provider_id,
                )
                .where(
                    data_provider.c.provider_key == lookup_provider,
                    external_identifier.c.season_id == season_id,
                    external_identifier.c.identifier_namespace == "fpl.team.id",
                    external_identifier.c.external_id_text == external_id,
                    external_identifier.c.entity_type == "TEAM",
                    external_identifier.c.mapping_status.in_(("AUTO_MATCHED", "HUMAN_VERIFIED")),
                    external_identifier.c.valid_during.op("@>")(domain_instant),
                    external_identifier.c.system_during.op("@>")(self.mapping_cutoff),
                )
            ).mappings()
        )
        mapped_ids = {_uuid(row["canonical_entity_id"]) for row in mapping_rows}
        if mapped_ids != {expected_team_id}:
            raise IngestionError("MAPPING_CONFLICT", "fixture participant mapping conflicts")
        aliases = set(
            self.session.execute(
                select(entity_alias.c.normalized_nfc)
                .join(data_provider, data_provider.c.provider_id == entity_alias.c.provider_id)
                .where(
                    entity_alias.c.canonical_entity_id == expected_team_id,
                    entity_alias.c.provider_id == data_provider.c.provider_id,
                    data_provider.c.provider_key == lookup_provider,
                    entity_alias.c.is_preferred.is_(True),
                    entity_alias.c.valid_during.op("@>")(domain_instant),
                    entity_alias.c.system_during.op("@>")(self.mapping_cutoff),
                )
            ).scalars()
        )
        if unicodedata.normalize("NFC", raw_label).strip() not in aliases:
            raise IngestionError(
                "MAPPING_CONFLICT", "fixture participant label contradicts mapping"
            )
        return tuple(
            sorted({_uuid(row["external_identifier_id"]) for row in mapping_rows}, key=str)
        )

    def resolve_operator(self, bookmaker: OddsBookmaker) -> ResolvedOperator:
        mapping = self.mapping_plan.operator(bookmaker.key)
        if bookmaker.title != mapping.canonical_display_name:
            raise IngestionError("MAPPING_CONFLICT", "bookmaker title contradicts mapping evidence")
        _advisory_lock(self.session, f"operator:{mapping.canonical_operator_key}")
        existing = (
            self.session.execute(
                select(betting_operator).where(
                    betting_operator.c.operator_key == mapping.canonical_operator_key
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is None:
            operator_id = _uuid(
                self.session.execute(
                    insert(canonical_entity)
                    .values(entity_type="BETTING_OPERATOR")
                    .returning(canonical_entity.c.entity_id)
                ).scalar_one()
            )
            self.session.execute(
                insert(betting_operator).values(
                    operator_id=operator_id,
                    entity_type="BETTING_OPERATOR",
                    operator_key=mapping.canonical_operator_key,
                    display_name=mapping.canonical_display_name,
                    active=True,
                )
            )
        else:
            if existing["display_name"] != mapping.canonical_display_name:
                raise IngestionError("MAPPING_CONFLICT", "canonical operator conflicts")
            operator_id = _uuid(existing["operator_id"])
        operator_mapping_id = _ensure_external_mapping(
            self.session,
            provider_id=self.odds_provider_id,
            # Bookmaker keys identify provider-scoped operators, not seasonal
            # participants.  Keeping this scope global also lets the database
            # exclusion constraint reject a conflicting canonical operator in
            # every competition and season.
            season_id=None,
            namespace="the_odds_api.bookmaker.key",
            entity_type="BETTING_OPERATOR",
            external_id=bookmaker.key,
            canonical_id=operator_id,
            product="soccer_epl/odds",
            snapshot_id=self.snapshot_id,
            valid_during=_operator_valid_range(self.mapping_plan.approved_at),
            resolution_cutoff=self.mapping_cutoff,
            system_known_at=self.mapping_plan.approved_at,
            evidence_class=self.mapping_plan.evidence_class,
            reviewer=self.mapping_plan.reviewer,
        )
        return ResolvedOperator(operator_id, operator_mapping_id)

    def _definition_ids(self) -> tuple[UUID, UUID]:
        definition_id = self.session.execute(
            postgresql_insert(market_definition)
            .values(
                definition_key=MARKET_DEFINITION_KEY,
                definition_version=MARKET_DEFINITION_VERSION,
                scope="FIXTURE",
                period="FULL_TIME",
                outcomes=["HOME", "DRAW", "AWAY"],
                description="Exclusive full-time fixture match result offered odds.",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    market_definition.c.definition_key,
                    market_definition.c.definition_version,
                ]
            )
            .returning(market_definition.c.market_definition_id)
        ).scalar_one_or_none()
        if definition_id is None:
            definition_id = self.session.scalar(
                select(market_definition.c.market_definition_id).where(
                    market_definition.c.definition_key == MARKET_DEFINITION_KEY,
                    market_definition.c.definition_version == MARKET_DEFINITION_VERSION,
                )
            )
        settlement_id = self.session.execute(
            postgresql_insert(settlement_profile)
            .values(
                profile_key=SETTLEMENT_PROFILE_KEY,
                profile_version=SETTLEMENT_PROFILE_VERSION,
                period="FULL_TIME",
                includes_extra_time=False,
                description="Provider-reference ninety-minute soccer result; no extra time.",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    settlement_profile.c.profile_key,
                    settlement_profile.c.profile_version,
                ]
            )
            .returning(settlement_profile.c.settlement_profile_id)
        ).scalar_one_or_none()
        if settlement_id is None:
            settlement_id = self.session.scalar(
                select(settlement_profile.c.settlement_profile_id).where(
                    settlement_profile.c.profile_key == SETTLEMENT_PROFILE_KEY,
                    settlement_profile.c.profile_version == SETTLEMENT_PROFILE_VERSION,
                )
            )
        return _uuid(definition_id), _uuid(settlement_id)

    def _market_and_selections(
        self, fixture_id: UUID, operator_id: UUID
    ) -> tuple[UUID, dict[MarketOutcome, UUID]]:
        definition_id, settlement_id = self._definition_ids()
        _advisory_lock(
            self.session,
            f"operator-market:{fixture_id}:{operator_id}:{definition_id}:{settlement_id}",
        )
        market_id = self.session.scalar(
            select(operator_fixture_market.c.market_id).where(
                operator_fixture_market.c.fixture_id == fixture_id,
                operator_fixture_market.c.operator_id == operator_id,
                operator_fixture_market.c.market_definition_id == definition_id,
                operator_fixture_market.c.period == "FULL_TIME",
                operator_fixture_market.c.line.is_(None),
                operator_fixture_market.c.settlement_profile_id == settlement_id,
            )
        )
        if market_id is None:
            market_uuid = _uuid(
                self.session.execute(
                    insert(canonical_entity)
                    .values(entity_type="MARKET")
                    .returning(canonical_entity.c.entity_id)
                ).scalar_one()
            )
            self.session.execute(
                insert(operator_fixture_market).values(
                    market_id=market_uuid,
                    entity_type="MARKET",
                    fixture_id=fixture_id,
                    operator_id=operator_id,
                    market_definition_id=definition_id,
                    period="FULL_TIME",
                    line=None,
                    settlement_profile_id=settlement_id,
                )
            )
        else:
            market_uuid = _uuid(market_id)
        selections: dict[MarketOutcome, UUID] = {}
        for outcome in MarketOutcome:
            selection_id = self.session.scalar(
                select(market_selection.c.selection_id).where(
                    market_selection.c.market_id == market_uuid,
                    market_selection.c.outcome == outcome.value,
                )
            )
            if selection_id is None:
                selection_uuid = _uuid(
                    self.session.execute(
                        insert(canonical_entity)
                        .values(entity_type="SELECTION")
                        .returning(canonical_entity.c.entity_id)
                    ).scalar_one()
                )
                self.session.execute(
                    insert(market_selection).values(
                        selection_id=selection_uuid,
                        entity_type="SELECTION",
                        market_id=market_uuid,
                        outcome=outcome.value,
                    )
                )
            else:
                selection_uuid = _uuid(selection_id)
            selections[outcome] = selection_uuid
        return market_uuid, selections

    def _representation(
        self,
        *,
        fixture_mapping_id: UUID,
        operator_mapping_id: UUID,
        market_id: UUID,
    ) -> UUID:
        values = {
            "provider_id": self.odds_provider_id,
            "event_mapping_id": fixture_mapping_id,
            "operator_mapping_id": operator_mapping_id,
            "market_id": market_id,
            "provider_market_key": "h2h",
            "representation_version": CONTRACT_VERSION,
            "mapping_plan_sha256": self.mapping_plan.sha256,
        }
        created = self.session.execute(
            postgresql_insert(provider_market_representation)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    provider_market_representation.c.provider_id,
                    provider_market_representation.c.event_mapping_id,
                    provider_market_representation.c.operator_mapping_id,
                    provider_market_representation.c.provider_market_key,
                    provider_market_representation.c.representation_version,
                ]
            )
            .returning(provider_market_representation.c.provider_market_representation_id)
        ).scalar_one_or_none()
        if created is not None:
            return _uuid(created)
        existing = (
            self.session.execute(
                select(provider_market_representation).where(
                    provider_market_representation.c.provider_id == self.odds_provider_id,
                    provider_market_representation.c.event_mapping_id == fixture_mapping_id,
                    provider_market_representation.c.operator_mapping_id == operator_mapping_id,
                    provider_market_representation.c.provider_market_key == "h2h",
                    provider_market_representation.c.representation_version == CONTRACT_VERSION,
                )
            )
            .mappings()
            .one()
        )
        if any(existing[key] != value for key, value in values.items()):
            raise IngestionError("MAPPING_CONFLICT", "provider market representation conflicts")
        return _uuid(existing["provider_market_representation_id"])

    @staticmethod
    def _outcomes(
        event: OddsEvent, market: OddsMarket
    ) -> tuple[dict[MarketOutcome, Decimal], MarketState, tuple[str, ...]]:
        mapped: dict[MarketOutcome, Decimal] = {}
        for item in market.outcomes:
            if item.point is not None:
                raise IngestionError("VALIDATION_FAILED", "h2h market must not contain a line")
            outcome = (
                MarketOutcome.HOME
                if item.name == event.home_team
                else MarketOutcome.AWAY
                if item.name == event.away_team
                else MarketOutcome.DRAW
                if item.name.casefold() == "draw"
                else None
            )
            if outcome is None:
                raise IngestionError("VALIDATION_FAILED", "h2h outcome contradicts fixture")
            previous = mapped.get(outcome)
            if previous is not None and previous != item.price:
                raise IngestionError("VALIDATION_FAILED", "h2h outcome is conflicting")
            mapped[outcome] = item.price
        missing = tuple(outcome.value for outcome in MarketOutcome if outcome not in mapped)
        state = (
            MarketState.COMPLETE
            if not missing
            else MarketState.UNAVAILABLE
            if not mapped
            else MarketState.INCOMPLETE
        )
        return mapped, state, missing

    def publish(
        self, prepared: PreparedOddsPublication, *, publication_batch_id: UUID
    ) -> PublishCounts:
        """Publish only the frozen prepared projection; perform no mapping work."""

        books_seen = complete = incomplete = created_quotes = reused_quotes = 0
        for book in prepared.books:
            books_seen += 1
            dependency = book.mapping_dependency
            dependency_values = {
                "provider_market_representation_id": dependency.representation_id,
                "publication_batch_id": publication_batch_id,
                "mapping_plan_sha256": dependency.mapping_plan_sha256,
                "fixture_lookup_mapping_id": dependency.fixture_lookup_mapping_id,
                "home_team_mapping_id": dependency.home_team_mapping_id,
                "away_team_mapping_id": dependency.away_team_mapping_id,
                "fixture_observation_id": dependency.fixture_observation_id,
                "expected_commence_time": dependency.expected_commence_time,
                "dependency_sha256": dependency.dependency_sha256,
            }
            self.session.execute(
                postgresql_insert(odds_mapping_dependency)
                .values(**dependency_values)
                .on_conflict_do_nothing(
                    index_elements=[
                        odds_mapping_dependency.c.provider_market_representation_id,
                        odds_mapping_dependency.c.publication_batch_id,
                    ]
                )
            )
            stored_dependency = (
                self.session.execute(
                    select(odds_mapping_dependency).where(
                        odds_mapping_dependency.c.provider_market_representation_id
                        == dependency.representation_id,
                        odds_mapping_dependency.c.publication_batch_id == publication_batch_id,
                    )
                )
                .mappings()
                .one()
            )
            if any(stored_dependency[key] != value for key, value in dependency_values.items()):
                raise IngestionError(
                    "CANONICAL_INVARIANT", "publication mapping dependency conflicts"
                )
            created_book = self.session.execute(
                postgresql_insert(operator_market_observation)
                .values(
                    market_id=book.market_id,
                    source_snapshot_id=self.snapshot_id,
                    publication_batch_id=publication_batch_id,
                    provider_market_representation_id=book.representation_id,
                    market_state=book.state.value,
                    provider_observed_at=book.observed_at,
                    received_at=self.captured_at,
                    usable_at=None,
                    missing_outcomes=list(book.missing),
                    semantic_sha256=book.semantic_sha256,
                    source_semantic_sha256=prepared.source_semantic_sha256,
                    contract_version=CONTRACT_VERSION,
                    rights_profile_record_id=self.rights_profile_record_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        operator_market_observation.c.source_snapshot_id,
                        operator_market_observation.c.market_id,
                    ]
                )
                .returning(operator_market_observation.c.book_observation_id)
            ).scalar_one_or_none()
            if created_book is None:
                existing = (
                    self.session.execute(
                        select(operator_market_observation).where(
                            operator_market_observation.c.source_snapshot_id == self.snapshot_id,
                            operator_market_observation.c.market_id == book.market_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    existing["semantic_sha256"] != book.semantic_sha256
                    or existing["publication_batch_id"] != publication_batch_id
                ):
                    raise IngestionError("CANONICAL_INVARIANT", "source market effect conflicts")
                reused_quotes += len(book.prices)
                continue
            book_id = _uuid(created_book)
            if book.state is MarketState.COMPLETE:
                complete += 1
            elif book.state is MarketState.INCOMPLETE:
                incomplete += 1
            selections = dict(book.selections)
            for outcome, price in book.prices:
                created = self.session.execute(
                    postgresql_insert(odds_observation)
                    .values(
                        book_observation_id=book_id,
                        source_snapshot_id=self.snapshot_id,
                        publication_batch_id=publication_batch_id,
                        fixture_id=book.fixture_id,
                        market_id=book.market_id,
                        selection_id=selections[outcome],
                        operator_id=book.operator_id,
                        outcome=outcome.value,
                        decimal_odds=price,
                        observed_at=book.observed_at,
                        received_at=self.captured_at,
                        usable_at=None,
                        source_semantic_sha256=prepared.source_semantic_sha256,
                        contract_version=CONTRACT_VERSION,
                        rights_profile_record_id=self.rights_profile_record_id,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            odds_observation.c.source_snapshot_id,
                            odds_observation.c.market_id,
                            odds_observation.c.selection_id,
                        ]
                    )
                    .returning(odds_observation.c.odds_observation_id)
                ).scalar_one_or_none()
                if created is None:
                    reused_quotes += 1
                else:
                    created_quotes += 1
        return PublishCounts(
            operator_books_seen=books_seen,
            complete_books_created=complete,
            incomplete_books_created=incomplete,
            observations_created=created_quotes,
            observations_reused=reused_quotes,
        )

    @classmethod
    def publish_prepared(
        cls,
        session: Session,
        *,
        prepared: PreparedOddsPublication,
        snapshot_id: UUID,
        rights_profile_record_id: UUID,
        captured_at: datetime,
        publication_batch_id: UUID,
    ) -> PublishCounts:
        """Activation-only entry point that cannot resolve mutable mapping state."""

        persistence = cls.__new__(cls)
        persistence.session = session
        persistence.snapshot_id = snapshot_id
        persistence.rights_profile_record_id = rights_profile_record_id
        persistence.captured_at = require_utc(captured_at)
        return persistence.publish(prepared, publication_batch_id=publication_batch_id)

    def prepare(self, parsed: ParsedOddsPayload) -> PreparedOddsPublication:
        """Resolve every mutable dependency into one immutable publication projection."""

        prepared: list[PreparedBook] = []
        for event in parsed.events:
            resolved_fixture = self.resolve_fixture(event)
            for bookmaker in event.bookmakers:
                resolved_operator = self.resolve_operator(bookmaker)
                for provider_market in bookmaker.markets:
                    if provider_market.key != "h2h":
                        continue
                    self._validate_pre_match(
                        bookmaker, provider_market, resolved_fixture.kickoff_at
                    )
                    mapped, state, missing = self._outcomes(event, provider_market)
                    market_id, selections = self._market_and_selections(
                        resolved_fixture.fixture_id, resolved_operator.operator_id
                    )
                    representation_id = self._representation(
                        fixture_mapping_id=resolved_fixture.event_mapping_id,
                        operator_mapping_id=resolved_operator.operator_mapping_id,
                        market_id=market_id,
                    )
                    mapping_dependency_material = {
                        "provider_market_representation_id": str(representation_id),
                        "mapping_plan_sha256": self.mapping_plan.sha256,
                        "fixture_lookup_mapping_id": str(resolved_fixture.fixture_mapping_id),
                        "home_team_mapping_id": str(resolved_fixture.home_team_mapping_id),
                        "away_team_mapping_id": str(resolved_fixture.away_team_mapping_id),
                        "fixture_observation_id": str(resolved_fixture.fixture_observation_id),
                        "expected_commence_time": resolved_fixture.kickoff_at.isoformat(),
                    }
                    mapping_dependency = PreparedMappingDependency(
                        representation_id=representation_id,
                        mapping_plan_sha256=self.mapping_plan.sha256,
                        fixture_lookup_mapping_id=resolved_fixture.fixture_mapping_id,
                        home_team_mapping_id=resolved_fixture.home_team_mapping_id,
                        away_team_mapping_id=resolved_fixture.away_team_mapping_id,
                        fixture_observation_id=resolved_fixture.fixture_observation_id,
                        expected_commence_time=resolved_fixture.kickoff_at,
                        dependency_sha256=canonical_sha256(mapping_dependency_material),
                    )
                    observed_at = provider_market.last_update or bookmaker.last_update
                    semantic = canonical_sha256(
                        {
                            "market_id": str(market_id),
                            "market_state": state.value,
                            "missing_outcomes": missing,
                            "observed_at": observed_at.isoformat(),
                            "prices": {
                                outcome.value: canonical_decimal_text(price)
                                for outcome, price in sorted(
                                    mapped.items(), key=lambda item: item[0].value
                                )
                            },
                        }
                    )
                    prepared.append(
                        PreparedBook(
                            fixture_id=resolved_fixture.fixture_id,
                            market_id=market_id,
                            operator_id=resolved_operator.operator_id,
                            representation_id=representation_id,
                            mapping_dependency=mapping_dependency,
                            selections=tuple(
                                (outcome, selections[outcome]) for outcome in MarketOutcome
                            ),
                            observed_at=observed_at,
                            state=state,
                            missing=missing,
                            prices=tuple(
                                (outcome, mapped[outcome])
                                for outcome in MarketOutcome
                                if outcome in mapped
                            ),
                            semantic_sha256=semantic,
                        )
                    )
        return PreparedOddsPublication(
            source_semantic_sha256=parsed.semantic_sha256,
            books=tuple(prepared),
        )
