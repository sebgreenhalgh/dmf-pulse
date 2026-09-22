"""Real-model, zero-network authentication and full-horizon binding acceptance."""

from __future__ import annotations

from datetime import timedelta

import pytest

from dmf_pulse.football_events.team_strength_adapter import (
    TeamStrengthSourceAssessmentV1,
    fixture_prior_bundle,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate, seal
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    SourceFreshnessState,
    classify_source_freshness,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import seal_execution_input, seal_fixture_score_prior
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.rolling_models import seal_rolling_execution_input
from dmf_pulse.private_v1.team_strength_shadow_inputs import (
    TeamStrengthShadowPreparation,
    _p0_club,
    _source_context,
    _TeamStrengthShadowResolver,
    horizon_fixtures,
    prepare_team_strength_shadow,
)
from tests.unit.private_v1.team_strength_shadow_support import (
    CUTOFF,
    synthetic_prepared,
    synthetic_strength,
)


def reseal(value, **updates):
    fields = {
        name: getattr(value, name) for name in type(value).model_fields if name != "semantic_sha256"
    }
    return seal(type(value), **(fields | updates))


def assessment_for(dataset, *, age=timedelta(hours=2), missing_due=0):
    received = CUTOFF - age
    freshness = classify_source_freshness(
        cutoff=CUTOFF,
        latest_successful_usable_retrieval=received,
        missing_due=missing_due,
        canonical_mapping_valid=True,
        status_unambiguous=True,
        schema_valid=True,
        source_lineage_valid=True,
    )
    return seal(
        TeamStrengthSourceAssessmentV1,
        dataset_sha256=dataset.semantic_sha256,
        competition_id=dataset.competition_id,
        fixture_registry_sha256=dataset.fixture_registry.semantic_sha256,
        forecast_season=dataset.forecast_season,
        dataset_mode=dataset.dataset_mode,
        information_cutoff=CUTOFF,
        source_usable_at=CUTOFF,
        latest_received_at=received,
        missing_due=missing_due,
        status_unambiguous=True,
        freshness=freshness,
        source_snapshot_sha256s=tuple(row.semantic_sha256 for row in dataset.sources),
    )


@pytest.fixture(scope="module")
def inputs(tmp_path_factory, repository_root):
    prepared = synthetic_prepared(repository_root, tmp_path_factory.mktemp("001p-inputs"))
    dataset, artifact = synthetic_strength()
    outcome = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
    )
    return prepared, dataset, artifact, outcome


def test_exact_p0_crosswalk_preserves_all_nine_private_identities(inputs):
    prepared, dataset, artifact, outcome = inputs
    assert outcome.status == "TEAM_STRENGTH_PRIOR_READY"
    shadow = outcome.shadow_input
    assert shadow is not None
    assert len(shadow.fixtures) == 9
    assert authenticate(shadow) == shadow
    assert shadow.artifact == artifact
    assert shadow.fixture_registry == dataset.fixture_registry
    resolver = _TeamStrengthShadowResolver(shadow)
    resolver.validate_execution(prepared.rolling_execution)
    rows = horizon_fixtures(prepared.rolling_execution)
    for source, binding in zip(rows, shadow.fixtures, strict=True):
        assert binding.baseline_prior == source.prior
        assert resolver.resolve(source.prior, source.gameweek) == binding.public_bundle.score_prior
        assert binding.public_bundle.fixture.home_team_id != source.prior.home_team_id
        assert binding.public_bundle.as_of == prepared.information_cutoff


def test_wrong_expected_artifact_is_hard_failure(inputs):
    prepared, dataset, artifact, _outcome = inputs
    with pytest.raises(ValueError, match="expected immutable"):
        prepare_team_strength_shadow(
            prepared.rolling_execution,
            artifact=artifact,
            expected_artifact_sha256="f" * 64,
            fixture_registry=dataset.fixture_registry,
        )


def test_absent_artifact_is_typed_unavailable(inputs):
    prepared, dataset, _artifact, _outcome = inputs
    result = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=None,
        expected_artifact_sha256="f" * 64,
        fixture_registry=dataset.fixture_registry,
    )
    assert result.status == "TEAM_STRENGTH_WORLD_UNAVAILABLE"
    assert result.reason == "CURRENT_ARTIFACT_UNAVAILABLE"


