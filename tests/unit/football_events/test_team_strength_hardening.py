"""Direct resealed-invalid-contract and immutable-publication failure paths."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from dmf_pulse.football_events import team_strength_adapter as adapter
from dmf_pulse.football_events import team_strength_model as model
from dmf_pulse.football_events import team_strength_store as store
from dmf_pulse.ingestion.openfootball.team_strength_data import build_dataset, seal
from tests.unit.football_events.team_strength_support import synthetic_artifact, synthetic_dataset
from tests.unit.football_events.test_team_strength_adapter import bundle, fixture
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP


def reseal(value, **updates):
    values = {k: getattr(value, k) for k in type(value).model_fields if k != "semantic_sha256"}
    values.update(updates)
    return seal(type(value), **values)


@pytest.mark.parametrize("value", [1.0, 1, "NaN", "Infinity", "1e999"])
def test_serialized_numbers_reject_wrong_type_or_nonfinite(value) -> None:
    with pytest.raises(ValueError):
        model._decimal_only(value)


@pytest.mark.parametrize(
    "change",
    [
        "ordering",
        "universe",
        "entrant",
        "cutoff",
        "live",
        "usable",
        "sources",
        "seasons",
        "cohort",
        "kappa",
        "constraint",
        "weights",
        "limitations",
    ],
)
def test_resealed_model_cannot_bypass_governed_consistency(change: str) -> None:
    state = synthetic_artifact().model
    updates = {}
    if change == "ordering":
        updates["effects"] = tuple(reversed(state.effects))
    elif change == "universe":
        effects = (
            *state.effects[:-1],
            state.effects[-1].model_copy(
                update={"team_id": UUID("ffffffff-ffff-7fff-bfff-ffffffffffff")}
            ),
        )
        updates.update(
            effects=effects,
            uncertainty=state.uncertainty.model_copy(
                update={
                    "parameter_order": model.parameter_order(tuple(row.team_id for row in effects))
                }
            ),
        )
    elif change == "entrant":
        updates["effects"] = (
            state.effects[0].model_copy(
                update={"is_forecast_entrant": not state.effects[0].is_forecast_entrant}
            ),
            *state.effects[1:],
        )
    elif change == "cutoff":
        updates["training_cutoff"] = STAMP + timedelta(days=1)
    elif change == "live":
        updates["dataset_mode"] = "LIVE_OBSERVED"
    elif change == "usable":
        updates["source_usable_at"] = state.source_usable_at - timedelta(seconds=1)
    elif change == "sources":
        updates["sources"] = ()
    elif change == "seasons":
        updates["seasons_represented"] = tuple(reversed(state.seasons_represented))
    elif change == "cohort":
        updates["entrant_cohort"] = state.entrant_cohort.model_copy(update={"contributors": ()})
    elif change == "kappa":
        updates["kappa_attack"] = Decimal("100")
    elif change == "constraint":
        updates["effects"] = (
            state.effects[0].model_copy(update={"attack": Decimal("3")}),
            *state.effects[1:],
        )
    elif change == "weights":
        updates["weighted_observation_count"] = Decimal("999999")
    else:
        updates["limitations"] = ()
    with pytest.raises(ValueError):
        reseal(state, **updates)


@pytest.mark.parametrize(
    "change", ["dimensions", "diagonal", "exclusions", "diagnostics", "execution"]
)
def test_numerical_artifact_internal_consistency(change: str) -> None:
    artifact = synthetic_artifact()
    uncertainty = artifact.model.uncertainty
    with pytest.raises(ValueError):
        if change == "dimensions":
            uncertainty.model_copy(update={"information": ()})
        elif change == "diagonal":
            uncertainty.model_copy(
                update={"covariance": (Decimal("0"), *uncertainty.covariance[1:])}
            )
        elif change == "exclusions":
            uncertainty.model_copy(update={"excludes": ()})
        elif change == "diagnostics":
            artifact.model.numerics.model_copy(update={"line_search_halvings": ()})
        else:
            reseal(artifact, fitted_at=STAMP - timedelta(seconds=1))


def test_cohort_unavailable_future_and_unknown_membership() -> None:
    with pytest.raises(model.InsufficientStrengthEvidence, match="membership"):
        model.entrants("2029/30", model.memberships())
    with pytest.raises(model.InsufficientStrengthEvidence, match="unavailable"):
        model.historical_cohort((), forecast_season="2010/11", cutoff=STAMP)
    rows = model.dataset_observations(synthetic_dataset())
    with pytest.raises(model.InsufficientStrengthEvidence, match="cutoff"):
        model.historical_cohort(rows, forecast_season="2025/26", cutoff=STAMP.replace(year=2010))


@pytest.mark.parametrize("change", ["postcutoff", "source", "unbound", "precision", "warning"])
def test_resealed_fixture_bundle_consistency(change: str) -> None:
    value = bundle()
    changes = {}
    if change == "postcutoff":
        changes["as_of"] = STAMP - timedelta(days=1)
    elif change == "source":
        changes["source_usable_at"] = STAMP + timedelta(days=1)
    elif change == "unbound":
        changes["due_completeness_assessed_at"] = value.as_of
    elif change == "precision":
        changes["score_prior"] = value.score_prior.model_copy(
            update={"home_goal_rate": Decimal("1.0")}
        )
    else:
        changes["warning"] = "REUSED_SEALED_MODEL_NO_CURRENT_REFIT_CLAIM"
    with pytest.raises(ValueError):
        reseal(value, **changes)


def test_resealed_bundle_prediction_mismatch() -> None:
    value = bundle()
    changed = reseal(value, model_state_sha256="a" * 64)
    with pytest.raises(ValueError, match="prediction"):
        adapter.authenticate_fixture_bundle(
            changed,
            artifact=synthetic_artifact(),
            expected_artifact_sha256=synthetic_artifact().semantic_sha256,
        )


def test_negative_fixture_covariance_fails_without_mixture() -> None:
    artifact = synthetic_artifact()
    uncertainty = artifact.model.uncertainty
    covariance = (uncertainty.covariance[0], Decimal("-1000000"), *uncertainty.covariance[2:])
    state = reseal(
        artifact.model, uncertainty=uncertainty.model_copy(update={"covariance": covariance})
    )
    changed = reseal(artifact, model=state)
    with pytest.raises(ValueError, match="negative fixture variance"):
        adapter.fixture_rate_uncertainty(
            artifact=changed,
            fixture=fixture(),
            as_of=STAMP + timedelta(seconds=2),
            expected_artifact_sha256=changed.semantic_sha256,
        )


@pytest.mark.parametrize("change", ["time", "freshness", "identity", "future"])
def test_source_assessment_consistency_and_context(change: str) -> None:
    assessment = adapter._source_assessment(synthetic_dataset())
    with pytest.raises(ValueError):
        if change == "time":
            reseal(assessment, latest_received_at=STAMP + timedelta(days=1))
        elif change == "freshness":
            reseal(assessment, freshness=adapter.SourceFreshnessState.DEGRADED)
        else:
            changed = reseal(
                assessment,
                **(
                    {"fixture_registry_sha256": "a" * 64}
                    if change == "identity"
                    else {"information_cutoff": STAMP + timedelta(hours=1)}
                ),
            )
            adapter.fixture_prior_bundle(
                artifact=synthetic_artifact(),
                fixture=fixture(),
                as_of=STAMP + timedelta(seconds=2),
                expected_artifact_sha256=synthetic_artifact().semantic_sha256,
                source_assessment=changed,
            )


@pytest.mark.parametrize("stage", [1, 2])
def test_store_rejects_symlink_before_or_after_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    checks = 0
    original = Path.is_symlink

    def symlink(path):
        nonlocal checks
        if path.name.endswith(".json"):
            checks += 1
            return checks == stage
        return original(path)

    monkeypatch.setattr(Path, "is_symlink", symlink)
    with pytest.raises(ValueError, match=r"escapes|changed"):
        store.persist_team_strength(synthetic_artifact(), artifact_root=tmp_path)
    assert not tuple(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("collision", [False, True])
def test_store_exclusive_publication_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, collision: bool
) -> None:
    def competing_publisher(source, destination):
        Path(destination).write_bytes(
            b"conflicting identity" if collision else Path(source).read_bytes()
        )
        raise FileExistsError

    monkeypatch.setattr(store.os, "link", competing_publisher)
    if collision:
        with pytest.raises(ValueError, match="collision"):
            store.persist_team_strength(synthetic_artifact(), artifact_root=tmp_path)
    else:
        path = store.persist_team_strength(synthetic_artifact(), artifact_root=tmp_path)
        assert (
            store.load_team_strength(
                path, expected_artifact_sha256=synthetic_artifact().semantic_sha256
            )
            == synthetic_artifact()
        )
    assert not tuple(tmp_path.rglob(".team-strength-*"))


def test_live_due_midnight_requires_reassessment_even_with_recent_retrieval() -> None:
    original = synthetic_dataset()
    source = original.sources[-1]
    pending = reseal(
        source.matches[0],
        finality="NO_SCORE",
        home_goals=None,
        away_goals=None,
        source_match_date=(STAMP - timedelta(days=1)).date(),
    )
    changed = reseal(source, matches=(pending, *source.matches[1:]))
    sources = (*original.sources[:-1], changed)

    def live(cutoff):
        return build_dataset(
            sources=sources,
            fixtures=original.fixture_registry,
            expected_fixture_registry_sha256=original.fixture_registry.semantic_sha256,
            information_cutoff=cutoff,
            training_cutoff=cutoff,
            forecast_season=original.forecast_season,
            mode="LIVE_OBSERVED",
        )

    initial = live(STAMP)
    assert initial.missing_due == 0 and initial.freshness.value == "FRESH"
    artifact = model.fit_team_strength(initial, clock=lambda: STAMP + timedelta(seconds=1))
    assessment = adapter._source_assessment(initial)
    for supplied in (None, assessment):
        before = adapter.fixture_prior_bundle(
            artifact=artifact,
            fixture=fixture(),
            as_of=STAMP + timedelta(days=1, seconds=-1),
            expected_artifact_sha256=artifact.semantic_sha256,
            source_assessment=supplied,
        )
        assert before.dataset_mode == "LIVE_OBSERVED"
        with pytest.raises(ValueError, match="UTC-day assessment"):
            adapter.fixture_prior_bundle(
                artifact=artifact,
                fixture=fixture(),
                as_of=STAMP + timedelta(days=1),
                expected_artifact_sha256=artifact.semantic_sha256,
                source_assessment=supplied,
            )
    current = live(STAMP + timedelta(days=1))
    assert current.missing_due == 1 and current.freshness.value == "STALE_BLOCKED"
    result = adapter.prepare_team_strength(current, latest_artifact=artifact)
    assert (
        result.status == "LEAGUE_LEVEL_SUPPORT_PRIOR_FALLBACK" and result.reason == "SOURCE_STALE"
    )
