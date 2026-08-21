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


@dataclass(frozen=True)
class ParsedHistoryPast:
    seasons: tuple[HistoryPastSeason, ...]
    schema_fingerprint: str
    unknown_fields: tuple[str, ...]


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
        except URLError as exc:
            raise IngestionError(
                "NETWORK_UNAVAILABLE", "official FPL history request failed"
            ) from exc


def _int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IngestionError(
            "HISTORY_SCHEMA_INVALID", f"history field {field} must be a non-negative integer"
        )
    return value


def _season(value: object) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "/":
        raise IngestionError("HISTORY_SCHEMA_INVALID", "history season is invalid")
    try:
        start = int(value[:4])
        end = int(value[-2:])
    except ValueError as exc:
        raise IngestionError("HISTORY_SCHEMA_INVALID", "history season is invalid") from exc
    if start < 2000 or end != (start + 1) % 100:
        raise IngestionError("HISTORY_SCHEMA_INVALID", "history season is invalid")
    return value


def history_past_schema_fingerprint(rows: object) -> str:
    """Fingerprint node shape only; no source values survive the calculation."""

    if not isinstance(rows, list):
        raise IngestionError("HISTORY_SCHEMA_INVALID", "history_past must be an array")
    shapes: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise IngestionError("HISTORY_SCHEMA_INVALID", "history_past row must be an object")
        shapes.append({str(key): type(value).__name__ for key, value in sorted(row.items())})
    return canonical_sha256({"node": "history_past", "row_shapes": shapes})


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
    for row in raw_rows:
        assert isinstance(row, Mapping)
        missing = _REQUIRED_FIELDS - set(row)
        if missing:
            raise IngestionError("HISTORY_SCHEMA_INVALID", "history_past required field is missing")
        if is_goalkeeper and "saves" not in row:
            raise IngestionError("HISTORY_SCHEMA_INVALID", "goalkeeper history lacks saves")
        season = _season(row["season_name"])
        if season == current_season:
            continue
        if season > current_season:
            raise IngestionError("HISTORY_SCHEMA_INVALID", "history contains a future season")
        allowed = set(_REQUIRED_FIELDS) | {"saves"}
        unknown.update(str(key) for key in row if key not in allowed)
        seasons.append(
            HistoryPastSeason(
                season=season,
                minutes=_int(row["minutes"], field="minutes"),
                goals=_int(row["goals_scored"], field="goals_scored"),
                assists=_int(row["assists"], field="assists"),
                yellow_cards=_int(row["yellow_cards"], field="yellow_cards"),
                red_cards=_int(row["red_cards"], field="red_cards"),
                saves=_int(row.get("saves", 0), field="saves"),
            )
        )
    ordered = tuple(sorted(seasons, key=lambda item: item.season))
    if len({item.season for item in ordered}) != len(ordered):
        raise IngestionError("HISTORY_SCHEMA_INVALID", "history has duplicate seasons")
    return ParsedHistoryPast(
        seasons=ordered,
        schema_fingerprint=fingerprint,
        unknown_fields=tuple(sorted(unknown)),
    )


def parse_history_bytes(
    body: bytes, *, current_season: str, is_goalkeeper: bool
) -> ParsedHistoryPast:
    """Decode one transient body without returning it or writing it anywhere."""

    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionError(
            "HISTORY_SCHEMA_INVALID", "history response is not valid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise IngestionError("HISTORY_SCHEMA_INVALID", "history response root must be an object")
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
    if request.expected_approval_sha256 != approval.approval_sha256:
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
    if request.information_cutoff.tzinfo is None or request.information_cutoff.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "information cutoff must be timezone-aware")
    if request.minimum_interval_seconds < 1.0:
        raise IngestionError(
            "PACING_INVALID", "history capture pacing is below the conservative minimum"
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
    try:
        for index, player in enumerate(players):
            url = request.approval.source_url_template.format(
                current_element_id=player.source_player_id
            )
            response = transport.get(url)
            if response.authentication_required or response.status_code in {401, 403}:
                raise IngestionError(
                    "HISTORY_AUTHENTICATION_BLOCKED", "history capture requires authentication"
                )
            if response.status_code == 429:
                raise IngestionError("HISTORY_RATE_LIMITED", "history capture received HTTP 429")
            if response.status_code != 200:
                raise IngestionError(
                    "HISTORY_HTTP_BLOCKED", "history capture received a non-success response"
                )
            observed_at = clock()
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise IngestionError(
                    "TEMPORAL_INVALID", "successful receipt time must be timezone-aware"
                )
            observed_at = observed_at.astimezone(UTC)
            if observed_at > request.information_cutoff.astimezone(UTC):
                raise IngestionError(
                    "POST_CUTOFF", "successful history receipt is after the information cutoff"
                )
            parsed = parse_history_bytes(
                response.body,
                current_season=request.catalogue.season_code,
                is_goalkeeper=player.position.value == "GK",
            )
            if parsed.schema_fingerprint != request.approval.history_past_schema_fingerprint:
                raise IngestionError(
                    "HISTORY_SCHEMA_DRIFT", "history_past schema fingerprint has changed"
                )
            fingerprints.add(parsed.schema_fingerprint)
            source_hashes[player.player_id] = (
                sha256(response.body).hexdigest()
                if request.approval.source_hash_permitted
                else None
            )
            source_observed_at[player.player_id] = observed_at
            evidence.append(
                PlayerHistoryEvidence(
                    player_id=player.player_id,
                    source_player_id=player.source_player_id,
                    seasons=parsed.seasons,
                )
            )
            if index + 1 < len(players):
                sleeper(request.minimum_interval_seconds)
    finally:
        # Bodies have no path, cache, log, artifact, or return-value reference.
        deleted_at = clock()
        if deleted_at.tzinfo is None or deleted_at.utcoffset() is None:
            raise IngestionError("TEMPORAL_INVALID", "deletion timestamp must be timezone-aware")
        deletion = DeletionManifest(
            run_id=run_id,
            temporary_object_identifiers=tuple(
                f"transient-history-{index}" for index in range(len(evidence))
            ),
            deletion_timestamp=deleted_at.astimezone(UTC),
            deletion_outcome="SUCCESS",
        )
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
