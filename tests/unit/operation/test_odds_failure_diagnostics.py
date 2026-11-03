"""Actual owned Odds refusals disclose fixed reasons and preserve old receipts."""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.models import QuotaSource
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.operation.diagnostics import SafeFailure, SafeFailureError, safe_failure
from dmf_pulse.operation.odds_failure_context import (
    _SITES,
    OddsQualityReason,
    odds_failure_context,
)
from tests.unit.ingestion.test_live_odds_001_current_boundaries import (
    CUTOFF,
    RECEIVED,
    _body,
    _build,
    _value,
)

pytestmark = pytest.mark.unit
CANARY = "OWNED-PRIVATE-ODDS-CANARY-953C"


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("empty", ("EMPTY_PROVIDER_RESPONSE",)),
        ("books", ("BOOKMAKER_MISSING",)),
        ("market", ("REQUESTED_MARKET_MISSING_OR_DUPLICATED",)),
        ("outcome", ("THREE_WAY_H2H_INCOMPLETE",)),
        ("line", ("LINE_BEARING_H2H_OUTCOME",)),
        ("duplicate", ("DUPLICATE_OUTCOME",)),
        ("provider_time", ("PROVIDER_TIMESTAMP_AFTER_RECEIPT",)),
        ("market_time", ("MARKET_TIMESTAMP_AFTER_BOOKMAKER",)),
        ("prematch", ("EVENT_NOT_PREMATCH_AT_CUTOFF",)),
        ("secret", ("SECRET_LIKE_PROVIDER_FIELD",)),
        (
            "multiple",
            ("PROVIDER_TIMESTAMP_AFTER_RECEIPT", "REQUESTED_MARKET_MISSING_OR_DUPLICATED"),
        ),
    ],
)
def test_owned_quality_gates_keep_rejection_and_report_all_fixed_reasons(
    repository_root: Path, case: str, expected: tuple[str, ...]
) -> None:
    value = _value(repository_root)
    book = value[0]["bookmakers"][0]
    market = book["markets"][0]
    if case == "empty":
        value.clear()
    elif case == "books":
        value[0]["bookmakers"] = []
    elif case == "market":
        book["markets"] = []
    elif case == "outcome":
        market["outcomes"].pop()
    elif case == "line":
        market["outcomes"][0]["point"] = 0.5
    elif case == "duplicate":
        market["outcomes"].append(dict(market["outcomes"][0]))
    elif case == "provider_time":
        book["last_update"] = "2026-08-20T12:00:01Z"
    elif case == "market_time":
        market["last_update"] = "2026-08-20T12:00:00Z"
    elif case == "prematch":
        value[0]["commence_time"] = CUTOFF.isoformat()
    elif case == "secret":
        value[0]["api_key"] = CANARY
    elif case == "multiple":
        book["last_update"] = "2026-08-20T12:00:01Z"
        book["markets"] = []
    with pytest.raises(IngestionError) as caught:
        _build(parse_odds_payload(_body(value)))
    error = caught.value
    assert error.code == "QUALITY_BLOCKED"
    failure = safe_failure(error, "MARKET_ACQUISITION")
    assert failure.code == "CURRENT_ODDS_QUALITY_BLOCKED"
    assert failure.odds_quality_reasons == expected
    assert failure.category == "RESPONSE_CONTRACT"
    assert failure.typed_code_recognized is True
    error.message = CANARY
    error.args = (CANARY,)
    error.__context__ = ValueError(CANARY)
    assert safe_failure(error, "MARKET_ACQUISITION") == failure
    assert CANARY not in failure.model_dump_json()
    copied = SafeFailureError(failure).failure
    assert SafeFailure.model_validate_json(copied.model_dump_json()) == failure


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"quota_observed_at": RECEIVED - timedelta(seconds=1)}, "QUOTA_TIMESTAMP_MISMATCH"),
        ({"last_cost": 1}, "QUOTA_REQUEST_COST_MISMATCH"),
        ({"quota_source": QuotaSource.SYNTHETIC_FIXTURE}, "QUOTA_SOURCE_INVALID"),
    ],
)
def test_real_compiler_quota_refusals_remain_distinct(repository_root, options, reason) -> None:
    with pytest.raises(IngestionError) as caught:
        _build(parse_odds_payload(_body(_value(repository_root))), **options)
    failure = safe_failure(caught.value, "MARKET_ACQUISITION")
    assert failure.code == "CURRENT_ODDS_QUALITY_BLOCKED"
    assert failure.odds_quality_reasons == (reason,)


