"""Owned manager refusals are named without source values or changed acceptance."""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import manager_current, manager_provider
from dmf_pulse.operation import diagnostics
from dmf_pulse.operation.diagnostics import safe_failure
from dmf_pulse.private_v1.one_command import _rules_authority
from tests.unit.ingestion.current_manager_test_support import (
    CUTOFF,
    DECLARED,
    MANAGER_RECEIVED,
    MANAGER_USABLE,
    declaration_for,
)
from tests.unit.ingestion.test_fpl_manager_provider import _context

pytestmark = pytest.mark.unit
CANARY = "OWNED-PRIVATE-MANAGER-CANARY-729A"
PROVIDER = "dmf_pulse.ingestion.fpl.manager_provider"
CURRENT = "dmf_pulse.ingestion.fpl.manager_current"
UNMAPPED_MANAGER_CODES = {
    "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED",
    "SCHEMA_DRIFT",
    "CONFIGURATION_INVALID",
    "USAGE_INVALID",
    "INTERNAL_INVARIANT",
}
EXPECTED_SITES = {
    (PROVIDER, "_chip_declarations", 114, "SCHEMA_DRIFT"),
    (PROVIDER, "_chip_declarations", 138, "SCHEMA_DRIFT"),
    (
        PROVIDER,
        "provider_current_manager_declaration",
        226,
        "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED",
    ),
    (CURRENT, "_compile_active_rules", 863, "CONFIGURATION_INVALID"),
    (CURRENT, "_compile_active_rules", 883, "CONFIGURATION_INVALID"),
    (CURRENT, "_compile_active_rules", 903, "CONFIGURATION_INVALID"),
    (CURRENT, "_require_rules_match_catalogue", 964, "CONFIGURATION_INVALID"),
    (CURRENT, "_resolve_squad", 1001, "CONFIGURATION_INVALID"),
    (CURRENT, "_resolve_chip_inventory", 1126, "USAGE_INVALID"),
    (CURRENT, "_clock_utc", 1315, "INTERNAL_INVARIANT"),
    (CURRENT, "compile", 1341, "INTERNAL_INVARIANT"),
    (CURRENT, "compile_provider_observed", 1379, "INTERNAL_INVARIANT"),
}


@pytest.fixture(scope="module")
def manager_context(repository_root: Path):
    return _context(repository_root)


def _source(context, *, mutation=None):
    body = deepcopy(context[3])
    if mutation is not None:
        mutation(body)
    return manager_provider.parse_provider_current_team(json.dumps(body).encode())


def _compile(context, source=None, *, clock=lambda: MANAGER_RECEIVED, **kwargs):
    fpl_input, ruleset, capability, _ = context
    return manager_current.CurrentManagerStateService(clock=clock).compile_provider_snapshot(
        source if source is not None else _source(context),
        fpl_input=fpl_input,
        ruleset=kwargs.pop("ruleset", ruleset),
        capability=kwargs.pop("capability", capability),
        observed_at=DECLARED,
        **kwargs,
    )


def _assert_report(error: IngestionError, code: str, category: str) -> None:
    before = safe_failure(error, "MANAGER_STATE")
    assert before.code == code
    assert before.category == category
    assert before.exception_family == "INGESTION"
    assert before.stage == "MANAGER_STATE"
    assert before.typed_code_recognized is True
    error.message = CANARY
    error.args = (CANARY,)
    error.details = {"owned_private_input": CANARY}
    error.__context__ = ValueError(CANARY)
    after = safe_failure(error, "MANAGER_STATE")
    assert after == before
    encoded = after.model_dump_json()
    assert CANARY not in encoded
    assert "OWNED-PRIVATE" not in encoded and "CANARY-729A" not in encoded
    assert "owned_private_input" not in encoded and "input_value" not in encoded


