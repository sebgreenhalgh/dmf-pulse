"""Independent owned metadata/legacy contracts; no provider, credential or database calls."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.operation.chip_schema_compat import ChipSchemaProof, StandingSourceSchemaProof
from dmf_pulse.operation.diagnostics import (
    DiagnosticEvent,
    DiagnosticLog,
    DiagnosticReport,
    safe_failure,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
CANARY = "OWNED_PRIVATE_SCHEMA_FIELD_6918_NEVER_EMIT"


def proof_payload():
    return {
        "target_gameweek": 11,
        "snapshot_sha256": "a" * 64,
        "fpl_input_sha256": "b" * 64,
        "manager_state_sha256": "c" * 64,
        "ruleset_sha256": "d" * 64,
        "capability_sha256": "e" * 64,
        "private_rules_authority_sha256": "f" * 64,
        "chip_schema_proof": {
            "source_manager_sha256": "1" * 64,
            "compiler_argument_sha256": "2" * 64,
            "governed_chip_bundle_sha256": "3" * 64,
            "assignment_sha256": "4" * 64,
            "translated_played_records": 1,
            "omitted_inactive_records": 4,
        },
    }


def proof():
    return StandingSourceSchemaProof.model_validate_json(canonical_json_bytes(proof_payload()))


def event_payload():
    return {
        "sequence": 0,
        "at": "2026-11-07T12:00:00Z",
        "kind": "SOURCE_SCHEMA_COMPATIBILITY",
        "stage": "MANAGER_STATE",
        "source_schema_proof": proof().model_dump(mode="json"),
    }


def test_owned_proof_is_exact_hash_count_metadata():
    actual = proof()
    wire = actual.model_dump(mode="json")
    assert set(wire) == {"schema_version", *proof_payload()}
    assert set(wire["chip_schema_proof"]) == {
        "schema_version",
        *proof_payload()["chip_schema_proof"],
    }
    assert actual.target_gameweek == 11
    assert CANARY not in actual.model_dump_json()
    event = DiagnosticEvent.model_validate_json(canonical_json_bytes(event_payload()))
    assert event.source_schema_proof == actual
    assert len(event.model_dump_json().encode()) < 4096


@pytest.mark.parametrize(
    "field",
    [
        "snapshot_sha256",
        "fpl_input_sha256",
        "manager_state_sha256",
        "ruleset_sha256",
        "capability_sha256",
        "private_rules_authority_sha256",
    ],
)
@pytest.mark.parametrize("bad", [CANARY, "a" * 63, "A" * 64, True, 123])
def test_wrong_hash_value_or_type_cannot_become_a_source_proof(field, bad):
    value = proof_payload()
    value[field] = bad
    with pytest.raises(ValidationError) as caught:
        StandingSourceSchemaProof.model_validate_json(canonical_json_bytes(value))
    failure = safe_failure(caught.value, "MANAGER_STATE")
    assert CANARY not in failure.model_dump_json()


@pytest.mark.parametrize("bad", [True, False, "11", 0, -1, 1.5])
def test_target_is_a_strict_positive_integer(bad):
    value = proof_payload()
    value["target_gameweek"] = bad
    with pytest.raises(ValidationError):
        StandingSourceSchemaProof.model_validate_json(canonical_json_bytes(value))


@pytest.mark.parametrize("field", ["translated_played_records", "omitted_inactive_records"])
@pytest.mark.parametrize("bad", [True, "1", -1, 1.5])
def test_nested_counts_do_not_accept_boolean_coercion_or_negative_values(field, bad):
    value = proof_payload()
    value["chip_schema_proof"][field] = bad
    with pytest.raises(ValidationError):
        StandingSourceSchemaProof.model_validate_json(canonical_json_bytes(value))


@pytest.mark.parametrize("where", ["proof", "chip", "event"])
def test_arbitrary_source_body_or_private_field_is_rejected_and_sanitized(where):
    value = event_payload()
    target = value if where == "event" else value["source_schema_proof"]
    if where == "chip":
        target = target["chip_schema_proof"]
    target["source_body"] = CANARY
    with pytest.raises(ValidationError) as caught:
        DiagnosticEvent.model_validate_json(canonical_json_bytes(value))
    assert CANARY not in safe_failure(caught.value, "MANAGER_STATE").model_dump_json()


@pytest.mark.parametrize(
    "stage", ["WORKER_START", "FPL_ACQUISITION", "MARKET_ACQUISITION", "PUBLICATION"]
)
def test_source_proof_is_only_a_manager_stage_event(stage):
    value = event_payload()
    value["stage"] = stage
    with pytest.raises(ValidationError):
        DiagnosticEvent.model_validate_json(canonical_json_bytes(value))


@pytest.mark.parametrize("kind", ["STAGE_STARTED", "STAGE_COMPLETED", "ADMITTED", "FAILURE"])
def test_source_proof_cannot_be_hidden_on_another_event_kind(kind):
    value = event_payload()
    value["kind"] = kind
    with pytest.raises(ValidationError):
        DiagnosticEvent.model_validate_json(canonical_json_bytes(value))


def test_missing_source_proof_does_not_form_a_schema_event():
    value = event_payload()
    value.pop("source_schema_proof")
    with pytest.raises(ValidationError):
        DiagnosticEvent.model_validate_json(canonical_json_bytes(value))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("snapshot_sha256", CANARY),
        ("target_gameweek", True),
    ],
)
def test_copied_invalid_proof_is_revalidated_before_any_emit(field, bad):
    sent = []
    log = DiagnosticLog(clock=lambda: NOW, send=sent.append)
    log.stage = "MANAGER_STATE"
    copied = proof().model_copy(update={field: bad})
    with pytest.raises((ValidationError, ValueError)):
        log.emit("SOURCE_SCHEMA_COMPATIBILITY", source_schema_proof=copied)
    assert sent == [] and log.events == []


def test_copied_invalid_nested_chip_proof_is_revalidated_before_any_emit():
    sent = []
    log = DiagnosticLog(clock=lambda: NOW, send=sent.append)
    log.stage = "MANAGER_STATE"
    copied_chip = ChipSchemaProof.model_validate(proof().chip_schema_proof).model_copy(
        update={"assignment_sha256": CANARY}
    )
    copied = proof().model_copy(update={"chip_schema_proof": copied_chip})
    with pytest.raises((ValidationError, ValueError)):
        log.emit("SOURCE_SCHEMA_COMPATIBILITY", source_schema_proof=copied)
    assert sent == [] and log.events == []


def test_absent_proof_preserves_owned_legacy_event_and_containing_row_bytes():
    legacy = {
        "schema_version": "operator-diagnostic-event-v1",
        "sequence": 0,
        "at": "2026-11-07T12:00:00Z",
        "kind": "STAGE_STARTED",
        "stage": "MANAGER_STATE",
        "request": None,
        "http_status": None,
        "http_category": None,
        "failure": None,
    }
    actual = DiagnosticEvent.model_validate_json(canonical_json_bytes(legacy)).model_dump(
        mode="json"
    )
    assert canonical_json_bytes(actual) == canonical_json_bytes(legacy)
    assert "source_schema_proof" not in actual
    report = {
        "schema_version": "operator-diagnostic-report-v1",
        "stage": "MANAGER_STATE",
        "failure": None,
        "requests": [],
        "events": [legacy],
        "history_truncated": False,
        "chronology_complete": True,
        "worker_terminal_received": True,
    }
    rebuilt = DiagnosticReport.model_validate_json(canonical_json_bytes(report)).model_dump(
        mode="json"
    )
    row = {
        "sequence": 7,
        "payload": {"recorded_at": "2026-11-07T12:00:00Z", "value": {"diagnostics": report}},
    }
    reconstructed = deepcopy(row)
    reconstructed["payload"]["value"]["diagnostics"] = rebuilt
    assert canonical_json_bytes(rebuilt) == canonical_json_bytes(report)
    assert canonical_sha256(reconstructed) == canonical_sha256(row)
