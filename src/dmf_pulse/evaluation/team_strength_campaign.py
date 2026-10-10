"""Authenticated forecast assignment and append-only campaign operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from dmf_pulse.evaluation.team_strength_prospective import (
    PublicProspectiveScoreV1,
    PublicTeamStrengthForecastV1,
    score_public_team_forecasts,
)
from dmf_pulse.evaluation.team_strength_protocol import (
    P01_SHA,
    PRODUCTS,
    CampaignLedgerV1,
    CohortAssignment,
    CohortEvent,
    CohortPlanV1,
    ProspectiveProtocolV1,
    append_event,
    guard_freeze,
    initial_campaign_ledger,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    ParsedSnapshot,
    StrengthEvidenceError,
    authenticate,
)


def _promoted_fixture_ids(forecast: PublicTeamStrengthForecastV1) -> tuple[UUID, ...]:
    return tuple(
        row.fixture.fixture_id
        for row in forecast.forecasts
        if any(
            effect.is_forecast_entrant
            and effect.team_id in {row.fixture.home_team_id, row.fixture.away_team_id}
            for effect in forecast.artifact.model.effects
        )
    )


def forecast_assignment(
    forecast: PublicTeamStrengthForecastV1, *, cohort_id: str, protocol: ProspectiveProtocolV1
) -> CohortAssignment:
    forecast, protocol = authenticate(forecast), authenticate(protocol)
    if forecast.draw_set.draw_policy_sha256 != protocol.draw_policy_sha256:
        raise StrengthEvidenceError("accepted research draw policy unavailable")
    if forecast.artifact.model.policy_sha256 != protocol.model_policy_sha256:
        raise StrengthEvidenceError("model methodology evaluation epoch mismatch")
    if any(
        tuple(row.product for row in item.distributions) != PRODUCTS for item in forecast.forecasts
    ):
        raise StrengthEvidenceError("PUBLIC_LEAGUE_BASELINE_UNAVAILABLE or product set differs")
    if forecast.dataset_mode != "LIVE_OBSERVED":
        raise StrengthEvidenceError("prospective campaign requires LIVE_OBSERVED")
    pilot = cohort_id == "P01"
    if pilot and forecast.semantic_sha256 != P01_SHA:
        raise StrengthEvidenceError("P01 forecast identity differs")
    return CohortAssignment(
        cohort_id=cohort_id,
        protocol_sha256=protocol.semantic_sha256,
        evaluation_epoch=protocol.evaluation_epoch,
        forecast_sha256=forecast.semantic_sha256,
        fixture_ids=tuple(row.fixture.fixture_id for row in forecast.forecasts),
        scheduled_dates=tuple(row.scheduled_date for row in forecast.forecasts),
        forecast_origin=forecast.forecast_origin,
        frozen_at=forecast.frozen_at,
        dataset_mode=forecast.dataset_mode,
        draw_policy_sha256=forecast.draw_set.draw_policy_sha256,
        model_artifact_sha256=forecast.artifact.semantic_sha256,
        model_sha256=forecast.artifact.model.semantic_sha256,
        source_snapshot_sha256=forecast.public_schedule.semantic_sha256,
        fixture_registry_sha256=forecast.fixture_registry.semantic_sha256,
        methodology_sha256=protocol.methodology_sha256,
        cohort_class="PROSPECTIVE_PILOT_COHORT" if pilot else "STANDARD_PROSPECTIVE_COHORT",
        lead_time_class="P01_PILOT_LONG_LEAD" if pilot else "P02_PLUS_STANDARD_WINDOW",
        promoted_team_fixture_ids=_promoted_fixture_ids(forecast),
    )


def initialize_campaign(
    *, protocol: ProspectiveProtocolV1, pilot: PublicTeamStrengthForecastV1, recorded_at: datetime
) -> CampaignLedgerV1:
    protocol = authenticate(protocol)
    if recorded_at < protocol.created_at:
        raise StrengthEvidenceError("campaign cannot predate protocol")
    assignment = forecast_assignment(pilot, cohort_id="P01", protocol=protocol)
    initial = initial_campaign_ledger()
    if initial.protocol != protocol or initial.events[0].assignment != assignment:
        raise StrengthEvidenceError("pilot differs from independently pinned campaign root")
    return initial


def register_frozen_cohort(
    *,
    ledger: CampaignLedgerV1,
    plan: CohortPlanV1,
    forecast: PublicTeamStrengthForecastV1,
    recorded_at: datetime,
) -> CampaignLedgerV1:
    ledger, forecast = authenticate(ledger), authenticate(forecast)
    if not plan.target_freeze <= recorded_at <= plan.freeze_window_end:
        raise StrengthEvidenceError(
            "COHORT_FREEZE_WINDOW_MISSED: retrospective registration forbidden"
        )
    guard_freeze(
        plan,
        ledger=ledger,
        schedule=forecast.public_schedule,
        registry=forecast.fixture_registry,
        forecast_origin=forecast.forecast_origin,
        frozen_at=forecast.frozen_at,
    )
    assignment = forecast_assignment(forecast, cohort_id=plan.cohort_id, protocol=ledger.protocol)
    if set(assignment.fixture_ids) != set(plan.fixture_ids):
        raise StrengthEvidenceError("frozen fixture assignments differ from selected cohort")
    return append_event(
        ledger,
        CohortEvent(
            cohort_id=plan.cohort_id,
            status="FROZEN",
            recorded_at=recorded_at,
            assignment=assignment,
            detail="Standard-window accepted public forecast",
        ),
    )


def register_score(
    *,
    ledger: CampaignLedgerV1,
    cohort_id: str,
    score: PublicProspectiveScoreV1,
    forecast: PublicTeamStrengthForecastV1,
    outcomes: ParsedSnapshot,
    recorded_at: datetime,
) -> CampaignLedgerV1:
    ledger, score = authenticate(ledger), authenticate(score)
    assignments = {
        row.cohort_id: row.assignment for row in ledger.events if row.assignment is not None
    }
    assignment = assignments.get(cohort_id)
    if assignment is None or score.forecast_sha256 != assignment.forecast_sha256:
        raise StrengthEvidenceError("score forecast absent from assigned campaign")
    verify_score_evidence(assignment, score=score, forecast=forecast, outcomes=outcomes)
    if (score.dataset_mode, score.draw_policy_sha256) != (
        assignment.dataset_mode,
        assignment.draw_policy_sha256,
    ):
        raise StrengthEvidenceError("score mode/draw-policy mismatch")
    expected = {(fixture, product) for fixture in assignment.fixture_ids for product in PRODUCTS}
    if {(fixture, product) for fixture, product, _ in score.scores} != expected:
        raise StrengthEvidenceError("paired comparisons require every assigned fixture/product")
    return append_event(
        ledger,
        CohortEvent(
            cohort_id=cohort_id,
            status="SCORED",
            recorded_at=recorded_at,
            assignment=assignment,
            score_sha256=score.semantic_sha256,
            scored_at=score.scored_at,
            detail="Authenticated complete prospective proper-score evidence",
        ),
    )


def verify_score_evidence(
    assignment: CohortAssignment,
    *,
    score: PublicProspectiveScoreV1,
    forecast: PublicTeamStrengthForecastV1,
    outcomes: ParsedSnapshot,
) -> None:
    forecast = authenticate(forecast, assignment.forecast_sha256)
    outcomes = authenticate(outcomes, score.outcome_snapshot_sha256)
    if (
        tuple(row.fixture.fixture_id for row in forecast.forecasts),
        tuple(row.scheduled_date for row in forecast.forecasts),
        forecast.forecast_origin,
        forecast.frozen_at,
        forecast.artifact.semantic_sha256,
        forecast.artifact.model.semantic_sha256,
        forecast.public_schedule.semantic_sha256,
        forecast.fixture_registry.semantic_sha256,
        forecast.draw_set.draw_policy_sha256,
        forecast.dataset_mode,
        _promoted_fixture_ids(forecast),
    ) != (
        assignment.fixture_ids,
        assignment.scheduled_dates,
        assignment.forecast_origin,
        assignment.frozen_at,
        assignment.model_artifact_sha256,
        assignment.model_sha256,
        assignment.source_snapshot_sha256,
        assignment.fixture_registry_sha256,
        assignment.draw_policy_sha256,
        assignment.dataset_mode,
        assignment.promoted_team_fixture_ids,
    ):
        raise StrengthEvidenceError("score forecast fixture assignment mismatch")
    expected = score_public_team_forecasts(forecast, outcomes=outcomes, as_of=score.scored_at)
    if expected != authenticate(score):
        raise StrengthEvidenceError(
            "score does not reproduce authenticated forecast/outcomes with governed D+2"
        )
