from __future__ import annotations

import pytest

from dmf_pulse.availability.persistence import register_model_evaluation
from dmf_pulse.availability.pipeline import MinutesModelEvaluation, ModelEvaluationPublication
from dmf_pulse.data_model.errors import DataModelError

EVALUATION = {
    "schema_version": "minutes-model-evaluation-v1",
    "evaluation_kind": "SYNTHETIC_CONTRACT_EVALUATION",
    "n_examples": 92,
    "role_log_loss": "0.594149",
    "persistence_role_log_loss": "0.792258",
    "role_multiclass_brier": "0.104682",
    "persistence_role_multiclass_brier": "0.157174",
    "p_zero_brier": "0.160983",
    "persistence_p_zero_brier": "0.261739",
    "p_60_plus_brier": "0.119925",
    "persistence_p_60_plus_brier": "0.209565",
    "expected_minutes_mae": "23.587945",
    "baseline_decision": "PROMOTE_BASELINE",
    "production_calibration_claim": False,
    "evaluation_sha256": "f2d075a9497331b73bf896be4610b684f8a3ed41eb17248a27284c79556cd748",
}


def test_public_evaluation_remains_frozen_and_publication_is_strict() -> None:
    public = MinutesModelEvaluation.model_validate(EVALUATION)
    publication = ModelEvaluationPublication(
        evaluation=public,
        model_version_semantic_sha256="a" * 64,
        model_artifact_sha256="b" * 64,
        model_family="REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
    )
    assert publication.evaluation.evaluation_sha256 == EVALUATION["evaluation_sha256"]
    with pytest.raises(DataModelError) as error:
        register_model_evaluation(None, None, EVALUATION)  # type: ignore[arg-type]
    assert error.value.code == "EVALUATION_PROVENANCE_REQUIRED"


def test_publication_rejects_production_calibration_claim() -> None:
    with pytest.raises(ValueError):
        ModelEvaluationPublication(
            evaluation={**EVALUATION, "production_calibration_claim": True},
            model_version_semantic_sha256="a" * 64,
            model_artifact_sha256="b" * 64,
            model_family="REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        )
