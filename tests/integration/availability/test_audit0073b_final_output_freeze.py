from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_final_player_projections,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.tables import player_minutes_projection, prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _projection(
    prediction: dict[str, object],
    dataset: dict[str, object],
    parts: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    pmf = [Decimal(1)] + [Decimal(0)] * 90
    players = [
        {
            "player_id": str(row["player_id"]),
            "position": str(row["position"]),
            "p_start": "0.8" if str(row["player_id"]).startswith("starter") else "0.1",
            "p_bench": "0.1" if str(row["player_id"]).startswith("starter") else "0.8",
            "p_out_of_squad": "0.1",
            "p_zero_minutes": "1",
            "p_60_plus": "0",
            "expected_minutes": "0",
            "minute_pmf": pmf,
        }
        for row in parts["role_marginals"]
    ]
    return {
        "fixture_id": prediction["fixture_id"],
        "team_id": prediction["team_id"],
        "as_of": prediction["as_of"],
        "model_family": "INTEGRATION",
        "dataset_sha256": dataset["dataset_sha256"],
        "model_artifact_sha256": "c" * 64,
        "players": players,
    }


def test_final_output_has_own_lifecycle_and_freeze(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    final = _projection(prediction, dataset, bundle_parts)
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model, artifact={"artifact_sha256": "c" * 64})
        run_id = register_prediction_bundle(
            session, prediction, final_projection=final, **bundle_parts
        )
        row = session.execute(
            select(prediction_run.c.final_output_state, prediction_run.c.final_output_count).where(
                prediction_run.c.prediction_run_id == run_id
            )
        ).one()
        assert row == ("COMPLETE", len(final["players"]))
        assert (
            register_prediction_bundle(session, prediction, final_projection=final, **bundle_parts)
            == run_id
        )
        altered = {**final, "extra": "ALTERED"}
        with pytest.raises(DataModelError) as error:
            register_final_player_projections(session, run_id, altered)
        assert error.value.code == "FINAL_OUTPUT_COLLISION"
        player_id = final["players"][0]["player_id"]
        for statement in (
            insert(player_minutes_projection).values(
                prediction_run_id=run_id,
                player_id="rogue",
                p_start=0,
                p_bench=1,
                p_out=0,
                minute_pmf=[1] + [0] * 90,
                p_zero=1,
                p_60_plus=0,
                expected_minutes=0,
            ),
            update(player_minutes_projection)
            .where(player_minutes_projection.c.prediction_run_id == run_id)
            .values(expected_minutes=1),
            delete(player_minutes_projection).where(
                player_minutes_projection.c.prediction_run_id == run_id,
                player_minutes_projection.c.player_id == player_id,
            ),
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(statement)
