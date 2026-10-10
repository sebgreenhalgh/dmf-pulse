"""Successful synthetic campaign through unchanged fitting, draws and scorer.

Only public-source fixture construction uses a synthetic date/clock. No numerical
model, forecast, scoring, replay, registration or report function is replaced.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from dmf_pulse.evaluation.team_strength_campaign import register_frozen_cohort, register_score
from dmf_pulse.evaluation.team_strength_campaign_report import campaign_report
from dmf_pulse.evaluation.team_strength_prospective import (
    freeze_public_team_forecasts,
    score_public_team_forecasts,
)
from dmf_pulse.evaluation.team_strength_protocol import initial_campaign_ledger, plan_cohort
from dmf_pulse.evaluation.team_strength_protocol_store import (
    load_campaign,
    persist_protocol_evidence,
)
from dmf_pulse.football_events.team_strength_parameter_draws import (
    draw_policy,
    joint_parameter_draws,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SourceLineage,
    SourceResource,
    parse_snapshot,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import load_historical_team_identity
from tests.unit.evaluation.test_team_strength_prospective import frozen
from tests.unit.private_v1 import team_strength_shadow_support as source_factory


def test_successful_five_cohort_campaign_retains_all_scores_and_reports(monkeypatch, tmp_path):
    source_time = datetime(2026, 10, 10, 11, tzinfo=UTC)
    origin = datetime(2026, 10, 10, 12, tzinfo=UTC)

    def source_date(year, month, day):
        return date(2026, 10, 12) if (year, month, day) == (2026, 10, 4) else date(year, month, day)

    def source_delta(*args, **kwargs):
        # Synthetic complete schedule has all rounds on one future date, giving
        # five disjoint cohort blocks at the same legitimate governed window.
        return timedelta(0) if set(kwargs) == {"days"} else timedelta(*args, **kwargs)

    with monkeypatch.context() as construction:
        construction.setattr(source_factory, "STAMP", source_time)
        construction.setattr(source_factory, "date", source_date)
        construction.setattr(source_factory, "timedelta", source_delta)
        dataset, artifact = source_factory.synthetic_strength.__wrapped__(mode="LIVE_OBSERVED")
    draws = joint_parameter_draws(artifact, policy=draw_policy(seed=23, draw_count=2048))
    ledger = initial_campaign_ledger()
    persist_protocol_evidence(ledger, artifact_root=tmp_path)
    forecasts = []
    for index in range(5):
        at = origin + timedelta(seconds=index)
        plan = plan_cohort(
            ledger=ledger, schedule=dataset.sources[-1], registry=dataset.fixture_registry, as_of=at
        )
        forecast = freeze_public_team_forecasts(
            artifact=artifact,
            draws=draws,
            fixture_registry=dataset.fixture_registry,
            public_schedule=dataset.sources[-1],
            training_dataset=dataset,
            forecast_origin=at,
            fixture_ids=tuple(map(str, plan.fixture_ids)),
            league_baseline=frozen().league_baseline,
            clock=lambda at=at: at,
        )
        with pytest.raises(ValueError, match="retrospective"):
            register_frozen_cohort(
                ledger=ledger, plan=plan, forecast=forecast, recorded_at=at + timedelta(days=1)
            )
        ledger = register_frozen_cohort(ledger=ledger, plan=plan, forecast=forecast, recorded_at=at)
        persist_protocol_evidence(ledger, artifact_root=tmp_path)
        forecasts.append(forecast)
    assert (
        len(
            {fixture.fixture.fixture_id for forecast in forecasts for fixture in forecast.forecasts}
        )
        == 50
    )
    identity = load_historical_team_identity()
    names = {
        row.canonical_team_id: row.source_team_name
        for row in identity.records
        if "2026/27" in row.season_scope
    }
    body = json.dumps(
        {
            "name": "English Premier League 2026/27",
            "matches": [
                {
                    "team1": names[row.fixture.home_team_id],
                    "team2": names[row.fixture.away_team_id],
                    "round": "Matchday 1",
                    "date": "2026-10-13" if index == 0 else "2026-10-12",
                    "score": {"ft": [2, 1]},
                }
                for index, row in enumerate(
                    item for forecast in forecasts for item in forecast.forecasts
                )
            ],
        }
    ).encode()
    scored_at = datetime(2026, 10, 15, tzinfo=UTC)
    resource = SourceResource(
        commit="d" * 40,
        season="2026/27",
        path="2026-27/en.1.json",
        git_blob_sha1=hashlib.sha1(
            f"blob {len(body)}\0".encode() + body, usedforsecurity=False
        ).hexdigest(),
        content_sha256=hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
    )
    lineage = seal(
        SourceLineage,
        resource=resource,
        retrieval_started_at=scored_at,
        received_at=scored_at,
        validated_at=scored_at,
        usable_at=scored_at,
        acquisition="LOCAL_IMMUTABLE_IMPORT",
    )
    outcomes = parse_snapshot(
        body,
        lineage=lineage,
        fixtures=dataset.fixture_registry,
        expected_fixture_registry_sha256=dataset.fixture_registry.semantic_sha256,
    )
    reports = []
    for index, forecast in enumerate(forecasts):
        report = score_public_team_forecasts(forecast, outcomes=outcomes, as_of=scored_at)
        ledger = register_score(
            ledger=ledger,
            cohort_id=f"P{index + 2:02d}",
            score=report,
            forecast=forecast,
            outcomes=outcomes,
            recorded_at=scored_at,
        )
        persist_protocol_evidence(ledger, artifact_root=tmp_path)
        reports.append(report)
    path = persist_protocol_evidence(ledger, artifact_root=tmp_path)
    retained = load_campaign(path, expected_sha256=ledger.semantic_sha256)
    result = campaign_report(
        ledger=retained, reports=tuple(reports), forecasts=tuple(forecasts), outcomes=(outcomes,)
    )
    assert result.interim_review == 5 and result.completed_scored_cohorts == 5
    assert result.score_sha256s == tuple(sorted(row.semantic_sha256 for row in reports))
    assert {row.level for row in result.metric_summaries} == {"FIXTURE", "COHORT", "CAMPAIGN"}
    assert len(result.inferences) == 1 and result.inferences[0].inference.n_fixtures == 50
    assert result.inferences[0].inference.n_cohorts == 5
    assert result.inferences[0].inference.lower_95 is None
    assert result.calibration[0].n_cohorts == 5 and result.calibration[0].n_fixtures == 50
    assert any("DATE_CHANGED_AFTER_FREEZE" in row.population for row in result.metric_summaries)
    assert any("PROMOTED_TEAM_INVOLVEMENT" in row.population for row in result.metric_summaries)
    assert any(
        row.product == "EXPLORATORY_MIXTURE_MINUS_PLUGIN" and row.metric == "goal_rps"
        for row in result.metric_summaries
    )
    with localcontext() as context:
        context.prec = 60
        plugin = [
            dict(values)["exact_score_log_loss"]
            for report in reports
            for _, product, values in report.scores
            if product == "PLUG_IN_TEAM_STRENGTH_SHADOW"
        ]
        baseline = [
            dict(values)["exact_score_log_loss"]
            for report in reports
            for _, product, values in report.scores
            if product == "LEAGUE_BASELINE"
        ]
        expected = (
            sum((left - right for left, right in zip(plugin, baseline, strict=True)), Decimal(0))
            / 50
        )
        assert result.inferences[0].inference.paired_mean_difference == expected
    assert not result.production_active and not result.automatic_activation
    assert retained.events[0] == initial_campaign_ledger().events[0]  # P01 still unscored.
