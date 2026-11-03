"""Closed reporting for unchanged, protected Odds ingestion raise sites."""

from __future__ import annotations

from typing import Literal, cast, get_args

from dmf_pulse.ingestion.errors import IngestionError

OddsQualityReason = Literal[
    "EMPTY_PROVIDER_RESPONSE",
    "DUPLICATE_OUTCOME",
    "SECRET_LIKE_PROVIDER_FIELD",
    "DUPLICATE_PROVIDER_EVENT_ID",
    "HOME_EQUALS_AWAY",
    "EVENT_NOT_PREMATCH_AT_CUTOFF",
    "BOOKMAKER_MISSING",
    "DUPLICATE_BOOKMAKER",
    "PROVIDER_TIMESTAMP_AFTER_RECEIPT",
    "REQUESTED_MARKET_MISSING_OR_DUPLICATED",
    "MARKET_TIMESTAMP_AFTER_BOOKMAKER",
    "MALFORMED_OUTCOME",
    "LINE_BEARING_H2H_OUTCOME",
    "THREE_WAY_H2H_INCOMPLETE",
    "QUOTA_TIMESTAMP_MISMATCH",
    "QUOTA_REQUEST_COST_MISMATCH",
    "QUOTA_SOURCE_INVALID",
]
_QUALITY_REASONS = frozenset(get_args(OddsQualityReason))
_PARSER_CODES = (
    "VALIDATION_FAILED",
    "MALFORMED_JSON",
    "DUPLICATE_JSON_KEY",
    "PAYLOAD_TOO_DEEP",
    "PAYLOAD_TOO_LARGE",
    "INTERNAL_INVARIANT",
)
ODDS_FAILURE_ACTIONS = {
    "CURRENT_ODDS_QUALITY_BLOCKED": (
        "The unchanged provider-native Odds quality gates rejected this input. "
        "Inspect only the fixed quality reason labels; keep every rejection and spent slot."
    ),
    "CURRENT_ODDS_CLOCK_REGRESSION": (
        "The unchanged Odds compiler rejected temporal order. Inspect operation clocks "
        "without backdating receipt or usable times."
    ),
    **{
        "CURRENT_ODDS_PARSER_" + code: (
            "The unchanged Odds parser rejected its source contract at a fixed raise site. "
            "Source bodies, field values and parser error text are not retained."
        )
        for code in _PARSER_CODES
    },
}

_CURRENT = "dmf_pulse.ingestion.odds.current"
_SITES = {
    (_CURRENT, "_provider_events", 785, "QUALITY_BLOCKED"): "CURRENT_ODDS_QUALITY_BLOCKED",
    (_CURRENT, "build_current_odds_input", 828, "CLOCK_REGRESSION"): (
        "CURRENT_ODDS_CLOCK_REGRESSION"
    ),
    **{
        (_CURRENT, "build_current_odds_input", line, "QUALITY_BLOCKED"): (
            "CURRENT_ODDS_QUALITY_BLOCKED"
        )
        for line in (830, 836, 842)
    },
    **{
        ("dmf_pulse.ingestion.odds.parser", "parse_odds_payload", 636, code): (
            "CURRENT_ODDS_PARSER_" + code
        )
        for code in _PARSER_CODES
    },
}


def odds_failure_context(
    error: IngestionError, module: str, function: str, line: int
) -> tuple[str, tuple[OddsQualityReason, ...]] | None:
    """Never format an error or export unknown keys, reasons, paths or values."""
    if type(error.code) is not str:
        return None
    code = _SITES.get((module, function, line, error.code))
    if code is None:
        return None
    reasons: tuple[OddsQualityReason, ...] = ()
    if code == "CURRENT_ODDS_QUALITY_BLOCKED":
        details = error.details
        if type(details) is dict and set(details) == {"blockers"}:
            values = details["blockers"]
            if (
                type(values) is list
                and 0 < len(values) <= len(_QUALITY_REASONS)
                and all(type(value) is str and value in _QUALITY_REASONS for value in values)
            ):
                reasons = tuple(cast(OddsQualityReason, value) for value in sorted(set(values)))
    return code, reasons
