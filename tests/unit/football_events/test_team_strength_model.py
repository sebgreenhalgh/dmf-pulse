"""Model provenance, immutable nested authentication and historical cohort safety."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.football_events.team_strength_model import (
    InsufficientStrengthEvidence,
    TeamStrengthModelArtifactV1,
    dataset_observations,
    fit_team_strength,
    historical_cohort,
    number,
)
from dmf_pulse.football_events.team_strength_numerics import Observation
from dmf_pulse.football_events.team_strength_store import load_team_strength, persist_team_strength
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate, seal
from tests.unit.football_events.team_strength_support import synthetic_artifact, synthetic_dataset
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP, dataset


def test_authenticated_complete_model_and_stable_semantic_execution_split() -> None:
    artifact = synthetic_artifact()
    assert authenticate(artifact) == artifact
    assert artifact.model.match_count == 6080
    assert len(artifact.model.effects) == 41
    assert artifact.model.status == "SHADOW_NOT_MODEL_INPUT"
    assert artifact.model.uncertainty.classification == "ASYMPTOTIC_LOCAL_PENALISED_V1"
    assert artifact.model.uncertainty.parameter_order[:2] == ("mu", "global_home")
    other = seal(
        TeamStrengthModelArtifactV1,
        model=artifact.model,
        fitted_at=STAMP + timedelta(seconds=2),
        usable_at=STAMP + timedelta(seconds=3),
    )
    assert other.model.semantic_sha256 == artifact.model.semantic_sha256
    assert other.semantic_sha256 != artifact.semantic_sha256
    repeated = fit_team_strength(synthetic_dataset(), clock=lambda: STAMP + timedelta(seconds=1))
    assert repeated == artifact


@pytest.mark.parametrize(
    "field",
    ["coefficient", "covariance", "source", "rights", "identity", "cutoff", "policy", "execution"],
)
def test_nested_tamper_fails(field: str) -> None:
    payload = synthetic_artifact().model_dump(mode="json")
    model = payload["model"]
    if field == "coefficient":
        model["effects"][0]["attack"] = "0.999999999"
    elif field == "covariance":
        model["uncertainty"]["covariance"][0] = "100.0"
    elif field == "source":
        model["sources"][0]["resource"]["content_sha256"] = "0" * 64
    elif field == "rights":
        model["sources"][0]["rights_config_sha256"] = "0" * 64
    elif field == "identity":
        model["identity_registry_sha256"] = "0" * 64
    elif field == "cutoff":
        model["training_cutoff"] = "2027-01-01T00:00:00Z"
    elif field == "policy":
        model["half_life_days"] = 180
    else:
        payload["usable_at"] = "2025-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        TeamStrengthModelArtifactV1.model_validate_json(json.dumps(payload))


def test_current_entrant_first_season_cannot_change_its_cohort() -> None:
    dataset_value = synthetic_dataset()
    rows = dataset_observations(dataset_value)
    original = synthetic_artifact().model.entrant_cohort
    revised = tuple(
        Observation(row.fixture_id, row.season, row.played_on, row.home, row.away, 99, 99)
        if row.season == "2025/26"
        else row
        for row in rows
    )
    assert (
        historical_cohort(revised, forecast_season="2025/26", cutoff=dataset_value.training_cutoff)
        == original
    )
    assert all(row.season < "2025/26" for row in original.contributors)
    with pytest.raises(InsufficientStrengthEvidence, match="complete"):
        historical_cohort(
            tuple(row for row in rows if row.season != "2024/25"),
            forecast_season="2025/26",
            cutoff=dataset_value.training_cutoff,
        )


def test_insufficient_or_degraded_evidence_does_not_fit() -> None:
    with pytest.raises(InsufficientStrengthEvidence, match="full corpus"):
        fit_team_strength(dataset())
    with pytest.raises(InsufficientStrengthEvidence, match="fresh source"):
        fit_team_strength(dataset(received=STAMP - timedelta(hours=25)))


def test_artifact_write_once_and_collision(tmp_path: Path) -> None:
    artifact = synthetic_artifact()
    path = persist_team_strength(artifact, artifact_root=tmp_path)
    original = path.read_bytes()
    assert persist_team_strength(artifact, artifact_root=tmp_path) == path
    assert load_team_strength(path, expected_artifact_sha256=artifact.semantic_sha256) == artifact
    with pytest.raises(ValueError, match="expected"):
        load_team_strength(path, expected_artifact_sha256="0" * 64)
    path.write_bytes(b"deliberate synthetic collision")
    with pytest.raises(ValueError, match="collision"):
        persist_team_strength(artifact, artifact_root=tmp_path)
    assert path.read_bytes() == b"deliberate synthetic collision" and original != path.read_bytes()


def test_nonfinite_serialization_rejected_and_decimal_boundary() -> None:
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            number(value)
    assert number(0.1) == Decimal("0.1")
