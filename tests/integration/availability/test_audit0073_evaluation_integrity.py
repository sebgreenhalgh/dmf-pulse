from __future__ import annotations

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError
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


def test_evaluation_is_strictly_bound_and_idempotent(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        model_id = register_model_version(session, model, artifact={"artifact_sha256": "c" * 64})
        publication = ModelEvaluationPublication(
            evaluation=MinutesModelEvaluation.model_validate(EVALUATION),
            model_version_semantic_sha256=model_version_semantic_sha256(model),
            model_artifact_sha256="c" * 64,
            model_family=model["model_family"],
        )
        first = register_model_evaluation(session, model_id, publication)
        assert register_model_evaluation(session, model_id, publication) == first
        with pytest.raises(DataModelError) as status_error:
            register_model_evaluation(session, model_id, publication, status="BLOCKED")
        assert status_error.value.code == "EVALUATION_CONFLICT"

        second_model = dict(model, model_key="second-model", code_identity="second-code")
        second_id = register_model_version(
            session, second_model, artifact={"artifact_sha256": "c" * 64}
        )
        with pytest.raises(DataModelError) as model_error:
            register_model_evaluation(session, second_id, publication)
        assert model_error.value.code == "EVALUATION_PROVENANCE_MISMATCH"

        with pytest.raises(Exception):
            ModelEvaluationPublication(
                evaluation={**EVALUATION, "production_calibration_claim": True},
                model_version_semantic_sha256=model_version_semantic_sha256(model),
                model_artifact_sha256="c" * 64,
                model_family=model["model_family"],
            )


def test_database_rejects_production_calibration_claim_bypass(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
) -> None:
    with pytest.raises(DBAPIError), postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        model_id = register_model_version(session, model)
        session.execute(
            insert(model_evaluation).values(
                model_version_id=model_id,
                evaluation_semantic_sha256="a" * 64,
                status="COMPLETE",
                evaluation={**EVALUATION, "production_calibration_claim": True},
            )
        )