def test_real_rolling_shadow_preserves_stage7_and_player_binding(inputs):
    prepared, _dataset, _artifact, outcome = inputs
    execution = prepared.rolling_execution
    before = execution.model_dump_json()
    baseline = PrivateV1RollingRecommendationService().run(execution)
    shadow = PrivateV1RollingRecommendationService(
        _score_prior_resolver=_TeamStrengthShadowResolver(outcome.shadow_input)
    ).run(execution)
    assert execution.model_dump_json() == before
    base_lineage = baseline.decision.lineage
    shadow_lineage = shadow.decision.lineage
    assert base_lineage.rolling_execution_input_sha256 == execution.semantic_sha256
    assert shadow_lineage.rolling_execution_input_sha256 == outcome.shadow_input.semantic_sha256
    assert (
        base_lineage.stage7_context_sha256_by_gameweek
        == shadow_lineage.stage7_context_sha256_by_gameweek
    )
    assert (
        base_lineage.player_prior_binding_sha256_by_gameweek
        == shadow_lineage.player_prior_binding_sha256_by_gameweek
    )
    assert (
        base_lineage.stage8_distribution_sha256_by_gameweek
        != shadow_lineage.stage8_distribution_sha256_by_gameweek
    )
    assert shadow.stage11_work.cumulative_legal_actions > 0
    assert baseline.stage11_work.cumulative_legal_actions > 0


@pytest.mark.parametrize(
    "age,reason",
    [
        (timedelta(hours=24), "FRESH_SEALED_MODEL"),
        (timedelta(hours=24, microseconds=1), "DEGRADED_SEALED_REUSE"),
        (timedelta(hours=72), "DEGRADED_SEALED_REUSE"),
        (timedelta(hours=72, microseconds=1), "SOURCE_STALE"),
    ],
)
def test_exact_freshness_boundaries(inputs, age, reason):
    prepared, dataset, artifact, _ = inputs
    result = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
        source_assessment=assessment_for(dataset, age=age),
    )
    assert result.reason == reason
    if reason == "SOURCE_STALE":
        assert result.shadow_input is None
    else:
        assert result.shadow_input.artifact == artifact
        if reason == "DEGRADED_SEALED_REUSE":
            assert all(
                row.public_bundle.warning == "REUSED_SEALED_MODEL_NO_CURRENT_REFIT_CLAIM"
                for row in result.shadow_input.fixtures
            )


def test_missing_due_blocks_even_with_recent_retrieval(inputs):
    prepared, dataset, artifact, _ = inputs
    result = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
        source_assessment=assessment_for(dataset, missing_due=1),
    )
    assert result.status == "TEAM_STRENGTH_WORLD_UNAVAILABLE"
    assert result.reason == "SOURCE_STALE"


def test_incomplete_public_fixture_registry_never_creates_hybrid_world(inputs):
    prepared, dataset, artifact, outcome = inputs
    missing = outcome.shadow_input.fixtures[-1].public_bundle.fixture.fixture_id
    registry = reseal(
        dataset.fixture_registry,
        fixtures=tuple(
            row for row in dataset.fixture_registry.fixtures if row.fixture_id != missing
        ),
    )
    # A structurally authenticated hypothetical model with an incomplete forecast
    # registry tests availability, not a fitted or accepted numerical result.
    model = reseal(artifact.model, fixture_registry_sha256=registry.semantic_sha256)
    incomplete = reseal(artifact, model=model)
    result = prepare_team_strength_shadow(
        prepared.rolling_execution,
        artifact=incomplete,
        expected_artifact_sha256=incomplete.semantic_sha256,
        fixture_registry=registry,
    )
    assert result.status == "TEAM_STRENGTH_COMPARISON_BLOCKED_INCOMPLETE_FIXTURE_COVERAGE"
    assert result.shadow_input is None


def test_incomplete_or_wrong_execution_binding_fails_before_projection(inputs):
    prepared, _dataset, _artifact, outcome = inputs
    shadow = outcome.shadow_input
    partial = reseal(shadow, fixtures=shadow.fixtures[:-1])
    with pytest.raises(ValueError, match="exact frozen horizon"):
        _TeamStrengthShadowResolver(partial).validate_execution(prepared.rolling_execution)
    other = reseal(shadow, baseline_execution_sha256="f" * 64)
    with pytest.raises(ValueError, match="different frozen execution"):
        _TeamStrengthShadowResolver(other).validate_execution(prepared.rolling_execution)


