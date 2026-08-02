"""Bounded strict parser for the frozen FPL-004 reference payload contract."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.config import load_provider_config
from dmf_pulse.ingestion.models import DriftClassification, SchemaDriftReport

MAX_PAYLOAD_BYTES = 5 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_COLLECTION_ITEMS = 100_000
CONTRACT_VERSION = "fpl-reference-v1"
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class FplResource(StrEnum):
    BOOTSTRAP = "bootstrap"
    FIXTURES = "fixtures"


def parse_rfc3339_timestamp(value: str) -> datetime:
    """Parse only the RFC 3339 grammar accepted by the frozen contract."""

    if RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError("timestamp must be valid RFC3339")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("timestamp must be valid RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(UTC)


def _aware_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp must be an RFC3339 string")
    return parse_rfc3339_timestamp(value)


class PayloadModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)
    optional_fields: ClassVar[frozenset[str]] = frozenset()


class Event(PayloadModel):
    id: StrictInt = Field(gt=0)
    name: StrictStr = Field(min_length=1)
    deadline_time: datetime
    finished: StrictBool | None = None
    data_checked: StrictBool | None = None
    is_previous: StrictBool | None = None
    is_current: StrictBool | None = None
    is_next: StrictBool | None = None
    average_entry_score: StrictInt | None = None
    highest_score: StrictInt | None = None
    optional_fields = frozenset(
        {
            "finished",
            "data_checked",
            "is_previous",
            "is_current",
            "is_next",
            "average_entry_score",
            "highest_score",
        }
    )

    @field_validator("deadline_time", mode="before")
    @classmethod
    def parse_deadline(cls, value: object) -> datetime:
        parsed = _aware_datetime(value)
        if parsed is None:
            raise ValueError("deadline_time cannot be null")
        return parsed


class Team(PayloadModel):
    id: StrictInt = Field(gt=0)
    code: StrictInt = Field(gt=0)
    name: StrictStr = Field(min_length=1)
    short_name: StrictStr = Field(min_length=1)
    strength: StrictInt | None = None
    strength_overall_home: StrictInt | None = None
    strength_overall_away: StrictInt | None = None
    strength_attack_home: StrictInt | None = None
    strength_attack_away: StrictInt | None = None
    strength_defence_home: StrictInt | None = None
    strength_defence_away: StrictInt | None = None
    position: StrictInt | None = None
    played: StrictInt | None = None
    win: StrictInt | None = None
    draw: StrictInt | None = None
    loss: StrictInt | None = None
    points: StrictInt | None = None
    optional_fields = frozenset(
        {
            "strength",
            "strength_overall_home",
            "strength_overall_away",
            "strength_attack_home",
            "strength_attack_away",
            "strength_defence_home",
            "strength_defence_away",
            "position",
            "played",
            "win",
            "draw",
            "loss",
            "points",
        }
    )


class PlayerElement(PayloadModel):
    id: StrictInt = Field(gt=0)
    code: StrictInt = Field(gt=0)
    first_name: StrictStr
    second_name: StrictStr = Field(min_length=1)
    web_name: StrictStr = Field(min_length=1)
    team: StrictInt = Field(gt=0)
    element_type: StrictInt = Field(gt=0)
    now_cost: StrictInt = Field(ge=0)
    status: StrictStr = Field(min_length=1)
    chance_of_playing_next_round: StrictInt | None = Field(default=None, ge=0, le=100)
    chance_of_playing_this_round: StrictInt | None = Field(default=None, ge=0, le=100)
    news: StrictStr | None = None
    news_added: datetime | None = None
    selected_by_percent: Decimal | None = None
    transfers_in: StrictInt | None = Field(default=None, ge=0)
    transfers_out: StrictInt | None = Field(default=None, ge=0)
    transfers_in_event: StrictInt | None = Field(default=None, ge=0)
    transfers_out_event: StrictInt | None = Field(default=None, ge=0)
    cost_change_start: StrictInt | None = None
    cost_change_event: StrictInt | None = None
    cost_change_start_fall: StrictInt | None = None
    cost_change_event_fall: StrictInt | None = None
    minutes: StrictInt | None = Field(default=None, ge=0)
    total_points: StrictInt | None = None
    optional_fields = frozenset(
        {
            "chance_of_playing_next_round",
            "chance_of_playing_this_round",
            "news",
            "news_added",
            "selected_by_percent",
            "transfers_in",
            "transfers_out",
            "transfers_in_event",
            "transfers_out_event",
            "cost_change_start",
            "cost_change_event",
            "cost_change_start_fall",
            "cost_change_event_fall",
            "minutes",
            "total_points",
        }
    )

    @field_validator("news_added", mode="before")
    @classmethod
    def parse_news_time(cls, value: object) -> datetime | None:
        return _aware_datetime(value)

    @field_validator("selected_by_percent", mode="before")
    @classmethod
    def parse_percentage(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("percentage must be a decimal string or number")
        try:
            parsed = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("percentage is not decimal") from exc
        if not parsed.is_finite() or parsed < 0 or parsed > 100:
            raise ValueError("percentage must be between zero and one hundred")
        return parsed


class ElementType(PayloadModel):
    id: StrictInt = Field(gt=0)
    singular_name: StrictStr = Field(min_length=1)
    singular_name_short: StrictStr = Field(min_length=1)
    plural_name: StrictStr = Field(min_length=1)
    plural_name_short: StrictStr = Field(min_length=1)
    squad_select: StrictInt = Field(gt=0)
    squad_min_play: StrictInt = Field(ge=0)
    squad_max_play: StrictInt = Field(gt=0)
    ui_shirt_specific: StrictBool | None = None
    sub_positions_locked: list[Any] | None = None
    optional_fields = frozenset({"ui_shirt_specific", "sub_positions_locked"})


class BootstrapPayload(PayloadModel):
    events: list[Event]
    game_settings: dict[str, Any]
    teams: list[Team]
    elements: list[PlayerElement]
    element_types: list[ElementType]
    phases: list[Any] | None = None
    total_players: StrictInt | None = Field(default=None, ge=0)
    element_stats: list[Any] | None = None
    optional_fields = frozenset({"phases", "total_players", "element_stats"})


class Fixture(PayloadModel):
    id: StrictInt = Field(gt=0)
    code: StrictInt = Field(gt=0)
    event: StrictInt | None = Field(gt=0)
    team_h: StrictInt = Field(gt=0)
    team_a: StrictInt = Field(gt=0)
    kickoff_time: datetime | None
    finished: StrictBool
    started: StrictBool | None = None
    finished_provisional: StrictBool | None = None
    minutes: StrictInt | None = Field(default=None, ge=0)
    team_h_score: StrictInt | None = None
    team_a_score: StrictInt | None = None
    team_h_difficulty: StrictInt | None = None
    team_a_difficulty: StrictInt | None = None
    provisional_start_time: StrictBool | None = None
    stats: list[Any] | None = None
    optional_fields = frozenset(
        {
            "started",
            "finished_provisional",
            "minutes",
            "team_h_score",
            "team_a_score",
            "team_h_difficulty",
            "team_a_difficulty",
            "provisional_start_time",
            "stats",
        }
    )

    @field_validator("kickoff_time", mode="before")
    @classmethod
    def parse_kickoff(cls, value: object) -> datetime | None:
        return _aware_datetime(value)


class FixturePayload(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    fixtures: list[Fixture]


class ParsedFplResource(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True
    )
    resource: FplResource
    payload: BootstrapPayload | FixturePayload
    payload_sha256: str
    semantic_sha256: str
    drift: SchemaDriftReport


def parsed_artifact(value: ParsedFplResource) -> dict[str, object]:
    """Return a declared-field artifact that preserves absent versus explicit null."""

    def declared(item: object) -> object:
        if isinstance(item, BaseModel):
            return {
                name: declared(getattr(item, name))
                for name, field in item.__class__.model_fields.items()
                if field.is_required() or name in item.model_fields_set
            }
        if isinstance(item, list):
            return [declared(child) for child in item]
        if isinstance(item, tuple):
            return [declared(child) for child in item]
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, (FplResource, DriftClassification)):
            return item.value
        return item

    artifact = declared(value)
    if not isinstance(artifact, dict):
        raise IngestionError("INTERNAL_INVARIANT", "parsed artifact is invalid")
    return artifact


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid numeric constant {value}")


def _pairs_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IngestionError(
                "DUPLICATE_JSON_KEY",
                "JSON contains a duplicate object key",
                details={"classification": DriftClassification.MALFORMED.value},
            )
        result[key] = value
    return result


def _check_depth(text: str, *, maximum: int = MAX_JSON_DEPTH) -> None:
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
                raise IngestionError(
                    "PAYLOAD_TOO_DEEP",
                    "JSON nesting exceeds the configured limit",
                    details={"classification": DriftClassification.LIMIT_EXCEEDED.value},
                )
        elif character in "]}":
            depth -= 1


def _check_collection_limits(value: object) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if len(current) > MAX_COLLECTION_ITEMS:
                raise IngestionError("PAYLOAD_TOO_LARGE", "payload object exceeds its item limit")
            pending.extend(current.values())
        elif isinstance(current, list):
            if len(current) > MAX_COLLECTION_ITEMS:
                raise IngestionError(
                    "PAYLOAD_TOO_LARGE", "payload collection exceeds its item limit"
                )
            pending.extend(current)


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


def _type_paths(value: object, path: str = "$") -> dict[str, str]:
    """Return an order-independent schema signature without losing array types.

    Array members intentionally share a semantic ``[]`` path.  Every observed
    JSON type at that path is retained in a sorted, pipe-delimited set instead
    of allowing the final member to overwrite earlier heterogeneous members.
    """

    observed: dict[str, set[str]] = {}

    def visit(item: object, item_path: str) -> None:
        observed.setdefault(item_path, set()).add(_json_type(item))
        if isinstance(item, dict):
            for key in sorted(item):
                visit(item[key], f"{item_path}.{key}")
        elif isinstance(item, list):
            for child in item:
                visit(child, f"{item_path}[]")

    visit(value, path)
    return {item_path: "|".join(sorted(kinds)) for item_path, kinds in sorted(observed.items())}


def _contract_projection(value: object) -> object:
    if isinstance(value, BaseModel):
        projection: dict[str, object] = {}
        for name, field in value.__class__.model_fields.items():
            if name not in value.model_fields_set and not field.is_required():
                projection[name] = {"missingness": "NOT_PUBLISHED"}
            else:
                projection[name] = _contract_projection(getattr(value, name))
        return projection
    if isinstance(value, list):
        return [_contract_projection(item) for item in value]
    if isinstance(value, tuple):
        return [_contract_projection(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        rendered = format(value, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    return value


def _drift_paths(value: object, path: str = "$") -> tuple[list[str], list[str]]:
    unknown: list[str] = []
    missing_optional: list[str] = []
    if isinstance(value, PayloadModel):
        for key in sorted(value.model_extra or {}):
            unknown.append(f"{path}.{key}")
        fields_set = value.model_fields_set
        for field in sorted(value.optional_fields - fields_set):
            missing_optional.append(f"{path}.{field}")
        for field in value.__class__.model_fields:
            child = getattr(value, field)
            child_path = f"{path}.{field}"
            if isinstance(child, list):
                for index, item in enumerate(child):
                    child_unknown, child_missing = _drift_paths(item, f"{child_path}[{index}]")
                    unknown.extend(child_unknown)
                    missing_optional.extend(child_missing)
            else:
                child_unknown, child_missing = _drift_paths(child, child_path)
                unknown.extend(child_unknown)
                missing_optional.extend(child_missing)
    elif isinstance(value, FixturePayload):
        for index, item in enumerate(value.fixtures):
            child_unknown, child_missing = _drift_paths(item, f"$[{index}]")
            unknown.extend(child_unknown)
            missing_optional.extend(child_missing)
    return unknown, missing_optional


def _error_path(location: tuple[int | str, ...]) -> str:
    path = "$"
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _validate_semantics(resource: FplResource, payload: BootstrapPayload | FixturePayload) -> None:
    if resource is FplResource.BOOTSTRAP:
        if not isinstance(payload, BootstrapPayload):
            raise IngestionError("INTERNAL_INVARIANT", "bootstrap payload model is invalid")
        team_ids = [item.id for item in payload.teams]
        team_codes = [item.code for item in payload.teams]
        type_ids = [item.id for item in payload.element_types]
        event_ids = [item.id for item in payload.events]
        if (
            len(team_ids) != len(set(team_ids))
            or len(team_codes) != len(set(team_codes))
            or len(type_ids) != len(set(type_ids))
        ):
            raise IngestionError("VALIDATION_FAILED", "provider identifiers are duplicated")
        if len(event_ids) != len(set(event_ids)):
            raise IngestionError("VALIDATION_FAILED", "Gameweek identifiers are duplicated")
        player_ids = [item.id for item in payload.elements]
        player_codes = [item.code for item in payload.elements]
        if len(player_ids) != len(set(player_ids)) or len(player_codes) != len(set(player_codes)):
            raise IngestionError("VALIDATION_FAILED", "player identifiers are duplicated")
        if any(item.team not in team_ids for item in payload.elements):
            raise IngestionError("VALIDATION_FAILED", "player references an unknown team")
        if any(item.element_type not in type_ids for item in payload.elements):
            raise IngestionError("VALIDATION_FAILED", "player references an unknown position")
    else:
        if not isinstance(payload, FixturePayload):
            raise IngestionError("INTERNAL_INVARIANT", "fixture payload model is invalid")
        identifiers = [item.id for item in payload.fixtures]
        codes = [item.code for item in payload.fixtures]
        if len(identifiers) != len(set(identifiers)) or len(codes) != len(set(codes)):
            raise IngestionError("VALIDATION_FAILED", "fixture identifiers are duplicated")
        for item in payload.fixtures:
            if item.team_h == item.team_a:
                raise IngestionError("VALIDATION_FAILED", "fixture teams must differ")
            score_present = item.team_h_score is not None or item.team_a_score is not None
            if score_present and not bool(item.started or item.finished):
                raise IngestionError(
                    "VALIDATION_FAILED", "fixture score lacks started or finished evidence"
                )


def parse_fpl_payload(
    resource: FplResource,
    body: bytes,
    *,
    contract_version: str = CONTRACT_VERSION,
) -> ParsedFplResource:
    """Parse exact bytes into a strict model and deterministic drift report."""

    config = load_provider_config()
    payload_sha256 = hashlib.sha256(body).hexdigest()
    if contract_version != config.contract_version:
        raise IngestionError("CONFIGURATION_INVALID", "unsupported FPL contract version")
    if len(body) > config.max_response_bytes:
        raise IngestionError(
            "PAYLOAD_TOO_LARGE",
            "payload exceeds the configured byte limit",
            details={"classification": DriftClassification.LIMIT_EXCEEDED.value},
        )
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise IngestionError(
            "MALFORMED_JSON",
            "payload is not valid UTF-8 JSON",
            details={"classification": DriftClassification.MALFORMED.value},
        ) from None
    _check_depth(text, maximum=config.max_json_depth)
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_pairs_object,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except IngestionError:
        raise
    except (json.JSONDecodeError, ValueError):
        raise IngestionError(
            "MALFORMED_JSON",
            "payload is not valid JSON",
            details={"classification": DriftClassification.MALFORMED.value},
        ) from None
    if resource is FplResource.BOOTSTRAP and not isinstance(decoded, dict):
        raise IngestionError("VALIDATION_FAILED", "bootstrap root must be an object")
    if resource is FplResource.FIXTURES and not isinstance(decoded, list):
        raise IngestionError("VALIDATION_FAILED", "fixtures root must be an array")
    _check_collection_limits(decoded)
    try:
        if resource is FplResource.BOOTSTRAP:
            payload: BootstrapPayload | FixturePayload = BootstrapPayload.model_validate(decoded)
        else:
            payload = FixturePayload.model_validate({"fixtures": decoded})
    except ValidationError as exc:
        missing = sorted(
            _error_path(tuple(error["loc"]))
            for error in exc.errors(include_url=False)
            if error["type"] == "missing"
        )
        type_errors = sorted(
            _error_path(tuple(error["loc"]))
            for error in exc.errors(include_url=False)
            if error["type"] != "missing"
        )
        classification = (
            DriftClassification.BLOCKING_MISSING_REQUIRED
            if missing
            else DriftClassification.BLOCKING_TYPE_CHANGE
        )
        raise IngestionError(
            "VALIDATION_FAILED",
            "payload does not satisfy the FPL reference contract",
            details={
                "classification": classification.value,
                "missing_required_paths": missing,
                "type_error_paths": type_errors,
            },
        ) from None
    _validate_semantics(resource, payload)
    unknown, missing_optional = _drift_paths(payload)
    observed_fingerprint = canonical_sha256(_type_paths(decoded))
    projection = _contract_projection(payload)
    schema_fingerprint = canonical_sha256(_type_paths(projection))
    classification = (
        DriftClassification.ADDITIVE_UNKNOWN
        if unknown
        else DriftClassification.MISSING_OPTIONAL
        if missing_optional
        else DriftClassification.NO_DRIFT
    )
    drift = SchemaDriftReport(
        contract_version=contract_version,
        classification=classification,
        unknown_paths=tuple(sorted(unknown)),
        missing_optional_paths=tuple(sorted(missing_optional)),
        payload_sha256=payload_sha256,
        observed_type_fingerprint=observed_fingerprint,
        schema_fingerprint=schema_fingerprint,
    )
    return ParsedFplResource(
        resource=resource,
        payload=payload,
        payload_sha256=payload_sha256,
        semantic_sha256=canonical_sha256(projection),
        drift=drift,
    )
