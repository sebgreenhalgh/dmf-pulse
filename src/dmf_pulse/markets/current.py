"""Private transient current H2H and totals market constraints.

The service consumes an already accepted ``CurrentUnifiedStateBundle``.  It performs no
acquisition, network activity, persistence, database write, score projection, or player
modelling.  Canonical fixture/provider/operator UUIDs arrive through a separately hash-bound
DAT-003 read-only view; adapter-local UUIDv5 values identify only transient observations and are
never presented as canonical entities.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Decimal,
    DecimalException,
    InvalidOperation,
    localcontext,
)
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import (
    betting_operator,
    competition,
    data_provider,
    external_identifier,
    season,
)
from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    PROBABILITY_SCALE,
    probability,
)
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
    cap_market_family_weights,
    constraints_from_market_consensus,
)
from dmf_pulse.football_events.service import ScoreBaselinePolicy, load_score_baseline_policy
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateBundle,
    current_unified_state_semantic_sha256,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfile, RightsProfileStatus
from dmf_pulse.ingestion.odds.config import load_rights_profiles, rights_config_sha256
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsBookmaker,
    CurrentOddsEvent,
    CurrentOddsMarket,
    CurrentOddsTotalsMarket,
)
from dmf_pulse.ingestion.odds.identity import ResolvedCurrentFixture
from dmf_pulse.markets.consensus import evaluate_market_consensus
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketConsensus,
    MarketOutcome,
    MarketState,
)
from dmf_pulse.markets.normalisation import (
    MarketNormalisationError,
    raw_implied_probability,
)
from dmf_pulse.markets.policy import (
    CONFIDENCE_GATE_POLICY_SHA256,
    CONFIDENCE_GRADES,
    MarketNormalisationPolicy,
    confidence_gate,
    load_market_normalisation_policy,
    require_authenticated_policy,
)

CURRENT_MARKET_CONTRACT_VERSION: Literal["current-market-constraints-v1"] = (
    "current-market-constraints-v1"
)
CURRENT_MARKET_IDENTITY_VIEW_VERSION: Literal["current-market-identity-view-v1"] = (
    "current-market-identity-view-v1"
)
_TRANSIENT_NAMESPACE = UUID("58c3d432-1488-5c53-a4aa-da5753f7a08c")
_ACCEPTED_ODDS_RIGHTS_PROFILE_ID = "the_odds_api_private_analytics_v1"
_ACCEPTED_ODDS_RIGHTS_PROFILE_VERSION = "1.0.0"
_ACCEPTED_ODDS_PROVIDER_KEY = "the_odds_api"
_ONE = Decimal(1)
_TWO = Decimal(2)
_ERROR_MESSAGES = {
    "CANONICAL_IDENTITY_UNAVAILABLE": "required canonical market identity is unavailable",
    "MARKET_POLICY_INVALID": "accepted market policy validation failed",
    "RIGHTS_BLOCKED": "current market analytical rights are not satisfied",
    "RUNTIME_BOUNDARY_BLOCKED": "current market runtime boundary is not transient",
    "SOURCE_INVALID": "current market source failed structural verification",
    "SOURCE_MISMATCH": "current market request differs from its exact source family",
    "VERIFICATION_FAILED": "current market result failed exact-source verification",
}
_LIMITATIONS = (
    "CURRENT_AVAILABILITY_001A_DATA_BLOCKED",
    "FULL_GCS008_NOT_EXECUTED",
    "NO_ACCEPTED_CURRENT_SCORE_PRIOR",
    "NO_FPL_POINTS_PROJECTIONS",
    "NO_LIVE_STAGE7_MINUTES",
    "NO_OPTIMISATION",
    "NO_PLAYER_EVENT_ALLOCATION",
    "TOTALS_FULL_TIME_HALF_GOAL_LINES_ONLY",
    "TRANSIENT_CURRENT_MARKET_EVIDENCE_ONLY",
)


class CurrentMarketConstraintError(ValueError):
    """Disclosure-safe fail-closed error at the current-market boundary."""

    def __init__(self, code: str) -> None:
        message = _ERROR_MESSAGES.get(code, "current market processing failed")
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error_object(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}

    def __repr__(self) -> str:
        return f"CurrentMarketConstraintError(code={self.code!r})"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class CurrentMarketReadiness(StrEnum):
    MARKET_READY = "MARKET_READY"
    H2H_ONLY_DEGRADED = "H2H_ONLY_DEGRADED"
    BLOCKED = "BLOCKED"


class CurrentMarketCanonicalFixture(_FrozenModel):
    official_fpl_fixture_id: int = Field(gt=0)
    official_fpl_fixture_lookup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_event_id: str = Field(min_length=1, max_length=500)
    provider_event_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_fixture_id: UUID
    official_fpl_external_mapping_id: UUID
    odds_event_external_mapping_id: UUID
    fixture_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentMarketCanonicalOperator(_FrozenModel):
    bookmaker_key: str = Field(min_length=1, max_length=500)
    bookmaker_title: str = Field(min_length=1, max_length=500)
    canonical_operator_id: UUID
    canonical_operator_key: str = Field(min_length=1, max_length=120)
    external_mapping_id: UUID
    target_occurrence_times_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentMarketCanonicalIdentityView(_FrozenModel):
    """Exact read-only canonical identities required by one current source family."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_MARKET_CANONICAL_IDENTITY_VIEW"] = (
        "CURRENT_MARKET_CANONICAL_IDENTITY_VIEW"
    )
    contract_version: Literal["current-market-identity-view-v1"] = (
        CURRENT_MARKET_IDENTITY_VIEW_VERSION
    )
    authority: Literal["DAT_003_READ_ONLY", "OPERATOR_INITIATED_DETERMINISTIC", "TEST_ONLY"]
    resolved_at: datetime
    resolution_cutoff: datetime
    database_read_performed: bool
    database_write_performed: Literal[False] = False
    provider_id: UUID
    provider_key: Literal["the_odds_api"] = "the_odds_api"
    provider_rights_profile_key: Literal["the_odds_api_private_analytics_v1"] = (
        "the_odds_api_private_analytics_v1"
    )
    fixtures: tuple[CurrentMarketCanonicalFixture, ...] = Field(min_length=1)
    operators: tuple[CurrentMarketCanonicalOperator, ...] = Field(min_length=1)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        if self.resolved_at > self.resolution_cutoff:
            raise ValueError("canonical identity resolution is post-cutoff")
        if self.database_write_performed:
            raise ValueError("canonical identity view cannot perform writes")
        if self.database_read_performed != (self.authority == "DAT_003_READ_ONLY"):
            raise ValueError("canonical identity authority contradicts database-read evidence")
        fixture_keys = [item.official_fpl_fixture_id for item in self.fixtures]
        event_keys = [item.provider_event_id for item in self.fixtures]
        if len(fixture_keys) != len(set(fixture_keys)) or len(event_keys) != len(set(event_keys)):
            raise ValueError("canonical fixture identity is duplicated")
        bookmaker_keys = [item.bookmaker_key for item in self.operators]
        if len(bookmaker_keys) != len(set(bookmaker_keys)):
            raise ValueError("canonical operator mapping is duplicated")
        if self.semantic_sha256 != current_market_identity_view_sha256(self):
            raise ValueError("canonical identity-view hash is inconsistent")
        return self

    def fixture(self, official_fpl_fixture_id: int) -> CurrentMarketCanonicalFixture:
        matches = [
            item
            for item in self.fixtures
            if item.official_fpl_fixture_id == official_fpl_fixture_id
        ]
        if len(matches) != 1:
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
        return matches[0]

    def operator(self, bookmaker_key: str) -> CurrentMarketCanonicalOperator:
        matches = [item for item in self.operators if item.bookmaker_key == bookmaker_key]
        if len(matches) != 1:
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
        return matches[0]


def current_market_identity_view_sha256(value: CurrentMarketCanonicalIdentityView) -> str:
    fixtures = sorted(
        (item.model_dump(mode="json") for item in value.fixtures),
        key=lambda item: (item["official_fpl_fixture_id"], item["provider_event_id"]),
    )
    operators = sorted(
        (item.model_dump(mode="json") for item in value.operators),
        key=lambda item: item["bookmaker_key"],
    )
    return canonical_sha256(
        {
            "authority": value.authority,
            "contract": value.contract,
            "contract_version": value.contract_version,
            "database_read_performed": value.database_read_performed,
            "database_write_performed": value.database_write_performed,
            "fixtures": fixtures,
            "operators": operators,
            "provider_id": str(value.provider_id),
            "provider_key": value.provider_key,
            "provider_rights_profile_key": value.provider_rights_profile_key,
            "resolution_cutoff": value.resolution_cutoff.isoformat(),
            "resolved_at": value.resolved_at.isoformat(),
            "schema_version": value.schema_version,
        }
    )


def _operator_occurrence_times(
    source: CurrentUnifiedStateBundle,
) -> dict[str, tuple[datetime, ...]]:
    target_event_ids = {
        mapping.provider_event_id for mapping in source.identity_map.fixture_mappings
    }
    occurrences: dict[str, set[datetime]] = {}
    for event in source.odds_input.events:
        if event.provider_event_id not in target_event_ids:
            continue
        for bookmaker in event.bookmakers:
            occurrences.setdefault(bookmaker.bookmaker_key, set()).add(event.commence_time)
    return {key: tuple(sorted(values)) for key, values in sorted(occurrences.items())}


def _operator_occurrence_times_sha256(
    bookmaker_key: str,
    occurrence_times: tuple[datetime, ...],
) -> str:
    return canonical_sha256(
        {
            "bookmaker_key": bookmaker_key,
            "contract_version": "current-market-operator-applicability-v1",
            "target_occurrence_times": [value.isoformat() for value in occurrence_times],
        }
    )


