"""Portable owned diagnostic/privacy checks; no private artifacts or services."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.config import load_provider_config
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.operation.diagnostics import SafeFailure, SafeFailureError, safe_failure
from dmf_pulse.operation.odds_failure_context import _SITES, OddsQualityReason, odds_failure_context
from tests.unit.ingestion.test_live_odds_001_current_boundaries import _body, _build, _value

pytestmark = pytest.mark.unit
CANARY = "OWNED-DIAGNOSTIC-PRIVACY-CANARY-7E19"


def actual_owned_quality_error(repository_root: Path):
    data = _value(repository_root)
    data[0]["bookmakers"] = []
    try:
        _build(parse_odds_payload(_body(data)))
    except IngestionError as error:
        assert error.code == "QUALITY_BLOCKED"
        return error
    raise AssertionError("UNCHANGED_QUALITY_GATE_DID_NOT_REJECT")


def test_all_seventeen_reasons_are_sorted_bounded_and_forwarded_unchanged(repository_root: Path):
    error = actual_owned_quality_error(repository_root)
    all_reasons = sorted(get_args(OddsQualityReason))
    assert len(all_reasons) == 17
    error.details = {"blockers": list(reversed(all_reasons))}
    failure = safe_failure(error, "WORKER_START")
    assert failure.odds_quality_reasons == tuple(all_reasons)
    assert failure.stage == "MARKET_ACQUISITION"
    assert failure.category == "RESPONSE_CONTRACT" and failure.typed_code_recognized is True
    assert safe_failure(SafeFailureError(failure), "WORKER_START") == failure
    dump = failure.model_dump(mode="json")
    for reasons in [
        [*all_reasons, all_reasons[-1]],
        [all_reasons[0], all_reasons[0]],
        list(reversed(all_reasons)),
        [CANARY],
    ]:
        with pytest.raises(ValidationError):
            SafeFailure.model_validate_json(
                canonical_json_bytes({**dump, "odds_quality_reasons": reasons})
            )


@pytest.mark.parametrize(
    "changed",
    [
        {"stage": "MANAGER_STATE"},
        {"exception_family": "OPERATOR"},
        {"code": "CURRENT_ODDS_CLOCK_REGRESSION"},
    ],
)
def test_nonempty_reasons_reject_wrong_owned_context(repository_root: Path, changed):
    failure = safe_failure(actual_owned_quality_error(repository_root), "MARKET_ACQUISITION")
    with pytest.raises(ValidationError):
        SafeFailure.model_validate_json(
            canonical_json_bytes({**failure.model_dump(mode="json"), **changed})
        )


@pytest.mark.parametrize(
    "kind",
    [
        "dict_subclass",
        "list_subclass",
        "str_subclass",
        "object",
        "unknown_key",
        "non_string",
        "oversize",
    ],
)
def test_hostile_values_are_never_formatted_or_iterated(repository_root: Path, kind, capsys):
    calls = []

    class HostileDict(dict):
        def __iter__(self):
            calls.append("dict_iter")
            raise AssertionError(CANARY)

    class HostileList(list):
        def __iter__(self):
            calls.append("list_iter")
            raise AssertionError(CANARY)

    class HostileString(str):
        def __str__(self):
            calls.append("str")
            raise AssertionError(CANARY)

        def __repr__(self):
            calls.append("repr")
            raise AssertionError(CANARY)

    class HostileObject:
        def __repr__(self):
            calls.append("object_repr")
            raise AssertionError(CANARY)

    details = {
        "dict_subclass": HostileDict(blockers=["BOOKMAKER_MISSING"]),
        "list_subclass": {"blockers": HostileList(["BOOKMAKER_MISSING"])},
        "str_subclass": {"blockers": [HostileString("BOOKMAKER_MISSING")]},
        "object": {"blockers": [HostileObject()]},
        "unknown_key": {"blockers": ["BOOKMAKER_MISSING"], CANARY: HostileObject()},
        "non_string": {"blockers": [1]},
        "oversize": {"blockers": ["BOOKMAKER_MISSING"] * 18},
    }[kind]
    error = actual_owned_quality_error(repository_root)
    error.details, error.message, error.args = details, CANARY, (CANARY,)
    error.__context__ = ValueError(CANARY)
    failure = safe_failure(error, "MARKET_ACQUISITION")
    assert failure.code == "CURRENT_ODDS_QUALITY_BLOCKED"
    assert failure.odds_quality_reasons == () and calls == []
    wire = failure.model_dump_json()
    assert CANARY not in wire and "odds_quality_reasons" not in wire
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("mode", ["constructor", "forwarding"])
def test_copied_invalid_literal_fault_is_reached_without_warning_or_stderr(
    repository_root: Path, mode, capsys, recwarn
):
    valid = safe_failure(actual_owned_quality_error(repository_root), "MARKET_ACQUISITION")
    corrupt = valid.model_copy(update={"odds_quality_reasons": (CANARY,)})
    if mode == "constructor":
        with pytest.raises(ValidationError):
            SafeFailureError(corrupt)
    else:
        wrapper = Exception.__new__(SafeFailureError)
        wrapper.failure = corrupt
        with pytest.raises(ValidationError):
            safe_failure(wrapper, "MARKET_ACQUISITION")
    assert not recwarn.list
    assert capsys.readouterr() == ("", "")


def test_every_site_rejects_adjacent_line_wrong_module_function_and_code():
    for module, function, line, raw_code in _SITES:
        error = IngestionError(raw_code, CANARY, details={"blockers": ["BOOKMAKER_MISSING"]})
        assert odds_failure_context(error, module, function, line) is not None
        assert odds_failure_context(error, module, function, line + 1000) is None
        assert odds_failure_context(error, module + ".owned", function, line) is None
        assert odds_failure_context(error, module, function + "_owned", line) is None
        error.code = CANARY
        assert odds_failure_context(error, module, function, line) is None
    assert (
        safe_failure(
            IngestionError("QUALITY_BLOCKED", CANARY), "MARKET_ACQUISITION"
        ).typed_code_recognized
        is False
    )


@pytest.mark.parametrize("kind", ["depth", "bytes"])
def test_actual_detached_limit_errors_remain_fixed(kind, capsys):
    config = load_provider_config()
    if kind == "depth":
        payload = b"[" * (config.max_json_depth + 2) + b"0" + b"]" * (config.max_json_depth + 2)
        expected = "PAYLOAD_TOO_DEEP"
    else:
        payload = b" " * (config.max_response_bytes + 1)
        expected = "PAYLOAD_TOO_LARGE"
    with pytest.raises(IngestionError) as caught:
        parse_odds_payload(payload)
    assert caught.value.code == expected
    failure = safe_failure(caught.value, "MARKET_ACQUISITION")
    assert failure.code == "CURRENT_ODDS_PARSER_" + expected
    assert failure.odds_quality_reasons == ()
    assert capsys.readouterr() == ("", "")


def test_new_context_module_has_only_pure_literal_initialization(repository_root: Path):
    source = repository_root / "src/dmf_pulse/operation/odds_failure_context.py"
    tree = ast.parse(source.read_bytes())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            continue
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            assert isinstance(call.func, ast.Name) and call.func.id in {"frozenset", "get_args"}
