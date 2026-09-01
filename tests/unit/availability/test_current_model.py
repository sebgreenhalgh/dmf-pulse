"""Accepted Stage-7 model to private transient scenario adaptation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.current_model import build_current_model_fixture_minutes
from dmf_pulse.availability.pipeline import fit_projection_artifact, predict_minutes_baseline

pytestmark = pytest.mark.unit


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_current_model_adapter_preserves_accepted_coherent_role_scenarios(
    repository_root: Path,
) -> None:
    root = repository_root / "src/dmf_pulse/availability/resources"
    history = _read(root / "MIN-007/canonical_history.json")
    training = _read(root / "MIN-007/training_dataset.json")
    policy = _read(root / "MIN-007G/minutes_baseline_policy.json")
    context = _read(root / "MIN-007G/contexts/stable_xi.json")
    assert isinstance(history, dict)
    assert isinstance(context, dict)
    fixture_id = str(uuid5(NAMESPACE_URL, "dmf-pulse:current-model-test-fixture"))
    context["fixture_id"] = fixture_id
    artifact = fit_projection_artifact(training, policy=policy)
    home = predict_minutes_baseline(history, artifact, context=context, policy=policy)

    rosters = history["rosters"]
    assert isinstance(rosters, dict)
    beta = rosters["beta"]
    assert isinstance(beta, list)
    beta_context = dict(context)
    beta_context.update(
        {
            "team_key": "beta",
            "team_id": beta[0]["team_id"],
            "manager_regime_id": str(uuid5(NAMESPACE_URL, "dmf-pulse:beta-regime")),
            "focus_player_key": beta[0]["player_key"],
        }
    )
    away = predict_minutes_baseline(history, artifact, context=beta_context, policy=policy)

    first = build_current_model_fixture_minutes(
        home,
        away,
        information_cutoff=datetime(2026, 8, 14, 17, 30, tzinfo=UTC),
        observed_history_sha256="1" * 64,
        warnings=("EARLY_SEASON_SHRINKAGE_ACTIVE",),
    )
    second = build_current_model_fixture_minutes(
        home,
        away,
        information_cutoff=datetime(2026, 8, 14, 17, 30, tzinfo=UTC),
        observed_history_sha256="1" * 64,
        warnings=("EARLY_SEASON_SHRINKAGE_ACTIVE",),
    )

    assert first == second
    assert first.model_derived is True
    assert first.model_family == "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
    assert len(first.home.scenarios) == 256
    assert len(first.away.scenarios) == 256
    assert all(item.count == 1 for item in first.home.scenarios)
    assert tuple(item.scenario_id for item in first.home.scenarios) == tuple(
        item.scenario_id for item in first.away.scenarios
    )
    assert all(
        len([player for player in scenario.players if player.role == "START"]) == 11
        for scenario in first.home.scenarios
    )
    assert all(
        player.official_minutes < 90
        for scenario in first.home.scenarios
        for player in scenario.players
        if player.role == "BENCH"
    )
    assert first.home_projection == home.projection
    assert first.away_projection == away.projection
