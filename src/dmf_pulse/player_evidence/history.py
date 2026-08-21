"""Guarded future history-past parsing and serial capture boundary.

Raw response bytes exist only in local variables while a response is parsed.
They are never accepted by a persistence API, emitted, or returned.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import sleep
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.models import (
    CurrentPlayerCatalogue,
    DeletionManifest,
    HistoryPastSeason,
    PlayerHistoryEvidence,
    PlayerHistoryRightsApproval,
    RetentionMode,
)

_REQUIRED_FIELDS = {
    "season_name",
    "minutes",
    "goals_scored",
    "assists",
    "yellow_cards",
    "red_cards",
}

_SAFE_CAPTURE_CODES = frozenset(
    {
        "HISTORY_JSON_INVALID",
        "HISTORY_ROOT_INVALID",
        "HISTORY_NODE_INVALID",
        "HISTORY_REQUIRED_FIELD_MISSING",
        "HISTORY_FIELD_TYPE_INVALID",
        "HISTORY_SEASON_INVALID",
        "HISTORY_FUTURE_SEASON",
        "HISTORY_DUPLICATE_SEASON",
        "HISTORY_GOALKEEPER_SAVES_MISSING",
        "HISTORY_MODEL_VALIDATION_FAILED",
        "HISTORY_SCHEMA_DRIFT",
        "HISTORY_HTTP_BLOCKED",
        "HISTORY_AUTHENTICATION_BLOCKED",
        "HISTORY_RATE_LIMITED",
        "POST_CUTOFF",
        "NETWORK_UNAVAILABLE",
    }
)

_SAFE_CAPTURE_MESSAGES = {
    "HISTORY_JSON_INVALID": "history response is not valid JSON",
    "HISTORY_ROOT_INVALID": "history response root is invalid",
    "HISTORY_NODE_INVALID": "history_past node is invalid",
    "HISTORY_REQUIRED_FIELD_MISSING": "history required field is missing",
    "HISTORY_FIELD_TYPE_INVALID": "history field type is invalid",
    "HISTORY_SEASON_INVALID": "history season is invalid",
    "HISTORY_FUTURE_SEASON": "history contains a future season",
    "HISTORY_DUPLICATE_SEASON": "history contains duplicate seasons",
    "HISTORY_GOALKEEPER_SAVES_MISSING": "goalkeeper history lacks saves",
    "HISTORY_MODEL_VALIDATION_FAILED": "history model validation failed",
    "HISTORY_SCHEMA_DRIFT": "history schema fingerprint has changed",
    "HISTORY_HTTP_BLOCKED": "history capture received a non-success response",
    "HISTORY_AUTHENTICATION_BLOCKED": "history capture requires authentication",
    "HISTORY_RATE_LIMITED": "history capture received HTTP 429",
    "POST_CUTOFF": "successful history receipt is after the information cutoff",
    "NETWORK_UNAVAILABLE": "official FPL history request failed",
}


def _history_error(
    code: str,
    *,
    model_validation_reason: str | None = None,
) -> IngestionError:
    """Create a source-body-free parser/model failure."""

    details: dict[str, object] | None = (
        {"model_validation_reason": model_validation_reason}
        if model_validation_reason is not None
        else None
    )
    return IngestionError(code, _SAFE_CAPTURE_MESSAGES[code], details=details)


def _failure_stage(code: str) -> str:
    if code in {"HISTORY_JSON_INVALID", "HISTORY_ROOT_INVALID"}:
        return "JSON"
    if code == "HISTORY_MODEL_VALIDATION_FAILED":
        return "MODEL"
    if code in {
        "HISTORY_NODE_INVALID",
        "HISTORY_REQUIRED_FIELD_MISSING",
        "HISTORY_FIELD_TYPE_INVALID",
        "HISTORY_SEASON_INVALID",
        "HISTORY_FUTURE_SEASON",
        "HISTORY_DUPLICATE_SEASON",
        "HISTORY_GOALKEEPER_SAVES_MISSING",
        "HISTORY_SCHEMA_DRIFT",
    }:
        return "SCHEMA"
    return "HTTP"


def approved_history_schema_fingerprint() -> str:
    """Return the accepted material schema for the permitted history projection.

    Unknown provider fields are neither retained nor material to this bounded
    transformation.  Missing or retyped allowed fields still fail parsing.
    """

    return canonical_sha256(
        {
            "node": "history_past",
            "required_fields": {
                "assists": "int",
                "goals_scored": "int",
                "minutes": "int",
                "red_cards": "int",
                "season_name": "str",
                "yellow_cards": "int",
            },
            "optional_goalkeeper_field": {"saves": "int"},
        }
    )


@dataclass(frozen=True)
class ParsedHistoryPast:
    seasons: tuple[HistoryPastSeason, ...]
    schema_fingerprint: str
    unknown_fields: tuple[str, ...]
    zero_exposure_discipline_rows_excluded_count: int = 0


@dataclass(frozen=True)
class HistoryHttpResponse:
    status_code: int
    body: bytes
    authentication_required: bool = False


class HistoryTransport(Protocol):
    def get(self, url: str) -> HistoryHttpResponse: ...


class UrllibHistoryTransport:
    """Unauthenticated GET-only production transport, constructed only on execution."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def get(self, url: str) -> HistoryHttpResponse:
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return HistoryHttpResponse(status_code=int(response.status), body=response.read())
        except HTTPError as exc:
            return HistoryHttpResponse(status_code=exc.code, body=b"")
        except URLError:
            pass
        raise _history_error("NETWORK_UNAVAILABLE")