@pytest.mark.parametrize("update", ["duplicate", "order", "swap", "postcutoff", "registry"])
def test_resealed_structural_corruption_is_rejected(inputs, update):
    _prepared, dataset, _artifact, outcome = inputs
    shadow = outcome.shadow_input
    with pytest.raises(ValueError):
        if update == "duplicate":
            reseal(shadow, fixtures=(*shadow.fixtures, shadow.fixtures[-1]))
        elif update == "order":
            reseal(shadow, fixtures=tuple(reversed(shadow.fixtures)))
        elif update == "swap":
            row = shadow.fixtures[0]
            reseal(
                row,
                official_home_team_id=row.official_away_team_id,
                official_away_team_id=row.official_home_team_id,
            )
        elif update == "postcutoff":
            registry = reseal(dataset.fixture_registry, registered_at=CUTOFF + timedelta(seconds=1))
            model = reseal(shadow.artifact.model, fixture_registry_sha256=registry.semantic_sha256)
            reseal(shadow, fixture_registry=registry, artifact=reseal(shadow.artifact, model=model))
        else:
            reseal(
                shadow,
                fixture_registry=reseal(
                    dataset.fixture_registry, registration_authority="WRONG_AUTHORITY"
                ),
            )


def test_nested_tamper_and_missing_resolver_fixture_fail(inputs):
    prepared, _dataset, _artifact, outcome = inputs
    shadow = outcome.shadow_input
    resolver = _TeamStrengthShadowResolver(shadow)
    row = shadow.fixtures[0]
    with pytest.raises(ValueError, match="fixture identity or coverage"):
        resolver.resolve(row.baseline_prior, row.gameweek + 20)
    with pytest.raises(ValueError, match="semantic hash"):
        bad = type(shadow).model_validate_json(shadow.model_dump_json())
        object.__setattr__(bad.fixtures[0], "gameweek", 37)
        _TeamStrengthShadowResolver(bad)
    resolver.validate_execution(prepared.rolling_execution)
    object.__setattr__(resolver.shadow.fixtures[0], "gameweek", 37)
    with pytest.raises(ValueError, match="semantic hash"):
        resolver.resolve(row.baseline_prior, row.gameweek)


@pytest.mark.parametrize("official,season", [(999, "2026/27"), (1, "2025/26")])
def test_unknown_and_wrong_season_crosswalk_fail_closed(official, season):
    with pytest.raises(ValueError, match="P0 club mapping"):
        _p0_club(official, season)


def test_postcutoff_model_and_mismatched_source_assessment_are_integrity_failures(inputs):
    prepared, dataset, artifact, _ = inputs
    late = reseal(
        artifact, fitted_at=CUTOFF + timedelta(seconds=1), usable_at=CUTOFF + timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="cutoff"):
        prepare_team_strength_shadow(
            prepared.rolling_execution,
            artifact=late,
            expected_artifact_sha256=late.semantic_sha256,
            fixture_registry=dataset.fixture_registry,
        )
    invalid = reseal(
        assessment_for(dataset),
        fixture_registry_sha256="f" * 64,
        missing_due=1,
        freshness=SourceFreshnessState.STALE_BLOCKED,
    )
    with pytest.raises(ValueError, match="assessment identity"):
        prepare_team_strength_shadow(
            prepared.rolling_execution,
            artifact=artifact,
            expected_artifact_sha256=artifact.semantic_sha256,
            fixture_registry=dataset.fixture_registry,
            source_assessment=invalid,
        )


def test_allocation_shadow_and_score_shadow_cannot_be_combined(inputs):
    with pytest.raises(PrivateV1Error, match="ordinary player allocation"):
        PrivateV1RollingRecommendationService(
            _score_prior_resolver=_TeamStrengthShadowResolver(inputs[-1].shadow_input),
            _allocation_profile_resolver=lambda **kwargs: None,
        )


