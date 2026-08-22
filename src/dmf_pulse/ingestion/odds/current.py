"""Provider-native current The Odds API input with explicit drift isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.config import (
    effective_config_sha256,
    load_provider_config,
    provider_config_sha256,
    rights_config_sha256,
)
from dmf_pulse.ingestion.odds.models import QuotaState
from dmf_pulse.ingestion.odds.parser import OddsEvent, OddsMarket, ParsedOddsPayload
from dmf_pulse.ingestion.rights import decide_rights, require_rights

_SECRET_FIELD_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "session",
    "token",
)
_SUPPORTED_MARKETS = frozenset({"h2h", "totals"})


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class CurrentOddsOutcome(_FrozenModel):
    provider_name: str = Field(min_length=1, max_length=500)
    outcome: Literal["HOME", "DRAW", "AWAY"]
    decimal_price: Decimal

    @field_validator("decimal_price")
    @classmethod
    def validate_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 1:
            raise ValueError("decimal price must be finite and greater than one")
        return value


class CurrentOddsMarket(_FrozenModel):
    market_key: Literal["h2h"] = "h2h"
    provider_last_update: datetime | None
    provider_last_update_state: Literal["PUBLISHED", "NOT_PUBLISHED"]
    outcomes: tuple[CurrentOddsOutcome, CurrentOddsOutcome, CurrentOddsOutcome]

    @model_validator(mode="after")
    def validate_market(self) -> CurrentOddsMarket:
        expected_state = "PUBLISHED" if self.provider_last_update is not None else "NOT_PUBLISHED"
        if self.provider_last_update_state != expected_state:
            raise ValueError("market timestamp state contradicts the timestamp")
        if {outcome.outcome for outcome in self.outcomes} != {"HOME", "DRAW", "AWAY"}:
            raise ValueError("h2h market must contain HOME, DRAW and AWAY once")
        return self


class CurrentOddsTotalsOutcome(_FrozenModel):
    provider_name: str = Field(min_length=1, max_length=500)
    outcome: Literal["OVER", "UNDER"]
    decimal_price: Decimal
    point: Decimal

    @field_validator("decimal_price")
    @classmethod
    def validate_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 1:
            raise ValueError("decimal price must be finite and greater than one")
        return value

    @field_validator("point")
    @classmethod
    def validate_point(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value % 1 != Decimal("0.5"):
            raise ValueError("totals point must be a nonnegative half-goal line")
        return value


class CurrentOddsTotalsMarket(_FrozenModel):
    market_key: Literal["totals"] = "totals"
    line: Decimal
    provider_last_update: datetime | None
    provider_last_update_state: Literal["PUBLISHED", "NOT_PUBLISHED"]
    outcomes: tuple[CurrentOddsTotalsOutcome, CurrentOddsTotalsOutcome]

    @field_validator("line")
    @classmethod
    def validate_line(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value % 1 != Decimal("0.5"):
            raise ValueError("totals line must be a nonnegative half-goal line")
        return value

    @model_validator(mode="after")
    def validate_market(self) -> CurrentOddsTotalsMarket:
        expected_state = "PUBLISHED" if self.provider_last_update is not None else "NOT_PUBLISHED"
        if self.provider_last_update_state != expected_state:
            raise ValueError("market timestamp state contradicts the timestamp")
        if {outcome.outcome for outcome in self.outcomes} != {"OVER", "UNDER"}:
            raise ValueError("totals market must contain OVER and UNDER once")
        if any(outcome.point != self.line for outcome in self.outcomes):
            raise ValueError("totals outcomes must bind one exact line")
        return self


class CurrentOddsBookmaker(_FrozenModel):
    bookmaker_key: str = Field(min_length=1, max_length=500)
    bookmaker_title: str = Field(min_length=1, max_length=500)
    provider_last_update: datetime
    age_at_receipt_seconds: int = Field(ge=0)
    markets: tuple[CurrentOddsMarket, ...] = Field(min_length=1, max_length=1)
    totals_markets: tuple[CurrentOddsTotalsMarket, ...] = ()

    @model_validator(mode="after")
    def validate_totals_lines(self) -> CurrentOddsBookmaker:
        lines = [market.line for market in self.totals_markets]
        if len(lines) != len(set(lines)):
            raise ValueError("totals line is duplicated within a bookmaker")
        return self


class CurrentOddsEvent(_FrozenModel):
    provider_event_id: str = Field(min_length=1, max_length=500)
    sport_key: Literal["soccer_epl"] = "soccer_epl"
    commence_time: datetime
    provider_home_team: str = Field(min_length=1, max_length=500)
    provider_away_team: str = Field(min_length=1, max_length=500)
    bookmakers: tuple[CurrentOddsBookmaker, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_teams(self) -> CurrentOddsEvent:
        if self.provider_home_team == self.provider_away_team:
            raise ValueError("event participants must differ")
        keys = tuple(bookmaker.bookmaker_key for bookmaker in self.bookmakers)
        if len(keys) != len(set(keys)):
            raise ValueError("bookmaker identity is duplicated within an event")
        return self


class CurrentOddsTemporalState(_FrozenModel):
    request_started_at: datetime
    received_at: datetime
    captured_at: datetime
    information_cutoff: datetime
    usable_at: datetime
    provider_response_generated_at: None = None
    provider_response_generated_at_state: Literal["NOT_PUBLISHED"] = "NOT_PUBLISHED"

    @model_validator(mode="after")
    def validate_order(self) -> CurrentOddsTemporalState:
        if self.captured_at != self.received_at:
            raise ValueError("captured_at must equal the provider receipt boundary")
        if not (
            self.request_started_at <= self.received_at <= self.usable_at <= self.information_cutoff
        ):
            raise ValueError("current odds temporal boundaries are inconsistent")
        return self


class CurrentOddsQuotaState(_FrozenModel):
    remaining: int = Field(ge=0)
    used: int = Field(ge=0)
    configured_request_cost: int = Field(gt=0)
    provider_last_request_cost: int = Field(ge=0)
    observed_at: datetime
    source: Literal["RESPONSE_HEADERS"] = "RESPONSE_HEADERS"

    @model_validator(mode="after")
    def validate_cost(self) -> CurrentOddsQuotaState:
        if self.provider_last_request_cost != self.configured_request_cost:
            raise ValueError("provider request cost contradicts configured request cost")
        return self


class CurrentOddsRightsState(_FrozenModel):
    rights_profile_id: str
    rights_profile_version: str
    automated_access_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    automated_access: Literal["ALLOW", "DENY"]
    transient_processing_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    transient_processing: Literal["ALLOW", "DENY"]
    derived_storage_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    derived_storage: Literal["ALLOW", "DENY"]
    private_internal_use_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    private_internal_use: Literal["ALLOW", "DENY"]
    raw_storage_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    raw_storage: Literal["ALLOW", "DENY"]
    public_display_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    public_display: Literal["ALLOW", "DENY"]
    redistribution_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    redistribution: Literal["ALLOW", "DENY"]
    backup_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    backup: Literal["ALLOW", "DENY"]
    model_training_declared: Literal["ALLOW", "DENY", "UNKNOWN"]
    model_training: Literal["ALLOW", "DENY"]
    raw_retention_seconds: int | None = Field(default=None, ge=0)
    termination_deletion_required: bool
    raw_payload_retained: Literal[False] = False
    unresolved_rights: tuple[str, ...]

    @model_validator(mode="after")
    def validate_private_current_use(self) -> CurrentOddsRightsState:
        if (
            self.automated_access != "ALLOW"
            or self.transient_processing != "ALLOW"
            or self.derived_storage != "ALLOW"
            or self.private_internal_use != "ALLOW"
        ):
            raise ValueError("required private analytical rights are not allowed")
        if self.raw_storage != "DENY" or self.raw_retention_seconds != 0:
            raise ValueError("live raw retention must remain denied")
        if self.public_display != "DENY" or self.redistribution != "DENY":
            raise ValueError("public display and redistribution must remain denied")
        if self.backup != "DENY" or self.model_training != "DENY":
            raise ValueError("unapproved secondary uses must remain denied")
        return self


class CurrentOddsProvenance(_FrozenModel):
    source_snapshot_id: UUID
    sanitized_target: str = Field(min_length=1, max_length=4096)
    attempt_count: int = Field(ge=1)
    transport_call_count: int = Field(ge=1)
    transport_id: Literal["stdlib_http_client", "stdlib_urllib", "injected"]
    provider_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_request_id_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_version: Literal["the-odds-api-v4-reference-v1"]
    contract_version: Literal["the-odds-api-v4-reference-v1"]
    raw_payload_retained: Literal[False] = False
    canonical_fpl_fixture_mapping_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_transport_provenance(self) -> CurrentOddsProvenance:
        target = urlsplit(self.sanitized_target)
        if (
            target.scheme != "https"
            or target.hostname != "api.the-odds-api.com"
            or target.path != "/v4/sports/soccer_epl/odds"
            or target.username is not None
            or target.password is not None
            or target.fragment
        ):
            raise ValueError("sanitized target is outside the approved boundary")
        query = parse_qsl(target.query, keep_blank_values=True)
        query_names = [name for name, _value in query]
        parameters = dict(query)
        config = load_provider_config()
        if (
            len(query_names) != len(set(query_names))
            or set(query_names)
            != {"regions", "markets", "oddsFormat", "dateFormat", "commenceTimeFrom"}
            or parameters.get("regions") != "uk"
            or parameters.get("markets") != "h2h,totals"
            or parameters.get("oddsFormat") != "decimal"
            or parameters.get("dateFormat") != "iso"
            or self.attempt_count != self.transport_call_count
            or self.attempt_count > config.retry.max_attempts
        ):
            raise ValueError("transport provenance is inconsistent")
        return self


class CurrentOddsQualityState(_FrozenModel):
    status: Literal["PASS", "WARNING"]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    additive_unsupported_markets: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> CurrentOddsQualityState:
        expected = "WARNING" if self.warnings else "PASS"
        if self.blockers or self.status != expected:
            raise ValueError("quality status contradicts findings")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("quality warnings must be unique and sorted")
        if self.additive_unsupported_markets != tuple(
            sorted(set(self.additive_unsupported_markets))
        ):
            raise ValueError("additive market drift must be unique and sorted")
        if any(key in _SUPPORTED_MARKETS for key in self.additive_unsupported_markets):
            raise ValueError("supported markets cannot be classified as additive drift")
        expected_drift_warnings = {
            f"ADDITIVE_UNSUPPORTED_MARKET:{key}" for key in self.additive_unsupported_markets
        }
        observed_drift_warnings = {
            warning
            for warning in self.warnings
            if warning.startswith("ADDITIVE_UNSUPPORTED_MARKET:")
        }
        if expected_drift_warnings != observed_drift_warnings:
            raise ValueError("additive market drift contradicts quality warnings")
        return self


class OddsProviderCurrentInput(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["ODDS_PROVIDER_CURRENT_INPUT"] = "ODDS_PROVIDER_CURRENT_INPUT"
    provider: Literal["the_odds_api"] = "the_odds_api"
    api_version: Literal["v4"] = "v4"
    sport_key: Literal["soccer_epl"] = "soccer_epl"
    region: Literal["uk"] = "uk"
    market: Literal["h2h,totals"] = "h2h,totals"
    odds_format: Literal["decimal"] = "decimal"
    identity_scope: Literal["PROVIDER_NATIVE_UNMAPPED"] = "PROVIDER_NATIVE_UNMAPPED"
    events: tuple[CurrentOddsEvent, ...] = Field(min_length=1)
    temporal: CurrentOddsTemporalState
    quota: CurrentOddsQuotaState
    rights: CurrentOddsRightsState
    provenance: CurrentOddsProvenance
    quality: CurrentOddsQualityState
    market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_cutoff_request_alignment(self) -> OddsProviderCurrentInput:
        parameters = dict(parse_qsl(urlsplit(self.provenance.sanitized_target).query))
        raw_cutoff = parameters.get("commenceTimeFrom")
        if raw_cutoff is None:
            raise ValueError("provider request cutoff is missing")
        try:
            requested_cutoff = datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("provider request cutoff is invalid") from exc
        if requested_cutoff.tzinfo is None or requested_cutoff.utcoffset() is None:
            raise ValueError("provider request cutoff must be timezone-aware")
        if requested_cutoff.astimezone(UTC) != self.temporal.information_cutoff:
            raise ValueError("provider request cutoff contradicts input cutoff")
        if self.market_semantic_sha256 != current_odds_market_semantic_sha256(self):
            raise ValueError("provider current-market semantic hash is inconsistent")
        return self


def _current_odds_market_semantic_payload(
    value: OddsProviderCurrentInput,
) -> dict[str, object]:
    """Project only provider-published supported-market meaning."""

    events: list[dict[str, object]] = []
    for event in value.events:
        bookmakers: list[dict[str, object]] = []
        for bookmaker in event.bookmakers:
            markets: list[dict[str, object]] = []
            for market in bookmaker.markets:
                markets.append(
                    {
                        "market_key": market.market_key,
                        "provider_last_update": (
                            market.provider_last_update.isoformat()
                            if market.provider_last_update is not None
                            else None
                        ),
                        "provider_last_update_state": market.provider_last_update_state,
                        "outcomes": sorted(
                            (
                                {
                                    "decimal_price": format(outcome.decimal_price, "f"),
                                    "outcome": outcome.outcome,
                                    "provider_name": outcome.provider_name,
                                }
                                for outcome in market.outcomes
                            ),
                            key=lambda item: str(item["outcome"]),
                        ),
                    }
                )
            for totals_market in bookmaker.totals_markets:
                markets.append(
                    {
                        "line": format(totals_market.line, "f"),
                        "market_key": totals_market.market_key,
                        "provider_last_update": (
                            totals_market.provider_last_update.isoformat()
                            if totals_market.provider_last_update is not None
                            else None
                        ),
                        "provider_last_update_state": totals_market.provider_last_update_state,
                        "outcomes": sorted(
                            (
                                {
                                    "decimal_price": format(outcome.decimal_price, "f"),
                                    "outcome": outcome.outcome,
                                    "point": format(outcome.point, "f"),
                                    "provider_name": outcome.provider_name,
                                }
                                for outcome in totals_market.outcomes
                            ),
                            key=lambda item: str(item["outcome"]),
                        ),
                    }
                )
            bookmakers.append(
                {
                    "bookmaker_key": bookmaker.bookmaker_key,
                    "bookmaker_title": bookmaker.bookmaker_title,
                    "markets": markets,
                    "provider_last_update": bookmaker.provider_last_update.isoformat(),
                }
            )
        events.append(
            {
                "bookmakers": sorted(bookmakers, key=lambda item: str(item["bookmaker_key"])),
                "commence_time": event.commence_time.isoformat(),
                "provider_away_team": event.provider_away_team,
                "provider_event_id": event.provider_event_id,
                "provider_home_team": event.provider_home_team,
                "sport_key": event.sport_key,
            }
        )
    events.sort(key=lambda item: str(item["provider_event_id"]))
    return {
        "api_version": value.api_version,
        "contract": value.contract,
        "events": events,
        "identity_scope": value.identity_scope,
        "market": value.market,
        "odds_format": value.odds_format,
        "provider": value.provider,
        "region": value.region,
        "schema_version": value.schema_version,
        "sport_key": value.sport_key,
    }


def current_odds_market_semantic_sha256(value: OddsProviderCurrentInput) -> str:
    """Hash supported provider market meaning, excluding local acquisition state."""

    return canonical_sha256(_current_odds_market_semantic_payload(value))


def _canonical_outcome(
    event: OddsEvent,
    name: str,
) -> Literal["HOME", "DRAW", "AWAY"] | None:
    if name == event.home_team:
        return "HOME"
    if name == event.away_team:
        return "AWAY"
    if name.casefold() == "draw":
        return "DRAW"
    return None


def _canonical_totals_outcome(name: str) -> Literal["OVER", "UNDER"] | None:
    normalized = name.casefold().strip()
    if normalized == "over":
        return "OVER"
    if normalized == "under":
        return "UNDER"
    return None


def _totals_market(
    market: OddsMarket,
    *,
    bookmaker_last_update: datetime,
    received_at: datetime,
) -> tuple[CurrentOddsTotalsMarket | None, str | None]:
    if market.last_update is not None and (
        market.last_update > received_at or market.last_update > bookmaker_last_update
    ):
        return None, "TOTALS_TIMESTAMP_INVALID"
    by_line: dict[Decimal, dict[str, CurrentOddsTotalsOutcome]] = {}
    for outcome in market.outcomes:
        canonical = _canonical_totals_outcome(outcome.name)
        if canonical is None or outcome.point is None:
            return None, "TOTALS_MALFORMED_OUTCOME"
        try:
            parsed = CurrentOddsTotalsOutcome(
                provider_name=outcome.name,
                outcome=canonical,
                decimal_price=outcome.price,
                point=outcome.point,
            )
        except ValueError:
            return None, "TOTALS_NON_HALF_GOAL_LINE"
        line_outcomes = by_line.setdefault(parsed.point, {})
        if canonical in line_outcomes:
            return None, "TOTALS_DUPLICATE_OUTCOME"
        line_outcomes[canonical] = parsed
    if len(market.outcomes) == 2 and len(by_line) != 1:
        return None, "TOTALS_LINE_MISMATCH"
    selected = by_line.get(Decimal("2.5"))
    if selected is None:
        return None, "TOTALS_PREFERRED_LINE_2_5_UNAVAILABLE"
    if set(selected) != {"OVER", "UNDER"}:
        return None, "TOTALS_INCOMPLETE"
    if selected["OVER"].point != selected["UNDER"].point:
        return None, "TOTALS_LINE_MISMATCH"
    line = selected["OVER"].point
    return (
        CurrentOddsTotalsMarket(
            line=line,
            provider_last_update=market.last_update,
            provider_last_update_state=(
                "PUBLISHED" if market.last_update is not None else "NOT_PUBLISHED"
            ),
            outcomes=(selected["OVER"], selected["UNDER"]),
        ),
        None,
    )


def _contains_secret_like_extra(value: object) -> bool:
    if isinstance(value, BaseModel):
        for key, child in (value.model_extra or {}).items():
            normalized = key.casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _SECRET_FIELD_FRAGMENTS):
                return True
            if _contains_secret_like_extra(child):
                return True
        return any(
            _contains_secret_like_extra(getattr(value, name))
            for name in value.__class__.model_fields
        )
    if isinstance(value, tuple | list):
        return any(_contains_secret_like_extra(item) for item in value)
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _SECRET_FIELD_FRAGMENTS):
                return True
            if _contains_secret_like_extra(child):
                return True
    return False


def _rights_state(profile: RightsProfile, checked_at: datetime) -> CurrentOddsRightsState:
    required = (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.PRIVATE_INTERNAL_USE,
    )
    for capability in required:
        require_rights(profile, capability, checked_at=checked_at)

    def declared(capability: RightsCapability) -> Literal["ALLOW", "DENY", "UNKNOWN"]:
        value = profile.capabilities[capability].value
        if value == "ALLOW":
            return "ALLOW"
        if value == "DENY":
            return "DENY"
        return "UNKNOWN"

    def decision(capability: RightsCapability) -> Literal["ALLOW", "DENY"]:
        value = decide_rights(profile, capability, checked_at=checked_at).decision
        return "ALLOW" if value == "ALLOW" else "DENY"

    return CurrentOddsRightsState(
        rights_profile_id=profile.rights_profile_id,
        rights_profile_version=profile.profile_version,
        automated_access_declared=declared(RightsCapability.AUTOMATED_ACCESS),
        automated_access=decision(RightsCapability.AUTOMATED_ACCESS),
        transient_processing_declared=declared(RightsCapability.TRANSIENT_PROCESSING),
        transient_processing=decision(RightsCapability.TRANSIENT_PROCESSING),
        derived_storage_declared=declared(RightsCapability.DERIVED_STORAGE),
        derived_storage=decision(RightsCapability.DERIVED_STORAGE),
        private_internal_use_declared=declared(RightsCapability.PRIVATE_INTERNAL_USE),
        private_internal_use=decision(RightsCapability.PRIVATE_INTERNAL_USE),
        raw_storage_declared=declared(RightsCapability.RAW_STORAGE),
        raw_storage=decision(RightsCapability.RAW_STORAGE),
        public_display_declared=declared(RightsCapability.PUBLIC_DISPLAY),
        public_display=decision(RightsCapability.PUBLIC_DISPLAY),
        redistribution_declared=declared(RightsCapability.REDISTRIBUTION),
        redistribution=decision(RightsCapability.REDISTRIBUTION),
        backup_declared=declared(RightsCapability.BACKUP),
        backup=decision(RightsCapability.BACKUP),
        model_training_declared=declared(RightsCapability.MODEL_TRAINING),
        model_training=decision(RightsCapability.MODEL_TRAINING),
        raw_retention_seconds=profile.retention_seconds,
        termination_deletion_required=profile.termination_deletion_required,
        unresolved_rights=profile.unresolved_rights,
    )


def _provider_events(
    parsed: ParsedOddsPayload,
    *,
    received_at: datetime,
    information_cutoff: datetime,
) -> tuple[tuple[CurrentOddsEvent, ...], tuple[str, ...], tuple[str, ...]]:
    blockers: set[str] = set()
    warnings: set[str] = set()
    additive_markets: set[str] = set()
    current_events: list[CurrentOddsEvent] = []
    if not parsed.events:
        blockers.add("EMPTY_PROVIDER_RESPONSE")
    if any(item.market_key == "h2h" for item in parsed.duplicate_outcomes):
        blockers.add("DUPLICATE_OUTCOME")
    if any(item.market_key == "totals" for item in parsed.duplicate_outcomes):
        warnings.add("TOTALS_DUPLICATE_OUTCOME")
    if _contains_secret_like_extra(parsed.events):
        blockers.add("SECRET_LIKE_PROVIDER_FIELD")

    seen_event_ids: set[str] = set()
    for event in parsed.events:
        if event.id in seen_event_ids:
            blockers.add("DUPLICATE_PROVIDER_EVENT_ID")
            continue
        seen_event_ids.add(event.id)
        if event.home_team == event.away_team:
            blockers.add("HOME_EQUALS_AWAY")
            continue
        if event.commence_time <= information_cutoff:
            blockers.add("EVENT_NOT_PREMATCH_AT_CUTOFF")
        if not event.bookmakers:
            blockers.add("BOOKMAKER_MISSING")
        seen_bookmakers: set[str] = set()
        current_bookmakers: list[CurrentOddsBookmaker] = []
        for bookmaker in event.bookmakers:
            if bookmaker.key in seen_bookmakers:
                blockers.add("DUPLICATE_BOOKMAKER")
                continue
            seen_bookmakers.add(bookmaker.key)
            if bookmaker.last_update > received_at:
                blockers.add("PROVIDER_TIMESTAMP_AFTER_RECEIPT")
            requested = [market for market in bookmaker.markets if market.key == "h2h"]
            totals = [market for market in bookmaker.markets if market.key == "totals"]
            additive_markets.update(
                market.key for market in bookmaker.markets if market.key not in _SUPPORTED_MARKETS
            )
            if len(requested) != 1:
                blockers.add("REQUESTED_MARKET_MISSING_OR_DUPLICATED")
                continue
            market = requested[0]
            if market.last_update is not None and market.last_update > received_at:
                blockers.add("PROVIDER_TIMESTAMP_AFTER_RECEIPT")
            if market.last_update is not None and market.last_update > bookmaker.last_update:
                blockers.add("MARKET_TIMESTAMP_AFTER_BOOKMAKER")
            by_outcome: dict[str, CurrentOddsOutcome] = {}
            for outcome in market.outcomes:
                canonical = _canonical_outcome(event, outcome.name)
                if canonical is None:
                    blockers.add("MALFORMED_OUTCOME")
                    continue
                if outcome.point is not None:
                    blockers.add("LINE_BEARING_H2H_OUTCOME")
                if canonical in by_outcome:
                    blockers.add("DUPLICATE_OUTCOME")
                    continue
                by_outcome[canonical] = CurrentOddsOutcome(
                    provider_name=outcome.name,
                    outcome=canonical,
                    decimal_price=outcome.price,
                )
            if set(by_outcome) != {"HOME", "DRAW", "AWAY"}:
                blockers.add("THREE_WAY_H2H_INCOMPLETE")
                continue
            current_market = CurrentOddsMarket(
                provider_last_update=market.last_update,
                provider_last_update_state=(
                    "PUBLISHED" if market.last_update is not None else "NOT_PUBLISHED"
                ),
                outcomes=(by_outcome["HOME"], by_outcome["DRAW"], by_outcome["AWAY"]),
            )
            current_totals: list[CurrentOddsTotalsMarket] = []
            if len(totals) != 1:
                warnings.add("TOTALS_MISSING")
            else:
                totals_market, totals_warning = _totals_market(
                    totals[0],
                    bookmaker_last_update=bookmaker.last_update,
                    received_at=received_at,
                )
                if totals_warning is not None:
                    warnings.add(totals_warning)
                elif totals_market is not None:
                    current_totals.append(totals_market)
            age_seconds = int((received_at - bookmaker.last_update).total_seconds())
            if age_seconds < 0:
                blockers.add("PROVIDER_TIMESTAMP_AFTER_RECEIPT")
                age_seconds = 0
            current_bookmakers.append(
                CurrentOddsBookmaker(
                    bookmaker_key=bookmaker.key,
                    bookmaker_title=bookmaker.title,
                    provider_last_update=bookmaker.last_update,
                    age_at_receipt_seconds=age_seconds,
                    markets=(current_market,),
                    totals_markets=tuple(current_totals),
                )
            )
        if current_bookmakers:
            current_events.append(
                CurrentOddsEvent(
                    provider_event_id=event.id,
                    commence_time=event.commence_time,
                    provider_home_team=event.home_team,
                    provider_away_team=event.away_team,
                    bookmakers=tuple(current_bookmakers),
                )
            )

    warnings.update(f"ADDITIVE_UNSUPPORTED_MARKET:{key}" for key in additive_markets)
    if blockers:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "provider-native odds response failed current-input quality gates",
            details={"blockers": sorted(blockers)},
        )
    return (
        tuple(current_events),
        tuple(sorted(warnings)),
        tuple(sorted(additive_markets)),
    )


def build_current_odds_input(
    parsed: ParsedOddsPayload,
    *,
    profile: RightsProfile,
    source_snapshot_id: UUID,
    request_started_at: datetime,
    received_at: datetime,
    information_cutoff: datetime,
    usable_at: datetime,
    quota: QuotaState,
    request_fingerprint: str,
    sanitized_target: str,
    attempt_count: int,
    transport_call_count: int,
    transport_id: Literal["stdlib_http_client", "stdlib_urllib", "injected"],
    provider_request_id_sha256: str | None,
) -> OddsProviderCurrentInput:
    """Validate one response into a cutoff-safe provider-native current input."""

    config = load_provider_config()
    times = (request_started_at, received_at, information_cutoff, usable_at, quota.observed_at)
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):
        raise IngestionError("VALIDATION_FAILED", "current odds timestamps must be timezone-aware")
    request_started = request_started_at.astimezone(UTC)
    received = received_at.astimezone(UTC)
    cutoff = information_cutoff.astimezone(UTC)
    usable = usable_at.astimezone(UTC)
    if received > cutoff or usable > cutoff:
        raise IngestionError("POST_CUTOFF", "odds response was not usable by the cutoff")
    if request_started > received or usable < received:
        raise IngestionError("CLOCK_REGRESSION", "current odds temporal order is invalid")
    if quota.observed_at.astimezone(UTC) != received:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "provider quota timestamp differs from receipt",
            details={"blockers": ["QUOTA_TIMESTAMP_MISMATCH"]},
        )
    if quota.last_cost != config.request_cost:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "provider quota cost contradicts approved configuration",
            details={"blockers": ["QUOTA_REQUEST_COST_MISMATCH"]},
        )
    if quota.source.value != "RESPONSE_HEADERS":
        raise IngestionError(
            "QUALITY_BLOCKED",
            "live provider quota evidence has an invalid source",
            details={"blockers": ["QUOTA_SOURCE_INVALID"]},
        )

    events, event_warnings, additive_markets = _provider_events(
        parsed,
        received_at=received,
        information_cutoff=cutoff,
    )
    warnings = tuple(sorted(set((*parsed.warnings, *event_warnings))))
    temporal = CurrentOddsTemporalState(
        request_started_at=request_started,
        received_at=received,
        captured_at=received,
        information_cutoff=cutoff,
        usable_at=usable,
    )
    current_quota = CurrentOddsQuotaState(
        remaining=quota.remaining,
        used=quota.used,
        configured_request_cost=config.request_cost,
        provider_last_request_cost=quota.last_cost,
        observed_at=quota.observed_at,
    )
    rights = _rights_state(profile, received)
    provenance = CurrentOddsProvenance(
        source_snapshot_id=source_snapshot_id,
        sanitized_target=sanitized_target,
        attempt_count=attempt_count,
        transport_call_count=transport_call_count,
        transport_id=transport_id,
        provider_config_sha256=provider_config_sha256(),
        rights_config_sha256=rights_config_sha256(),
        effective_config_sha256=effective_config_sha256(),
        request_fingerprint=request_fingerprint,
        provider_request_id_sha256=provider_request_id_sha256,
        response_body_sha256=parsed.body_sha256,
        adapter_version=config.adapter_version,
        contract_version=config.contract_version,
    )
    quality = CurrentOddsQualityState(
        status="WARNING" if warnings else "PASS",
        warnings=warnings,
        additive_unsupported_markets=additive_markets,
    )
    provisional = OddsProviderCurrentInput.model_construct(
        schema_version="1.0.0",
        contract="ODDS_PROVIDER_CURRENT_INPUT",
        provider="the_odds_api",
        api_version="v4",
        sport_key="soccer_epl",
        region="uk",
        market="h2h,totals",
        odds_format="decimal",
        identity_scope="PROVIDER_NATIVE_UNMAPPED",
        events=events,
        temporal=temporal,
        quota=current_quota,
        rights=rights,
        provenance=provenance,
        quality=quality,
        market_semantic_sha256="0" * 64,
    )
    return OddsProviderCurrentInput(
        events=events,
        temporal=temporal,
        quota=current_quota,
        rights=rights,
        provenance=provenance,
        quality=quality,
        market_semantic_sha256=current_odds_market_semantic_sha256(provisional),
    )