def _int(value: object, *, field: str) -> int:
    del field
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _history_error("HISTORY_FIELD_TYPE_INVALID")
    return value


def _season(value: object) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "/":
        raise _history_error("HISTORY_SEASON_INVALID")
    conversion_failed = False
    try:
        start = int(value[:4])
        end = int(value[-2:])
    except ValueError:
        conversion_failed = True
        start = 0
        end = 0
    if conversion_failed:
        raise _history_error("HISTORY_SEASON_INVALID")
    if start < 2000 or end != (start + 1) % 100:
        raise _history_error("HISTORY_SEASON_INVALID")
    return value


def history_past_schema_fingerprint(rows: object) -> str:
    """Validate and fingerprint permitted field types; no source values survive."""

    if not isinstance(rows, list):
        raise _history_error("HISTORY_NODE_INVALID")
    for row in rows:
        if not isinstance(row, Mapping):
            raise _history_error("HISTORY_NODE_INVALID")
        missing = _REQUIRED_FIELDS - set(row)
        if missing:
            raise _history_error("HISTORY_REQUIRED_FIELD_MISSING")
        if not isinstance(row["season_name"], str):
            raise _history_error("HISTORY_FIELD_TYPE_INVALID")
        for field in _REQUIRED_FIELDS - {"season_name"}:
            _int(row[field], field=field)
        if "saves" in row:
            _int(row["saves"], field="saves")
    return approved_history_schema_fingerprint()


