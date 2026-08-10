from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    get_prediction_run,
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.tables import prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_registry_and_prediction_bundle_are_idempotent(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    with postgres_session_factory.begin() as session:
        dataset_id = register_dataset_version(session, dataset)
        assert register_dataset_version(session, dataset) == dataset_id
        model_id = register_model_version(session, model)
        assert register_model_version(session, model) == model_id
        run_id = register_prediction_bundle(session, prediction, **bundle_parts)
        assert register_prediction_bundle(session, prediction, **bundle_parts) == run_id
        signature = next(
            iter(
                session.execute(
                    select(prediction_run.c.prediction_input_signature_sha256)
                ).scalars()
            )
        )
        recovered = get_prediction_run(session, signature)
    assert recovered["prediction_run_id"] == run_id
    assert len(recovered["dependencies"]) == 1
    assert len(recovered["scenarios"]) == 1
    assert len(recovered["scenarios"][0]["members"]) == 20


def test_committed_prediction_rows_are_immutable(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
) -> None:
    with pytest.raises(DBAPIError), postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        run_id = register_prediction_bundle(session, prediction)
        session.execute(
            update(prediction_run)
            .where(prediction_run.c.prediction_run_id == run_id)
            .values(seed="mutated")
        )
