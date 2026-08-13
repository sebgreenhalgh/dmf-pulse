from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import register_prediction_bundle
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.tables import player_minutes_projection, prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_canonical_array_shape_and_half_even_ties(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    with postgres_session_factory.begin() as session:
        results = session.execute(
            text(
                """
                SELECT
                  football.validate_minute_pmf(array_fill(1::numeric, ARRAY[91], ARRAY[0]), 'BENCH') AS alternate,
                  football.validate_minute_pmf(NULL::numeric[], 'BENCH') AS malformed,
                  football.validate_minute_pmf(
                    ARRAY[1::numeric + 1e-300] || array_fill(0::numeric, ARRAY[90]), 'BENCH'
                  ) AS tiny_excess,
                  football.round_half_even_6(0.123456500000::numeric) AS tie_1,
                  football.round_half_even_6(0.123457500000::numeric) AS tie_2,
                  football.round_half_even_6(1.234566500000::numeric) AS tie_3,
                  football.round_half_even_6(1.234567500000::numeric) AS tie_4
                """
            )
        ).one()
    assert results.alternate is False
    assert results.malformed is False
    assert results.tiny_excess is False
    assert results.tie_1 == Decimal("0.123456")
    assert results.tie_2 == Decimal("0.123458")
    assert results.tie_3 == Decimal("1.234566")
    assert results.tie_4 == Decimal("1.234568")


def test_scenario_members_must_equal_marginals(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    bad = deepcopy(bundle_parts)
    bad["scenarios"][0]["members"][0]["player_id"] = "rogue-player"
    with postgres_session_factory.begin() as session, pytest.raises(DataModelError) as error:
        from dmf_pulse.availability.persistence import (
            register_dataset_version,
            register_model_version,
        )

        register_dataset_version(session, dataset)
        register_model_version(session, model)
        register_prediction_bundle(session, prediction, **bad)
    assert error.value.code == "SCENARIO_MARGINAL_COHERENCE"


def test_final_projection_wrong_run_identity_leaves_no_rows(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    from dmf_pulse.availability.persistence import register_dataset_version, register_model_version

    final = {
        "fixture_id": "00000000-0000-0000-0000-000000000099",
        "team_id": prediction["team_id"],
        "as_of": prediction["as_of"],
        "model_family": "INTEGRATION",
        "dataset_sha256": dataset["dataset_sha256"],
        "model_artifact_sha256": "c" * 64,
        "players": [],
    }
    model_artifact = {"artifact_sha256": "c" * 64}
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model, artifact=model_artifact)
        with pytest.raises(DataModelError) as error:
            register_prediction_bundle(session, prediction, final_projection=final, **bundle_parts)
        assert error.value.code == "FINAL_PROJECTION_RUN_MISMATCH"
        assert session.scalar(select(func.count()).select_from(prediction_run)) == 0
        assert session.scalar(select(func.count()).select_from(player_minutes_projection)) == 0