def build_transient_current_market_identity_view(
    source: CurrentUnifiedStateBundle,
    *,
    resolved_at: datetime,
) -> CurrentMarketCanonicalIdentityView:
    """Build run-local deterministic identities without claiming DAT-003 entities."""

    resolved = require_utc(resolved_at)
    if resolved > source.information_cutoff:
        raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
    occurrence_times = _operator_occurrence_times(source)
    target_event_ids = {item.provider_event_id for item in source.identity_map.fixture_mappings}
    events = {
        item.provider_event_id: item
        for item in source.odds_input.events
        if item.provider_event_id in target_event_ids
    }
    if set(events) != target_event_ids:
        raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
    fixtures = tuple(
        CurrentMarketCanonicalFixture(
            official_fpl_fixture_id=item.official_fpl_fixture_id,
            official_fpl_fixture_lookup_sha256=(
                item.official_fpl_fixture_identity.canonical_lookup_sha256
            ),
            provider_event_id=item.provider_event_id,
            provider_event_identity_sha256=item.provider_event_identity_sha256,
            canonical_fixture_id=uuid5(
                _TRANSIENT_NAMESPACE,
                "one-command:fixture:" + item.official_fpl_fixture_identity.canonical_lookup_sha256,
            ),
            official_fpl_external_mapping_id=uuid5(
                _TRANSIENT_NAMESPACE,
                "one-command:fpl-fixture-map:"
                + item.official_fpl_fixture_identity.canonical_lookup_sha256,
            ),
            odds_event_external_mapping_id=uuid5(
                _TRANSIENT_NAMESPACE,
                "one-command:odds-event-map:" + item.provider_event_identity_sha256,
            ),
            fixture_binding_sha256=item.fixture_binding_sha256,
        )
        for item in sorted(
            source.identity_map.fixture_mappings,
            key=lambda value: value.official_fpl_fixture_id,
        )
    )
    bookmaker_by_key = {
        bookmaker.bookmaker_key: bookmaker
        for event_id, event in events.items()
        if event_id in target_event_ids
        for bookmaker in event.bookmakers
    }
    if set(bookmaker_by_key) != set(occurrence_times):
        raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
    operators = tuple(
        CurrentMarketCanonicalOperator(
            bookmaker_key=key,
            bookmaker_title=bookmaker_by_key[key].bookmaker_title,
            canonical_operator_id=uuid5(_TRANSIENT_NAMESPACE, "one-command:operator:" + key),
            canonical_operator_key="transient:" + key,
            external_mapping_id=uuid5(_TRANSIENT_NAMESPACE, "one-command:operator-map:" + key),
            target_occurrence_times_sha256=_operator_occurrence_times_sha256(
                key, occurrence_times[key]
            ),
        )
        for key in sorted(bookmaker_by_key)
    )
    provider_id = uuid5(
        _TRANSIENT_NAMESPACE,
        "one-command:provider:the_odds_api:the_odds_api_private_analytics_v1",
    )
    provisional = CurrentMarketCanonicalIdentityView.model_construct(
        authority="OPERATOR_INITIATED_DETERMINISTIC",
        resolved_at=resolved,
        resolution_cutoff=source.information_cutoff,
        database_read_performed=False,
        provider_id=provider_id,
        fixtures=fixtures,
        operators=operators,
        semantic_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["semantic_sha256"] = current_market_identity_view_sha256(provisional)
    return CurrentMarketCanonicalIdentityView.model_validate(payload)


class CurrentMarketConstraintRequest(_FrozenModel):
    contract_version: Literal["current-market-constraints-v1"] = CURRENT_MARKET_CONTRACT_VERSION
    target_gameweek: int = Field(gt=0)
    information_cutoff: datetime
    current_unified_state_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_full_representation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_odds_identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_quality_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_temporal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_rights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence_gate_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    constraint_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentMarketConstraintLineage(_FrozenModel):
    current_unified_state_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_input_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_full_representation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_odds_identity_map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_odds_identity_map_source_lineage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_quality_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_temporal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    odds_rights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_identity_view_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence_gate_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    constraint_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentMarketRightsBoundary(_FrozenModel):
    classification: Literal["PRIVATE"] = "PRIVATE"
    private_internal_use: Literal["ALLOW"] = "ALLOW"
    transient_processing: Literal["ALLOW"] = "ALLOW"
    persistent_storage: Literal["DENY"] = "DENY"
    derived_storage: Literal["DENY"] = "DENY"
    raw_storage: Literal["DENY"] = "DENY"
    cache: Literal["DENY"] = "DENY"
    backup: Literal["DENY"] = "DENY"
    public_display: Literal["DENY"] = "DENY"
    redistribution: Literal["DENY"] = "DENY"


class CurrentMarketRuntimeBoundary(_FrozenModel):
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_read_performed: bool
    database_write_performed: Literal[False] = False
    network_called: Literal[False] = False


class CurrentMarketExclusionCount(_FrozenModel):
    reason: str = Field(min_length=1, max_length=120)
    count: int = Field(gt=0)


class CurrentTotalsOperatorMarket(_FrozenModel):
    provider_id: UUID
    operator_id: UUID
    line: Decimal
    observed_at: datetime
    usable_at: datetime
    timestamp_source: Literal["MARKET", "BOOKMAKER"]
    primary_method: Literal["POWER", "PROPORTIONAL"]
    fallback_used: bool
    over_probability: Decimal
    under_probability: Decimal
    proportional_over_probability: Decimal
    proportional_under_probability: Decimal
    raw_booksum: Decimal
    overround: Decimal
    power_exponent: Decimal | None
    input_signature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "over_probability",
        "under_probability",
        "proportional_over_probability",
        "proportional_under_probability",
        mode="before",
    )
    @classmethod
    def validate_probability(cls, value: object) -> Decimal:
        return probability(value, label="totals probability")

    @model_validator(mode="after")
    def validate_operator_market(self) -> Self:
        if not self.line.is_finite() or self.line < 0 or self.line % 1 != Decimal("0.5"):
            raise ValueError("totals line must be a nonnegative half-goal line")
        if self.over_probability + self.under_probability != _ONE:
            raise ValueError("totals market probabilities must sum to one")
        if self.proportional_over_probability + self.proportional_under_probability != _ONE:
            raise ValueError("totals proportional probabilities must sum to one")
        if self.observed_at > self.usable_at:
            raise ValueError("totals operator timestamps are inconsistent")
        if self.fallback_used != (self.primary_method == "PROPORTIONAL"):
            raise ValueError("totals fallback status is inconsistent")
        return self


class CurrentTotalsConsensusOutcome(_FrozenModel):
    outcome: Literal["OVER", "UNDER"]
    consensus_probability: Decimal
    lower_bound: Decimal
    upper_bound: Decimal

    @field_validator("consensus_probability", "lower_bound", "upper_bound", mode="before")
    @classmethod
    def validate_probability(cls, value: object) -> Decimal:
        return probability(value, label="totals consensus probability")

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if not self.lower_bound <= self.consensus_probability <= self.upper_bound:
            raise ValueError("totals consensus probability is outside its bounds")
        return self


class CurrentTotalsConsensus(_FrozenModel):
    fixture_id: UUID
    as_of: datetime
    mapping_cutoff: datetime
    market_definition: Literal["FULL_TIME_TOTALS_HALF_GOAL"] = "FULL_TIME_TOTALS_HALF_GOAL"
    line: Decimal
    provider_count: int = Field(ge=1)
    operator_count: int = Field(ge=1)
    eligible_operator_count: int = Field(ge=1)
    operator_markets: tuple[CurrentTotalsOperatorMarket, ...] = Field(min_length=1)
    outcomes: tuple[CurrentTotalsConsensusOutcome, CurrentTotalsConsensusOutcome]
    operator_disagreement: Decimal
    method_disagreement: Decimal
    market_disagreement: Decimal
    minimum_age_seconds: int = Field(ge=0)
    maximum_age_seconds: int = Field(ge=0)
    confidence_grade: Literal["A", "B", "C", "D"]
    policy_id: Literal["market-normalisation-v1"] = "market-normalisation-v1"
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence_gate_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_signature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "operator_disagreement", "method_disagreement", "market_disagreement", mode="before"
    )
    @classmethod
    def validate_probability(cls, value: object) -> Decimal:
        return probability(value, label="totals disagreement")

    @model_validator(mode="after")
    def validate_consensus(self) -> Self:
        if not self.line.is_finite() or self.line < 0 or self.line % 1 != Decimal("0.5"):
            raise ValueError("totals consensus line is unsupported")
        if tuple(item.outcome for item in self.outcomes) != ("OVER", "UNDER"):
            raise ValueError("totals consensus outcome order is invalid")
        if sum((item.consensus_probability for item in self.outcomes), Decimal(0)) != _ONE:
            raise ValueError("totals consensus probabilities must sum to one")
        if self.operator_count != len({item.operator_id for item in self.operator_markets}):
            raise ValueError("totals operator count is inconsistent")
        if self.provider_count != len({item.provider_id for item in self.operator_markets}):
            raise ValueError("totals provider count is inconsistent")
        if self.eligible_operator_count != len(self.operator_markets):
            raise ValueError("totals eligible count is inconsistent")
        if self.market_disagreement != max(self.operator_disagreement, self.method_disagreement):
            raise ValueError("totals disagreement is inconsistent")
        if self.minimum_age_seconds > self.maximum_age_seconds:
            raise ValueError("totals freshness range is reversed")
        if self.mapping_cutoff > self.as_of:
            raise ValueError("totals mapping cutoff is post-cutoff")
        if self.result_sha256 != current_totals_consensus_sha256(self):
            raise ValueError("totals consensus hash is inconsistent")
        return self


def current_totals_consensus_sha256(value: CurrentTotalsConsensus) -> str:
    return canonical_sha256(
        {
            "as_of": value.as_of.isoformat(),
            "confidence_gate_policy_sha256": value.confidence_gate_policy_sha256,
            "confidence_grade": value.confidence_grade,
            "eligible_operator_count": value.eligible_operator_count,
            "fixture_id": str(value.fixture_id),
            "input_signature_sha256": value.input_signature_sha256,
            "line": format(value.line, "f"),
            "mapping_cutoff": value.mapping_cutoff.isoformat(),
            "market_definition": value.market_definition,
            "market_disagreement": format(value.market_disagreement, "f"),
            "maximum_age_seconds": value.maximum_age_seconds,
            "method_disagreement": format(value.method_disagreement, "f"),
            "minimum_age_seconds": value.minimum_age_seconds,
            "operator_count": value.operator_count,
            "operator_disagreement": format(value.operator_disagreement, "f"),
            "operator_result_sha256": [item.result_sha256 for item in value.operator_markets],
            "outcomes": [item.model_dump(mode="json") for item in value.outcomes],
            "policy_id": value.policy_id,
            "policy_sha256": value.policy_sha256,
            "provider_count": value.provider_count,
        }
    )


