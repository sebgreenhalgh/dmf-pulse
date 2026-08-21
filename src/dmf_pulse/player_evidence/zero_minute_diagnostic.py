"""One-request, body-free diagnostic for the exact GW1 zero-minute failure."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.diagnostic_approval import (
    DIAGNOSTIC_APPROVAL_SHA256,
    DIAGNOSTIC_CATALOGUE_SHA256,
    DIAGNOSTIC_INFORMATION_CUTOFF,
    DIAGNOSTIC_TARGET_IDENTITY_SHA256,
    DIAGNOSTIC_TARGET_ORDINAL,
    DIAGNOSTIC_TERMS_FINGERPRINT,
    ZeroMinuteDiagnosticApproval,
)
from dmf_pulse.player_evidence.history import HistoryHttpResponse, HistoryTransport
from dmf_pulse.player_evidence.models import CurrentPlayerCatalogue

_REQUIRED_FIELDS = {
    "season_name",
    "minutes",
    "goals_scored",
    "assists",
    "yellow_cards",
    "red_cards",
    "saves",
}


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        return None


class OneShotUrllibDiagnosticTransport:
    """Unauthenticated GET transport with redirects and retries disabled."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    def get(self, url: str) -> HistoryHttpResponse:
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        opener = build_opener(_RejectRedirects())
        try:
            with opener.open(request, timeout=self._timeout_seconds) as response:
                return HistoryHttpResponse(status_code=int(response.status), body=response.read())
        except HTTPError as exc:
            return HistoryHttpResponse(status_code=exc.code, body=b"")
        except (URLError, TimeoutError, OSError):
            raise IngestionError(
                "NETWORK_UNAVAILABLE", "official FPL diagnostic request failed"
            ) from None


@dataclass(frozen=True)
class ZeroMinuteDiagnosticTarget:
    """Transient target; the provider identifier never enters safe output."""

    player_id: UUID
    source_player_id: int
    ordinal: int
    position: str
    identity_sha256: str


@dataclass(frozen=True)
class ZeroMinuteDiagnosticResult:
    request_count: int
    zero_minute_row_count: int
    zero_minute_positive_goal_present: bool
    zero_minute_positive_assist_present: bool
    zero_minute_positive_yellow_present: bool
    zero_minute_positive_red_present: bool
    zero_minute_positive_saves_present: bool
    zero_minute_rate_event_present: bool
    zero_minute_discipline_only_present: bool
    all_nonzero_minute_rows_basic_schema_valid: bool
    source_body_sha256: str
    raw_fpl_history_persisted: bool = False
    current_fpl_catalogue_persisted: bool = False

    def safe_dict(self) -> dict[str, bool | int | str]:
        return {
            "actual_diagnostic_request_count": self.request_count,
            "all_nonzero_minute_rows_basic_schema_valid": (
                self.all_nonzero_minute_rows_basic_schema_valid
            ),
            "current_fpl_catalogue_persisted": self.current_fpl_catalogue_persisted,
            "raw_fpl_history_persisted": self.raw_fpl_history_persisted,
            "source_body_sha256": self.source_body_sha256,
            "zero_minute_discipline_only_present": (self.zero_minute_discipline_only_present),
            "zero_minute_positive_assist_present": (self.zero_minute_positive_assist_present),
            "zero_minute_positive_goal_present": self.zero_minute_positive_goal_present,
            "zero_minute_positive_red_present": self.zero_minute_positive_red_present,
            "zero_minute_positive_saves_present": self.zero_minute_positive_saves_present,
            "zero_minute_positive_yellow_present": self.zero_minute_positive_yellow_present,
            "zero_minute_rate_event_present": self.zero_minute_rate_event_present,
            "zero_minute_row_count": self.zero_minute_row_count,
        }


@dataclass(frozen=True)
class ApprovedZeroMinuteDiagnosticRequest:
    approval: ZeroMinuteDiagnosticApproval
    target: ZeroMinuteDiagnosticTarget
    catalogue: CurrentPlayerCatalogue
    information_cutoff: datetime
    terms_fingerprint: str
    maximum_official_history_requests: int = 1


