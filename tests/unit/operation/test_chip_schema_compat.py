"""A source-schema adapter preserves accepted chip semantics and closed failures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from dmf_pulse.ingestion.fpl.manager_provider import (
    _chip_declarations,
    parse_provider_current_team,
    provider_current_manager_declaration,
)
from dmf_pulse.operation.chip_schema_compat import adapt_chip_source
from dmf_pulse.operation.diagnostics import safe_failure
from dmf_pulse.rules.chips import build_chip_rules_view
from tests.unit.ingestion.current_manager_test_support import DECLARED, MANAGER_RECEIVED
from tests.unit.ingestion.test_fpl_manager_provider import _context

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def context(repository_root: Path):
    return _context(repository_root)


def source_for(context, *, chips=None):
    body = deepcopy(context[3])
    if chips is not None:
        body["chips"] = chips
    return parse_provider_current_team(json.dumps(body).encode())


def bundle_for(context):
    return compile_optimisation_chip_rules(build_chip_rules_view(context[1]))


@pytest.mark.parametrize("status", ["available", "unavailable", "active", "pending"])
def test_known_single_copy_contract_and_opaque_number_are_preserved(context, status):
    chips = deepcopy(context[3]["chips"])
    chips[0].update(number=27, status_for_entry=status)
    source = source_for(context, chips=chips)
    bundle = bundle_for(context)
    adapted = adapt_chip_source(source, bundle, target_gameweek=3)
    assert adapted.compiler_source == source
    assert adapted.proof.source_manager_sha256 == adapted.proof.compiler_argument_sha256
    assert adapted.proof.translated_played_records == adapted.proof.omitted_inactive_records == 0
    assert _chip_declarations(adapted.compiler_source, bundle, target_gameweek=3) == (
        _chip_declarations(source, bundle, target_gameweek=3)
    )


def test_played_status_uses_exact_existing_used_semantics_without_mutating_source(context):
    chips = deepcopy(context[3]["chips"])
    chips[0].update(status_for_entry="played", played_by_entry=[2])
    source = source_for(context, chips=chips)
    before = source.model_dump_json()
    bundle = bundle_for(context)
    adapted = adapt_chip_source(source, bundle, target_gameweek=3)
    expected = deepcopy(chips)
    expected[0]["status_for_entry"] = "unavailable"
    legacy = source_for(context, chips=expected)
    assert adapted.compiler_source == legacy
    assert source.model_dump_json() == before
    assert source.chips[0].status_for_entry == "played"
    assert adapted.proof.translated_played_records == 1
    assert adapted.proof.omitted_inactive_records == 0
    assert adapted.proof.source_manager_sha256 == canonical_sha256(source.model_dump(mode="json"))
    assert _chip_declarations(adapted.compiler_source, bundle, target_gameweek=3) == (
        _chip_declarations(legacy, bundle, target_gameweek=3)
    )


@pytest.mark.parametrize("used", [False, True])
def test_explicit_future_copies_require_unique_current_or_used_assignment(context, used):
    chips = deepcopy(context[3]["chips"])
    if used:
        chips[0].update(status_for_entry="played", played_by_entry=[2])
    complete = [
        candidate
        for chip in chips
        for candidate in (
            chip,
            {**chip, "number": 2, "status_for_entry": "unavailable", "played_by_entry": []},
        )
    ]
    source = source_for(context, chips=complete)
    bundle = bundle_for(context)
    adapted = adapt_chip_source(source, bundle, target_gameweek=3)
    assert len(source.chips) == 8 and len(adapted.compiler_source.chips) == 4
    assert adapted.proof.omitted_inactive_records == 4
    assert adapted.proof.translated_played_records == int(used)
    expected = deepcopy(chips)
    if used:
        expected[0]["status_for_entry"] = "unavailable"
    assert _chip_declarations(adapted.compiler_source, bundle, target_gameweek=3) == (
        _chip_declarations(source_for(context, chips=expected), bundle, target_gameweek=3)
    )


@pytest.mark.parametrize("history", [[], [2, 2], [1, 2], [3], [4], [1]])
def test_empty_duplicate_future_or_outside_window_played_history_refuses(context, history):
    chips = deepcopy(context[3]["chips"])
    chips[0].update(status_for_entry="played", played_by_entry=history)
    with pytest.raises(IngestionError):
        adapt_chip_source(source_for(context, chips=chips), bundle_for(context), target_gameweek=3)


def test_two_unavailable_copies_cannot_be_assigned_by_numbers(context):
    chips = deepcopy(context[3]["chips"])
    chips[0]["status_for_entry"] = "unavailable"
    chips.append({**chips[0], "number": 2})
    with pytest.raises(IngestionError) as caught:
        adapt_chip_source(source_for(context, chips=chips), bundle_for(context), target_gameweek=3)
    assert caught.value.code == "DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS"


@pytest.mark.parametrize(
    "field, value",
    [("name", "OWNED_PRIVATE_CHIP_CANARY"), ("status_for_entry", "OWNED_PRIVATE_STATUS_CANARY")],
)
def test_unknown_source_fields_remain_closed_and_absent_from_safe_diagnostics(
    context, field, value
):
    chips = deepcopy(context[3]["chips"])
    chips[0][field] = value
    with pytest.raises(IngestionError) as caught:
        adapt_chip_source(source_for(context, chips=chips), bundle_for(context), target_gameweek=3)
    failure = safe_failure(caught.value, "MANAGER_STATE")
    assert failure.typed_code_recognized
    assert failure.category == "RESPONSE_CONTRACT"
    assert value not in failure.model_dump_json()


def test_unchanged_manager_compiler_produces_exact_baseline_bundle(context):
    fpl_input, rules, capability, _ = context
    source = source_for(context)
    service = CurrentManagerStateService(clock=lambda: MANAGER_RECEIVED)
    baseline = service.compile_provider_snapshot(
        source, fpl_input=fpl_input, ruleset=rules, capability=capability, observed_at=DECLARED
    )
    bundle = bundle_for(context)
    adapted = adapt_chip_source(source, bundle, target_gameweek=fpl_input.target_gameweek)
    declaration = provider_current_manager_declaration(
        adapted.compiler_source, fpl_input, bundle, observed_at=DECLARED
    )
    actual = service.compile_provider_observed(
        declaration, fpl_input=fpl_input, ruleset=rules, capability=capability
    )
    assert actual == baseline
    assert actual.semantic_sha256 == baseline.semantic_sha256


def test_played_and_complete_future_copy_source_produces_existing_used_manager_bundle(context):
    fpl_input, rules, capability, _ = context
    chips = deepcopy(context[3]["chips"])
    next(chip for chip in chips if chip["name"] == "bboost").update(
        status_for_entry="unavailable", played_by_entry=[1]
    )
    legacy = source_for(context, chips=chips)
    service = CurrentManagerStateService(clock=lambda: MANAGER_RECEIVED)
    baseline = service.compile_provider_snapshot(
        legacy, fpl_input=fpl_input, ruleset=rules, capability=capability, observed_at=DECLARED
    )
    complete = []
    for chip in chips:
        current = {**chip}
        if chip["name"] == "bboost":
            current["status_for_entry"] = "played"
        complete.extend(
            (
                current,
                {**chip, "number": 2, "status_for_entry": "unavailable", "played_by_entry": []},
            )
        )
    original = source_for(context, chips=complete)
    bundle = bundle_for(context)
    adapted = adapt_chip_source(original, bundle, target_gameweek=fpl_input.target_gameweek)
    declaration = provider_current_manager_declaration(
        adapted.compiler_source, fpl_input, bundle, observed_at=DECLARED
    )
    actual = service.compile_provider_observed(
        declaration, fpl_input=fpl_input, ruleset=rules, capability=capability
    )
    assert actual == baseline
    assert adapted.proof.translated_played_records == 1
    assert adapted.proof.omitted_inactive_records == 4
    assert len(original.chips) == 8 and original.chips[4].status_for_entry == "played"


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_identity", "duplicate_current", "missing_family", "contradictory_history"],
)
def test_contradictions_and_nonunique_source_assignments_stay_rejected(context, mutation):
    chips = deepcopy(context[3]["chips"])
    if mutation == "duplicate_identity":
        chips.append({**chips[0], "status_for_entry": "unavailable"})
    elif mutation == "duplicate_current":
        chips.append({**chips[0], "number": 2})
    elif mutation == "missing_family":
        chips.pop()
    else:
        chips[0]["played_by_entry"] = [2]
    with pytest.raises(IngestionError) as caught:
        adapt_chip_source(source_for(context, chips=chips), bundle_for(context), target_gameweek=3)
    report = safe_failure(caught.value, "MANAGER_STATE")
    assert report.typed_code_recognized and report.category == "RESPONSE_CONTRACT"


def test_invalid_copied_provider_model_cannot_print_serializer_source_values(context, capsys):
    source = source_for(context).model_copy(update={"chips": "OWNED_PRIVATE_SERIALIZER_CANARY"})
    with pytest.raises(IngestionError) as caught:
        adapt_chip_source(source, bundle_for(context), target_gameweek=3)
    report = safe_failure(caught.value, "MANAGER_STATE")
    assert report.code == "DIAGNOSTIC_MANAGER_CHIP_SCHEMA_INVALID"
    assert "OWNED_PRIVATE_SERIALIZER_CANARY" not in report.model_dump_json()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