def test_provider_null_transfer_limit_is_reported_and_never_inferred(manager_context) -> None:
    source = _source(manager_context, mutation=lambda body: body["transfers"].update(limit=None))
    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, source)
    assert source.transfers.limit is None
    assert caught.value.code == "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED"
    _assert_report(caught.value, "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED", "RESPONSE_CONTRACT")


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("name", "CURRENT_MANAGER_CHIP_IDENTITY_UNSUPPORTED"),
        ("status_for_entry", "CURRENT_MANAGER_CHIP_STATUS_UNSUPPORTED"),
    ],
)
def test_provider_unknown_chip_contract_keeps_real_refusal(manager_context, field, code) -> None:
    source = _source(
        manager_context, mutation=lambda body: body["chips"][0].update({field: CANARY})
    )
    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, source)
    assert caught.value.code == "SCHEMA_DRIFT"
    _assert_report(caught.value, code, "RESPONSE_CONTRACT")


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("private_status", "CURRENT_MANAGER_PRIVATE_RULES_STATUS_INVALID"),
        ("authority", "CURRENT_MANAGER_RULES_AUTHORITY_INVALID"),
        ("compilation", "CURRENT_MANAGER_RULES_COMPILATION_FAILED"),
    ],
)
def test_provider_rules_failures_name_actual_protected_raise(manager_context, case, code) -> None:
    verified, capability, authority = _rules_authority(DECLARED)
    if case == "private_status":
        kwargs = {"private_rules_authority": authority}
    elif case == "authority":
        kwargs = {"ruleset": verified, "capability": capability}
    else:
        kwargs = {"ruleset": manager_context[1].model_copy(update={"ruleset_hash": "0" * 64})}
    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, **kwargs)
    assert caught.value.code == "CONFIGURATION_INVALID"
    _assert_report(caught.value, code, "INPUT_CONTRACT")


def test_inconsistent_rule_views_are_reported_without_accepting_them(manager_context) -> None:
    fpl_input, ruleset, capability, _ = manager_context
    active = manager_current._compile_active_rules(ruleset, capability, information_cutoff=CUTOFF)
    invalid = replace(active, tactical=active.tactical.model_copy(update={"squad_size": 16}))
    with pytest.raises(IngestionError) as caught:
        manager_current._require_rules_match_catalogue(fpl_input, invalid)
    _assert_report(caught.value, "CURRENT_MANAGER_RULE_VIEWS_INCONSISTENT", "INPUT_CONTRACT")


def test_missing_price_unit_remains_unresolved(manager_context) -> None:
    fpl_input, ruleset, capability, _ = manager_context
    active = manager_current._compile_active_rules(ruleset, capability, information_cutoff=CUTOFF)
    declaration = manager_provider.provider_current_manager_declaration(
        _source(manager_context), fpl_input, active.chips, observed_at=DECLARED
    )
    invalid = replace(
        active, tactical=active.tactical.model_copy(update={"initial_budget_tenths": None})
    )
    with pytest.raises(IngestionError) as caught:
        manager_current._resolve_squad(declaration, fpl_input, invalid)
    _assert_report(caught.value, "CURRENT_MANAGER_PRICE_UNIT_UNRESOLVED", "INPUT_CONTRACT")


def test_active_free_hit_still_refuses_missing_restoration_state(manager_context) -> None:
    def activate_free_hit(body):
        next(chip for chip in body["chips"] if chip["name"] == "freehit")["status_for_entry"] = (
            "active"
        )

    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, _source(manager_context, mutation=activate_free_hit))
    assert caught.value.code == "USAGE_INVALID"
    _assert_report(
        caught.value, "CURRENT_MANAGER_FREE_HIT_RESTORATION_UNAVAILABLE", "MODEL_CONTRACT"
    )


def test_provider_naive_manager_clock_is_reported(manager_context) -> None:
    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, clock=lambda: MANAGER_RECEIVED.replace(tzinfo=None))
    _assert_report(caught.value, "CURRENT_MANAGER_CLOCK_NAIVE", "INTERNAL_EXCEPTION")


def test_provider_regressed_manager_clock_is_reported(manager_context) -> None:
    times = iter((MANAGER_USABLE, MANAGER_RECEIVED))
    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, clock=lambda: next(times))
    _assert_report(caught.value, "CURRENT_MANAGER_CLOCK_REGRESSED", "INTERNAL_EXCEPTION")


def test_owned_manual_regressed_clock_uses_its_separate_exact_site(
    manager_context, tmp_path: Path
) -> None:
    fpl_input, ruleset, capability, _ = manager_context
    declaration = tmp_path / "owned-manager.json"
    declaration.write_text(json.dumps(declaration_for(fpl_input, ruleset)), encoding="utf-8")
    request = manager_current.bind_current_manager_state_request(
        declaration, fpl_input, ruleset, capability
    )
    times = iter((MANAGER_USABLE, MANAGER_RECEIVED))
    with pytest.raises(IngestionError) as caught:
        manager_current.CurrentManagerStateService(clock=lambda: next(times)).compile(
            request, fpl_input=fpl_input, ruleset=ruleset, capability=capability
        )
    _assert_report(caught.value, "CURRENT_MANAGER_CLOCK_REGRESSED", "INTERNAL_EXCEPTION")