def resolve_zero_minute_diagnostic_target(
    catalogue: CurrentPlayerCatalogue,
) -> ZeroMinuteDiagnosticTarget:
    """Resolve exactly one hash-bound target without names or fuzzy matching."""

    if catalogue.semantic_sha256 != DIAGNOSTIC_CATALOGUE_SHA256:
        raise IngestionError(
            "DIAGNOSTIC_CATALOGUE_HASH_MISMATCH",
            "current catalogue does not match the approved diagnostic universe",
        )
    matches = [
        (ordinal, player)
        for ordinal, player in enumerate(catalogue.players, start=1)
        if sha256(player.player_id.bytes).hexdigest() == DIAGNOSTIC_TARGET_IDENTITY_SHA256
    ]
    if len(matches) != 1:
        raise IngestionError(
            "DIAGNOSTIC_TARGET_MISMATCH", "diagnostic target is not uniquely resolved"
        )
    ordinal, player = matches[0]
    if ordinal != DIAGNOSTIC_TARGET_ORDINAL or player.position.value != "GK":
        raise IngestionError(
            "DIAGNOSTIC_TARGET_MISMATCH", "diagnostic target binding does not match"
        )
    return ZeroMinuteDiagnosticTarget(
        player_id=player.player_id,
        source_player_id=player.source_player_id,
        ordinal=ordinal,
        position=player.position.value,
        identity_sha256=DIAGNOSTIC_TARGET_IDENTITY_SHA256,
    )


def validate_zero_minute_diagnostic_request(request: ApprovedZeroMinuteDiagnosticRequest) -> None:
    """Fail before transport unless every single-row guard agrees."""

    if request.approval.approval_sha256 != DIAGNOSTIC_APPROVAL_SHA256:
        raise IngestionError(
            "DIAGNOSTIC_APPROVAL_HASH_MISMATCH", "diagnostic approval hash does not match"
        )
    binding = request.approval.diagnostic_binding
    if (
        binding.expected_catalogue_semantic_sha256 != request.catalogue.semantic_sha256
        or binding.transient_player_identity_sha256 != request.target.identity_sha256
        or binding.failed_request_ordinal != request.target.ordinal
        or binding.player_position != request.target.position
    ):
        raise IngestionError("DIAGNOSTIC_TARGET_MISMATCH", "diagnostic approval binding differs")
    if request.catalogue.semantic_sha256 != DIAGNOSTIC_CATALOGUE_SHA256:
        raise IngestionError(
            "DIAGNOSTIC_CATALOGUE_HASH_MISMATCH",
            "current catalogue does not match the approved diagnostic universe",
        )
    if request.target.identity_sha256 != DIAGNOSTIC_TARGET_IDENTITY_SHA256:
        raise IngestionError("DIAGNOSTIC_TARGET_MISMATCH", "diagnostic target hash differs")
    if sha256(request.target.player_id.bytes).hexdigest() != request.target.identity_sha256:
        raise IngestionError("DIAGNOSTIC_TARGET_MISMATCH", "diagnostic player identity differs")
    if request.target.ordinal != DIAGNOSTIC_TARGET_ORDINAL or request.target.position != "GK":
        raise IngestionError("DIAGNOSTIC_TARGET_MISMATCH", "diagnostic target binding differs")
    if resolve_zero_minute_diagnostic_target(request.catalogue) != request.target:
        raise IngestionError("DIAGNOSTIC_TARGET_MISMATCH", "diagnostic target differs")
    if request.maximum_official_history_requests != 1:
        raise IngestionError(
            "DIAGNOSTIC_REQUEST_BOUND_INVALID", "diagnostic request bound is not one"
        )
    if request.approval.capture_constraints.maximum_official_history_requests != 1:
        raise IngestionError(
            "DIAGNOSTIC_REQUEST_BOUND_INVALID", "approval request bound is not one"
        )
    if request.approval.bulk_capture_authority != "NONE":
        raise IngestionError("DIAGNOSTIC_BULK_AUTHORITY_FORBIDDEN", "bulk authority is forbidden")
    if request.terms_fingerprint != DIAGNOSTIC_TERMS_FINGERPRINT:
        raise IngestionError("TERMS_FINGERPRINT_DRIFT", "rights/terms fingerprint has changed")
    if request.approval.terms_review.snapshot_sha256 != request.terms_fingerprint:
        raise IngestionError("TERMS_FINGERPRINT_DRIFT", "diagnostic approval terms differ")
    if request.information_cutoff.tzinfo is None or request.information_cutoff.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "information cutoff must be timezone-aware")
    if request.information_cutoff.astimezone(UTC) != DIAGNOSTIC_INFORMATION_CUTOFF:
        raise IngestionError("TEMPORAL_INVALID", "information cutoff differs from approval")


def _safe_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IngestionError("DIAGNOSTIC_FIELD_TYPE_INVALID", "diagnostic field type is invalid")
    return value


def _safe_season(value: object) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "/":
        raise IngestionError("DIAGNOSTIC_SEASON_INVALID", "diagnostic season is invalid")
    try:
        start = int(value[:4])
        end = int(value[-2:])
    except ValueError:
        raise IngestionError("DIAGNOSTIC_SEASON_INVALID", "diagnostic season is invalid") from None
    if start < 2000 or end != (start + 1) % 100:
        raise IngestionError("DIAGNOSTIC_SEASON_INVALID", "diagnostic season is invalid")
    return value