def test_actual_clock_refusal_is_named_without_altering_times(repository_root: Path) -> None:
    with pytest.raises(IngestionError) as caught:
        _build(
            parse_odds_payload(_body(_value(repository_root))),
            request_started_at=RECEIVED + timedelta(seconds=2),
        )
    assert caught.value.code == "CLOCK_REGRESSION"
    assert safe_failure(caught.value, "MARKET_ACQUISITION").code == (
        "CURRENT_ODDS_CLOCK_REGRESSION"
    )


@pytest.mark.parametrize(
    ("body", "raw_code"),
    [
        (b"[\xff]", "MALFORMED_JSON"),
        (b'[{"id":"first","id":"second"}]', "DUPLICATE_JSON_KEY"),
        (b'[{"private_input":"' + CANARY.encode() + b'"}]', "VALIDATION_FAILED"),
    ],
)
def test_actual_detached_parser_failures_are_fixed_and_private(body, raw_code) -> None:
    with pytest.raises(IngestionError) as caught:
        parse_odds_payload(body)
    assert caught.value.code == raw_code
    failure = safe_failure(caught.value, "MARKET_ACQUISITION")
    assert failure.code == "CURRENT_ODDS_PARSER_" + raw_code
    assert failure.typed_code_recognized is True
    assert CANARY not in failure.model_dump_json()
    assert "invalid_paths" not in failure.model_dump_json()


def test_unknown_reasons_details_and_unlisted_sites_cannot_escape(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"] = []
    with pytest.raises(IngestionError) as caught:
        _build(parse_odds_payload(_body(value)))
    error = caught.value
    for details in (
        {"blockers": [CANARY]},
        {"blockers": ["BOOKMAKER_MISSING", CANARY]},
        {"blockers": ["BOOKMAKER_MISSING"], CANARY: CANARY},
        {"blockers": "BOOKMAKER_MISSING"},
        {"blockers": []},
        {"blockers": ["BOOKMAKER_MISSING"] * 18},
    ):
        error.details = details
        failure = safe_failure(error, "MARKET_ACQUISITION")
        assert failure.code == "CURRENT_ODDS_QUALITY_BLOCKED"
        assert failure.odds_quality_reasons == ()
        assert CANARY not in failure.model_dump_json()
    assert (
        odds_failure_context(error, "dmf_pulse.ingestion.odds.current", "_provider_events", 786)
        is None
    )
    generic = safe_failure(IngestionError("QUALITY_BLOCKED", CANARY), "MARKET_ACQUISITION")
    assert generic.code == "CURRENT_TYPED_FAILURE_UNRECOGNIZED"


def test_old_failure_wire_hashes_are_preserved() -> None:
    legacy = {
        "stage": "MARKET_ACQUISITION",
        "category": "UNRECOGNIZED_TYPED_FAILURE",
        "exception_family": "INGESTION",
        "code": "CURRENT_TYPED_FAILURE_UNRECOGNIZED",
        "typed_code_recognized": False,
        "integrity_reason": None,
    }
    failure = SafeFailure.model_validate_json(canonical_json_bytes(legacy))
    assert failure.model_dump(mode="json") == legacy
    assert canonical_sha256(failure.model_dump(mode="json")) == canonical_sha256(legacy)
    assert "odds_quality_reasons" not in json.loads(failure.model_dump_json())
    assert SafeFailureError(failure).failure.model_dump(mode="json") == legacy
    with pytest.raises(ValidationError):
        SafeFailure.model_validate({**legacy, "odds_quality_reasons": ["BOOKMAKER_MISSING"]})
    with pytest.raises(ValidationError):
        SafeFailure.model_validate({**legacy, "odds_quality_reasons": [CANARY]})


def test_closed_sites_and_reason_labels_match_unchanged_protected_source(repository_root) -> None:
    root = repository_root / "src"
    current = ast.parse((root / "dmf_pulse/ingestion/odds/current.py").read_bytes())
    reasons = {
        node.args[0].value
        for node in ast.walk(current)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "blockers"
        and node.func.attr == "add"
        and isinstance(node.args[0], ast.Constant)
    }
    reasons.update(
        {"QUOTA_TIMESTAMP_MISMATCH", "QUOTA_REQUEST_COST_MISMATCH", "QUOTA_SOURCE_INVALID"}
    )
    assert reasons == set(get_args(OddsQualityReason))
    for module, function, line, _ in _SITES:
        source = ast.parse((root / (module.replace(".", "/") + ".py")).read_bytes())
        declaration = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == function
        )
        assert any(
            isinstance(node, ast.Raise) and node.lineno == line for node in ast.walk(declaration)
        )
