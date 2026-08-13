from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.tables import dataset_version, model_version

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_independent_sessions_converge_on_registry_rows(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    barrier = Barrier(2)

    def register_dataset() -> object:
        with postgres_session_factory.begin() as session:
            barrier.wait()
            return register_dataset_version(session, dataset)

    with ThreadPoolExecutor(max_workers=2) as executor:
        dataset_ids = list(executor.map(lambda _: register_dataset(), range(2)))
    assert dataset_ids[0] == dataset_ids[1]

    barrier = Barrier(2)

    def register_model() -> object:
        with postgres_session_factory.begin() as session:
            barrier.wait()
            return register_model_version(session, model)

    with ThreadPoolExecutor(max_workers=2) as executor:
        model_ids = list(executor.map(lambda _: register_model(), range(2)))
    assert model_ids[0] == model_ids[1]
    with postgres_session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(dataset_version)) == 1
        assert session.scalar(select(func.count()).select_from(model_version)) == 1

    barrier = Barrier(2)

    def register_prediction() -> object:
        with postgres_session_factory.begin() as session:
            barrier.wait()
            return register_prediction_bundle(session, prediction, **bundle_parts)

    with ThreadPoolExecutor(max_workers=2) as executor:
        prediction_ids = list(executor.map(lambda _: register_prediction(), range(2)))
    assert prediction_ids[0] == prediction_ids[1]
