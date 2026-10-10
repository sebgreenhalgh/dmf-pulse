"""Offline synthetic attacks, pairing, cluster inference and campaign retention."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.team_strength_campaign import _promoted_fixture_ids, verify_score_evidence
from dmf_pulse.evaluation.team_strength_campaign_report import (
    PairedCohort,
    _population,
    _summary,
    campaign_report,
    paired_differences,
    primary_inference,
    review_checkpoint_count,
)
from dmf_pulse.evaluation.team_strength_prospective import (
    PublicProspectiveScoreV1,
    freeze_public_team_forecasts,
    score_public_team_forecasts,
)
from dmf_pulse.evaluation.team_strength_protocol import (
    CampaignLedgerV1,
    CohortAssignment,
    CohortEvent,
    InferencePolicy,
    advance_campaign_protocol,
    amend_protocol,
    append_event,
    initial_campaign_ledger,
    next_freeze_opportunity,
    plan_cohort,
)
from dmf_pulse.evaluation.team_strength_protocol_store import (
    load_campaign,
    persist_protocol_evidence,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from tests.unit.evaluation.test_team_strength_prospective import frozen, outcome
from tests.unit.evaluation.test_team_strength_protocol import STAMP, assignment
from tests.unit.private_v1.team_strength_shadow_support import synthetic_strength


def test_root_cannot_be_rehashed_or_truncated(tmp_path):
    root = initial_campaign_ledger()
    values = root.model_dump(mode="python", exclude={"semantic_sha256"})
    values["created_at"] = root.created_at + timedelta(seconds=1)
    forged = seal(CampaignLedgerV1, **values)
    with pytest.raises(ValueError, match="genesis"):
        persist_protocol_evidence(forged, artifact_root=tmp_path)
    # Loading directly forged bytes is equally fail-closed.
    path = tmp_path / (forged.semantic_sha256 + ".json")
    path.write_text(forged.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="genesis"):
        load_campaign(path, expected_sha256=forged.semantic_sha256)


def test_predecessor_cannot_be_missing_or_history_rewritten(tmp_path):
    root = initial_campaign_ledger()
    prior = persist_protocol_evidence(root, artifact_root=tmp_path)
    child = append_event(
        root,
        CohortEvent(
            cohort_id="P02",
            status="SOURCE_BLOCKED",
            recorded_at=STAMP,
            detail="Retain unavailable source",
        ),
    )
    path = persist_protocol_evidence(child, artifact_root=tmp_path)
    prior.unlink()
    with pytest.raises(OSError):
        load_campaign(path, expected_sha256=child.semantic_sha256)
    persist_protocol_evidence(root, artifact_root=tmp_path)
    values = child.model_dump(mode="python", exclude={"semantic_sha256"})
    values["events"] = (root.events[0].model_copy(update={"detail": "rewritten"}), child.events[-1])
    forged = seal(CampaignLedgerV1, **values)
    with pytest.raises(ValueError, match=r"append|rewrite|edge"):
        persist_protocol_evidence(forged, artifact_root=tmp_path)


@pytest.mark.parametrize(
    "status", ["FREEZE_WINDOW_MISSED", "SOURCE_BLOCKED", "MODEL_FIT_BLOCKED", "SCHEDULE_BLOCKED"]
)
def test_freeze_failures_are_terminal_retained_evidence(status, tmp_path):
    root = initial_campaign_ledger()
    persist_protocol_evidence(root, artifact_root=tmp_path)
    child = append_event(
        root,
        CohortEvent(
            cohort_id="P02",
            status=status,
            recorded_at=STAMP,
            detail="Operational failure, no forecast",
        ),
    )
    path = persist_protocol_evidence(child, artifact_root=tmp_path)
    assert load_campaign(path, expected_sha256=child.semantic_sha256).events[-1].status == status


def test_next_window_reapplies_first_ten_without_hand_skipping():
    dataset, _ = synthetic_strength()
    root = initial_campaign_ledger()
    missed = plan_cohort(
        ledger=root, schedule=dataset.sources[-1], registry=dataset.fixture_registry, as_of=STAMP
    )
    assert missed.status == "COHORT_FREEZE_WINDOW_MISSED"
    child = append_event(
        root,
        CohortEvent(
            cohort_id=missed.cohort_id,
            status="FREEZE_WINDOW_MISSED",
            recorded_at=STAMP,
            detail="Expired governed window",
        ),
    )
    next_plan = next_freeze_opportunity(
        ledger=child, schedule=dataset.sources[-1], registry=dataset.fixture_registry, as_of=STAMP
    )
    assert next_plan.cohort_id == "P03" and next_plan.status == "READY"
    assert next_plan.target_freeze > STAMP
    assert next_plan == plan_cohort(
        ledger=child,
        schedule=dataset.sources[-1],
        registry=dataset.fixture_registry,
        as_of=next_plan.target_freeze,
    )
    assert child.events[-1].status == "FREEZE_WINDOW_MISSED"


def test_amendment_preserves_history_and_restarts_review_count(tmp_path):
    root = initial_campaign_ledger()
    persist_protocol_evidence(root, artifact_root=tmp_path)
    revised = amend_protocol(
        root.protocol,
        ticket="CURRENT-TEAM-STRENGTH-001V-AMEND-01",
        created_at=STAMP + timedelta(days=1),
    )
    child = advance_campaign_protocol(root, revised)
    path = persist_protocol_evidence(child, artifact_root=tmp_path)
    loaded = load_campaign(path, expected_sha256=child.semantic_sha256)
    assert loaded.events == root.events and loaded.protocol_history == (root.protocol,)
    with pytest.raises(ValueError, match="5/10"):
        campaign_report(ledger=child, reports=(), forecasts=(), outcomes=())


def test_pilot_alone_cannot_trigger_interim_review_or_promotion():
    with pytest.raises(ValueError, match="5/10"):
        campaign_report(ledger=initial_campaign_ledger(), reports=(), forecasts=(), outcomes=())


def paired_blocks(count=10):
    return tuple(
        PairedCohort(
            cohort_id=f"P{index + 2:02d}",
            fixture_ids=(UUID(int=2 * index + 1), UUID(int=2 * index + 2)),
            differences=(Decimal(index - 5), Decimal(index - 5)),
        )
        for index in range(count)
    )


def test_small_sample_explicitly_insufficient_and_negative_favours_plugin():
    result = primary_inference(
        paired_blocks(1), policy=InferencePolicy(), population_identity="fixed"
    )
    assert result.paired_mean_difference == -5
    assert result.status == "INSUFFICIENT_PROSPECTIVE_COHORTS_FOR_STABLE_INFERENCE"
    assert result.lower_95 is result.upper_95 is None and not result.promotion_decision


def test_bootstrap_reproducible_order_invariant_and_whole_cohort():
    blocks = paired_blocks()
    first = primary_inference(blocks, policy=InferencePolicy(), population_identity="fixed")
    assert first == primary_inference(
        tuple(reversed(blocks)), policy=InferencePolicy(), population_identity="fixed"
    )
    # Two identical correlated rows per block have exactly the same interval as one.
    singles = tuple(
        row.model_copy(
            update={"fixture_ids": row.fixture_ids[:1], "differences": row.differences[:1]}
        )
        for row in blocks
    )
    second = primary_inference(singles, policy=InferencePolicy(), population_identity="fixed")
    assert (first.lower_95, first.upper_95) == (second.lower_95, second.upper_95)
    assert first.n_fixtures == 20 and first.n_cohorts == 10
    assert not first.independent_fixture_assumption and not first.promotion_decision


def test_partial_cohort_weighting_and_overlap_rejection():
    blocks = paired_blocks(2)
    short = blocks[1].model_copy(
        update={"fixture_ids": blocks[1].fixture_ids[:1], "differences": (Decimal(4),)}
    )
    result = primary_inference(
        (blocks[0], short), policy=InferencePolicy(), population_identity="fixed"
    )
    assert result.paired_mean_difference == -2  # (-5 -5 +4)/3
    with pytest.raises(ValueError, match="overlap"):
        primary_inference(
            (blocks[0], blocks[1].model_copy(update={"fixture_ids": blocks[0].fixture_ids})),
            policy=InferencePolicy(),
            population_identity="fixed",
        )


def test_paired_scores_use_identical_fixtures_and_challenger_minus_baseline():
    value = frozen()
    score = score_public_team_forecasts(
        value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    pair = paired_differences(
        score,
        challenger="PLUG_IN_TEAM_STRENGTH_SHADOW",
        baseline="LEAGUE_BASELINE",
        metric="exact_score_log_loss",
    )
    metrics = {product: dict(values) for _, product, values in score.scores}
    with localcontext() as context:
        context.prec = 60
        assert (
            pair[0][1]
            == metrics["PLUG_IN_TEAM_STRENGTH_SHADOW"]["exact_score_log_loss"]
            - metrics["LEAGUE_BASELINE"]["exact_score_log_loss"]
        )
    with pytest.raises(ValueError, match="unmatched"):
        paired_differences(
            score, challenger="ABSENT", baseline="LEAGUE_BASELINE", metric="exact_score_log_loss"
        )


def test_authenticated_score_replay_rejects_rehashed_metric_and_d_plus_two():
    old = frozen()
    origin = datetime(2026, 10, 2, 12, tzinfo=UTC)
    value = freeze_public_team_forecasts(
        artifact=old.artifact,
        draws=old.draw_set,
        fixture_registry=old.fixture_registry,
        public_schedule=old.public_schedule,
        training_dataset=old.training_dataset,
        forecast_origin=origin,
        fixture_ids=(str(old.forecasts[0].fixture.fixture_id),),
        league_baseline=old.league_baseline,
        clock=lambda: origin,
    )
    base = assignment(cohort="P02", scheduled=value.forecasts[0].scheduled_date)
    assigned = CohortAssignment(
        **(
            base.model_dump(mode="python")
            | {
                "fixture_ids": (value.forecasts[0].fixture.fixture_id,),
                "forecast_origin": value.forecast_origin,
                "frozen_at": value.frozen_at,
                "forecast_sha256": value.semantic_sha256,
                "dataset_mode": value.dataset_mode,
                "draw_policy_sha256": value.draw_set.draw_policy_sha256,
                "model_artifact_sha256": value.artifact.semantic_sha256,
                "model_sha256": value.artifact.model.semantic_sha256,
                "source_snapshot_sha256": value.public_schedule.semantic_sha256,
                "fixture_registry_sha256": value.fixture_registry.semantic_sha256,
                "promoted_team_fixture_ids": _promoted_fixture_ids(value),
            }
        )
    )
    source = outcome(value)
    score = score_public_team_forecasts(
        value, outcomes=source, as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    verify_score_evidence(assigned, score=score, forecast=value, outcomes=source)
    altered_subgroup = assigned.model_copy(update={"promoted_team_fixture_ids": None})
    with pytest.raises(ValueError, match="assignment mismatch"):
        verify_score_evidence(altered_subgroup, score=score, forecast=value, outcomes=source)
    values = score.model_dump(mode="python", exclude={"semantic_sha256"})
    altered = tuple(
        (f, p, tuple((m, v + 1 if m == "exact_score_log_loss" else v) for m, v in metrics))
        for f, p, metrics in score.scores
    )
    forged = seal(PublicProspectiveScoreV1, **(values | {"scores": altered}))
    with pytest.raises(ValueError, match="reproduce"):
        verify_score_evidence(assigned, score=forged, forecast=value, outcomes=source)
    early_source = outcome(value, at=datetime(2026, 10, 5, tzinfo=UTC))
    early = seal(
        PublicProspectiveScoreV1,
        **(
            values
            | {
                "scored_at": datetime(2026, 10, 5, tzinfo=UTC),
                "outcome_snapshot_sha256": early_source.semantic_sha256,
            }
        ),
    )
    with pytest.raises(ValueError, match=r"eligible|D.2"):
        verify_score_evidence(assigned, score=early, forecast=value, outcomes=early_source)


def test_offline_protocol_cli_retains_only_governance_and_authenticates(tmp_path):
    runner = CliRunner()
    shown = runner.invoke(app, ["events", "team-strength", "protocol", "show"])
    assert shown.exit_code == 0, shown.stdout
    assert json.loads(shown.stdout)["effective_from_cohort"] == "P02"
    retained = runner.invoke(
        app,
        [
            "events",
            "team-strength",
            "protocol",
            "retain",
            "--retained-artifact-root",
            str(tmp_path),
        ],
    )
    assert retained.exit_code == 0, retained.stdout
    result = json.loads(retained.stdout)
    shown = runner.invoke(
        app,
        [
            "events",
            "team-strength",
            "protocol",
            "campaign-show",
            "--ledger",
            result["ledger_path"],
            "--ledger-sha256",
            result["ledger_sha256"],
        ],
    )
    assert shown.exit_code == 0 and len(json.loads(shown.stdout)["events"]) == 1
    assert not list(tmp_path.glob("**/public-team-strength-prospective/*"))
    denied = runner.invoke(
        app,
        [
            "events",
            "team-strength",
            "protocol",
            "campaign-show",
            "--ledger",
            result["ledger_path"],
            "--ledger-sha256",
            "0" * 64,
        ],
    )
    assert denied.exit_code == 2


def test_review_checkpoints_count_current_epoch_standard_cohorts_only():
    # Unit metadata exercises checkpoint counting, not score registration or accuracy.
    ledger = initial_campaign_ledger()
    assignments = tuple(assignment(cohort=f"P{index:02d}", fixture=index) for index in range(2, 7))
    for row in assignments:
        ledger = append_event(
            ledger,
            CohortEvent(
                cohort_id=row.cohort_id,
                status="FROZEN",
                recorded_at=STAMP,
                assignment=row,
                detail="Synthetic counter test",
            ),
        )
    at = STAMP + timedelta(days=3)
    for row in assignments:
        ledger = append_event(
            ledger,
            CohortEvent(
                cohort_id=row.cohort_id,
                status="SCORED",
                recorded_at=at,
                scored_at=at,
                score_sha256="e" * 64,
                assignment=row,
                detail="Synthetic counter metadata; not registered score evidence",
            ),
        )
    assert review_checkpoint_count(ledger) == 5
    with pytest.raises(ValueError, match="match every"):
        campaign_report(ledger=ledger, reports=(), forecasts=(), outcomes=())
    revised = amend_protocol(
        ledger.protocol,
        ticket="CURRENT-TEAM-STRENGTH-001V-AMEND-01",
        created_at=at + timedelta(days=1),
    )
    child = advance_campaign_protocol(ledger, revised)
    assert review_checkpoint_count(child) == 0
    with pytest.raises(ValueError, match="5/10"):
        campaign_report(ledger=child, reports=(), forecasts=(), outcomes=())


@pytest.mark.parametrize("level", ["FIXTURE", "COHORT", "CAMPAIGN"])
def test_metric_aggregation_counts_mean_median_sum(level):
    summary = _summary(
        level=level,
        cohort_id=None,
        fixture_id=None,
        product="LEAGUE_BASELINE",
        metric="exact_score_log_loss",
        population="fixed",
        rows=(("P02", Decimal(1)), ("P02", Decimal(3)), ("P03", Decimal(8))),
    )
    assert (summary.n_fixtures, summary.n_cohorts) == (3, 2)
    assert (summary.mean, summary.median, summary.cumulative_sum) == (4, 3, 12)


def test_report_populations_separate_epoch_mode_policy_and_pilot_lead():
    base = assignment(cohort="P02")
    keys = {
        _population(base),
        _population(assignment()),
        _population(base.model_copy(update={"dataset_mode": "RECONSTRUCTED"})),
        _population(base.model_copy(update={"evaluation_epoch": "EVALUATION_EPOCH_002"})),
        _population(base.model_copy(update={"draw_policy_sha256": "e" * 64})),
    }
    assert len(keys) == 5


def test_low_level_event_cannot_backdate_registration():
    row = assignment(cohort="P02")
    with pytest.raises(ValueError, match="retrospective"):
        CohortEvent(
            cohort_id="P02",
            status="FROZEN",
            assignment=row,
            recorded_at=STAMP + timedelta(days=3),
            detail="Late attempt",
        )


def test_plan_cli_requires_external_schedule_and_registry_identities(tmp_path):
    dataset, _ = synthetic_strength()
    root = initial_campaign_ledger()
    ledger_path = persist_protocol_evidence(root, artifact_root=tmp_path)
    schedule_path, registry_path = tmp_path / "schedule.json", tmp_path / "registry.json"
    schedule_path.write_text(dataset.sources[-1].model_dump_json(), encoding="utf-8")
    registry_path.write_text(dataset.fixture_registry.model_dump_json(), encoding="utf-8")
    args = [
        "events",
        "team-strength",
        "protocol",
        "plan",
        "--ledger",
        str(ledger_path),
        "--ledger-sha256",
        root.semantic_sha256,
        "--schedule",
        str(schedule_path),
        "--fixture-registry",
        str(registry_path),
    ]
    runner = CliRunner()
    assert runner.invoke(app, args).exit_code == 2
    bad = runner.invoke(
        app,
        [
            *args,
            "--schedule-sha256",
            "0" * 64,
            "--fixture-registry-sha256",
            dataset.fixture_registry.semantic_sha256,
        ],
    )
    assert bad.exit_code == 2 and "immutable identity" in bad.stdout