def parse_history_past(
    payload: Mapping[str, object],
    *,
    current_season: str,
    is_goalkeeper: bool,
) -> ParsedHistoryPast:
    """Parse allowed metrics from a transient ``history_past`` node only."""

    _season(current_season)
    raw_rows = payload.get("history_past")
    fingerprint = history_past_schema_fingerprint(raw_rows)
    assert isinstance(raw_rows, list)
    seasons: list[HistoryPastSeason] = []
    unknown: set[str] = set()
    zero_exposure_discipline_rows_excluded_count = 0
    for row in raw_rows:
        assert isinstance(row, Mapping)
        missing = _REQUIRED_FIELDS - set(row)
        if missing:
            raise _history_error("HISTORY_REQUIRED_FIELD_MISSING")
        if is_goalkeeper and "saves" not in row:
            raise _history_error("HISTORY_GOALKEEPER_SAVES_MISSING")
        season = _season(row["season_name"])
        if season == current_season:
            continue
        if season > current_season:
            raise _history_error("HISTORY_FUTURE_SEASON")
        allowed = set(_REQUIRED_FIELDS) | {"saves"}
        unknown.update(str(key) for key in row if key not in allowed)
        minutes = _int(row["minutes"], field="minutes")
        goals = _int(row["goals_scored"], field="goals_scored")
        assists = _int(row["assists"], field="assists")
        yellow_cards = _int(row["yellow_cards"], field="yellow_cards")
        red_cards = _int(row["red_cards"], field="red_cards")
        saves = _int(row.get("saves", 0), field="saves")
        if minutes == 0 and any(value > 0 for value in (goals, assists, saves)):
            raise _history_error(
                "HISTORY_MODEL_VALIDATION_FAILED",
                model_validation_reason="ZERO_MINUTE_RATE_EVENT",
            )
        if minutes == 0 and (yellow_cards > 0 or red_cards > 0):
            zero_exposure_discipline_rows_excluded_count += 1
            continue
        history_season: HistoryPastSeason | None = None
        model_failure = False
        try:
            history_season = HistoryPastSeason(
                season=season,
                minutes=minutes,
                goals=goals,
                assists=assists,
                yellow_cards=yellow_cards,
                red_cards=red_cards,
                saves=saves,
            )
        except ValidationError:
            model_failure = True
        if model_failure:
            raise _history_error(
                "HISTORY_MODEL_VALIDATION_FAILED",
                model_validation_reason="HISTORY_PAST_SEASON",
            )
        assert history_season is not None
        seasons.append(history_season)
    ordered = tuple(sorted(seasons, key=lambda item: item.season))
    if len({item.season for item in ordered}) != len(ordered):
        raise _history_error("HISTORY_DUPLICATE_SEASON")
    return ParsedHistoryPast(
        seasons=ordered,
        schema_fingerprint=fingerprint,
        unknown_fields=tuple(sorted(unknown)),
        zero_exposure_discipline_rows_excluded_count=(zero_exposure_discipline_rows_excluded_count),
    )


def parse_history_bytes(
    body: bytes, *, current_season: str, is_goalkeeper: bool
) -> ParsedHistoryPast:
    """Decode one transient body without returning it or writing it anywhere."""

    value: object | None = None
    json_invalid = False
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        json_invalid = True
    if json_invalid:
        raise _history_error("HISTORY_JSON_INVALID")
    if not isinstance(value, Mapping):
        raise _history_error("HISTORY_ROOT_INVALID")
    return parse_history_past(value, current_season=current_season, is_goalkeeper=is_goalkeeper)


@dataclass(frozen=True)
class ApprovedCaptureRequest:
    approval: PlayerHistoryRightsApproval
    expected_approval_sha256: str
    catalogue: CurrentPlayerCatalogue
    information_cutoff: datetime
    maximum_player_count: int
    terms_fingerprint: str
    retention_mode: RetentionMode = RetentionMode.POSTERIOR_ONLY
    minimum_interval_seconds: float = 1.0


@dataclass(frozen=True)
class ApprovedCaptureResult:
    evidence: tuple[PlayerHistoryEvidence, ...]
    source_hashes: Mapping[UUID, str | None]
    source_observed_at: Mapping[UUID, datetime]
    schema_fingerprint: str
    deletion_manifest: DeletionManifest


def bind_posterior_to_deletion_manifest(
    deletion_manifest: DeletionManifest, *, posterior_artifact_sha256: str
) -> DeletionManifest:
    """Bind a posterior-only result after transient history has been deleted."""

    if deletion_manifest.deletion_outcome != "SUCCESS":
        raise IngestionError(
            "DELETION_UNCONFIRMED", "cannot bind a posterior to an unconfirmed deletion"
        )
    return deletion_manifest.model_copy(
        update={"posterior_artifact_sha256": posterior_artifact_sha256}
    )


