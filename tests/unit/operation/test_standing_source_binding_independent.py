"""Pure owned proof-to-lineage/chronology attacks; no recommendation is executed."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.operation.chip_schema_compat import StandingSourceSchemaProof
from dmf_pulse.operation.diagnostics import DiagnosticEvent
from dmf_pulse.operation.standing_pipeline import validate_standing_source_proof
from dmf_pulse.private_v1 import one_command as accepted
from dmf_pulse.private_v1.models import PrivateDecisionLineage, PrivateV1Decision
from dmf_pulse.rules.chips import build_chip_rules_view

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def owned_rules():
    # Existing packaged rule compilation only; this creates no grant or activation.
    return accepted._rules_authority(NOW)


@pytest.fixture
def case(owned_rules):
    rules, capability, authority = owned_rules
    chips = compile_optimisation_chip_rules(build_chip_rules_view(rules))
    proof = StandingSourceSchemaProof.model_validate_json(
        canonical_json_bytes(
            {
                "target_gameweek": 11,
                "snapshot_sha256": "a" * 64,
                "fpl_input_sha256": "b" * 64,
                "manager_state_sha256": "c" * 64,
                "ruleset_sha256": rules.ruleset_hash,
                "capability_sha256": capability.capability_hash,
                "private_rules_authority_sha256": authority.attestation_sha256,
                "chip_schema_proof": {
                    "source_manager_sha256": "1" * 64,
                    "compiler_argument_sha256": "2" * 64,
                    "governed_chip_bundle_sha256": canonical_sha256(chips.model_dump(mode="json")),
                    "assignment_sha256": "3" * 64,
                    "translated_played_records": 1,
                    "omitted_inactive_records": 4,
                },
            }
        )
    )
    schema = DiagnosticEvent(
        sequence=2,
        at=NOW + timedelta(seconds=5),
        kind="SOURCE_SCHEMA_COMPATIBILITY",
        stage="MANAGER_STATE",
        source_schema_proof=proof,
    )
    market = DiagnosticEvent.model_validate_json(
        canonical_json_bytes(
            {
                "sequence": 3,
                "at": (NOW + timedelta(seconds=6)).isoformat(),
                "kind": "ADMITTED",
                "stage": "MARKET_ACQUISITION",
                "request": {
                    "provider": "ODDS",
                    "route_sha256": "4" * 64,
                    "ordinal": 1,
                },
            }
        )
    )
    # Partial owned types cover only this binding seam. They never enter a kernel,
    # result envelope, publication, database or provider path.
    lineage = PrivateDecisionLineage.model_construct(
        fpl_input_sha256=proof.fpl_input_sha256,
        manager_state_sha256=proof.manager_state_sha256,
        ruleset_sha256=proof.ruleset_sha256,
        private_rules_authority_sha256=proof.private_rules_authority_sha256,
    )
    decision = PrivateV1Decision.model_construct(target_gameweek=11, lineage=lineage)
    result = SimpleNamespace(decision=decision)
    request = SimpleNamespace(
        horizon=1,
        authorization_id="OPR001-OWNED-BINDING-ONLY",
        information_cutoff=NOW + timedelta(seconds=300),
    )
    launch = SimpleNamespace(grant=SimpleNamespace(issued_at=NOW, request=request))
    return SimpleNamespace(
        events=(schema, market),
        proof=proof,
        result=result,
        launch=launch,
        rules=rules,
        capability=capability,
        authority=authority,
    )


def refuses(case, events=None, result=None, launch=None):
    with pytest.raises(AuthorizationError) as caught:
        validate_standing_source_proof(
            case.events if events is None else events, result or case.result, launch or case.launch
        )
    assert caught.value.code == "WORKER_RESULT_BINDING_INVALID"


def changed_lineage_result(case, field):
    # Bypass whole-decision construction only for a deliberately partial owned
    # binding-seam DTO. Public model_copy correctly rejects partial full models.
    fields = case.result.decision.lineage.model_dump(mode="python")
    fields[field] = "9" * 64
    lineage = PrivateDecisionLineage.model_construct(**fields)
    decision = PrivateV1Decision.model_construct(target_gameweek=11, lineage=lineage)
    return SimpleNamespace(decision=decision)


def test_one_owned_manager_proof_before_market_matches_existing_lineage(case):
    validate_standing_source_proof(case.events, case.result, case.launch)


@pytest.mark.parametrize(
    "events", ["none", "missing_schema", "missing_market", "two_schema", "two_market"]
)
def test_proof_and_market_admission_are_each_unique(case, events):
    first, market = case.events
    values = {
        "none": (),
        "missing_schema": (market,),
        "missing_market": (first,),
        "two_schema": (first, first, market),
        "two_market": (first, market, market),
    }
    refuses(case, events=values[events])


@pytest.mark.parametrize(
    "field",
    [
        "fpl_input_sha256",
        "manager_state_sha256",
        "ruleset_sha256",
        "capability_sha256",
        "private_rules_authority_sha256",
    ],
)
def test_wrong_valid_hash_in_proof_cannot_bind_the_result(case, field):
    changed = case.proof.model_copy(update={field: "9" * 64})
    event = case.events[0].model_copy(update={"source_schema_proof": changed})
    refuses(case, events=(event, case.events[1]))


def test_wrong_governed_chip_bundle_does_not_bind_current_rules(case):
    chip = case.proof.chip_schema_proof.model_copy(update={"governed_chip_bundle_sha256": "9" * 64})
    changed = case.proof.model_copy(update={"chip_schema_proof": chip})
    event = case.events[0].model_copy(update={"source_schema_proof": changed})
    refuses(case, events=(event, case.events[1]))


@pytest.mark.parametrize(
    "field",
    [
        "fpl_input_sha256",
        "manager_state_sha256",
        "ruleset_sha256",
        "private_rules_authority_sha256",
    ],
)
def test_wrong_result_lineage_cannot_be_excused_by_a_valid_proof(case, field):
    refuses(case, result=changed_lineage_result(case, field))


@pytest.mark.parametrize("target", [1, 10, 12, 38])
def test_different_target_in_proof_is_rejected(case, target):
    changed = case.proof.model_copy(update={"target_gameweek": target})
    refuses(
        case,
        events=(case.events[0].model_copy(update={"source_schema_proof": changed}), case.events[1]),
    )


@pytest.mark.parametrize(
    "where", ["same_sequence", "later_sequence", "pre_grant", "after_market", "market_after_cutoff"]
)
def test_event_chronology_cannot_move_past_market_or_grant_bounds(case, where):
    first, market = case.events
    if where == "same_sequence":
        first = first.model_copy(update={"sequence": market.sequence})
    elif where == "later_sequence":
        first = first.model_copy(update={"sequence": market.sequence + 1})
    elif where == "pre_grant":
        first = first.model_copy(update={"at": NOW - timedelta(microseconds=1)})
    elif where == "after_market":
        first = first.model_copy(update={"at": market.at + timedelta(microseconds=1)})
    else:
        market = market.model_copy(
            update={"at": case.launch.grant.request.information_cutoff + timedelta(microseconds=1)}
        )
    refuses(case, events=(first, market))


@pytest.mark.parametrize(
    "authorization,horizon",
    [
        ("OPR003-OWNED", 1),
        ("OPR001-OWNED", 3),
        ("CALLER-OWNED", 1),
    ],
)
def test_proof_does_not_confer_authority_for_another_path(case, authorization, horizon):
    launch = deepcopy(case.launch)
    launch.grant.request.authorization_id = authorization
    launch.grant.request.horizon = horizon
    refuses(case, launch=launch)


def test_rules_authority_is_resolved_from_actual_grant_issue_time(case):
    launch = deepcopy(case.launch)
    launch.grant.issued_at = NOW - timedelta(seconds=1)
    refuses(case, launch=launch)


def test_same_mutation_of_result_and_proof_still_cannot_override_packaged_rules(case):
    proof = case.proof.model_copy(update={"ruleset_sha256": "9" * 64})
    event = case.events[0].model_copy(update={"source_schema_proof": proof})
    result = changed_lineage_result(case, "ruleset_sha256")
    refuses(case, events=(event, case.events[1]), result=result)
