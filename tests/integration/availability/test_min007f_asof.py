from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    latest_unambiguous_prediction,
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.errors import DataModelError

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_latest_asof_and_ambiguity_fail_closed(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        first = register_prediction_bundle(session, prediction)
        later = dict(prediction)
        later["as_of"] = "2026-08-14T18:00:00Z"
        second = register_prediction_bundle(session, later)
        assert first != second
        chosen = latest_unambiguous_prediction(
            session,
            fixture_id=prediction["fixture_id"],
            team_id=prediction["team_id"],
            model_version_sha256=model_version_hash(model),
            cutoff=datetime(2026, 8, 14, 19, tzinfo=UTC),
        )
        assert chosen["prediction_run_id"] == second
        ambiguous = dict(prediction)
        ambiguous["code_identity"] = "different"
        register_prediction_bundle(session, ambiguous)
        with pytest.raises(DataModelError) as error:
            latest_unambiguous_prediction(
                session,
                fixture_id=prediction["fixture_id"],
                team_id=prediction["team_id"],
                model_version_sha256=model_version_hash(model),
                cutoff=datetime(2026, 8, 14, 17, 30, tzinfo=UTC),
            )
        assert error.value.code == "AMBIGUOUS_HISTORICAL_RUN"


def model_version_hash(model: dict[str, object]) -> str:
    from dmf_pulse.availability.registry import model_version_semantic_sha256

    return model_version_semantic_sha256(model)