def validate_capture_request(request: ApprovedCaptureRequest) -> None:
    """Fail before a transport exists unless every human-controlled guard agrees."""

    approval = request.approval
    effective_approval_sha256 = approval.governance_approval_sha256 or approval.approval_sha256
    if request.expected_approval_sha256 != effective_approval_sha256:
        raise IngestionError("RIGHTS_APPROVAL_HASH_MISMATCH", "rights approval hash does not match")
    if request.retention_mode is not RetentionMode.POSTERIOR_ONLY:
        raise IngestionError("RAW_RETENTION_FORBIDDEN", "only POSTERIOR_ONLY retention is allowed")
    if approval.terms_fingerprint != request.terms_fingerprint:
        raise IngestionError("TERMS_FINGERPRINT_DRIFT", "rights/terms fingerprint has changed")
    if request.maximum_player_count <= 0 or request.maximum_player_count > len(
        request.catalogue.players
    ):
        raise IngestionError(
            "REQUEST_BOUND_INVALID", "maximum player count is outside catalogue bounds"
        )
    if (
        approval.maximum_player_requests is not None
        and request.maximum_player_count > approval.maximum_player_requests
    ):
        raise IngestionError(
            "REQUEST_BOUND_INVALID", "maximum player count exceeds rights approval"
        )
    if request.information_cutoff.tzinfo is None or request.information_cutoff.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "information cutoff must be timezone-aware")
    if request.minimum_interval_seconds < 1.0:
        raise IngestionError(
            "PACING_INVALID", "history capture pacing is below the conservative minimum"
        )


def _capture_failure(
    error: IngestionError,
    *,
    player_id: UUID,
    position: str,
    request_ordinal: int,
    total_requested_bound: int,
    successful_responses: int,
) -> IngestionError:
    """Bind a typed history error to safe, per-request progress only."""

    code = error.code if error.code in _SAFE_CAPTURE_CODES else "HISTORY_MODEL_VALIDATION_FAILED"
    details: dict[str, object] = {
        "current_player_position": position,
        "failed_request_ordinal": request_ordinal,
        "failure_code": code,
        "failure_stage": _failure_stage(code),
        "raw_persistence": False,
        "request_ordinal": request_ordinal,
        "requests_attempted_before_stop": request_ordinal,
        "successful_responses_before_stop": successful_responses,
        "total_requested_bound": total_requested_bound,
        "transient_player_identity_sha256": sha256(player_id.bytes).hexdigest(),
    }
    reason = error.details.get("model_validation_reason")
    if reason in {
        "ZERO_MINUTE_RATE_EVENT",
        "HISTORY_PAST_SEASON",
        "PLAYER_HISTORY_EVIDENCE",
        "UNEXPECTED_CAPTURE_VALUE_ERROR",
    }:
        details["model_validation_reason"] = reason
    return IngestionError(code, _SAFE_CAPTURE_MESSAGES[code], details=details)


def _failure_with_deletion(
    error: IngestionError,
    *,
    run_id: UUID,
    deletion_manifest: DeletionManifest,
) -> IngestionError:
    """Emit only the safe deletion confirmation when a capture stops."""

    return IngestionError(
        error.code,
        error.message,
        details={
            **error.details,
            "current_catalogue_persisted": False,
            "deletion_outcome": deletion_manifest.deletion_outcome,
            "deletion_run_id": str(run_id),
        },
    )


