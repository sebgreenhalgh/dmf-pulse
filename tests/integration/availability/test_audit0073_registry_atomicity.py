from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    get_prediction_run,
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.tables import dataset_version, prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_dataset_exception_cannot_commit_or_back_model(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
) -> None:
    incomplete = dict(dataset)
    incomplete["training_example_count"] = 1
    with postgres_session_factory.begin() as session, pytest.raises(DataModelError):
        register_dataset_version(session, incomplete, training_examples=[])
    with postgres_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(dataset_version)) == 0
        with pytest.raises(DataModelError):
            register_model_version(session, {**model, "dataset_version_sha256": "a" * 64})


def test_conflicting_model_artifact_is_not_idempotent(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model, artifact={"version": 1})
        with pytest.raises(DataModelError) as error:
            register_model_version(session, model, artifact={"version": 2})
        assert error.value.code == "MODEL_IDENTITY_COLLISION"


def test_late_pmf_failure_rolls_back_the_complete_graph(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    invalid = deepcopy(bundle_parts)
    invalid["minute_pmfs"][0]["minute_pmf"] = ["not-a-decimal"]
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        with pytest.raises(DataModelError):
            register_prediction_bundle(session, prediction, **invalid)
    with postgres_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(prediction_run)) == 0


def test_incomplete_graph_and_mismatched_output_fail_closed(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        with pytest.raises(DataModelError):
            register_prediction_bundle(session, prediction)
        mismatched = dict(prediction)
        mismatched["sample_count"] = 2
        with pytest.raises(DataModelError):
            register_prediction_bundle(session, mismatched, **bundle_parts)


def test_declared_output_hash_cannot_hide_changed_bundle(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        run_id = register_prediction_bundle(session, prediction, **bundle_parts)
        output_hash = session.scalar(
            select(prediction_run.c.output_semantic_sha256).where(
                prediction_run.c.prediction_run_id == run_id
            )
        )
        altered = deepcopy(bundle_parts)
        altered["role_marginals"][0]["p_start"] = "0.7"
        altered["role_marginals"][0]["p_bench"] = "0.2"
        declared = dict(prediction)
        declared["output_semantic_sha256"] = output_hash
        with pytest.raises(DataModelError) as error:
            register_prediction_bundle(session, declared, **altered)
        assert error.value.code == "OUTPUT_IDENTITY_MISMATCH"


def test_complete_prediction_is_recoverable_by_exact_signature(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        run_id = register_prediction_bundle(session, prediction, **bundle_parts)
        signature = prediction["model_version_sha256"]
        assert run_id
        assert get_prediction_run(session, prediction_signature(prediction))
        assert signature


def prediction_signature(prediction: dict[str, object]) -> str:
    from dmf_pulse.availability.registry import prediction_input_signature_sha256

    return prediction_input_signature_sha256(prediction)