def test_live_observation_simulation_needs_exact_current_completeness(inputs):
    prepared, _dataset, _artifact, _ = inputs
    # Entirely generated score bytes, never reconstructed real final files.
    dataset, artifact = synthetic_strength(mode="LIVE_OBSERVED")
    assert dataset.dataset_mode == "LIVE_OBSERVED"
    arguments = dict(
        artifact=artifact,
        expected_artifact_sha256=artifact.semantic_sha256,
        fixture_registry=dataset.fixture_registry,
    )
    missing = prepare_team_strength_shadow(prepared.rolling_execution, **arguments)
    assert missing.reason == "CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE"
    assessment = assessment_for(dataset)
    ready = prepare_team_strength_shadow(
        prepared.rolling_execution, source_assessment=assessment, **arguments
    )
    assert ready.status == "TEAM_STRENGTH_PRIOR_READY"
    old = reseal(
        assessment,
        information_cutoff=CUTOFF - timedelta(seconds=1),
        source_usable_at=CUTOFF - timedelta(seconds=1),
    )
    outdated = prepare_team_strength_shadow(
        prepared.rolling_execution, source_assessment=old, **arguments
    )
    assert outdated.reason == "CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE"


def test_reconstructed_evidence_cannot_claim_live_private_world(inputs):
    prepared, dataset, artifact, _ = inputs
    # Directly probe the source-context guard; public preparation still revalidates
    # all execution fields and does not accept this deliberately unsealed copy.
    execution = type(prepared.rolling_execution).model_validate_json(
        prepared.rolling_execution.model_dump_json()
    )
    object.__setattr__(
        execution.current_execution, "retention_class", "PRIVATE_TRANSIENT_NO_RETENTION"
    )
    with pytest.raises(ValueError, match="reconstructed model"):
        _source_context(execution, artifact, dataset.fixture_registry, None)


@pytest.mark.parametrize(
    "status,reason",
    [
        ("TEAM_STRENGTH_PRIOR_READY", "SOURCE_STALE"),
        ("TEAM_STRENGTH_WORLD_UNAVAILABLE", "INCOMPLETE_FIXTURE_COVERAGE"),
    ],
)
def test_outcome_rejects_false_readiness(status, reason):
    with pytest.raises(ValueError):
        seal(TeamStrengthShadowPreparation, status=status, reason=reason)


def test_resealed_cross_fixture_context_and_freshness_lies_fail(inputs):
    _prepared, _dataset, _artifact, outcome = inputs
    shadow = outcome.shadow_input
    first = reseal(shadow.fixtures[0], private_identity_map_sha256="f" * 64)
    with pytest.raises(ValueError, match="one frozen source context"):
        reseal(shadow, fixtures=(first, *shadow.fixtures[1:]))
    with pytest.raises(ValueError, match="freshness claim"):
        reseal(outcome, reason="DEGRADED_SEALED_REUSE")


def test_authenticated_bundles_cannot_use_postcutoff_registry(inputs):
    _prepared, dataset, artifact, outcome = inputs
    registry = reseal(dataset.fixture_registry, registered_at=CUTOFF + timedelta(seconds=1))
    model = reseal(artifact.model, fixture_registry_sha256=registry.semantic_sha256)
    altered = reseal(artifact, model=model)
    bindings = tuple(
        reseal(
            row,
            public_bundle=fixture_prior_bundle(
                artifact=altered,
                fixture=row.public_bundle.fixture,
                as_of=CUTOFF,
                expected_artifact_sha256=altered.semantic_sha256,
            ),
        )
        for row in outcome.shadow_input.fixtures
    )
    with pytest.raises(ValueError, match="mapping is absent or post-cutoff"):
        reseal(outcome.shadow_input, artifact=altered, fixture_registry=registry, fixtures=bindings)


def test_private_prior_orientation_must_match_frozen_fpl(inputs):
    prepared, dataset, artifact, _outcome = inputs
    execution = prepared.rolling_execution
    current = execution.current_execution
    prior = current.score_priors[0]
    swapped = seal_fixture_score_prior(
        type(prior).model_construct(
            **(
                dict(prior)
                | {"home_team_id": prior.away_team_id, "away_team_id": prior.home_team_id}
            )
        )
    )
    values = dict(current)
    values["score_priors"] = (swapped, *current.score_priors[1:])
    values_current = seal_execution_input(type(current).model_construct(**values))
    rolling_values = dict(execution)
    rolling_values["current_execution"] = values_current
    invalid = seal_rolling_execution_input(type(execution).model_construct(**rolling_values))
    with pytest.raises(ValueError, match="baseline fixture identity"):
        prepare_team_strength_shadow(
            invalid,
            artifact=artifact,
            expected_artifact_sha256=artifact.semantic_sha256,
            fixture_registry=dataset.fixture_registry,
        )
