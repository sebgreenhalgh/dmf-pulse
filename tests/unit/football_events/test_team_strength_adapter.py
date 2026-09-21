"""Real Stage-8 compatibility, authenticated shadow fixtures and explicit fallback."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from time import perf_counter
from uuid import UUID

import pytest

from dmf_pulse.football_events import team_strength_adapter as adapter
from dmf_pulse.football_events.market_constraints import MarketConstraint, MarketFamily, ScoreEvent
from dmf_pulse.football_events.minutes_context import (
    Stage7MinutesContext,
    TeamMinutesProjectionIdentity,
)
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionService,
    load_score_distribution_request,
)
from dmf_pulse.football_events.team_strength_adapter import (
    TeamStrengthFixtureBundleV1,
    authenticate_fixture_bundle,
    fixture_prior_bundle,
    fixture_rate_uncertainty,
    prepare_team_strength,
)
from dmf_pulse.football_events.team_strength_model import (
    TeamStrengthModelArtifactV1,
    TeamStrengthModelStateV1,
)
from dmf_pulse.football_events.team_strength_numerics import StrengthFitError
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistration,
    build_dataset,
    seal,
)
from tests.unit.football_events.team_strength_support import synthetic_artifact, synthetic_dataset
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP, dataset


def fixture() -> FixtureRegistration:
    return next(
        row for row in synthetic_dataset().fixture_registry.fixtures if row.season == "2025/26"
    )


def bundle(
    *,
    as_of: datetime | None = None,
    artifact: TeamStrengthModelArtifactV1 | None = None,
    match: FixtureRegistration | None = None,
) -> TeamStrengthFixtureBundleV1:
    artifact = artifact or synthetic_artifact()
    return fixture_prior_bundle(
        artifact=artifact,
        fixture=match or fixture(),
        as_of=as_of or STAMP + timedelta(seconds=2),
        expected_artifact_sha256=artifact.semantic_sha256,
    )


def stage8_request(value: TeamStrengthFixtureBundleV1, *, market: bool) -> ScoreDistributionRequest:
    match = value.fixture

    def identity(team: UUID) -> TeamMinutesProjectionIdentity:
        return TeamMinutesProjectionIdentity(
            schema_version="team-minutes-projection-v1",
            fixture_id=str(match.fixture_id),
            team_id=str(team),
            as_of=value.as_of - timedelta(seconds=1),
            model_family="REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
            dataset_sha256="1" * 64,
            model_artifact_sha256="2" * 64,
            sample_count=256,
            scenario_set_sha256="3" * 64,
            result_sha256="4" * 64,
        )

    constraints = (
        tuple(
            row.model_copy(update={"usable_at": value.as_of - timedelta(seconds=1)})
            for row in load_score_distribution_request(
                Path("fixtures/events/score/GCS-008/balanced_fixture.json")
            ).constraints
        )
        if market
        else ()
    )
    return ScoreDistributionRequest(
        schema_version="score-distribution-request-v1",
        fixture_id=match.fixture_id,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        as_of=value.as_of,
        minutes_context=Stage7MinutesContext(
            home=identity(match.home_team_id), away=identity(match.away_team_id)
        ),
        prior=value.score_prior,
        constraints=constraints,
    )


def test_exact_fixture_rates_and_uncertainty() -> None:
    result = bundle()
    artifact = synthetic_artifact()
    assert (
        authenticate_fixture_bundle(
            result, artifact=artifact, expected_artifact_sha256=artifact.semantic_sha256
        )
        == result
    )
    effects = {row.team_id: row for row in artifact.model.effects}
    home, away = effects[result.fixture.home_team_id], effects[result.fixture.away_team_id]
    expected = math.exp(
        float(artifact.model.mu)
        + float(artifact.model.global_home_effect)
        + float(home.attack)
        - float(away.defence)
    )
    assert float(result.score_prior.home_goal_rate) == pytest.approx(expected, abs=0.5e-6)
    assert result.score_prior.model_family == "INDEPENDENT_POISSON_V1"
    uncertainty = fixture_rate_uncertainty(
        artifact=artifact,
        fixture=result.fixture,
        as_of=result.as_of,
        expected_artifact_sha256=artifact.semantic_sha256,
    )
    assert uncertainty.log_home_rate_variance > 0 and uncertainty.log_away_rate_variance > 0
    assert uncertainty.status == "DIAGNOSTIC_ONLY_NO_PARAMETER_MIXTURE"
    assert (
        bundle(as_of=STAMP + timedelta(hours=25)).warning
        == "REUSED_SEALED_MODEL_NO_CURRENT_REFIT_CLAIM"
    )


@pytest.mark.parametrize("market", [False, True])
def test_real_stage8_public_service_without_mathematical_changes(market: bool) -> None:
    value = bundle()
    request = stage8_request(value, market=market)
    result = ScoreDistributionService().project(request)
    assert result.status == "PROJECTED" and result.distribution is not None
    assert (
        result.distribution.prior_home_goal_rate
        == value.score_prior.public_dict()["home_goal_rate"]
    )
    if market:
        assert result.distribution.diagnostics.projection_status != "PRIOR_ONLY"
        assert "MARKET_CONSTRAINED" in result.distribution.confidence_reasons
        assert result.distribution.diagnostics.solver_converged
        assert len(result.distribution.market_residuals) == 4
    else:
        assert result.distribution.diagnostics.projection_status == "PRIOR_ONLY"
        baseline = request.model_copy(
            update={
                "prior": ScorePriorRequest(
                    home_goal_rate=Decimal("1.613158"), away_goal_rate=Decimal("1.374561")
                )
            }
        )
        baseline_result = ScoreDistributionService().project(baseline)
        assert baseline_result.distribution is not None
        assert baseline_result.distribution.prior_sha256 != result.distribution.prior_sha256
        assert baseline_result.distribution.probabilities != result.distribution.probabilities


@pytest.mark.parametrize("mu", ["10.0", "1000.0", "-1000.0", "-30.0"])
def test_rate_failures_never_clamp(mu: str) -> None:
    original = synthetic_artifact()
    state = seal(
        TeamStrengthModelStateV1,
        **{
            name: getattr(original.model, name)
            for name in TeamStrengthModelStateV1.model_fields
            if name not in {"semantic_sha256", "mu"}
        },
        mu=Decimal(mu),
    )
    amended = seal(
        TeamStrengthModelArtifactV1,
        model=state,
        fitted_at=original.fitted_at,
        usable_at=original.usable_at,
    )
    with pytest.raises(ValueError, match=r"rate|clamping"):
        bundle(artifact=amended)


@pytest.mark.parametrize(
    "failure", ["post_cutoff", "naive", "stale", "competition", "season", "club", "expected"]
)
def test_adapter_context_failures(failure: str) -> None:
    match = fixture()
    artifact = synthetic_artifact()
    as_of = STAMP + timedelta(seconds=2)
    if failure == "post_cutoff":
        as_of = STAMP
    elif failure == "naive":
        as_of = as_of.replace(tzinfo=None)
    elif failure == "stale":
        as_of += timedelta(hours=73)
    elif failure == "competition":
        match = match.model_copy(
            update={"competition_id": UUID("ffffffff-ffff-7fff-bfff-ffffffffffff")}
        )
    elif failure == "season":
        match = match.model_copy(update={"season": "2026/27"})
    elif failure == "club":
        match = match.model_copy(
            update={"home_team_id": UUID("ffffffff-ffff-7fff-bfff-ffffffffffff")}
        )
    with pytest.raises(ValueError):
        fixture_prior_bundle(
            artifact=artifact,
            fixture=match,
            as_of=as_of,
            expected_artifact_sha256="0" * 64
            if failure == "expected"
            else artifact.semantic_sha256,
        )


@pytest.mark.parametrize("field", ["swap", "prior", "model", "cutoff"])
def test_bundle_nested_tamper_is_rejected(field: str) -> None:
    payload = bundle().model_dump(mode="json")
    if field == "swap":
        payload["fixture"]["home_team_id"], payload["fixture"]["away_team_id"] = (
            payload["fixture"]["away_team_id"],
            payload["fixture"]["home_team_id"],
        )
    elif field == "prior":
        payload["score_prior"]["home_goal_rate"] = "1.000000"
    elif field == "model":
        payload["model_state_sha256"] = "0" * 64
    else:
        payload["as_of"] = "2025-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        TeamStrengthFixtureBundleV1.model_validate_json(json.dumps(payload))


def test_authentication_cache_cannot_hide_nested_tamper() -> None:
    fresh = TeamStrengthModelArtifactV1.model_validate_json(synthetic_artifact().model_dump_json())
    bundle(artifact=fresh)
    object.__setattr__(fresh.model, "mu", Decimal("2.5"))
    with pytest.raises(ValueError, match="hash"):
        bundle(artifact=fresh)


def test_half_even_boundary_and_decimal_context_independence() -> None:
    result = adapter._request(1.2345665, 1.2345675)
    assert result.home_goal_rate == Decimal("1.234566")
    assert result.away_goal_rate == Decimal("1.234568")
    expected = bundle()
    with localcontext() as context:
        context.prec = 6
        assert bundle() == expected


@pytest.mark.performance
def test_thirty_fixture_inferences_under_100ms() -> None:
    artifact = synthetic_artifact()
    matches = tuple(
        row for row in synthetic_dataset().fixture_registry.fixtures if row.season == "2025/26"
    )[:30]
    adapter._validated_artifact_json.cache_clear()
    start = perf_counter()
    results = [
        fixture_prior_bundle(
            artifact=artifact,
            fixture=match,
            as_of=STAMP + timedelta(seconds=2),
            expected_artifact_sha256=artifact.semantic_sha256,
        )
        for match in matches
    ]
    elapsed = perf_counter() - start
    assert len({row.semantic_sha256 for row in results}) == 30
    assert elapsed < 0.1, f"30 cold-cache adapter calls took {elapsed:.6f}s"


def test_typed_fallback_never_substitutes_a_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    insufficient = prepare_team_strength(dataset())
    assert (
        insufficient.status == "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK"
        and insufficient.reason == "EVIDENCE_INSUFFICIENT"
    )
    stale = prepare_team_strength(dataset(received=STAMP - timedelta(hours=73)))
    assert stale.reason == "SOURCE_STALE" and stale.artifact is None
    unavailable = prepare_team_strength(dataset(received=STAMP - timedelta(hours=25)))
    assert unavailable.reason == "CURRENT_ARTIFACT_UNAVAILABLE"

    def fail(*args: object, **kwargs: object) -> TeamStrengthModelArtifactV1:
        raise StrengthFitError("synthetic numerical failure")

    monkeypatch.setattr(adapter, "fit_team_strength", fail)
    assert prepare_team_strength(dataset()).reason == "FIT_FAILURE"


def test_degraded_retains_latest_sealed_without_refit_and_future_fails() -> None:
    original = synthetic_dataset()
    reassessed = build_dataset(
        sources=original.sources,
        fixtures=original.fixture_registry,
        expected_fixture_registry_sha256=original.fixture_registry.semantic_sha256,
        information_cutoff=STAMP + timedelta(hours=25),
        training_cutoff=original.training_cutoff,
        forecast_season=original.forecast_season,
        mode=original.dataset_mode,
    )
    result = prepare_team_strength(reassessed, latest_artifact=synthetic_artifact())
    assert result.reason == "DEGRADED_SEALED_REUSE" and result.artifact == synthetic_artifact()
    with pytest.raises(ValueError, match="post-cutoff"):
        prepare_team_strength(original, latest_artifact=synthetic_artifact())
    expected = bundle()
    assert result.artifact is not None
    object.__setattr__(result.artifact.model, "mu", Decimal("2.5"))
    assert bundle() == expected  # a public return cannot poison the private cache
    with pytest.raises(ValueError, match="hash"):
        bundle(artifact=result.artifact)


def test_decimal_representation_tamper_cannot_hit_authentication_cache() -> None:
    fresh = TeamStrengthModelArtifactV1.model_validate_json(synthetic_artifact().model_dump_json())
    bundle(artifact=fresh)
    object.__setattr__(fresh.model, "mu", Decimal(str(fresh.model.mu) + "0"))
    with pytest.raises(ValueError, match="hash"):
        bundle(artifact=fresh)


def test_existing_stage8_nonconvergence_remains_visible_not_misclaimed_as_projection() -> None:
    value = bundle()
    request = stage8_request(value, market=False)
    constraints = tuple(
        MarketConstraint(
            constraint_id=f"synthetic-{event.value}",
            family=MarketFamily.ONE_X_TWO,
            event=event,
            target_probability=Decimal(probability),
            uncertainty=Decimal("0.05"),
            usable_at=value.as_of - timedelta(seconds=1),
        )
        for event, probability in (
            (ScoreEvent.HOME_WIN, "0.55"),
            (ScoreEvent.DRAW, "0.25"),
            (ScoreEvent.AWAY_WIN, "0.20"),
        )
    )
    with localcontext() as context:
        context.prec = 28
        result = ScoreDistributionService().project(
            request.model_copy(update={"constraints": constraints})
        )
    assert result.distribution is not None
    assert result.distribution.diagnostics.projection_status == "DEGRADED"
    assert result.distribution.diagnostics.solver_error_code == "PROJECTION_DID_NOT_CONVERGE"
    assert "NUMERICAL_FALLBACK_TO_PRIOR" in result.distribution.confidence_reasons


def test_old_model_reuses_new_degraded_assessment_without_refit() -> None:
    original = synthetic_dataset()
    sources = []
    for source in original.sources:
        lineage_values = {
            key: getattr(source.lineage, key)
            for key in type(source.lineage).model_fields
            if key != "semantic_sha256"
        }
        for key in ("retrieval_started_at", "received_at", "validated_at", "usable_at"):
            lineage_values[key] += timedelta(days=9)
        lineage = seal(type(source.lineage), **lineage_values)
        rows = tuple(
            seal(
                type(row),
                **{
                    key: getattr(row, key)
                    for key in type(row).model_fields
                    if key not in {"semantic_sha256", "source_snapshot_sha256"}
                },
                source_snapshot_sha256=lineage.semantic_sha256,
            )
            for row in source.matches
        )
        sources.append(
            seal(
                type(source),
                lineage=lineage,
                matches=rows,
                fixture_registry_sha256=source.fixture_registry_sha256,
            )
        )
    cutoff = STAMP + timedelta(days=10, hours=1)
    reassessed = build_dataset(
        sources=tuple(sources),
        fixtures=original.fixture_registry,
        expected_fixture_registry_sha256=original.fixture_registry.semantic_sha256,
        information_cutoff=cutoff,
        training_cutoff=original.training_cutoff,
        forecast_season=original.forecast_season,
        mode=original.dataset_mode,
    )
    prepared = prepare_team_strength(reassessed, latest_artifact=synthetic_artifact())
    assert prepared.reason == "DEGRADED_SEALED_REUSE" and prepared.artifact is not None
    assert prepared.artifact.semantic_sha256 == synthetic_artifact().semantic_sha256
    result = fixture_prior_bundle(
        artifact=prepared.artifact,
        fixture=fixture(),
        as_of=cutoff,
        expected_artifact_sha256=prepared.artifact.semantic_sha256,
        source_assessment=prepared.source_assessment,
    )
    assert result.retrieval_freshness_at_as_of == "DEGRADED"
    assert result.due_completeness_assessed_at == cutoff
    assert result.model_information_cutoff == STAMP
    assert (
        authenticate_fixture_bundle(
            result,
            artifact=prepared.artifact,
            expected_artifact_sha256=prepared.artifact.semantic_sha256,
        )
        == result
    )
    assessment = prepared.source_assessment
    assert assessment is not None
    blocked = seal(
        type(assessment),
        **{
            key: getattr(assessment, key)
            for key in type(assessment).model_fields
            if key not in {"semantic_sha256", "missing_due", "freshness"}
        },
        missing_due=1,
        freshness=adapter.SourceFreshnessState.STALE_BLOCKED,
    )
    with pytest.raises(ValueError, match="stale"):
        fixture_prior_bundle(
            artifact=prepared.artifact,
            fixture=fixture(),
            as_of=cutoff,
            expected_artifact_sha256=prepared.artifact.semantic_sha256,
            source_assessment=blocked,
        )


def test_historical_club_cannot_masquerade_as_current_epl_fixture() -> None:
    current = adapter.memberships()["2025/26"]
    historical = next(
        row.team_id for row in synthetic_artifact().model.effects if row.team_id not in current
    )
    with pytest.raises(ValueError, match="forecast-season"):
        bundle(match=fixture().model_copy(update={"home_team_id": historical}))
