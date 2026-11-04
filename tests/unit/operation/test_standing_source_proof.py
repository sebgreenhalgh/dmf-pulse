"""Closed derived metadata keeps historical diagnostic wires and rejects misuse."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dmf_pulse.operation.chip_schema_compat import ChipSchemaProof, StandingSourceSchemaProof
from dmf_pulse.operation.diagnostics import DiagnosticEvent, DiagnosticLog

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def owned_proof() -> StandingSourceSchemaProof:
    return StandingSourceSchemaProof(
        target_gameweek=11,
        snapshot_sha256="a" * 64,
        fpl_input_sha256="b" * 64,
        manager_state_sha256="c" * 64,
        ruleset_sha256="d" * 64,
        capability_sha256="e" * 64,
        private_rules_authority_sha256="f" * 64,
        chip_schema_proof=ChipSchemaProof(
            source_manager_sha256="1" * 64,
            compiler_argument_sha256="2" * 64,
            governed_chip_bundle_sha256="3" * 64,
            assignment_sha256="4" * 64,
            translated_played_records=1,
            omitted_inactive_records=4,
        ),
    )


def test_legacy_event_wire_is_exactly_unchanged():
    event = DiagnosticEvent(sequence=0, at=NOW, kind="STAGE_STARTED", stage="WORKER_START")
    assert event.model_dump(mode="json") == {
        "schema_version": "operator-diagnostic-event-v1",
        "sequence": 0,
        "at": "2026-11-04T00:00:00Z",
        "kind": "STAGE_STARTED",
        "stage": "WORKER_START",
        "request": None,
        "http_status": None,
        "http_category": None,
        "failure": None,
    }


def test_fixed_proof_round_trips_through_the_existing_event_reducer():
    sent = []
    source = DiagnosticLog(clock=lambda: NOW, send=sent.append)
    source.enter("MANAGER_STATE")
    source.emit("SOURCE_SCHEMA_COMPATIBILITY", source_schema_proof=owned_proof())
    parent = DiagnosticLog(clock=lambda: NOW)
    for event in sent:
        parent.accept(DiagnosticEvent.model_validate_json(event.model_dump_json()))
    assert parent.report() == source.report()
    assert parent.events[-1].source_schema_proof == owned_proof()
    assert len(parent.events[-1].model_dump_json().encode()) < 4096


@pytest.mark.parametrize(
    "kind,stage,proof",
    [
        ("SOURCE_SCHEMA_COMPATIBILITY", "MANAGER_STATE", None),
        ("SOURCE_SCHEMA_COMPATIBILITY", "MARKET_ACQUISITION", owned_proof()),
        ("STAGE_STARTED", "MANAGER_STATE", owned_proof()),
    ],
)
def test_proof_has_one_fixed_kind_and_manager_stage(kind, stage, proof):
    with pytest.raises(ValidationError):
        DiagnosticEvent(sequence=0, at=NOW, kind=kind, stage=stage, source_schema_proof=proof)


def test_arbitrary_provider_values_and_boolean_gameweek_are_refused():
    data = owned_proof().model_dump(mode="json")
    for key, value in (
        ("snapshot_sha256", "owned-private-value-canary"),
        ("target_gameweek", True),
    ):
        with pytest.raises(ValidationError):
            StandingSourceSchemaProof.model_validate_json(json.dumps({**data, key: value}))