def _literal_sites(module, *, provider_only):
    tree = ast.parse(Path(module.__file__).read_bytes())
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CurrentManagerStateService":
            functions.update(
                {item.name: item for item in node.body if isinstance(item, ast.FunctionDef)}
            )
    if provider_only:
        pending = [
            "compile_provider_snapshot"
            if module is manager_current
            else "provider_current_manager_declaration"
        ]
        reachable = set()
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            for call in ast.walk(functions[name]):
                if isinstance(call, ast.Call):
                    candidate = (
                        call.func.id
                        if isinstance(call.func, ast.Name)
                        else (
                            call.func.attr
                            if isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "self"
                            else None
                        )
                    )
                    if candidate in functions and candidate not in reachable:
                        pending.append(candidate)
    else:
        reachable = set(functions)
    sites = set()
    for name in reachable:
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            call = node.exc
            if (
                isinstance(call.func, ast.Name)
                and call.func.id == "IngestionError"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value in UNMAPPED_MANAGER_CODES
            ):
                sites.add((module.__name__, name, node.lineno, call.args[0].value))
    return sites


def test_fixed_table_covers_exact_provider_reachable_unmapped_manager_sites() -> None:
    assert set(diagnostics._MANAGER_FAILURE_SITES) == EXPECTED_SITES
    provider_sites = _literal_sites(manager_current, provider_only=True) | _literal_sites(
        manager_provider, provider_only=True
    )
    manual_clock = (CURRENT, "compile", 1341, "INTERNAL_INVARIANT")
    assert provider_sites == EXPECTED_SITES - {manual_clock}
    all_sites = _literal_sites(manager_current, provider_only=False) | _literal_sites(
        manager_provider, provider_only=False
    )
    assert all_sites >= EXPECTED_SITES
    # File parsing, declarations and request-file access do not add provider-callsite refinements.
    assert all(
        site[1] not in {"_read_declaration", "_parse_declaration"} for site in EXPECTED_SITES
    )


@pytest.mark.parametrize(
    "raw_code",
    [
        "SCHEMA_DRIFT",
        "CONFIGURATION_INVALID",
        "USAGE_INVALID",
        "INTERNAL_INVARIANT",
        "OWNED_UNKNOWN_CODE",
    ],
)
def test_matching_raw_code_without_exact_owned_raise_site_stays_unrecognized(raw_code) -> None:
    try:
        raise IngestionError(raw_code, CANARY, details={"owned_private_input": CANARY})
    except IngestionError as error:
        result = safe_failure(error, "MANAGER_STATE")
    assert result.code == "CURRENT_TYPED_FAILURE_UNRECOGNIZED"
    assert result.typed_code_recognized is False
    assert CANARY not in result.model_dump_json()


@pytest.mark.parametrize("part", ["module", "function", "line", "raw_code"])
def test_changed_tuple_component_cannot_match_real_chip_site(
    manager_context, monkeypatch, part
) -> None:
    key = (PROVIDER, "_chip_declarations", 114, "SCHEMA_DRIFT")
    replacement = list(key)
    index = {"module": 0, "function": 1, "line": 2, "raw_code": 3}[part]
    replacement[index] = key[index] + 1 if part == "line" else "OWNED_OTHER_COMPONENT"
    monkeypatch.setattr(
        diagnostics,
        "_MANAGER_FAILURE_SITES",
        {tuple(replacement): diagnostics._MANAGER_FAILURE_SITES[key]},
    )
    source = _source(manager_context, mutation=lambda body: body["chips"][0].update(name=CANARY))
    with pytest.raises(IngestionError) as caught:
        _compile(manager_context, source)
    result = safe_failure(caught.value, "MANAGER_STATE")
    assert result.code == "CURRENT_TYPED_FAILURE_UNRECOGNIZED"
    assert result.typed_code_recognized is False


def test_validation_error_does_not_export_input_value_or_context() -> None:
    class OwnedInput(BaseModel):
        count: int

    with pytest.raises(ValidationError) as caught:
        OwnedInput(count=CANARY)
    result = safe_failure(caught.value, "MANAGER_STATE")
    assert result.code == "CURRENT_INPUT_CONTRACT_FAILED"
    assert CANARY not in result.model_dump_json() and "input_value" not in result.model_dump_json()


def test_other_exception_family_cannot_claim_manager_refinement() -> None:
    class OwnedOtherFailure(RuntimeError):
        code = "SCHEMA_DRIFT"

        def __str__(self):
            raise AssertionError("exception text must never be read")

    result = safe_failure(OwnedOtherFailure(CANARY), "MANAGER_STATE")
    assert result.code == "CURRENT_INTERNAL_EXCEPTION"
    assert result.exception_family == "OTHER"
    assert CANARY not in result.model_dump_json()