def parse_zero_minute_diagnostic_bytes(
    body: bytes, *, current_season: str = "2026/27"
) -> ZeroMinuteDiagnosticResult:
    """Derive only the approved boolean/count signature before the strict history model."""

    source_body_sha256 = sha256(body).hexdigest()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise IngestionError("DIAGNOSTIC_JSON_INVALID", "diagnostic JSON is invalid") from None
    if not isinstance(payload, Mapping):
        raise IngestionError("DIAGNOSTIC_ROOT_INVALID", "diagnostic root is invalid")
    rows = payload.get("history_past")
    if not isinstance(rows, list):
        raise IngestionError("DIAGNOSTIC_NODE_INVALID", "diagnostic history node is invalid")

    zero_rows = 0
    goal = assist = yellow = red = saves = False
    discipline_only = False
    for row in rows:
        if not isinstance(row, Mapping):
            raise IngestionError("DIAGNOSTIC_NODE_INVALID", "diagnostic history node is invalid")
        if _REQUIRED_FIELDS - set(row):
            raise IngestionError(
                "DIAGNOSTIC_REQUIRED_FIELD_MISSING", "diagnostic required field is missing"
            )
        season = _safe_season(row["season_name"])
        values = {
            field: _safe_int(row[field]) for field in _REQUIRED_FIELDS if field != "season_name"
        }
        if season == current_season:
            continue
        if season > current_season:
            raise IngestionError("DIAGNOSTIC_FUTURE_SEASON", "diagnostic contains a future season")
        if values["minutes"] != 0:
            continue
        zero_rows += 1
        row_goal = values["goals_scored"] > 0
        row_assist = values["assists"] > 0
        row_yellow = values["yellow_cards"] > 0
        row_red = values["red_cards"] > 0
        row_saves = values["saves"] > 0
        goal = goal or row_goal
        assist = assist or row_assist
        yellow = yellow or row_yellow
        red = red or row_red
        saves = saves or row_saves
        discipline_only = discipline_only or (
            not row_goal and not row_assist and not row_saves and (row_yellow or row_red)
        )
    return ZeroMinuteDiagnosticResult(
        request_count=1,
        zero_minute_row_count=zero_rows,
        zero_minute_positive_goal_present=goal,
        zero_minute_positive_assist_present=assist,
        zero_minute_positive_yellow_present=yellow,
        zero_minute_positive_red_present=red,
        zero_minute_positive_saves_present=saves,
        zero_minute_rate_event_present=goal or assist or saves,
        zero_minute_discipline_only_present=discipline_only,
        all_nonzero_minute_rows_basic_schema_valid=True,
        source_body_sha256=source_body_sha256,
    )


def execute_zero_minute_diagnostic(
    request: ApprovedZeroMinuteDiagnosticRequest,
    *,
    transport: HistoryTransport,
    clock: Callable[[], datetime],
) -> ZeroMinuteDiagnosticResult:
    """Perform one GET with no loop, retry, raw return, or persistence path."""

    validate_zero_minute_diagnostic_request(request)
    url = request.approval.source.url_template.format(
        current_element_id=request.target.source_player_id
    )
    response = transport.get(url)
    if response.authentication_required or response.status_code in {401, 403}:
        raise IngestionError(
            "DIAGNOSTIC_AUTHENTICATION_BLOCKED", "diagnostic request requires authentication"
        )
    if response.status_code == 429:
        raise IngestionError("DIAGNOSTIC_RATE_LIMITED", "diagnostic request received HTTP 429")
    if response.status_code != 200:
        raise IngestionError(
            "DIAGNOSTIC_HTTP_BLOCKED", "diagnostic request received a non-success response"
        )
    observed_at = clock()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "diagnostic receipt time must be timezone-aware")
    if observed_at.astimezone(UTC) > request.information_cutoff.astimezone(UTC):
        raise IngestionError("POST_CUTOFF", "diagnostic receipt is after the information cutoff")
    return parse_zero_minute_diagnostic_bytes(response.body)


__all__ = [
    "ApprovedZeroMinuteDiagnosticRequest",
    "OneShotUrllibDiagnosticTransport",
    "ZeroMinuteDiagnosticResult",
    "ZeroMinuteDiagnosticTarget",
    "execute_zero_minute_diagnostic",
    "parse_zero_minute_diagnostic_bytes",
    "resolve_zero_minute_diagnostic_target",
    "validate_zero_minute_diagnostic_request",
]
