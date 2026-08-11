from __future__ import annotations

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.data_model.tables import (
    conditional_minute_pmf,
    lineup_scenario,
    lineup_scenario_member,
    prediction_dependency,
    prediction_hard_eligibility,
    prediction_run,
    role_marginal,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_complete_prediction_core_rejects_all_child_mutations(
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
        assert (
            session.scalar(
                select(prediction_run.c.core_state).where(
                    prediction_run.c.prediction_run_id == run_id
                )
            )
            == "COMPLETE"
        )
        scenario_id = session.scalar(
            select(lineup_scenario.c.lineup_scenario_id).where(
                lineup_scenario.c.prediction_run_id == run_id
            )
        )
        statements = (
            insert(prediction_dependency).values(
                prediction_run_id=run_id,
                dependency_type="ROGUE",
                dependency_key="rogue",
                semantic_sha256="a" * 64,
                ordinal=99,
            ),
            insert(prediction_hard_eligibility).values(
                prediction_run_id=run_id, player_id="rogue", reason="rogue", hard_ineligible=True
            ),
            insert(role_marginal).values(
                prediction_run_id=run_id,
                player_id="rogue",
                player_key="rogue",
                position="MID",
                p_start=0,
                p_bench=1,
                p_out=0,
            ),
            insert(conditional_minute_pmf).values(
                prediction_run_id=run_id,
                player_id="rogue",
                role="BENCH",
                minute_pmf=[1] + [0] * 90,
            ),
            insert(lineup_scenario).values(
                prediction_run_id=run_id, scenario_index=99, scenario_sha256="b" * 64
            ),
            insert(lineup_scenario_member).values(
                lineup_scenario_id=scenario_id,
                prediction_run_id=run_id,
                player_id="rogue",
                role="BENCH",
                position="MID",
            ),
        )
        for statement in statements:
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(statement)
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                update(prediction_dependency)
                .where(prediction_dependency.c.prediction_run_id == run_id)
                .values(dependency_key="mutated")
            )
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                delete(prediction_dependency).where(
                    prediction_dependency.c.prediction_run_id == run_id
                )
            )
