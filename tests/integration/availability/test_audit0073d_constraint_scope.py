from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_final_player_projections,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.availability.projection import canonical_sha256
from dmf_pulse.data_model.tables import prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_two_valid_publications_compose_in_one_outer_transaction(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
    final_projection: dict[str, object],
) -> None:
    prediction_b = {
        **prediction,
        "fixture_id": "943094f5-1d10-5d96-b88b-d271464f3e49",
        "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760783",
        "as_of": "2026-08-14T18:30:00Z",
        "seed": "integration-b",
    }
    final_b_body = {
        **final_projection,
        "fixture_id": prediction_b["fixture_id"],
        "team_id": prediction_b["team_id"],
        "as_of": prediction_b["as_of"],
    }
    final_b_body.pop("result_sha256", None)
    final_b = {**final_b_body, "result_sha256": canonical_sha256(final_b_body)}

    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model, artifact={"artifact_sha256": "c" * 64})
        run_a = register_prediction_bundle(
            session, prediction, final_projection=final_projection, **bundle_parts
        )
        run_b = register_prediction_bundle(session, prediction_b, **bundle_parts)
        register_final_player_projections(session, run_b, final_b)

        assert run_a != run_b
        states = session.execute(
            select(prediction_run.c.core_state, prediction_run.c.final_output_state).where(
                prediction_run.c.prediction_run_id.in_([run_a, run_b])
            )
        ).all()
        assert states == [("COMPLETE", "COMPLETE"), ("COMPLETE", "COMPLETE")]

    with postgres_session_factory() as session:
        rows = session.execute(
            select(
                prediction_run.c.core_state,
                prediction_run.c.final_output_state,
                prediction_run.c.final_output_count,
            )
            .where(prediction_run.c.prediction_run_id.in_([run_a, run_b]))
            .order_by(prediction_run.c.prediction_run_id)
        ).all()
    assert len(rows) == 2
    assert all(row.core_state == "COMPLETE" for row in rows)
    assert all(row.final_output_state == "COMPLETE" for row in rows)
    assert all(row.final_output_count == 20 for row in rows)
