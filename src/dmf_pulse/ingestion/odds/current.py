"""Provider-native current The Odds API contract for GW1 readiness."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.config import (
    effective_config_sha256,
    load_provider_config,
    provider_config_sha256,
    rights_config_sha256,
)
from dmf_pulse.ingestion.odds.models import QuotaState
from dmf_pulse.ingestion.odds.parser import OddsEvent, ParsedOddsPayload
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
        if {outcome.outcome for outcome in self.outcomes} != {
            "HOME",
            "DRAW",
            "AWAY",
        }:
            raise ValueError("h2h market must contain HOME, DRAW and AWAY once")
        return self


class CurrentOddsBookmaker(_FrozenModel):
    bookmaker_key: str = Field(min_length=1, max_length=500)
    bookmaker_title: str = Field(min_length=1, max_length=500)
    provider_last_update: datetime
    age_at_receipt_seconds: int = Field(ge=0)
    markets: tuple[CurrentOddsMarket, ...] = Field(min_length=1, max_length=1)


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
    provider_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_request_id_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
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
        expected_names = {
            "regions",
            "markets",
            "oddsFormat",
            "dateFormat",
            "commenceTimeFrom",
        }
        parameters = dict(query)
        config = load_provider_config()
        if (
            len(query_names) != len(set(query_names))
            or set(query_names) != expected_names
            or parameters.get("regions") != "uk"
            or parameters.get("markets") != "h2h"
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

    @model_validator(mode="after")
    def validate_status(self) -> CurrentOddsQualityState:
        expected = "WARNING" if self.warnings else "PASS"
        if self.blockers or self.status != expected:
            raise ValueError("quality status contradicts findings")
        return self


class OddsProviderCurrentInput(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["ODDS_PROVIDER_CURRENT_INPUT"] = "ODDS_PROVIDER_CURRENT_INPUT"
    provider: Literal["the_odds_api"] = "the_odds_api"
    api_version: Literal["v4"] = "v4"
    sport_key: Literal["soccer_epl"] = "soccer_epl"
    region: Literal["uk"] = "uk"
    market: Literal["h2h"] = "h2h"
    odds_format: Literal["decimal"] = "decimal"
    identity_scope: Literal["PROVIDER_NATIVE_UNMAPPED"] = "PROVIDER_NATIVE_UNMAPPED"
    events: tuple[CurrentOddsEvent, ...] = Field(min_length=1)
    temporal: CurrentOddsTemporalState
    quota: CurrentOddsQuotaState
    rights: CurrentOddsRightsState
    provenance: CurrentOddsProvenance
    quality: CurrentOddsQualityState

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
        return self


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


def _rights_state(
    profile: RightsProfile,
    checked_at: datetime,
) -> CurrentOddsRightsState:
    required = (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.PRIVATE_INTERNAL_USE,
    )
    for capability in required:
        require_rights(profile, capability, checked_at=checked_at)

    def declared(
        capability: RightsCapability,
    ) -> Literal["ALLOW", "DENY", "UNKNOWN"]:
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
) -> tuple[CurrentOddsEvent, ...]:
    blockers: set[str] = set()
    current_events: list[CurrentOddsEvent] = []
    if not parsed.events:
        blockers.add("EMPTY_PROVIDER_RESPONSE")
    if parsed.duplicate_outcomes:
        blockers.add("DUPLICATE_OUTCOME")
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
            if any(market.key != "h2h" for market in bookmaker.markets):
                blockers.add("UNSUPPORTED_MARKET")
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
                outcomes=(
                    by_outcome["HOME"],
                    by_outcome["DRAW"],
                    by_outcome["AWAY"],
                ),
            )
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

    if blockers:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "provider-native odds response failed current-input quality gates",
            details={"blockers": sorted(blockers)},
        )
    return tuple(current_events)


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
    provider_request_id_sha256: str | None,
) -> OddsProviderCurrentInput:
    """Validate one response into a cutoff-safe provider-native current input."""

    config = load_provider_config()
    times = (
        request_started_at,
        received_at,
        information_cutoff,
        usable_at,
        quota.observed_at,
    )
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):
        raise IngestionError(
            "VALIDATION_FAILED",
            "current odds timestamps must be timezone-aware",
        )
    request_started = request_started_at.astimezone(UTC)
    received = received_at.astimezone(UTC)
    cutoff = information_cutoff.astimezone(UTC)
    usable = usable_at.astimezone(UTC)
    if received > cutoff or usable > cutoff:
        raise IngestionError(
            "POST_CUTOFF",
            "odds response was not usable by the cutoff",
        )
    if request_started > received or usable < received:
        raise IngestionError(
            "CLOCK_REGRESSION",
            "current odds temporal order is invalid",
        )
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

    events = _provider_events(
        parsed,
        received_at=received,
        information_cutoff=cutoff,
    )
    warnings = tuple(sorted(set(parsed.warnings)))
    return OddsProviderCurrentInput(
        events=events,
        temporal=CurrentOddsTemporalState(
            request_started_at=request_started,
            received_at=received,
            captured_at=received,
            information_cutoff=cutoff,
            usable_at=usable,
        ),
        quota=CurrentOddsQuotaState(
            remaining=quota.remaining,
            used=quota.used,
            configured_request_cost=config.request_cost,
            provider_last_request_cost=quota.last_cost,
            observed_at=quota.observed_at,
        ),
        rights=_rights_state(profile, received),
        provenance=CurrentOddsProvenance(
            source_snapshot_id=source_snapshot_id,
            sanitized_target=sanitized_target,
            attempt_count=attempt_count,
            transport_call_count=transport_call_count,
            provider_config_sha256=provider_config_sha256(),
            rights_config_sha256=rights_config_sha256(),
            effective_config_sha256=effective_config_sha256(),
            request_fingerprint=request_fingerprint,
            provider_request_id_sha256=provider_request_id_sha256,
            response_body_sha256=parsed.body_sha256,
            adapter_version=config.adapter_version,
            contract_version=config.contract_version,
        ),
        quality=CurrentOddsQualityState(
            status="WARNING" if warnings else "PASS",
            warnings=warnings,
        ),
    )