def capture_approved_history(
    request: ApprovedCaptureRequest,
    *,
    transport: HistoryTransport,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], None] = sleep,
) -> ApprovedCaptureResult:
    """Serially capture approved history; returns derived evidence only.

    The caller supplies transport explicitly.  Normal application imports and
    tests therefore cannot perform a network request accidentally.
    """

    validate_capture_request(request)
    run_id = uuid4()
    evidence: list[PlayerHistoryEvidence] = []
    source_hashes: dict[UUID, str | None] = {}
    source_observed_at: dict[UUID, datetime] = {}
    fingerprints: set[str] = set()
    players = request.catalogue.players[: request.maximum_player_count]
    failure: IngestionError | None = None
    for index, player in enumerate(players):
        ordinal = index + 1
        try:
            url = request.approval.source_url_template.format(
                current_element_id=player.source_player_id
            )
            response = transport.get(url)
            if response.authentication_required or response.status_code in {401, 403}:
                raise _history_error("HISTORY_AUTHENTICATION_BLOCKED")
            if response.status_code == 429:
                raise _history_error("HISTORY_RATE_LIMITED")
            if response.status_code != 200:
                raise _history_error("HISTORY_HTTP_BLOCKED")
            observed_at = clock()
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise _history_error("HISTORY_MODEL_VALIDATION_FAILED")
            observed_at = observed_at.astimezone(UTC)
            if observed_at > request.information_cutoff.astimezone(UTC):
                raise _history_error("POST_CUTOFF")
            parsed = parse_history_bytes(
                response.body,
                current_season=request.catalogue.season_code,
                is_goalkeeper=player.position.value == "GK",
            )
            if parsed.schema_fingerprint != request.approval.history_past_schema_fingerprint:
                raise _history_error("HISTORY_SCHEMA_DRIFT")
            fingerprints.add(parsed.schema_fingerprint)
            source_hashes[player.player_id] = (
                sha256(response.body).hexdigest()
                if request.approval.source_hash_permitted
                else None
            )
            source_observed_at[player.player_id] = observed_at
            player_evidence: PlayerHistoryEvidence | None = None
            evidence_model_failure = False
            try:
                player_evidence = PlayerHistoryEvidence(
                    player_id=player.player_id,
                    source_player_id=player.source_player_id,
                    seasons=parsed.seasons,
                    zero_exposure_discipline_rows_excluded_count=(
                        parsed.zero_exposure_discipline_rows_excluded_count
                    ),
                )
            except ValidationError:
                evidence_model_failure = True
            if evidence_model_failure:
                raise _history_error(
                    "HISTORY_MODEL_VALIDATION_FAILED",
                    model_validation_reason="PLAYER_HISTORY_EVIDENCE",
                )
            assert player_evidence is not None
            evidence.append(player_evidence)
            if ordinal < len(players):
                sleeper(request.minimum_interval_seconds)
        except OSError:
            failure = _capture_failure(
                _history_error("NETWORK_UNAVAILABLE"),
                player_id=player.player_id,
                position=player.position.value,
                request_ordinal=ordinal,
                total_requested_bound=len(players),
                successful_responses=len(evidence),
            )
            break
        except IngestionError as error:
            failure = _capture_failure(
                error,
                player_id=player.player_id,
                position=player.position.value,
                request_ordinal=ordinal,
                total_requested_bound=len(players),
                successful_responses=len(evidence),
            )
            break
        except (ValidationError, ValueError):
            failure = _capture_failure(
                _history_error(
                    "HISTORY_MODEL_VALIDATION_FAILED",
                    model_validation_reason="UNEXPECTED_CAPTURE_VALUE_ERROR",
                ),
                player_id=player.player_id,
                position=player.position.value,
                request_ordinal=ordinal,
                total_requested_bound=len(players),
                successful_responses=len(evidence),
            )
            break
    # Bodies have no path, cache, log, artifact, or return-value reference.
    deleted_at = clock()
    if deleted_at.tzinfo is None or deleted_at.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "deletion timestamp must be timezone-aware")
    deletion = DeletionManifest(
        run_id=run_id,
        temporary_object_identifiers=tuple(
            (
                "transient-current-catalogue",
                *(f"transient-history-{index}" for index in range(len(evidence))),
            )
        ),
        deletion_timestamp=deleted_at.astimezone(UTC),
        deletion_outcome="SUCCESS",
    )
    if failure is not None:
        raise _failure_with_deletion(failure, run_id=run_id, deletion_manifest=deletion) from None
    if len(fingerprints) > 1:
        raise IngestionError(
            "HISTORY_SCHEMA_DRIFT", "history responses disagree on schema fingerprint"
        )
    return ApprovedCaptureResult(
        evidence=tuple(evidence),
        source_hashes=source_hashes,
        source_observed_at=source_observed_at,
        schema_fingerprint=next(
            iter(fingerprints), canonical_sha256({"node": "history_past", "row_shapes": []})
        ),
        deletion_manifest=deletion,
    )


def future_capture_endpoint() -> str:
    """Expose the approved template without making a request."""

    return "https://fantasy.premierleague.com/api/element-summary/{current_element_id}/"
