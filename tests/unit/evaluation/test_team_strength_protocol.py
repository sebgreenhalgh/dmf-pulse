"""Result-blind protocol contracts and adversarial governance checks."""

import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.evaluation.team_strength_protocol import (
    DRAW_POLICY_SHA,
    P01_SHA,
    CampaignLedgerV1,
    CohortAssignment,
    CohortEvent,
    ProspectiveProtocolV1,
    amend_protocol,
    append_event,
    freeze_window,
    guard_freeze,
    load_protocol,
    plan_cohort,
    protocol_summary,
)
from dmf_pulse.evaluation.team_strength_protocol_store import (
    load_campaign,
    load_protocol_evidence,
    persist_protocol_evidence,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate, seal
from tests.unit.private_v1.team_strength_shadow_support import synthetic_strength

STAMP = datetime(2026, 10, 10, 12, tzinfo=UTC)


def assignment(*, cohort="P01", fixture=1, scheduled=date(2026, 10, 12), mode="LIVE_OBSERVED"):
    protocol = load_protocol()
    start, _ = freeze_window(scheduled)
    return CohortAssignment(
        cohort_id=cohort,
        protocol_sha256=protocol.semantic_sha256,
        evaluation_epoch=protocol.evaluation_epoch,
        forecast_sha256=P01_SHA if cohort == "P01" else str(fixture).zfill(64),
        fixture_ids=(UUID(int=fixture),),
        scheduled_dates=(scheduled,),
        forecast_origin=start,
        frozen_at=start,
        dataset_mode=mode,
        draw_policy_sha256=DRAW_POLICY_SHA,
        model_artifact_sha256="a" * 64,
        model_sha256="b" * 64,
        source_snapshot_sha256="c" * 64,
        fixture_registry_sha256="d" * 64,
        methodology_sha256=protocol.methodology_sha256,
        cohort_class="PROSPECTIVE_PILOT_COHORT"
        if cohort == "P01"
        else "STANDARD_PROSPECTIVE_COHORT",
        lead_time_class="P01_PILOT_LONG_LEAD" if cohort == "P01" else "P02_PLUS_STANDARD_WINDOW",
    )


def ledger(*, pilot=None, at=STAMP):
    events = (
        ()
        if pilot is None
        else (
            CohortEvent(
                cohort_id="P01",
                status="FROZEN",
                recorded_at=at,
                assignment=pilot,
                detail="Synthetic contract pilot",
            ),
        )
    )
    return seal(CampaignLedgerV1, protocol=load_protocol(), created_at=at, events=events)


def test_canonical_protocol_serialization_and_authentication():
    protocol = load_protocol()
    assert authenticate(protocol, protocol.semantic_sha256) == protocol
    summary = protocol_summary(protocol)
    encoded = canonical_json_bytes(summary)
    reordered = dict(reversed(list(summary.items())))
    assert encoded == canonical_json_bytes(reordered)
    assert ProspectiveProtocolV1.model_validate_json(encoded) == protocol
    assert protocol.effective_from_cohort == "P02"
    assert protocol.protocol_semantic_sha256 == protocol.semantic_sha256
    assert not protocol.automatic_activation and not protocol.production_active
    assert protocol.parameter_mixture_status == "RESEARCH_ONLY"
    assert not protocol.operational_draw_count_selected


@pytest.mark.parametrize(
    "field,value",
    [
        ("cohort_size", 9),
        ("effective_from_cohort", "P01"),
        ("freeze_window_hours", 12),
        ("production_activation", True),
        ("automatic_activation", True),
        ("private_provider_policy", "ALLOW_FPL"),
        ("draw_policy_sha256", "0" * 64),
        ("primary_metric", "BEST_OBSERVED_SCORE"),
        ("primary_comparison", ("x", "y")),
        ("secondary_metrics", ("x",)),
        ("interim_review_policy", (1, 2)),
        ("subgroup_registry", ("PROBABILITY_BAND",)),
    ],
)
def test_predeclared_policy_cannot_be_silently_changed(field, value):
    protocol = load_protocol()
    values = protocol.model_dump(
        mode="python", exclude={"semantic_sha256", "protocol_semantic_sha256"}
    )
    values[field] = value
    with pytest.raises(ValueError):
        seal(ProspectiveProtocolV1, **values)


def test_private_schema_and_rehashed_alias_tampering_rejected():
    values = protocol_summary(load_protocol())
    values["manager_state"] = {"private": True}
    with pytest.raises(ValueError):
        ProspectiveProtocolV1.model_validate_json(json.dumps(values))
    del values["manager_state"]
    values["protocol_semantic_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        ProspectiveProtocolV1.model_validate_json(json.dumps(values))
    with pytest.raises(ValueError):
        authenticate(load_protocol(), "e" * 64)


def test_amendment_requires_new_version_epoch_and_preserves_old_evidence():
    protocol = load_protocol()
    before = protocol.model_dump_json()
    revised = amend_protocol(
        protocol, ticket="CURRENT-TEAM-STRENGTH-001V-AMEND-01", created_at=STAMP + timedelta(days=1)
    )
    assert revised.protocol_version == "2.0.0"
    assert revised.evaluation_epoch == "EVALUATION_EPOCH_002"
    assert revised.predecessor_protocol_sha256 == protocol.semantic_sha256
    assert protocol.model_dump_json() == before
    with pytest.raises(ValueError):
        amend_protocol(protocol, ticket="invalid", created_at=STAMP)


def test_protocol_store_authenticates_and_rejects_collision(tmp_path):
    protocol = load_protocol()
    path = persist_protocol_evidence(protocol, artifact_root=tmp_path)
    assert path.name == protocol.semantic_sha256 + ".json"
    assert load_protocol_evidence(path, expected_sha256=protocol.semantic_sha256) == protocol
    assert persist_protocol_evidence(protocol, artifact_root=tmp_path) == path
    path.write_text("different bytes", encoding="utf-8")
    with pytest.raises(ValueError, match="collision"):
        persist_protocol_evidence(protocol, artifact_root=tmp_path)


def test_target_window_and_inclusive_six_hours():
    start, end = freeze_window(date(2026, 10, 17))
    assert start == datetime(2026, 10, 15, 12, tzinfo=UTC)
    assert end == datetime(2026, 10, 15, 18, tzinfo=UTC)
    row = assignment(cohort="P02", scheduled=date(2026, 10, 17))
    assert row.model_copy(update={"frozen_at": end}).frozen_at == end
    with pytest.raises(ValueError, match="MISSED"):
        row.model_copy(update={"frozen_at": end + timedelta(microseconds=1)})
    with pytest.raises(ValueError):
        row.model_copy(update={"forecast_origin": start - timedelta(microseconds=1)})


def test_pilot_classification_fixed():
    row = assignment()
    assert row.cohort_class == "PROSPECTIVE_PILOT_COHORT"
    with pytest.raises(ValueError):
        row.model_copy(update={"lead_time_class": "P02_PLUS_STANDARD_WINDOW"})


def test_no_overlap_date_move_no_replacement_and_terminal_identity():
    first = ledger(pilot=assignment())
    second = assignment(cohort="P02", fixture=1)
    with pytest.raises(ValueError, match="prior cohort"):
        append_event(
            first,
            CohortEvent(
                cohort_id="P02",
                status="FROZEN",
                recorded_at=STAMP,
                assignment=second,
                detail="Overlap",
            ),
        )
    moved = first.events[0].assignment.model_copy(update={"scheduled_dates": (date(2026, 10, 13),)})
    with pytest.raises(ValueError, match="rewritten"):
        append_event(
            first,
            CohortEvent(
                cohort_id="P01",
                status="OUTCOME_NOT_YET_ELIGIBLE",
                recorded_at=STAMP,
                assignment=moved,
                detail="No rewrite",
            ),
        )
    missing = append_event(
        first,
        CohortEvent(
            cohort_id="P02",
            status="FREEZE_WINDOW_MISSED",
            recorded_at=STAMP,
            detail="Retain operational miss",
        ),
    )
    assert missing.events[: len(first.events)] == first.events
    with pytest.raises(ValueError, match="terminal"):
        append_event(
            missing,
            CohortEvent(
                cohort_id="P02",
                status="FROZEN",
                recorded_at=STAMP,
                assignment=assignment(cohort="P02", fixture=2),
                detail="Cannot reuse missed identity",
            ),
        )


def test_ledger_store_preserves_predecessor_and_failures(tmp_path):
    first = ledger(pilot=assignment())
    before = first.model_dump_json()
    path = persist_protocol_evidence(first, artifact_root=tmp_path)
    second = append_event(
        first,
        CohortEvent(
            cohort_id="P02",
            status="SOURCE_BLOCKED",
            recorded_at=STAMP,
            detail="Public source unavailable",
        ),
    )
    second_path = persist_protocol_evidence(second, artifact_root=tmp_path)
    assert load_campaign(path, expected_sha256=first.semantic_sha256).model_dump_json() == before
    assert (
        load_campaign(second_path, expected_sha256=second.semantic_sha256).events[-1].status
        == "SOURCE_BLOCKED"
    )
    assert second.predecessor_sha256 == first.semantic_sha256


@pytest.mark.parametrize("change", ["epoch", "draw", "method"])
def test_epoch_draw_method_mismatch(change):
    row = assignment()
    field = {
        "epoch": "evaluation_epoch",
        "draw": "draw_policy_sha256",
        "method": "methodology_sha256",
    }[change]
    bad = row.model_copy(update={field: "EVALUATION_EPOCH_002" if change == "epoch" else "f" * 64})
    with pytest.raises(ValueError, match="epoch mismatch"):
        ledger(pilot=bad)


def test_deterministic_order_ten_and_season_end_partial():
    dataset, _ = synthetic_strength(mode="LIVE_OBSERVED")
    schedule = dataset.sources[-1]
    as_of = STAMP
    base = ledger(at=as_of)
    plan = plan_cohort(
        ledger=base, schedule=schedule, registry=dataset.fixture_registry, as_of=as_of
    )
    candidates = sorted(
        (
            row
            for row in schedule.matches
            if row.finality == "NO_SCORE" and row.source_match_date > as_of.date()
        ),
        key=lambda row: (row.source_match_date, row.fixture.fixture_id),
    )
    assert plan.fixture_ids == tuple(row.fixture.fixture_id for row in candidates[:10])
    assert len(plan.fixture_ids) == 10
    # Retain an authenticated subset schedule to exercise a legitimate season-end tail.
    values = schedule.model_dump(mode="python", exclude={"semantic_sha256"})
    values["matches"] = tuple(candidates[-3:])
    tail = seal(type(schedule), **values)
    partial = plan_cohort(
        ledger=base, schedule=tail, registry=dataset.fixture_registry, as_of=as_of
    )
    assert len(partial.fixture_ids) == 3
    with pytest.raises(ValueError, match="MISSED"):
        guard_freeze(
            plan,
            ledger=base,
            schedule=schedule,
            registry=dataset.fixture_registry,
            forecast_origin=plan.freeze_window_end + timedelta(seconds=1),
            frozen_at=plan.freeze_window_end + timedelta(seconds=1),
        )