class CurrentFixtureMarketConstraints(_FrozenModel):
    canonical_fixture_id: UUID
    safe_target_fixture_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    readiness: CurrentMarketReadiness
    h2h_consensus: MarketConsensus | None
    totals_consensuses: tuple[CurrentTotalsConsensus, ...]
    constraint_set: MarketConstraintSet
    exclusion_counts: tuple[CurrentMarketExclusionCount, ...]
    warnings: tuple[str, ...]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_fixture_result(self) -> Self:
        if self.constraint_set.constraints and any(
            item.usable_at > self.constraint_set.as_of for item in self.constraint_set.constraints
        ):
            raise ValueError("fixture contains post-cutoff market constraints")
        h2h = [
            item
            for item in self.constraint_set.constraints
            if item.family is MarketFamily.ONE_X_TWO
        ]
        totals = [
            item for item in self.constraint_set.constraints if item.family is MarketFamily.TOTALS
        ]
        if self.readiness is CurrentMarketReadiness.MARKET_READY:
            if self.h2h_consensus is None or not self.totals_consensuses or len(h2h) != 3:
                raise ValueError("MARKET_READY evidence is incomplete")
        elif self.readiness is CurrentMarketReadiness.H2H_ONLY_DEGRADED:
            if self.h2h_consensus is None or self.totals_consensuses or len(h2h) != 3 or totals:
                raise ValueError("H2H-only readiness is inconsistent")
        elif self.h2h_consensus is not None or self.constraint_set.constraints:
            raise ValueError("blocked fixture cannot publish usable constraints")
        if (
            len(totals) != 2 * len(self.totals_consensuses)
            and self.readiness is not CurrentMarketReadiness.BLOCKED
        ):
            raise ValueError("totals constraint count is inconsistent")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("fixture warnings must be unique and sorted")
        if self.exclusion_counts != tuple(
            sorted(self.exclusion_counts, key=lambda item: item.reason)
        ):
            raise ValueError("fixture exclusion counts must be sorted")
        if self.semantic_sha256 != current_fixture_market_constraints_sha256(self):
            raise ValueError("fixture market semantic hash is inconsistent")
        return self


def current_fixture_market_constraints_sha256(value: CurrentFixtureMarketConstraints) -> str:
    return canonical_sha256(
        {
            "canonical_fixture_id": str(value.canonical_fixture_id),
            "constraint_set": value.constraint_set.public_dict(),
            "exclusion_counts": [item.model_dump(mode="json") for item in value.exclusion_counts],
            "h2h_consensus_sha256": (
                value.h2h_consensus.result_sha256 if value.h2h_consensus is not None else None
            ),
            "readiness": value.readiness.value,
            "safe_target_fixture_identity_sha256": value.safe_target_fixture_identity_sha256,
            "totals_consensus_sha256": [item.result_sha256 for item in value.totals_consensuses],
            "warnings": list(value.warnings),
        }
    )


class CurrentMarketConfidenceCount(_FrozenModel):
    confidence_grade: Literal["A", "B", "C", "D"]
    count: int = Field(gt=0)


