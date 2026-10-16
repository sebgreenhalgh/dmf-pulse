"""P01 fallback scores retain their post-event descriptive authority everywhere."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.evaluation.p01_fallback_context import (
    P01FallbackContext,
    load_context,
    require_forecast_binding,
    require_openligadb_rights,
)
from dmf_pulse.evaluation.p01_frozen_view import P01FrozenScoringView
from dmf_pulse.evaluation.team_strength_prospective import (
    CALIBRATION_EVENTS,
    PRODUCT,
    PromotionEvidenceStatus,
    PublicProspectiveScoreV1,
    PublicTeamStrengthForecastV1,
    score_public_fixture_labels,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    ParsedSnapshot,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    require_team_strength_rights,
    seal,
)
from dmf_pulse.ingestion.p01_fallback import PublicP01FallbackOutcomesV1, require_d_plus_2

PRODUCTS: tuple[PRODUCT, ...] = (
    "LEAGUE_BASELINE",
    "PLUG_IN_TEAM_STRENGTH_SHADOW",
    "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW",
)
MEANS = ("exact_score_log_loss", "team_count_log_loss", "goal_rps", "home_bias", "away_bias")


class P01FallbackScoreV1(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-score-v1"] = (
        "public-team-strength-p01-fallback-score-v1"
    )
    provenance: Literal["PUBLIC_FALLBACK_OUTCOME_SOURCE"] = "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    classification: Literal["DESCRIPTIVE_P01_PILOT"] = "DESCRIPTIVE_P01_PILOT"
    context: P01FallbackContext
    outcome_artifact_sha256: SHA
    metrics: PublicProspectiveScoreV1
    promotion: PromotionEvidenceStatus = PromotionEvidenceStatus()
    reconciliation_status: Literal["OPENFOOTBALL_RECONCILIATION_PENDING"] = (
        "OPENFOOTBALL_RECONCILIATION_PENDING"
    )

    @model_validator(mode="after")
    def exact_score_cohort(self) -> Self:
        expected = {
            (row.fixture.fixture_id, product)
            for row in self.context.fixtures
            for product in PRODUCTS
        }
        if (
            {(fixture, product) for fixture, product, _ in self.metrics.scores} != expected
            or len(self.metrics.scores) != 30
            or self.metrics.forecast_sha256 != self.context.forecast_sha256
            or self.metrics.outcome_snapshot_sha256 != self.outcome_artifact_sha256
            or self.metrics.draw_policy_sha256 != self.context.draw_policy_sha256
            or self.metrics.scored_at < self.context.amended_at
        ):
            raise ValueError("fallback score binding or exact product/cohort differs")
        authenticate(self.metrics)
        return self


def _score_admitted(
    forecast: PublicTeamStrengthForecastV1 | P01FrozenScoringView,
    *,
    outcomes: PublicP01FallbackOutcomesV1,
    as_of: datetime,
) -> P01FallbackScoreV1:
    """Pure typed admission; separate synthetic contexts exercise this same boundary."""
    outcomes = authenticate(outcomes)
    require_forecast_binding(forecast, context=outcomes.context)
    as_of = FrozenEvidence.utc_datetimes(as_of)
    require_d_plus_2(outcomes, as_of=as_of)
    rows = tuple(
        score
        for prediction, outcome in zip(forecast.forecasts, outcomes.outcomes, strict=True)
        for score in score_public_fixture_labels(
            prediction, hg=outcome.home_goals, ag=outcome.away_goals
        )
    )
    metrics = seal(
        PublicProspectiveScoreV1,
        forecast_sha256=forecast.semantic_sha256,
        outcome_snapshot_sha256=outcomes.semantic_sha256,
        scored_at=as_of,
        dataset_mode=forecast.dataset_mode,
        draw_policy_sha256=forecast.draw_set.draw_policy_sha256,
        scores=rows,
    )
    return seal(
        P01FallbackScoreV1,
        context=outcomes.context,
        outcome_artifact_sha256=outcomes.semantic_sha256,
        metrics=metrics,
    )


def score_p01_fallback(
    forecast: P01FrozenScoringView,
    *,
    outcomes: PublicP01FallbackOutcomesV1,
    as_of: datetime,
) -> P01FallbackScoreV1:
    """Operational scoring requires the literal approved P01 authority and rights."""
    context = load_context()
    require_openligadb_rights()
    if (
        type(forecast) is not P01FrozenScoringView
        or outcomes.context != context
        or forecast.dataset_mode != "LIVE_OBSERVED"
    ):
        raise StrengthEvidenceError("P01 fallback authority or live forecast identity differs")
    return _score_admitted(forecast, outcomes=outcomes, as_of=as_of)


class ProductMeans(FrozenEvidence):
    product: PRODUCT
    fixture_count: Literal[10] = 10
    metrics: tuple[tuple[str, Decimal], ...]
    event_brier_means: tuple[tuple[str, Decimal], ...]


class LossDelta(FrozenEvidence):
    left: PRODUCT
    right: PRODUCT
    deltas: tuple[tuple[str, Decimal], ...]


class P01FallbackScorecardV1(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-scorecard-v1"] = (
        "public-team-strength-p01-fallback-scorecard-v1"
    )
    provenance: Literal["PUBLIC_FALLBACK_OUTCOME_SOURCE"] = "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    classification: Literal["DESCRIPTIVE_P01_PILOT"] = "DESCRIPTIVE_P01_PILOT"
    score: P01FallbackScoreV1
    outcome_artifact: PublicP01FallbackOutcomesV1
    product_means: tuple[ProductMeans, ...]
    loss_deltas: tuple[LossDelta, ...]
    delta_convention: Literal["NEGATIVE LOSS DELTA = BETTER"] = "NEGATIVE LOSS DELTA = BETTER"
    interpretation: Literal["TEN_FIXTURE_DESCRIPTIVE_PILOT_NO_TUNING_PROMOTION_OR_ACTIVATION"] = (
        "TEN_FIXTURE_DESCRIPTIVE_PILOT_NO_TUNING_PROMOTION_OR_ACTIVATION"
    )

    @model_validator(mode="after")
    def report_binding(self) -> Self:
        score, outcomes = authenticate(self.score), authenticate(self.outcome_artifact)
        if (
            score.outcome_artifact_sha256 != outcomes.semantic_sha256
            or score.context != outcomes.context
        ):
            raise ValueError("fallback report provenance differs")
        means, deltas = _summary(score)
        if self.product_means != means or self.loss_deltas != deltas:
            raise ValueError("fallback aggregate metrics differ from sealed rows")
        return self


def _summary(score: P01FallbackScoreV1) -> tuple[tuple[ProductMeans, ...], tuple[LossDelta, ...]]:
    products: list[ProductMeans] = []
    with localcontext() as context:
        context.prec = 60
        for product in PRODUCTS:
            rows = [dict(pairs) for _, key, pairs in score.metrics.scores if key == product]
            products.append(
                ProductMeans(
                    product=product,
                    metrics=tuple(
                        (name, sum((row[name] for row in rows), Decimal(0)) / 10) for name in MEANS
                    ),
                    event_brier_means=tuple(
                        (event, sum((row[event + "_brier"] for row in rows), Decimal(0)) / 10)
                        for event in CALIBRATION_EVENTS
                    ),
                )
            )
        values = {row.product: dict(row.metrics) for row in products}
        deltas = tuple(
            LossDelta(
                left=left,
                right=right,
                deltas=tuple(
                    (name, values[left][name] - values[right][name]) for name in MEANS[:3]
                ),
            )
            for left, right in (
                (PRODUCTS[1], PRODUCTS[0]),
                (PRODUCTS[2], PRODUCTS[0]),
                (PRODUCTS[2], PRODUCTS[1]),
            )
        )
    return tuple(products), deltas


def fallback_scorecard(
    score: P01FallbackScoreV1, *, outcomes: PublicP01FallbackOutcomesV1
) -> P01FallbackScorecardV1:
    score, outcomes = authenticate(score), authenticate(outcomes)
    means, deltas = _summary(score)
    return seal(
        P01FallbackScorecardV1,
        score=score,
        outcome_artifact=outcomes,
        product_means=means,
        loss_deltas=deltas,
    )


class ReconciliationDifference(FrozenEvidence):
    fixture_id: UUID
    agrees: bool
    fallback_date_and_score: tuple[str, int, int]
    openfootball_date_and_score: tuple[str, int | None, int | None]
    fixture_identity_agrees: bool


class P01FallbackReconciliationV1(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-reconciliation-v1"] = (
        "public-team-strength-p01-fallback-reconciliation-v1"
    )
    provenance: Literal["PUBLIC_FALLBACK_OUTCOME_SOURCE"] = "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    context: P01FallbackContext
    outcome_artifact_sha256: SHA
    openfootball_snapshot: ParsedSnapshot
    outcome_artifact: PublicP01FallbackOutcomesV1
    audited_at: datetime
    comparisons: tuple[ReconciliationDifference, ...] = Field(min_length=10, max_length=10)
    status: Literal["FULL_RECONCILIATION", "DISAGREEMENT"]
    label_evidence_disputed: bool
    human_review_required_before_promotion_evidence_use: Literal[True] = True
    production_active: Literal[False] = False

    @model_validator(mode="after")
    def audit_binding(self) -> Self:
        snapshot = authenticate(self.openfootball_snapshot)
        fallback = authenticate(self.outcome_artifact)
        if (
            self.audited_at < snapshot.lineage.usable_at
            or self.audited_at < fallback.usable_at
            or self.context != fallback.context
            or self.outcome_artifact_sha256 != fallback.semantic_sha256
            or snapshot.fixture_registry_sha256 != self.context.fixture_registry_sha256
            or tuple(row.fixture_id for row in self.comparisons)
            != tuple(row.fixture.fixture_id for row in self.context.fixtures)
            or self.label_evidence_disputed != any(not row.agrees for row in self.comparisons)
            or (self.status == "DISAGREEMENT") != self.label_evidence_disputed
            or self.comparisons != _reconciliation_comparisons(fallback, snapshot)
        ):
            raise ValueError("reconciliation identity, chronology or dispute state differs")
        return self


def reconcile_openfootball(
    outcomes: PublicP01FallbackOutcomesV1, *, snapshot: ParsedSnapshot, audited_at: datetime
) -> P01FallbackReconciliationV1:
    """Appendable audit only; no network, label replacement or promotion decision."""
    require_team_strength_rights()
    outcomes, snapshot = authenticate(outcomes), authenticate(snapshot)
    comparisons = _reconciliation_comparisons(outcomes, snapshot)
    disputed = any(not row.agrees for row in comparisons)
    return seal(
        P01FallbackReconciliationV1,
        context=outcomes.context,
        outcome_artifact_sha256=outcomes.semantic_sha256,
        outcome_artifact=outcomes,
        openfootball_snapshot=snapshot,
        audited_at=audited_at,
        comparisons=comparisons,
        status="DISAGREEMENT" if disputed else "FULL_RECONCILIATION",
        label_evidence_disputed=disputed,
    )


def _reconciliation_comparisons(
    outcomes: PublicP01FallbackOutcomesV1, snapshot: ParsedSnapshot
) -> tuple[ReconciliationDifference, ...]:
    rows = {row.fixture.fixture_id: row for row in snapshot.matches}
    comparisons = []
    for fallback in outcomes.outcomes:
        observed = rows.get(fallback.fixture.fixture_id)
        if (
            observed is None
            or observed.finality != "FULL_TIME"
            or observed.home_goals is None
            or observed.away_goals is None
        ):
            raise StrengthEvidenceError("OPENFOOTBALL_RECONCILIATION_PENDING")
        fallback_values = (
            fallback.actual_played_date.isoformat(),
            fallback.home_goals,
            fallback.away_goals,
        )
        observed_values = (
            observed.source_match_date.isoformat(),
            observed.home_goals,
            observed.away_goals,
        )
        identity_agrees = observed.fixture == fallback.fixture
        comparisons.append(
            ReconciliationDifference(
                fixture_id=fallback.fixture.fixture_id,
                agrees=identity_agrees and fallback_values == observed_values,
                fixture_identity_agrees=identity_agrees,
                fallback_date_and_score=fallback_values,
                openfootball_date_and_score=observed_values,
            )
        )
    return tuple(comparisons)
