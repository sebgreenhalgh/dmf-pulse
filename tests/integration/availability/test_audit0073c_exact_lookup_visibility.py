"""Committed draft runs cannot escape through any MIN-007 lookup."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    AvailabilityPersistence,
    get_prediction_run,
    latest_unambiguous_prediction,
    list_prediction_runs_as_of,
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.availability.registry import prediction_input_signature_sha256
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.tables import prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_committed_core_draft_is_hidden_from_exact_asof_and_public_reads(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
) -> None:
    signature = prediction_input_signature_sha256(prediction)
    draft_signature = "d" * 64
    draft_fixture = UUID("ae874b3c-7f59-51b3-a9d4-503536480267")
    draft_team = UUID("bf03d9dd-dc31-58ee-b8ec-8d246f08821b")
    cutoff = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model, artifact={"artifact_sha256": "c" * 64})
        complete_id = register_prediction_bundle(session, prediction, **bundle_parts)
        source = dict(
            session.execute(
                select(prediction_run).where(prediction_run.c.prediction_run_id == complete_id)
            )
            .mappings()
            .one()
        )
        for key in (
            "prediction_run_id",
            "created_at",
            "core_output_payload",
            "final_output_payload",
        ):
            source.pop(key)
        source.update(
            prediction_input_signature_sha256=draft_signature,
            output_semantic_sha256="e" * 64,
            fixture_id=draft_fixture,
            team_id=draft_team,
            core_state="DRAFT",
            final_output_state="NONE",
            final_output_count=0,
            final_output_semantic_sha256=None,
        )
        session.execute(insert(prediction_run).values(**source))
        session.execute(
            update(prediction_run)
            .where(prediction_run.c.prediction_run_id == complete_id)
            .values(final_output_state="DRAFT")
        )

    with postgres_session_factory() as session:
        with pytest.raises(DataModelError, match="prediction signature was not found") as error:
            get_prediction_run(session, draft_signature)
        assert error.value.code == "PREDICTION_NOT_FOUND"
        with pytest.raises(DataModelError, match="prediction signature was not found"):
            AvailabilityPersistence(session).get_prediction_run(draft_signature)
        assert (
            list_prediction_runs_as_of(
                session,
                fixture_id=draft_fixture,
                team_id=draft_team,
                model_version_sha256=prediction["model_version_sha256"],
                cutoff=cutoff,
            )
            == []
        )
        with pytest.raises(DataModelError, match="no prediction existed"):
            latest_unambiguous_prediction(
                session,
                fixture_id=draft_fixture,
                team_id=draft_team,
                model_version_sha256=prediction["model_version_sha256"],
                cutoff=cutoff,
            )
        complete = get_prediction_run(session, signature)
        assert complete["prediction_run_id"] == complete_id
        assert complete["core_state"] == "COMPLETE"
        assert complete["final_output_state"] == "DRAFT"
        assert "final_players" not in complete
