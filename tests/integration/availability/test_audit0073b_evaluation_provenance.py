from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_model_evaluation,
    register_model_version,
)
from dmf_pulse.availability.pipeline import MinutesModelEvaluation, ModelEvaluationPublication
from dmf_pulse.availability.registry import model_version_semantic_sha256
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.tables import model_evaluation

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


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


def test_evaluation_persistence_requires_target_model_binding(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
) -> None:
    public = MinutesModelEvaluation.model_validate(EVALUATION)
    artifact = {"artifact_sha256": "c" * 64}
    publication = ModelEvaluationPublication(
        evaluation=public,
        model_version_semantic_sha256=model_version_semantic_sha256(model),
        model_artifact_sha256=artifact["artifact_sha256"],
        model_family=model["model_family"],
    )
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        model_id = register_model_version(session, model, artifact=artifact)
        with pytest.raises(DataModelError) as raw_error:
            register_model_evaluation(session, model_id, EVALUATION)
        assert raw_error.value.code == "EVALUATION_PROVENANCE_REQUIRED"
        evaluation_id = register_model_evaluation(session, model_id, publication)
        assert register_model_evaluation(session, model_id, publication) == evaluation_id
        bound = (
            session.execute(
                select(model_evaluation).where(
                    model_evaluation.c.model_evaluation_id == evaluation_id
                )
            )
            .mappings()
            .one()
        )
        assert bound["evaluated_model_semantic_sha256"] == publication.model_version_semantic_sha256
        assert bound["evaluated_model_artifact_sha256"] == publication.model_artifact_sha256
        assert bound["evaluated_model_family"] == publication.model_family
        wrong = publication.model_copy(update={"model_artifact_sha256": "d" * 64})
        with pytest.raises(DataModelError) as mismatch:
            register_model_evaluation(session, model_id, wrong)
        assert mismatch.value.code == "EVALUATION_PROVENANCE_MISMATCH"