class CurrentMarketConstraintSummary(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_MARKET_CONSTRAINT_SUMMARY"] = "CURRENT_MARKET_CONSTRAINT_SUMMARY"
    target_gameweek: int = Field(gt=0)
    information_cutoff: datetime
    fixture_count: int = Field(gt=0)
    market_ready_count: int = Field(ge=0)
    h2h_only_degraded_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    eligible_operator_count: int = Field(ge=0)
    totals_line_count: int = Field(ge=0)
    confidence_grade_counts: tuple[CurrentMarketConfidenceCount, ...]
    exclusion_counts: tuple[CurrentMarketExclusionCount, ...]
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_read_performed: bool
    database_write_performed: Literal[False] = False
    network_called: Literal[False] = False
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if (
            self.market_ready_count + self.h2h_only_degraded_count + self.blocked_count
            != self.fixture_count
        ):
            raise ValueError("summary fixture counts are inconsistent")
        return self


class CurrentMarketConstraintBundle(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_MARKET_CONSTRAINT_BUNDLE"] = "CURRENT_MARKET_CONSTRAINT_BUNDLE"
    contract_version: Literal["current-market-constraints-v1"] = CURRENT_MARKET_CONTRACT_VERSION
    status: Literal["USABLE"] = "USABLE"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    information_cutoff: datetime
    decision_information_at: datetime
    fixtures: tuple[CurrentFixtureMarketConstraints, ...] = Field(min_length=1)
    source_quality_warnings: tuple[str, ...]
    source_exclusion_counts: tuple[CurrentMarketExclusionCount, ...]
    lineage: CurrentMarketConstraintLineage
    rights: CurrentMarketRightsBoundary
    runtime: CurrentMarketRuntimeBoundary
    limitations: tuple[str, ...]
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        fixture_ids = [item.canonical_fixture_id for item in self.fixtures]
        if fixture_ids != sorted(fixture_ids, key=str) or len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("current fixture results must be uniquely sorted")
        if self.decision_information_at > self.information_cutoff:
            raise ValueError("current market decision information is post-cutoff")
        if self.limitations != _LIMITATIONS:
            raise ValueError("current market limitations are inconsistent")
        if self.source_quality_warnings != tuple(sorted(set(self.source_quality_warnings))):
            raise ValueError("source quality warnings must be unique and sorted")
        if self.source_exclusion_counts != tuple(
            sorted(self.source_exclusion_counts, key=lambda item: item.reason)
        ):
            raise ValueError("source exclusion counts must be sorted")
        if self.runtime.persistence_performed or self.runtime.database_write_performed:
            raise ValueError("current market runtime cannot persist")
        if self.runtime.network_called:
            raise ValueError("current market runtime cannot call the network")
        if self.semantic_sha256 != current_market_constraint_bundle_sha256(self):
            raise ValueError("current market bundle hash is inconsistent")
        return self

    def safe_summary(self) -> CurrentMarketConstraintSummary:
        readiness = Counter(item.readiness for item in self.fixtures)
        confidence = Counter[str]()
        exclusions = Counter({item.reason: item.count for item in self.source_exclusion_counts})
        eligible_operator_count = 0
        totals_line_count = 0
        for fixture in self.fixtures:
            exclusions.update({item.reason: item.count for item in fixture.exclusion_counts})
            if fixture.h2h_consensus is not None:
                confidence[fixture.h2h_consensus.confidence_grade] += 1
                eligible_operator_count += fixture.h2h_consensus.eligible_operator_count
            for totals in fixture.totals_consensuses:
                confidence[totals.confidence_grade] += 1
                eligible_operator_count += totals.eligible_operator_count
                totals_line_count += 1
        return CurrentMarketConstraintSummary(
            target_gameweek=self.target_gameweek,
            information_cutoff=self.information_cutoff,
            fixture_count=len(self.fixtures),
            market_ready_count=readiness[CurrentMarketReadiness.MARKET_READY],
            h2h_only_degraded_count=readiness[CurrentMarketReadiness.H2H_ONLY_DEGRADED],
            blocked_count=readiness[CurrentMarketReadiness.BLOCKED],
            eligible_operator_count=eligible_operator_count,
            totals_line_count=totals_line_count,
            confidence_grade_counts=tuple(
                CurrentMarketConfidenceCount(confidence_grade=grade, count=confidence[grade])
                for grade in CONFIDENCE_GRADES
                if confidence[grade]
            ),
            exclusion_counts=tuple(
                CurrentMarketExclusionCount(reason=reason, count=count)
                for reason, count in sorted(exclusions.items())
                if count
            ),
            database_read_performed=self.runtime.database_read_performed,
            semantic_sha256=self.semantic_sha256,
        )


def current_market_constraint_bundle_sha256(value: CurrentMarketConstraintBundle) -> str:
    return canonical_sha256(
        {
            "competition_key": value.competition_key,
            "contract": value.contract,
            "contract_version": value.contract_version,
            "decision_information_at": value.decision_information_at.isoformat(),
            "fixtures": [item.semantic_sha256 for item in value.fixtures],
            "information_cutoff": value.information_cutoff.isoformat(),
            "limitations": list(value.limitations),
            "lineage": value.lineage.model_dump(mode="json"),
            "rights": value.rights.model_dump(mode="json"),
            "runtime": value.runtime.model_dump(mode="json"),
            "schema_version": value.schema_version,
            "season_code": value.season_code,
            "source_exclusion_counts": [
                item.model_dump(mode="json") for item in value.source_exclusion_counts
            ],
            "source_quality_warnings": list(value.source_quality_warnings),
            "status": value.status,
            "target_gameweek": value.target_gameweek,
        }
    )


def bind_current_market_constraint_request(
    source: CurrentUnifiedStateBundle,
    identity_view: CurrentMarketCanonicalIdentityView,
    *,
    market_policy: MarketNormalisationPolicy | None = None,
    constraint_policy: ScoreBaselinePolicy | None = None,
) -> CurrentMarketConstraintRequest:
    policy = market_policy or load_market_normalisation_policy()
    score_policy = constraint_policy or load_score_baseline_policy()
    return CurrentMarketConstraintRequest(
        target_gameweek=source.target_gameweek,
        information_cutoff=source.information_cutoff,
        current_unified_state_semantic_sha256=source.semantic_sha256,
        fpl_full_representation_sha256=source.lineage.fpl_full_representation_sha256,
        fpl_odds_identity_map_semantic_sha256=(
            source.lineage.fpl_odds_identity_map_semantic_sha256
        ),
        odds_market_semantic_sha256=source.lineage.odds_market_semantic_sha256,
        odds_identity_semantic_sha256=source.lineage.odds_identity_semantic_sha256,
        odds_provider_provenance_sha256=source.lineage.odds_provider_provenance_sha256,
        odds_quality_sha256=current_odds_quality_sha256(source),
        odds_temporal_sha256=current_odds_temporal_sha256(source),
        odds_rights_sha256=current_odds_rights_sha256(source),
        canonical_identity_view_sha256=identity_view.semantic_sha256,
        market_policy_sha256=policy.sha256,
        confidence_gate_policy_sha256=CONFIDENCE_GATE_POLICY_SHA256,
        constraint_policy_sha256=score_policy.sha256,
    )


def _q12(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(PROBABILITY_SCALE)


def current_odds_quality_sha256(value: CurrentUnifiedStateBundle) -> str:
    """Bind accepted upstream exclusions absent from the 001D market-only digest."""

    return canonical_sha256(value.odds_input.quality.model_dump(mode="json"))


def current_odds_temporal_sha256(value: CurrentUnifiedStateBundle) -> str:
    """Bind the complete local acquisition-time state used by current markets."""

    return canonical_sha256(value.odds_input.temporal.model_dump(mode="json"))


def _accepted_odds_rights_authority() -> tuple[RightsProfile, str]:
    profiles = load_rights_profiles()
    profile = profiles.get(_ACCEPTED_ODDS_RIGHTS_PROFILE_ID)
    if (
        profile is None
        or profile.rights_profile_id != _ACCEPTED_ODDS_RIGHTS_PROFILE_ID
        or profile.profile_version != _ACCEPTED_ODDS_RIGHTS_PROFILE_VERSION
        or profile.provider_key != _ACCEPTED_ODDS_PROVIDER_KEY
        or profile.status is not RightsProfileStatus.HUMAN_APPROVED
    ):
        raise IngestionError("RIGHTS_BLOCKED", "accepted odds rights profile is unavailable")
    return profile, rights_config_sha256()


def current_odds_rights_sha256(value: CurrentUnifiedStateBundle) -> str:
    """Bind the complete supplied rights state to the packaged approved authority."""

    profile, accepted_config_sha256 = _accepted_odds_rights_authority()
    return canonical_sha256(
        {
            "accepted_profile": {
                "profile_version": profile.profile_version,
                "provider_key": profile.provider_key,
                "rights_profile_id": profile.rights_profile_id,
                "status": profile.status.value,
            },
            "accepted_rights_config_sha256": accepted_config_sha256,
            "source_provenance_rights_config_sha256": (
                value.odds_input.provenance.rights_config_sha256
            ),
            "source_rights": value.odds_input.rights.model_dump(mode="json"),
        }
    )


def _require_accepted_odds_rights(value: CurrentUnifiedStateBundle) -> None:
    profile, accepted_config_sha256 = _accepted_odds_rights_authority()
    if (
        value.odds_input.provenance.rights_config_sha256 != accepted_config_sha256
        or value.odds_input.rights.rights_profile_id != profile.rights_profile_id
        or value.odds_input.rights.rights_profile_version != profile.profile_version
    ):
        raise CurrentMarketConstraintError("RIGHTS_BLOCKED")


def _public_pair(values: tuple[Decimal, Decimal]) -> tuple[Decimal, Decimal]:
    rounded = [_q12(value) for value in values]
    residual = _ONE - sum(rounded, Decimal(0))
    winner = max(range(2), key=lambda index: (values[index], -index))
    rounded[winner] += residual
    return rounded[0], rounded[1]


def _public_weight_pair(
    values: tuple[Decimal, Decimal], *, target_total: Decimal
) -> tuple[Decimal, Decimal]:
    """Round an exact pair to the public scale while preserving its intended mass."""

    rounded = [_q12(value) for value in values]
    residual = target_total - sum(rounded, Decimal(0))
    winner = max(range(2), key=lambda index: (values[index], -index))
    rounded[winner] = _q12(rounded[winner] + residual)
    return rounded[0], rounded[1]


def _source_quality_exclusions(
    warnings: tuple[str, ...],
) -> tuple[CurrentMarketExclusionCount, ...]:
    counts: Counter[str] = Counter()
    for warning in warnings:
        if "INCOMPLETE" in warning or warning == "TOTALS_MISSING":
            reason = ExclusionReason.INCOMPLETE.value
        elif "UNSUPPORTED" in warning:
            reason = ExclusionReason.UNSUPPORTED.value
        elif "UNAVAILABLE" in warning:
            reason = ExclusionReason.UNAVAILABLE.value
        elif "TIMESTAMP" in warning:
            reason = ExclusionReason.FUTURE_OBSERVATION.value
        else:
            reason = ExclusionReason.QUALITY_BLOCKED.value
        counts[reason] += 1
    return tuple(
        CurrentMarketExclusionCount(reason=reason, count=count)
        for reason, count in sorted(counts.items())
    )


def _binary_power(raw: tuple[Decimal, Decimal]) -> tuple[tuple[Decimal, Decimal], Decimal]:
    try:
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            context.rounding = ROUND_HALF_EVEN

            def residual(exponent: Decimal) -> Decimal:
                return raw[0] ** exponent + raw[1] ** exponent - _ONE

            if residual(_ONE) <= 0:
                lower, upper = Decimal(0), _ONE
            else:
                lower, upper = _ONE, _TWO
                while residual(upper) >= 0:
                    upper *= _TWO
                    if upper > Decimal(1024):
                        raise ArithmeticError("binary power bracket exceeded")
            for _ in range(256):
                midpoint = (lower + upper) / _TWO
                if residual(midpoint) > 0:
                    lower = midpoint
                else:
                    upper = midpoint
            exponent = (lower + upper) / _TWO
            powered = (raw[0] ** exponent, raw[1] ** exponent)
            total = powered[0] + powered[1]
            if not total.is_finite() or total <= 0:
                raise ArithmeticError("binary power total invalid")
            result = (powered[0] / total, powered[1] / total)
            if any(not value.is_finite() or value <= 0 for value in result):
                raise ArithmeticError("binary power vector invalid")
            return result, exponent
    except (DecimalException, InvalidOperation, OverflowError) as exc:
        raise ArithmeticError("binary power decimal failure") from exc


def _transient_uuid(label: str, material: Mapping[str, object]) -> UUID:
    return uuid5(_TRANSIENT_NAMESPACE, f"{label}:{canonical_sha256(material)}")


def _observation_time(
    bookmaker: CurrentOddsBookmaker,
    market: CurrentOddsMarket | CurrentOddsTotalsMarket,
) -> tuple[datetime, Literal["MARKET", "BOOKMAKER"]]:
    if market.provider_last_update is not None:
        return market.provider_last_update, "MARKET"
    return bookmaker.provider_last_update, "BOOKMAKER"


def _h2h_quotes(
    *,
    source: CurrentUnifiedStateBundle,
    event: CurrentOddsEvent,
    fixture: CurrentMarketCanonicalFixture,
    identity_view: CurrentMarketCanonicalIdentityView,
) -> tuple[
    tuple[ExclusiveOutcomeQuote, ...],
    tuple[ExcludedBook, ...],
    tuple[str, ...],
]:
    quotes: list[ExclusiveOutcomeQuote] = []
    warnings: set[str] = set()
    exclusions: list[ExcludedBook] = []
    candidates: dict[UUID, list[CurrentOddsBookmaker]] = {}
    for bookmaker in event.bookmakers:
        market = bookmaker.markets[0]
        for outcome in market.outcomes:
            if (
                (outcome.outcome == "HOME" and outcome.provider_name != event.provider_home_team)
                or (outcome.outcome == "AWAY" and outcome.provider_name != event.provider_away_team)
                or (outcome.outcome == "DRAW" and outcome.provider_name.casefold() != "draw")
            ):
                raise CurrentMarketConstraintError("SOURCE_INVALID")
        canonical_operator = identity_view.operator(bookmaker.bookmaker_key)
        observed_at, timestamp_source = _observation_time(bookmaker, market)
        if timestamp_source == "BOOKMAKER":
            warnings.add("H2H_TIMESTAMP_BOOKMAKER_FALLBACK")
        if observed_at > source.odds_input.temporal.received_at:
            exclusions.append(
                ExcludedBook(
                    operator_key=canonical_operator.canonical_operator_key,
                    reason=ExclusionReason.FUTURE_OBSERVATION,
                )
            )
            warnings.add("H2H_FUTURE_OBSERVATION_EXCLUDED")
            continue
        candidates.setdefault(canonical_operator.canonical_operator_id, []).append(bookmaker)
    selected_books: list[CurrentOddsBookmaker] = []
    for aliases in candidates.values():
        ranked = sorted(
            aliases,
            key=lambda item: (
                _observation_time(item, item.markets[0])[0],
                item.bookmaker_key,
            ),
            reverse=True,
        )
        canonical_operator = identity_view.operator(ranked[0].bookmaker_key)
        if len(ranked) > 1:
            warnings.add("H2H_DUPLICATE_OPERATOR_ALIAS_EXCLUDED")
            exclusions.extend(
                ExcludedBook(
                    operator_key=canonical_operator.canonical_operator_key,
                    reason=ExclusionReason.DUPLICATE_OPERATOR,
                )
                for _item in ranked[1:]
            )
            newest_time = _observation_time(ranked[0], ranked[0].markets[0])[0]
            tied = [
                item
                for item in ranked
                if _observation_time(item, item.markets[0])[0] == newest_time
            ]
            tied_prices = {
                tuple(
                    format(outcome.decimal_price, "f")
                    for outcome in sorted(
                        item.markets[0].outcomes,
                        key=lambda outcome: outcome.outcome,
                    )
                )
                for item in tied
            }
            if len(tied_prices) > 1:
                warnings.add("H2H_DUPLICATE_OPERATOR_ALIAS_CONFLICT")
                exclusions.append(
                    ExcludedBook(
                        operator_key=canonical_operator.canonical_operator_key,
                        reason=ExclusionReason.QUALITY_BLOCKED,
                    )
                )
                continue
        selected_books.append(ranked[0])
    for bookmaker in selected_books:
        canonical_operator = identity_view.operator(bookmaker.bookmaker_key)
        market = bookmaker.markets[0]
        observed_at = _observation_time(bookmaker, market)[0]
        market_id = _transient_uuid(
            "h2h-market",
            {
                "fixture_id": str(fixture.canonical_fixture_id),
                "operator_id": str(canonical_operator.canonical_operator_id),
            },
        )
        book_id = _transient_uuid(
            "h2h-book",
            {
                "market_id": str(market_id),
                "market_semantic_sha256": source.odds_input.market_semantic_sha256,
                "provider_bookmaker_identity_sha256": canonical_sha256(
                    {
                        "bookmaker_key": bookmaker.bookmaker_key,
                        "bookmaker_title": bookmaker.bookmaker_title,
                    }
                ),
                "provider_event_identity_sha256": fixture.provider_event_identity_sha256,
                "source_snapshot_id": str(source.odds_input.provenance.source_snapshot_id),
            },
        )
        for outcome in market.outcomes:
            mapped_outcome = MarketOutcome(outcome.outcome)
            selection_id = _transient_uuid(
                "h2h-selection",
                {"market_id": str(market_id), "outcome": mapped_outcome.value},
            )
            observation_id = _transient_uuid(
                "h2h-observation",
                {
                    "book_id": str(book_id),
                    "decimal_price": format(outcome.decimal_price, "f"),
                    "outcome": mapped_outcome.value,
                },
            )
            quotes.append(
                ExclusiveOutcomeQuote(
                    fixture_id=fixture.canonical_fixture_id,
                    market_id=market_id,
                    selection_id=selection_id,
                    operator_id=canonical_operator.canonical_operator_id,
                    outcome=mapped_outcome,
                    decimal_odds=outcome.decimal_price,
                    observed_at=observed_at,
                    received_at=source.odds_input.temporal.received_at,
                    usable_at=source.odds_input.temporal.usable_at,
                    source_snapshot_id=source.odds_input.provenance.source_snapshot_id,
                    market_state=MarketState.COMPLETE,
                    contract_version="the-odds-api-v4-reference-v1",
                    book_observation_id=book_id,
                    odds_observation_id=observation_id,
                    provider_id=identity_view.provider_id,
                    operator_key=canonical_operator.canonical_operator_key,
                )
            )
    return tuple(quotes), tuple(exclusions), tuple(sorted(warnings))


def _normalise_totals_operator(
    *,
    source: CurrentUnifiedStateBundle,
    fixture_id: UUID,
    provider_event_identity_sha256: str,
    bookmaker: CurrentOddsBookmaker,
    market: CurrentOddsTotalsMarket,
    canonical_operator: CurrentMarketCanonicalOperator,
    provider_id: UUID,
    policy_sha256: str,
) -> CurrentTotalsOperatorMarket:
    by_outcome = {item.outcome: item for item in market.outcomes}
    over = by_outcome["OVER"].decimal_price
    under = by_outcome["UNDER"].decimal_price
    observed_at, timestamp_source = _observation_time(bookmaker, market)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        raw = (raw_implied_probability(over), raw_implied_probability(under))
        booksum = raw[0] + raw[1]
        proportional = (raw[0] / booksum, raw[1] / booksum)
        fallback = False
        exponent: Decimal | None
        try:
            primary, exponent = _binary_power(raw)
            method: Literal["POWER", "PROPORTIONAL"] = "POWER"
        except ArithmeticError:
            primary = proportional
            exponent = None
            fallback = True
            method = "PROPORTIONAL"
    primary_public = _public_pair(primary)
    proportional_public = _public_pair(proportional)
    input_material = {
        "fixture_id": str(fixture_id),
        "line": format(market.line, "f"),
        "market_semantic_sha256": source.odds_input.market_semantic_sha256,
        "operator_id": str(canonical_operator.canonical_operator_id),
        "provider_event_identity_sha256": provider_event_identity_sha256,
        "source_snapshot_id": str(source.odds_input.provenance.source_snapshot_id),
    }
    input_signature = canonical_sha256(input_material)
    result_material = {
        **input_material,
        "fallback_used": fallback,
        "observed_at": observed_at.isoformat(),
        "over_decimal_price": format(over, "f"),
        "over_probability": format(primary_public[0], "f"),
        "policy_sha256": policy_sha256,
        "primary_method": method,
        "proportional_over_probability": format(proportional_public[0], "f"),
        "proportional_under_probability": format(proportional_public[1], "f"),
        "under_decimal_price": format(under, "f"),
        "under_probability": format(primary_public[1], "f"),
        "usable_at": source.odds_input.temporal.usable_at.isoformat(),
    }
    return CurrentTotalsOperatorMarket(
        provider_id=provider_id,
        operator_id=canonical_operator.canonical_operator_id,
        line=market.line,
        observed_at=observed_at,
        usable_at=source.odds_input.temporal.usable_at,
        timestamp_source=timestamp_source,
        primary_method=method,
        fallback_used=fallback,
        over_probability=primary_public[0],
        under_probability=primary_public[1],
        proportional_over_probability=proportional_public[0],
        proportional_under_probability=proportional_public[1],
        raw_booksum=_q12(booksum),
        overround=_q12(booksum - _ONE),
        power_exponent=_q12(exponent) if exponent is not None else None,
        input_signature_sha256=input_signature,
        result_sha256=canonical_sha256(result_material),
    )


def _confidence_grade(
    *,
    operator_count: int,
    maximum_age_seconds: int,
    disagreement: Decimal,
    fallback_used: bool,
    has_warning: bool,
    policy: MarketNormalisationPolicy,
) -> Literal["A", "B", "C", "D"]:
    for grade in CONFIDENCE_GRADES:
        threshold = getattr(policy.confidence, grade)
        gate = confidence_gate(policy.sha256, grade)
        if operator_count < threshold.minimum_operators:
            continue
        if (
            threshold.maximum_age_seconds is not None
            and maximum_age_seconds > threshold.maximum_age_seconds
        ):
            continue
        if threshold.maximum_disagreement is not None and disagreement > Decimal(
            threshold.maximum_disagreement
        ):
            continue
        if fallback_used and not gate.fallback_allowed:
            continue
        if has_warning and gate.maximum_warning_level == "NONE":
            continue
        return grade
    raise MarketNormalisationError("confidence policy rejects totals market")


def _totals_consensus(
    *,
    source: CurrentUnifiedStateBundle,
    event: CurrentOddsEvent,
    fixture: CurrentMarketCanonicalFixture,
    identity_view: CurrentMarketCanonicalIdentityView,
    line: Decimal,
    policy: MarketNormalisationPolicy,
    exclusions: Counter[str],
    as_of: datetime,
) -> CurrentTotalsConsensus | None:
    candidates: dict[UUID, list[tuple[CurrentOddsBookmaker, CurrentOddsTotalsMarket]]] = {}
    has_warning = False
    for bookmaker in event.bookmakers:
        canonical_operator = identity_view.operator(bookmaker.bookmaker_key)
        for market in bookmaker.totals_markets:
            if market.line == line:
                observed_at, _timestamp_source = _observation_time(bookmaker, market)
                if observed_at > source.odds_input.temporal.received_at:
                    exclusions[ExclusionReason.FUTURE_OBSERVATION.value] += 1
                    has_warning = True
                    continue
                candidates.setdefault(canonical_operator.canonical_operator_id, []).append(
                    (bookmaker, market)
                )
    selected: list[CurrentTotalsOperatorMarket] = []
    for _operator_id, aliases in sorted(candidates.items(), key=lambda item: str(item[0])):
        ranked = sorted(
            aliases,
            key=lambda item: (
                _observation_time(item[0], item[1])[0],
                item[0].bookmaker_key,
            ),
            reverse=True,
        )
        if len(ranked) > 1:
            has_warning = True
            exclusions[ExclusionReason.DUPLICATE_OPERATOR.value] += len(ranked) - 1
            newest_time = _observation_time(ranked[0][0], ranked[0][1])[0]
            tied = [
                item for item in ranked if _observation_time(item[0], item[1])[0] == newest_time
            ]
            price_pairs = {
                tuple(
                    format(outcome.decimal_price, "f")
                    for outcome in sorted(item[1].outcomes, key=lambda outcome: outcome.outcome)
                )
                for item in tied
            }
            if len(price_pairs) > 1:
                exclusions[ExclusionReason.QUALITY_BLOCKED.value] += len(tied)
                continue
        bookmaker, market = ranked[0]
        observed_at, timestamp_source = _observation_time(bookmaker, market)
        if observed_at > as_of or source.odds_input.temporal.usable_at > as_of:
            exclusions[ExclusionReason.FUTURE_OBSERVATION.value] += 1
            has_warning = True
            continue
        if as_of - observed_at > timedelta(seconds=policy.freshness.stale_after_seconds):
            exclusions[ExclusionReason.STALE.value] += 1
            has_warning = True
            continue
        if timestamp_source == "BOOKMAKER":
            has_warning = True
        canonical_operator = identity_view.operator(bookmaker.bookmaker_key)
        selected.append(
            _normalise_totals_operator(
                source=source,
                fixture_id=fixture.canonical_fixture_id,
                provider_event_identity_sha256=fixture.provider_event_identity_sha256,
                bookmaker=bookmaker,
                market=market,
                canonical_operator=canonical_operator,
                provider_id=identity_view.provider_id,
                policy_sha256=policy.sha256,
            )
        )
    if not selected:
        return None
    selected.sort(key=lambda item: str(item.operator_id))
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        count = Decimal(len(selected))
        over_internal = sum((item.over_probability for item in selected), Decimal(0)) / count
        under_internal = sum((item.under_probability for item in selected), Decimal(0)) / count
        consensus = _public_pair((over_internal, under_internal))
        operator_disagreement = max(
            (
                abs(left.over_probability - right.over_probability)
                for index, left in enumerate(selected)
                for right in selected[index + 1 :]
            ),
            default=Decimal(0),
        )
        method_disagreement = max(
            (abs(item.over_probability - item.proportional_over_probability) for item in selected),
            default=Decimal(0),
        )
        market_disagreement = max(operator_disagreement, method_disagreement)
    vectors = [(item.over_probability, item.under_probability) for item in selected] + [
        (item.proportional_over_probability, item.proportional_under_probability)
        for item in selected
    ]
    outcomes = (
        CurrentTotalsConsensusOutcome(
            outcome="OVER",
            consensus_probability=consensus[0],
            lower_bound=min(item[0] for item in vectors),
            upper_bound=max(item[0] for item in vectors),
        ),
        CurrentTotalsConsensusOutcome(
            outcome="UNDER",
            consensus_probability=consensus[1],
            lower_bound=min(item[1] for item in vectors),
            upper_bound=max(item[1] for item in vectors),
        ),
    )
    ages = [int((as_of - item.observed_at).total_seconds()) for item in selected]
    grade = _confidence_grade(
        operator_count=len(selected),
        maximum_age_seconds=max(ages),
        disagreement=market_disagreement,
        fallback_used=any(item.fallback_used for item in selected),
        has_warning=has_warning,
        policy=policy,
    )
    input_signature = canonical_sha256(
        {
            "as_of": as_of.isoformat(),
            "exclusions": dict(sorted(exclusions.items())),
            "line": format(line, "f"),
            "mapping_cutoff": source.identity_map.mapping_decided_at.isoformat(),
            "operator_input_sha256": [item.input_signature_sha256 for item in selected],
            "policy_sha256": policy.sha256,
        }
    )
    provisional = CurrentTotalsConsensus.model_construct(
        fixture_id=fixture.canonical_fixture_id,
        as_of=as_of,
        mapping_cutoff=source.identity_map.mapping_decided_at,
        line=line,
        provider_count=len({item.provider_id for item in selected}),
        operator_count=len({item.operator_id for item in selected}),
        eligible_operator_count=len(selected),
        operator_markets=tuple(selected),
        outcomes=outcomes,
        operator_disagreement=_q12(operator_disagreement),
        method_disagreement=_q12(method_disagreement),
        market_disagreement=_q12(market_disagreement),
        minimum_age_seconds=min(ages),
        maximum_age_seconds=max(ages),
        confidence_grade=grade,
        policy_sha256=policy.sha256,
        confidence_gate_policy_sha256=CONFIDENCE_GATE_POLICY_SHA256,
        input_signature_sha256=input_signature,
        result_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["result_sha256"] = current_totals_consensus_sha256(provisional)
    return CurrentTotalsConsensus.model_validate(payload)


def _confidence_weight(grade: str) -> Decimal:
    return {
        "A": Decimal("1"),
        "B": Decimal("0.75"),
        "C": Decimal("0.50"),
        "D": Decimal("0.25"),
    }[grade]


def _totals_constraints(
    consensus: CurrentTotalsConsensus,
    *,
    uncertainty_floor: Decimal,
) -> tuple[MarketConstraint, MarketConstraint]:
    total_weight = _confidence_weight(consensus.confidence_grade)
    half = total_weight / _TWO
    weights = _public_pair((half / total_weight, half / total_weight))
    effective_weights = _public_weight_pair(
        (weights[0] * total_weight, weights[1] * total_weight),
        target_total=total_weight,
    )
    events = (ScoreEvent.TOTAL_OVER, ScoreEvent.TOTAL_UNDER)
    constraints: list[MarketConstraint] = []
    line_key = format(consensus.line, "f").replace(".", "_")
    for index, outcome in enumerate(consensus.outcomes):
        uncertainty = max(
            (outcome.upper_bound - outcome.lower_bound) / _TWO,
            consensus.market_disagreement,
            uncertainty_floor,
        )
        constraints.append(
            MarketConstraint(
                constraint_id=f"current-totals-{line_key}-{outcome.outcome.casefold()}",
                family=MarketFamily.TOTALS,
                event=events[index],
                target_probability=outcome.consensus_probability,
                uncertainty=uncertainty,
                weight=effective_weights[index],
                usable_at=consensus.as_of,
                line=consensus.line,
                source_result_sha256=consensus.result_sha256,
                provider_count=consensus.provider_count,
                operator_count=consensus.eligible_operator_count,
                maximum_age_seconds=consensus.maximum_age_seconds,
                market_disagreement=consensus.market_disagreement,
                confidence_grade=consensus.confidence_grade,
            )
        )
    return constraints[0], constraints[1]


def _lineage(
    source: CurrentUnifiedStateBundle,
    identity_view: CurrentMarketCanonicalIdentityView,
    policy: MarketNormalisationPolicy,
    score_policy: ScoreBaselinePolicy,
) -> CurrentMarketConstraintLineage:
    return CurrentMarketConstraintLineage(
        current_unified_state_semantic_sha256=source.semantic_sha256,
        fpl_input_semantic_sha256=source.lineage.fpl_input_semantic_sha256,
        fpl_full_representation_sha256=source.lineage.fpl_full_representation_sha256,
        fpl_odds_identity_map_semantic_sha256=(
            source.lineage.fpl_odds_identity_map_semantic_sha256
        ),
        fpl_odds_identity_map_source_lineage_sha256=(
            source.lineage.fpl_odds_identity_map_source_lineage_sha256
        ),
        odds_market_semantic_sha256=source.lineage.odds_market_semantic_sha256,
        odds_identity_semantic_sha256=source.lineage.odds_identity_semantic_sha256,
        odds_provider_provenance_sha256=source.lineage.odds_provider_provenance_sha256,
        odds_quality_sha256=current_odds_quality_sha256(source),
        odds_temporal_sha256=current_odds_temporal_sha256(source),
        odds_rights_sha256=current_odds_rights_sha256(source),
        canonical_identity_view_sha256=identity_view.semantic_sha256,
        market_policy_sha256=policy.sha256,
        confidence_gate_policy_sha256=CONFIDENCE_GATE_POLICY_SHA256,
        constraint_policy_sha256=score_policy.sha256,
    )


def _identity_sets_are_exact(
    source: CurrentUnifiedStateBundle,
    identity_view: CurrentMarketCanonicalIdentityView,
) -> bool:
    mapped = source.identity_map.fixture_mappings
    expected_fixtures = {
        (
            item.official_fpl_fixture_id,
            item.official_fpl_fixture_identity.canonical_lookup_sha256,
            item.provider_event_id,
            item.provider_event_identity_sha256,
            item.fixture_binding_sha256,
        )
        for item in mapped
    }
    observed_fixtures = {
        (
            item.official_fpl_fixture_id,
            item.official_fpl_fixture_lookup_sha256,
            item.provider_event_id,
            item.provider_event_identity_sha256,
            item.fixture_binding_sha256,
        )
        for item in identity_view.fixtures
    }
    target_event_ids = {item.provider_event_id for item in mapped}
    target_events = [
        event for event in source.odds_input.events if event.provider_event_id in target_event_ids
    ]
    occurrence_times = _operator_occurrence_times(source)
    expected_operators = {
        (
            bookmaker.bookmaker_key,
            bookmaker.bookmaker_title,
            _operator_occurrence_times_sha256(
                bookmaker.bookmaker_key,
                occurrence_times[bookmaker.bookmaker_key],
            ),
        )
        for event in target_events
        for bookmaker in event.bookmakers
    }
    observed_operators = {
        (
            item.bookmaker_key,
            item.bookmaker_title,
            item.target_occurrence_times_sha256,
        )
        for item in identity_view.operators
    }
    return expected_fixtures == observed_fixtures and expected_operators == observed_operators


def _provider_event_identity_sha256(event: CurrentOddsEvent) -> str:
    return canonical_sha256(
        {
            "commence_time": event.commence_time.isoformat(),
            "provider_away_team": event.provider_away_team,
            "provider_event_id": event.provider_event_id,
            "provider_home_team": event.provider_home_team,
            "sport_key": event.sport_key,
        }
    )


def _require_cross_source_orientation(
    source: CurrentUnifiedStateBundle,
    mapping: ResolvedCurrentFixture,
    event: CurrentOddsEvent,
) -> None:
    if (
        event.provider_event_id != mapping.provider_event_id
        or event.sport_key != mapping.sport_key
        or event.commence_time != mapping.provider_commence_time
        or event.provider_home_team != mapping.provider_home_team
        or event.provider_away_team != mapping.provider_away_team
        or _provider_event_identity_sha256(event) != mapping.provider_event_identity_sha256
    ):
        raise CurrentMarketConstraintError("SOURCE_INVALID")

    home_matches = tuple(
        team
        for team in source.identity_map.team_mappings
        if team.provider_team_text == mapping.provider_home_team
    )
    away_matches = tuple(
        team
        for team in source.identity_map.team_mappings
        if team.provider_team_text == mapping.provider_away_team
    )
    if len(home_matches) != 1 or len(away_matches) != 1:
        raise CurrentMarketConstraintError("SOURCE_INVALID")
    home = home_matches[0]
    away = away_matches[0]
    if (
        home.official_fpl_team_id != mapping.official_home_team_id
        or home.official_fpl_team_identity != mapping.official_home_team_identity
        or away.official_fpl_team_id != mapping.official_away_team_id
        or away.official_fpl_team_identity != mapping.official_away_team_identity
    ):
        raise CurrentMarketConstraintError("SOURCE_INVALID")

    fixture_matches = tuple(
        fixture
        for fixture in source.fpl_input.fixtures
        if fixture.provider_fixture_id == mapping.official_fpl_fixture_id
    )
    if len(fixture_matches) != 1:
        raise CurrentMarketConstraintError("SOURCE_INVALID")
    official_fixture = fixture_matches[0]
    if (
        official_fixture.home_team_identity != mapping.official_home_team_identity
        or official_fixture.away_team_identity != mapping.official_away_team_identity
        or official_fixture.kickoff_at != mapping.official_fpl_kickoff_at
    ):
        raise CurrentMarketConstraintError("SOURCE_INVALID")


def _request_matches(
    request: CurrentMarketConstraintRequest,
    source: CurrentUnifiedStateBundle,
    identity_view: CurrentMarketCanonicalIdentityView,
    policy: MarketNormalisationPolicy,
    score_policy: ScoreBaselinePolicy,
) -> bool:
    return request == bind_current_market_constraint_request(
        source,
        identity_view,
        market_policy=policy,
        constraint_policy=score_policy,
    )


class CurrentMarketConstraintService:
    """Deterministic private transient current-market service."""

    def build(
        self,
        request: CurrentMarketConstraintRequest,
        *,
        source: CurrentUnifiedStateBundle,
        identity_view: CurrentMarketCanonicalIdentityView,
        market_policy: MarketNormalisationPolicy | None = None,
        constraint_policy: ScoreBaselinePolicy | None = None,
    ) -> CurrentMarketConstraintBundle:
        """Build one exact-source bundle and sanitize subordinate boundary failures."""

        try:
            return self._build(
                request,
                source=source,
                identity_view=identity_view,
                market_policy=market_policy,
                constraint_policy=constraint_policy,
            )
        except CurrentMarketConstraintError:
            raise
        except (
            ArithmeticError,
            DecimalException,
            IngestionError,
            KeyError,
            MarketNormalisationError,
            TypeError,
            ValidationError,
            ValueError,
        ):
            raise CurrentMarketConstraintError("SOURCE_INVALID") from None

    def _build(
        self,
        request: CurrentMarketConstraintRequest,
        *,
        source: CurrentUnifiedStateBundle,
        identity_view: CurrentMarketCanonicalIdentityView,
        market_policy: MarketNormalisationPolicy | None = None,
        constraint_policy: ScoreBaselinePolicy | None = None,
    ) -> CurrentMarketConstraintBundle:
        try:
            checked_source = CurrentUnifiedStateBundle.model_validate(
                source.model_dump(mode="python")
            )
            checked_view = CurrentMarketCanonicalIdentityView.model_validate(
                identity_view.model_dump(mode="python")
            )
        except (ValidationError, ValueError):
            raise CurrentMarketConstraintError("SOURCE_INVALID") from None
        policy = market_policy or load_market_normalisation_policy()
        score_policy = constraint_policy or load_score_baseline_policy()
        try:
            require_authenticated_policy(policy)
            if policy.sha256 != request.market_policy_sha256:
                raise ValueError("policy mismatch")
        except (IngestionError, ValueError):
            raise CurrentMarketConstraintError("MARKET_POLICY_INVALID") from None
        if current_unified_state_semantic_sha256(checked_source) != checked_source.semantic_sha256:
            raise CurrentMarketConstraintError("SOURCE_INVALID")
        if not _request_matches(request, checked_source, checked_view, policy, score_policy):
            raise CurrentMarketConstraintError("SOURCE_MISMATCH")
        if not _identity_sets_are_exact(checked_source, checked_view):
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
        try:
            _require_accepted_odds_rights(checked_source)
        except IngestionError:
            raise CurrentMarketConstraintError("RIGHTS_BLOCKED") from None
        if (
            checked_source.rights.private_internal_use != "ALLOW"
            or checked_source.rights.transient_processing != "ALLOW"
            or checked_source.odds_input.rights.transient_processing != "ALLOW"
            or checked_source.odds_input.rights.private_internal_use != "ALLOW"
        ):
            raise CurrentMarketConstraintError("RIGHTS_BLOCKED")
        if (
            checked_source.runtime.persistence_performed
            or checked_source.runtime.network_called
            or checked_source.runtime.database_accessed
            or checked_view.database_write_performed
        ):
            raise CurrentMarketConstraintError("RUNTIME_BOUNDARY_BLOCKED")
        events_by_id = {
            event.provider_event_id: event for event in checked_source.odds_input.events
        }
        market_as_of = max(
            checked_source.decision_information_at,
            checked_view.resolved_at,
        )
        fixture_results: list[CurrentFixtureMarketConstraints] = []
        for mapping in sorted(
            checked_source.identity_map.fixture_mappings,
            key=lambda item: item.official_fpl_fixture_id,
        ):
            fixture_identity = checked_view.fixture(mapping.official_fpl_fixture_id)
            event = events_by_id[mapping.provider_event_id]
            _require_cross_source_orientation(checked_source, mapping, event)
            h2h_quotes, adapter_exclusions, timestamp_warnings = _h2h_quotes(
                source=checked_source,
                event=event,
                fixture=fixture_identity,
                identity_view=checked_view,
            )
            h2h_evaluation = evaluate_market_consensus(
                h2h_quotes,
                as_of=market_as_of,
                mapping_cutoff=checked_source.identity_map.mapping_decided_at,
                policy=policy,
                initial_exclusions=adapter_exclusions,
                initial_warnings=timestamp_warnings,
            )
            exclusions: Counter[str] = Counter(
                item.reason.value for item in h2h_evaluation.exclusions
            )
            warnings = set(h2h_evaluation.warnings)
            lines = sorted(
                {
                    market.line
                    for bookmaker in event.bookmakers
                    for market in bookmaker.totals_markets
                }
            )
            totals_consensuses: list[CurrentTotalsConsensus] = []
            for line in lines:
                totals = _totals_consensus(
                    source=checked_source,
                    event=event,
                    fixture=fixture_identity,
                    identity_view=checked_view,
                    line=line,
                    policy=policy,
                    exclusions=exclusions,
                    as_of=market_as_of,
                )
                if totals is not None:
                    totals_consensuses.append(totals)
            h2h_consensus = h2h_evaluation.consensus
            if h2h_consensus is None:
                readiness = CurrentMarketReadiness.BLOCKED
                constraints = MarketConstraintSet(
                    as_of=market_as_of,
                    constraints=(),
                    source_result_sha256=None,
                )
            else:
                h2h_set = constraints_from_market_consensus(
                    h2h_consensus,
                    fixture_id=fixture_identity.canonical_fixture_id,
                    as_of=market_as_of,
                    uncertainty_floor=score_policy.projection.market_uncertainty_floor,
                )
                combined = list(h2h_set.constraints)
                for totals in totals_consensuses:
                    combined.extend(
                        _totals_constraints(
                            totals,
                            uncertainty_floor=score_policy.projection.market_uncertainty_floor,
                        )
                    )
                source_result_sha256 = canonical_sha256(
                    {
                        "h2h": h2h_consensus.result_sha256,
                        "totals": [item.result_sha256 for item in totals_consensuses],
                    }
                )
                constraints = cap_market_family_weights(
                    MarketConstraintSet(
                        as_of=market_as_of,
                        constraints=tuple(combined),
                        source_result_sha256=source_result_sha256,
                    ),
                    score_policy.projection.family_cap_map,
                )
                readiness = (
                    CurrentMarketReadiness.MARKET_READY
                    if totals_consensuses
                    else CurrentMarketReadiness.H2H_ONLY_DEGRADED
                )
            safe_fixture_hash = canonical_sha256(
                {
                    "canonical_fixture_id": str(fixture_identity.canonical_fixture_id),
                    "fixture_binding_sha256": mapping.fixture_binding_sha256,
                    "official_fpl_fixture_lookup_sha256": (
                        mapping.official_fpl_fixture_identity.canonical_lookup_sha256
                    ),
                    "provider_event_identity_sha256": mapping.provider_event_identity_sha256,
                }
            )
            provisional = CurrentFixtureMarketConstraints.model_construct(
                canonical_fixture_id=fixture_identity.canonical_fixture_id,
                safe_target_fixture_identity_sha256=safe_fixture_hash,
                readiness=readiness,
                h2h_consensus=h2h_consensus,
                totals_consensuses=tuple(totals_consensuses),
                constraint_set=constraints,
                exclusion_counts=tuple(
                    CurrentMarketExclusionCount(reason=reason, count=count)
                    for reason, count in sorted(exclusions.items())
                    if count
                ),
                warnings=tuple(sorted(warnings)),
                semantic_sha256="0" * 64,
            )
            fixture_payload = provisional.model_dump(mode="python")
            fixture_payload["h2h_consensus"] = h2h_consensus
            fixture_payload["semantic_sha256"] = current_fixture_market_constraints_sha256(
                provisional
            )
            fixture_results.append(CurrentFixtureMarketConstraints.model_validate(fixture_payload))
        fixture_results.sort(key=lambda item: str(item.canonical_fixture_id))
        provisional_bundle = CurrentMarketConstraintBundle.model_construct(
            target_gameweek=checked_source.target_gameweek,
            information_cutoff=checked_source.information_cutoff,
            decision_information_at=market_as_of,
            fixtures=tuple(fixture_results),
            source_quality_warnings=checked_source.odds_input.quality.warnings,
            source_exclusion_counts=_source_quality_exclusions(
                checked_source.odds_input.quality.warnings
            ),
            lineage=_lineage(checked_source, checked_view, policy, score_policy),
            rights=CurrentMarketRightsBoundary(),
            runtime=CurrentMarketRuntimeBoundary(
                database_read_performed=checked_view.database_read_performed
            ),
            limitations=_LIMITATIONS,
            semantic_sha256="0" * 64,
        )
        bundle_payload = provisional_bundle.model_dump(mode="python")
        bundle_payload["fixtures"] = tuple(fixture_results)
        bundle_payload["semantic_sha256"] = current_market_constraint_bundle_sha256(
            provisional_bundle
        )
        return CurrentMarketConstraintBundle.model_validate(bundle_payload)

    def verify(
        self,
        value: CurrentMarketConstraintBundle,
        request: CurrentMarketConstraintRequest,
        *,
        source: CurrentUnifiedStateBundle,
        identity_view: CurrentMarketCanonicalIdentityView,
        market_policy: MarketNormalisationPolicy | None = None,
        constraint_policy: ScoreBaselinePolicy | None = None,
    ) -> CurrentMarketConstraintBundle:
        try:
            if not isinstance(value, CurrentMarketConstraintBundle):
                raise ValueError("unexpected result type")
            checked = value
            expected = self.build(
                request,
                source=source,
                identity_view=identity_view,
                market_policy=market_policy,
                constraint_policy=constraint_policy,
            )
        except CurrentMarketConstraintError:
            raise
        except (ValidationError, ValueError, IngestionError, MarketNormalisationError):
            raise CurrentMarketConstraintError("VERIFICATION_FAILED") from None
        if checked != expected:
            raise CurrentMarketConstraintError("VERIFICATION_FAILED")
        return checked


class CurrentMarketCanonicalIdentityRepository:
    """Resolve only existing DAT-003 identities using SELECT statements."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _one_uuid(rows: Iterable[Mapping[str, object] | RowMapping], key: str) -> UUID:
        values = {row[key] for row in rows}
        if len(values) != 1:
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
        value = values.pop()
        if not isinstance(value, UUID):
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
        return value

    def resolve(
        self,
        source: CurrentUnifiedStateBundle,
        *,
        resolved_at: datetime,
    ) -> CurrentMarketCanonicalIdentityView:
        try:
            cutoff = require_utc(source.information_cutoff)
            resolution_time = require_utc(resolved_at)
        except (TypeError, ValueError):
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE") from None
        if resolution_time > cutoff:
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
        try:
            provider_rows = list(
                self.session.execute(
                    select(
                        data_provider.c.provider_id,
                        data_provider.c.provider_key,
                        data_provider.c.rights_profile_key,
                    ).where(
                        data_provider.c.provider_key == "the_odds_api",
                        data_provider.c.rights_profile_key == "the_odds_api_private_analytics_v1",
                        data_provider.c.active.is_(True),
                    )
                ).mappings()
            )
            provider_id = self._one_uuid(provider_rows, "provider_id")
            fixture_results: list[CurrentMarketCanonicalFixture] = []
            event_by_id = {event.provider_event_id: event for event in source.odds_input.events}
            for mapping in source.identity_map.fixture_mappings:
                official_rows = list(
                    self.session.execute(
                        select(
                            external_identifier.c.canonical_entity_id,
                            external_identifier.c.external_identifier_id,
                        )
                        .join(
                            data_provider,
                            data_provider.c.provider_id == external_identifier.c.provider_id,
                        )
                        .join(season, season.c.season_id == external_identifier.c.season_id)
                        .join(
                            competition,
                            competition.c.competition_id == season.c.competition_id,
                        )
                        .where(
                            data_provider.c.provider_key == "official_fpl",
                            data_provider.c.active.is_(True),
                            external_identifier.c.provider_product == "fantasy_premierleague",
                            competition.c.competition_key == "PL",
                            season.c.season_code == source.season_code,
                            external_identifier.c.identifier_namespace == "fpl.fixture.id",
                            external_identifier.c.entity_type == "FIXTURE",
                            external_identifier.c.external_id_text
                            == str(mapping.official_fpl_fixture_id),
                            external_identifier.c.mapping_status == "HUMAN_VERIFIED",
                            external_identifier.c.valid_during.op("@>")(
                                mapping.official_fpl_kickoff_at
                            ),
                            external_identifier.c.system_during.op("@>")(
                                source.identity_map.mapping_decided_at
                            ),
                        )
                    ).mappings()
                )
                event = event_by_id[mapping.provider_event_id]
                odds_rows = list(
                    self.session.execute(
                        select(
                            external_identifier.c.canonical_entity_id,
                            external_identifier.c.external_identifier_id,
                        )
                        .join(
                            data_provider,
                            data_provider.c.provider_id == external_identifier.c.provider_id,
                        )
                        .join(season, season.c.season_id == external_identifier.c.season_id)
                        .where(
                            data_provider.c.provider_id == provider_id,
                            season.c.season_code == source.season_code,
                            external_identifier.c.provider_product == "soccer_epl/odds",
                            external_identifier.c.identifier_namespace == "the_odds_api.event.id",
                            external_identifier.c.entity_type == "FIXTURE",
                            external_identifier.c.external_id_text == mapping.provider_event_id,
                            external_identifier.c.mapping_status == "HUMAN_VERIFIED",
                            external_identifier.c.valid_during.op("@>")(event.commence_time),
                            external_identifier.c.system_during.op("@>")(
                                source.identity_map.mapping_decided_at
                            ),
                        )
                    ).mappings()
                )
                official_fixture_id = self._one_uuid(official_rows, "canonical_entity_id")
                odds_fixture_id = self._one_uuid(odds_rows, "canonical_entity_id")
                if official_fixture_id != odds_fixture_id:
                    raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
                fixture_results.append(
                    CurrentMarketCanonicalFixture(
                        official_fpl_fixture_id=mapping.official_fpl_fixture_id,
                        official_fpl_fixture_lookup_sha256=(
                            mapping.official_fpl_fixture_identity.canonical_lookup_sha256
                        ),
                        provider_event_id=mapping.provider_event_id,
                        provider_event_identity_sha256=mapping.provider_event_identity_sha256,
                        canonical_fixture_id=official_fixture_id,
                        official_fpl_external_mapping_id=self._one_uuid(
                            official_rows, "external_identifier_id"
                        ),
                        odds_event_external_mapping_id=self._one_uuid(
                            odds_rows, "external_identifier_id"
                        ),
                        fixture_binding_sha256=mapping.fixture_binding_sha256,
                    )
                )
            target_event_ids = {
                item.provider_event_id for item in source.identity_map.fixture_mappings
            }
            bookmaker_by_key: dict[str, CurrentOddsBookmaker] = {}
            event_times_by_key: dict[str, set[datetime]] = {}
            for event_id in target_event_ids:
                event = event_by_id[event_id]
                for bookmaker in event.bookmakers:
                    existing = bookmaker_by_key.get(bookmaker.bookmaker_key)
                    if (
                        existing is not None
                        and existing.bookmaker_title != bookmaker.bookmaker_title
                    ):
                        raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
                    bookmaker_by_key[bookmaker.bookmaker_key] = bookmaker
                    event_times_by_key.setdefault(bookmaker.bookmaker_key, set()).add(
                        event.commence_time
                    )
            operator_results: list[CurrentMarketCanonicalOperator] = []
            for bookmaker_key, bookmaker in sorted(bookmaker_by_key.items()):
                occurrence_times = tuple(sorted(event_times_by_key[bookmaker_key]))
                valid_at_every_occurrence = tuple(
                    external_identifier.c.valid_during.op("@>")(event_time)
                    for event_time in occurrence_times
                )
                rows = list(
                    self.session.execute(
                        select(
                            external_identifier.c.canonical_entity_id,
                            external_identifier.c.external_identifier_id,
                            betting_operator.c.operator_key,
                        )
                        .join(
                            data_provider,
                            data_provider.c.provider_id == external_identifier.c.provider_id,
                        )
                        .join(
                            betting_operator,
                            betting_operator.c.operator_id
                            == external_identifier.c.canonical_entity_id,
                        )
                        .where(
                            data_provider.c.provider_id == provider_id,
                            external_identifier.c.season_id.is_(None),
                            external_identifier.c.provider_product == "soccer_epl/odds",
                            external_identifier.c.identifier_namespace
                            == "the_odds_api.bookmaker.key",
                            external_identifier.c.entity_type == "BETTING_OPERATOR",
                            external_identifier.c.external_id_text == bookmaker_key,
                            external_identifier.c.mapping_status == "HUMAN_VERIFIED",
                            *valid_at_every_occurrence,
                            external_identifier.c.system_during.op("@>")(
                                source.identity_map.mapping_decided_at
                            ),
                            betting_operator.c.active.is_(True),
                        )
                    ).mappings()
                )
                if len(rows) != 1:
                    raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
                operator_key = rows[0].get("operator_key")
                if not isinstance(operator_key, str) or not operator_key:
                    raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE")
                operator_results.append(
                    CurrentMarketCanonicalOperator(
                        bookmaker_key=bookmaker_key,
                        bookmaker_title=bookmaker.bookmaker_title,
                        canonical_operator_id=self._one_uuid(rows, "canonical_entity_id"),
                        canonical_operator_key=operator_key,
                        external_mapping_id=self._one_uuid(rows, "external_identifier_id"),
                        target_occurrence_times_sha256=(
                            _operator_occurrence_times_sha256(
                                bookmaker_key,
                                occurrence_times,
                            )
                        ),
                    )
                )
        except CurrentMarketConstraintError:
            raise
        except (DBAPIError, KeyError, TypeError, ValueError):
            raise CurrentMarketConstraintError("CANONICAL_IDENTITY_UNAVAILABLE") from None
        provisional = CurrentMarketCanonicalIdentityView.model_construct(
            authority="DAT_003_READ_ONLY",
            resolved_at=resolution_time,
            resolution_cutoff=cutoff,
            database_read_performed=True,
            provider_id=provider_id,
            fixtures=tuple(fixture_results),
            operators=tuple(operator_results),
            semantic_sha256="0" * 64,
        )
        payload = provisional.model_dump(mode="python")
        payload["semantic_sha256"] = current_market_identity_view_sha256(provisional)
        return CurrentMarketCanonicalIdentityView.model_validate(payload)


__all__ = [
    "CURRENT_MARKET_CONTRACT_VERSION",
    "CURRENT_MARKET_IDENTITY_VIEW_VERSION",
    "CurrentFixtureMarketConstraints",
    "CurrentMarketCanonicalFixture",
    "CurrentMarketCanonicalIdentityRepository",
    "CurrentMarketCanonicalIdentityView",
    "CurrentMarketCanonicalOperator",
    "CurrentMarketConstraintBundle",
    "CurrentMarketConstraintError",
    "CurrentMarketConstraintLineage",
    "CurrentMarketConstraintRequest",
    "CurrentMarketConstraintService",
    "CurrentMarketConstraintSummary",
    "CurrentMarketReadiness",
    "CurrentMarketRightsBoundary",
    "CurrentMarketRuntimeBoundary",
    "CurrentTotalsConsensus",
    "CurrentTotalsConsensusOutcome",
    "CurrentTotalsOperatorMarket",
    "bind_current_market_constraint_request",
    "build_transient_current_market_identity_view",
    "current_fixture_market_constraints_sha256",
    "current_market_constraint_bundle_sha256",
    "current_market_identity_view_sha256",
    "current_odds_quality_sha256",
    "current_odds_rights_sha256",
    "current_odds_temporal_sha256",
    "current_totals_consensus_sha256",
]
