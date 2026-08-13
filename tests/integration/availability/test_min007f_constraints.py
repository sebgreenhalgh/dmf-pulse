from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.errors import DataModelError

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_exact_pmf_constraint_rejects_deficit(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
) -> None:
    bad_pmf = [Decimal("0")] + [Decimal("0.01")] * 90
    with pytest.raises(DataModelError) as error, postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model)
        register_prediction_bundle(
            session,
            prediction,
            minute_pmfs=[{"player_id": "p", "role": "START", "minute_pmf": bad_pmf}],
        )
    assert error.value.code == "DATABASE_CONSTRAINT_VIOLATION"
