"""Bounded strict parser for synthetic The Odds API v4-shaped payloads."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import parse_rfc3339_timestamp
from dmf_pulse.ingestion.odds.config import OddsProviderConfig, load_provider_config
from dmf_pulse.markets.models import canonical_decimal_text

CONTRACT_VERSION = "the-odds-api-v4-reference-v1"
SOURCE_PRICE_PATTERN = re.compile(r"^(?:1\.\d*[1-9]\d*|(?:[2-9]\d*|1\d+)\.\d+)$")


class _SourceDecimal(Decimal):
    """Decimal retaining the JSON token for field-specific lexical validation."""

    lexical: str


def _source_decimal(value: str) -> Decimal:
    parsed = _SourceDecimal(value)
    parsed.lexical = value
    return parsed


class OddsPayloadModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)
    optional_fields: ClassVar[frozenset[str]] = frozenset()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an RFC3339 string")
    return parse_rfc3339_timestamp(value)


def _decimal(value: object, maximum: int) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError("price must be an exact decimal")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("price must be an exact decimal") from exc
    if not parsed.is_finite():
        raise ValueError("price must be finite")
    if (
        len(parsed.as_tuple().digits) > maximum
        or abs(parsed.adjusted()) > maximum
        or len(format(parsed, "f")) > maximum
    ):
        raise ValueError("decimal magnitude exceeds the limit")
    return parsed


class OddsOutcome(OddsPayloadModel):
    name: StrictStr = Field(min_length=1, max_length=500)
    price: Decimal
    point: Decimal | None = None
    optional_fields = frozenset({"point"})

    @field_validator("price", mode="before")
    @classmethod
    def parse_price(cls, value: object, info: ValidationInfo) -> Decimal:
        maximum = int((info.context or {}).get("max_text_length", 500))
        if (
            isinstance(value, _SourceDecimal)
            and SOURCE_PRICE_PATTERN.fullmatch(value.lexical) is None
        ):
            raise ValueError("decimal odds token violates the source-scale contract")
        parsed = _decimal(value, maximum)
        if parsed <= 1:
            raise ValueError("decimal odds must be greater than one")
        return parsed

    @field_validator("point", mode="before")
    @classmethod
    def parse_point(cls, value: object, info: ValidationInfo) -> Decimal | None:
        maximum = int((info.context or {}).get("max_text_length", 500))
        return None if value is None else _decimal(value, maximum)


class OddsMarket(OddsPayloadModel):
    key: StrictStr = Field(min_length=1, max_length=500)
    last_update: datetime | None = None
    outcomes: tuple[OddsOutcome, ...]
    optional_fields = frozenset({"last_update"})

    @field_validator("last_update", mode="before")
    @classmethod
    def parse_last_update(cls, value: object) -> datetime | None:
        return None if value is None else _timestamp(value)


class OddsBookmaker(OddsPayloadModel):
    key: StrictStr = Field(min_length=1, max_length=500)
    title: StrictStr = Field(min_length=1, max_length=500)
    last_update: datetime
    markets: tuple[OddsMarket, ...]

    @field_validator("last_update", mode="before")
    @classmethod
    def parse_last_update(cls, value: object) -> datetime:
        return _timestamp(value)


class OddsEvent(OddsPayloadModel):
    id: StrictStr = Field(min_length=1, max_length=500)
    sport_key: StrictStr
    sport_title: StrictStr | None = Field(default=None, max_length=500)
    commence_time: datetime
    home_team: StrictStr = Field(min_length=1, max_length=500)
    away_team: StrictStr = Field(min_length=1, max_length=500)
    bookmakers: tuple[OddsBookmaker, ...]
    optional_fields = frozenset({"sport_title"})

    @field_validator("commence_time", mode="before")
    @classmethod
    def parse_commence_time(cls, value: object) -> datetime:
        return _timestamp(value)

    @field_validator("sport_key")
    @classmethod
    def validate_sport_key(cls, value: str) -> str:
        if value != "soccer_epl":
            raise ValueError("sport_key is not allowlisted")
        return value


@dataclass(frozen=True, slots=True)
class DuplicateOutcomeEvidence:
    event_external_id_sha256: str
    bookmaker_key: str
    market_key: str
    outcome: str
    duplicate_count: int


@dataclass(frozen=True, slots=True)
class ParsedOddsPayload:
    events: tuple[OddsEvent, ...]
    body_sha256: str
    semantic_sha256: str
    schema_fingerprint: str
    warnings: tuple[str, ...]
    duplicate_outcomes: tuple[DuplicateOutcomeEvidence, ...]

    @property
    def operator_books_seen(self) -> int:
        return sum(len(event.bookmakers) for event in self.events)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IngestionError("DUPLICATE_JSON_KEY", "JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid numeric constant {value}")


def _decode_utf8(body: bytes) -> str | None:
    try:
        return body.decode("utf-8")
    except UnicodeError:
        return None


def _load_json(text: str) -> tuple[object | None, str | None]:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_source_decimal,
            parse_constant=_reject_constant,
        )
    except IngestionError as exc:
        return None, exc.code
    except (json.JSONDecodeError, ValueError):
        return None, "MALFORMED_JSON"
    return value, None


def _check_depth(text: str, maximum: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > maximum:
                raise IngestionError("PAYLOAD_TOO_DEEP", "JSON nesting exceeds the limit")
        elif character in "]}":
            depth -= 1
    if depth != 0 or in_string:
        raise IngestionError("MALFORMED_JSON", "provider JSON is malformed")


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _type_paths(value: object) -> dict[str, str]:
    observed: dict[str, set[str]] = {}

    def visit(item: object, path: str) -> None:
        observed.setdefault(path, set()).add(_json_type(item))
        if isinstance(item, dict):
            for key in sorted(item):
                visit(item[key], f"{path}.{key}")
        elif isinstance(item, list):
            for child in item:
                visit(child, f"{path}[]")

    visit(value, "$")
    return {path: "|".join(sorted(kinds)) for path, kinds in sorted(observed.items())}


def _check_text_limits(value: object, maximum: int) -> None:
    if isinstance(value, str):
        if len(value) > maximum:
            raise IngestionError("PAYLOAD_TOO_LARGE", "provider text exceeds the limit")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise IngestionError("VALIDATION_FAILED", "provider text contains invalid Unicode")
        return
    if isinstance(value, list):
        for item in value:
            _check_text_limits(item, maximum)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if len(key) > maximum:
                raise IngestionError("PAYLOAD_TOO_LARGE", "provider text exceeds the limit")
            if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                raise IngestionError("VALIDATION_FAILED", "provider text contains invalid Unicode")
            _check_text_limits(item, maximum)


def _check_numeric_limits(value: object, maximum: int) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if value.bit_length() > maximum * 4 or len(str(abs(value))) > maximum:
            raise IngestionError("PAYLOAD_TOO_LARGE", "provider number exceeds the limit")
        return
    if isinstance(value, Decimal):
        if (
            not value.is_finite()
            or len(value.as_tuple().digits) > maximum
            or abs(value.adjusted()) > maximum
            or len(format(value, "f")) > maximum
        ):
            raise IngestionError("PAYLOAD_TOO_LARGE", "provider number exceeds the limit")
        return
    if isinstance(value, list):
        for item in value:
            _check_numeric_limits(item, maximum)
        return
    if isinstance(value, dict):
        for item in value.values():
            _check_numeric_limits(item, maximum)


def _semantic(value: object) -> object:
    if isinstance(value, BaseModel):
        result: dict[str, object] = {}
        for name, field in value.__class__.model_fields.items():
            if name not in value.model_fields_set and not field.is_required():
                result[name] = {"missingness": "NOT_PUBLISHED"}
            else:
                result[name] = _semantic(getattr(value, name))
        for key, item in sorted((value.model_extra or {}).items()):
            result[key] = _semantic(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_semantic(item) for item in value]
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in sorted(value.items())}
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    return value


def _unknown_paths(value: object, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, BaseModel):
        paths.extend(f"{path}.{key}" for key in sorted(value.model_extra or {}))
        for name in value.__class__.model_fields:
            child = getattr(value, name)
            if isinstance(child, tuple):
                for index, item in enumerate(child):
                    paths.extend(_unknown_paths(item, f"{path}.{name}[{index}]"))
            else:
                paths.extend(_unknown_paths(child, f"{path}.{name}"))
    return paths


def _safe_outcome_key(event: OddsEvent, name: str) -> str:
    if name == event.home_team:
        return "HOME"
    if name == event.away_team:
        return "AWAY"
    if name.casefold() == "draw":
        return "DRAW"
    return "UNMAPPED"


def _outcome_identity(event: OddsEvent, name: str) -> tuple[str, str]:
    canonical = _safe_outcome_key(event, name)
    return ("CANONICAL", canonical) if canonical != "UNMAPPED" else ("SOURCE", name)


def _market_outcome_identity(
    event: OddsEvent,
    market: OddsMarket,
    outcome: OddsOutcome,
) -> tuple[str, ...]:
    """Keep distinct totals lines distinct while preserving H2H duplicate rules."""

    identity = _outcome_identity(event, outcome.name)
    if market.key != "totals":
        return identity
    point = "MISSING" if outcome.point is None else canonical_decimal_text(outcome.point)
    return (*identity, point)


def _validate_limits(events: tuple[OddsEvent, ...], config: OddsProviderConfig) -> None:
    if len(events) > config.max_events:
        raise IngestionError("PAYLOAD_TOO_LARGE", "provider event count exceeds the limit")
    event_ids: set[str] = set()
    for event in events:
        if event.id in event_ids:
            raise IngestionError("VALIDATION_FAILED", "provider event identifier is duplicated")
        event_ids.add(event.id)
        if event.home_team == event.away_team:
            raise IngestionError("VALIDATION_FAILED", "event participants must differ")
        if len(event.bookmakers) > config.max_bookmakers_per_event:
            raise IngestionError("PAYLOAD_TOO_LARGE", "bookmaker count exceeds the limit")
        bookmaker_keys: set[str] = set()
        for bookmaker in event.bookmakers:
            if bookmaker.key in bookmaker_keys:
                raise IngestionError("VALIDATION_FAILED", "bookmaker key is duplicated")
            bookmaker_keys.add(bookmaker.key)
            if len(bookmaker.markets) > config.max_markets_per_bookmaker:
                raise IngestionError("PAYLOAD_TOO_LARGE", "market count exceeds the limit")
            market_keys: set[str] = set()
            for market in bookmaker.markets:
                if market.key in market_keys:
                    raise IngestionError("VALIDATION_FAILED", "market key is duplicated")
                market_keys.add(market.key)
                if len(market.outcomes) > config.max_outcomes_per_market:
                    raise IngestionError("PAYLOAD_TOO_LARGE", "outcome count exceeds the limit")
                by_outcome: dict[tuple[str, ...], tuple[Decimal, Decimal | None]] = {}
                for outcome in market.outcomes:
                    identity = _market_outcome_identity(event, market, outcome)
                    previous = by_outcome.get(identity)
                    candidate = (outcome.price, outcome.point)
                    if previous is not None and previous != candidate:
                        raise IngestionError(
                            "VALIDATION_FAILED", "operator market has conflicting outcomes"
                        )
                    by_outcome[identity] = candidate


def _deduplicate_equal_outcomes(
    events: tuple[OddsEvent, ...],
) -> tuple[tuple[OddsEvent, ...], tuple[DuplicateOutcomeEvidence, ...]]:
    deduped_events: list[OddsEvent] = []
    evidence: list[DuplicateOutcomeEvidence] = []
    for event in events:
        bookmakers: list[OddsBookmaker] = []
        for bookmaker in event.bookmakers:
            markets: list[OddsMarket] = []
            for market in bookmaker.markets:
                outcomes: list[OddsOutcome] = []
                positions: dict[tuple[str, ...], int] = {}
                duplicate_counts: dict[tuple[str, ...], int] = {}
                for outcome in market.outcomes:
                    identity = _market_outcome_identity(event, market, outcome)
                    if identity in positions:
                        duplicate_counts[identity] = duplicate_counts.get(identity, 0) + 1
                        continue
                    positions[identity] = len(outcomes)
                    outcomes.append(outcome)
                for identity, count in sorted(duplicate_counts.items()):
                    retained = outcomes[positions[identity]]
                    evidence.append(
                        DuplicateOutcomeEvidence(
                            event_external_id_sha256=canonical_sha256(event.id),
                            bookmaker_key=bookmaker.key,
                            market_key=market.key,
                            outcome=_safe_outcome_key(event, retained.name),
                            duplicate_count=count,
                        )
                    )
                markets.append(market.model_copy(update={"outcomes": tuple(outcomes)}))
            bookmakers.append(bookmaker.model_copy(update={"markets": tuple(markets)}))
        deduped_events.append(event.model_copy(update={"bookmakers": tuple(bookmakers)}))
    return tuple(deduped_events), tuple(evidence)


def _parse_events(
    raw: list[object], config: OddsProviderConfig
) -> tuple[tuple[OddsEvent, ...] | None, tuple[str, ...]]:
    try:
        events = tuple(
            OddsEvent.model_validate(
                item,
                strict=False,
                context={"max_text_length": config.max_text_length},
            )
            for item in raw
        )
    except ValidationError as exc:
        paths = tuple(
            sorted(
                ".".join(str(part) for part in error["loc"])
                for error in exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            )[:20]
        )
        return None, paths
    return events, ()


def parse_odds_payload(body: bytes) -> ParsedOddsPayload:
    """Parse one bounded body without performing transport or persistence."""

    config = load_provider_config()
    if len(body) > config.max_response_bytes:
        raise IngestionError("PAYLOAD_TOO_LARGE", "provider response exceeds the byte limit")
    text = _decode_utf8(body)
    if text is None:
        raise IngestionError("MALFORMED_JSON", "provider JSON is not UTF-8")
    _check_depth(text, config.max_json_depth)
    raw, load_error = _load_json(text)
    if load_error == "DUPLICATE_JSON_KEY":
        raise IngestionError("DUPLICATE_JSON_KEY", "JSON contains a duplicate object key")
    if load_error is not None:
        raise IngestionError("MALFORMED_JSON", "provider JSON is malformed")
    if not isinstance(raw, list):
        raise IngestionError("VALIDATION_FAILED", "provider response must be a top-level array")
    _check_text_limits(raw, config.max_text_length)
    _check_numeric_limits(raw, config.max_text_length)
    # JSON arrays are decoded as lists. Permit that representation at the
    # model boundary while strict field validators reject provider coercions.
    events, invalid_paths = _parse_events(raw, config)
    if events is None:
        raise IngestionError(
            "VALIDATION_FAILED",
            "provider payload violates the reference contract",
            details={"invalid_paths": list(invalid_paths)},
        )
    _validate_limits(events, config)
    events, duplicate_outcomes = _deduplicate_equal_outcomes(events)
    warnings = [f"ADDITIVE_UNKNOWN:{path}" for event in events for path in _unknown_paths(event)]
    warnings.extend(
        f"ADDITIVE_UNSUPPORTED_MARKET:{market.key}"
        for event in events
        for bookmaker in event.bookmakers
        for market in bookmaker.markets
        if market.key not in config.markets
    )
    if duplicate_outcomes:
        warnings.append("DUPLICATE_OUTCOME_DEDUPED")
    return ParsedOddsPayload(
        events=events,
        body_sha256=hashlib.sha256(body).hexdigest(),
        semantic_sha256=canonical_sha256(_semantic(events)),
        schema_fingerprint=canonical_sha256(_type_paths(raw)),
        warnings=tuple(sorted(set(warnings))),
        duplicate_outcomes=duplicate_outcomes,
    )
