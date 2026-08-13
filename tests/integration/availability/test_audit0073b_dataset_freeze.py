from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import register_dataset_version, register_model_version
from dmf_pulse.data_model.tables import dataset_training_example, dataset_version

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _example() -> dict[str, object]:
    return {
        "example_id": "example-1",
        "fixture_id": "fixture-1",
        "fixture_key": "fixture-1",
        "feature_cutoff": "2026-06-01T00:00:00Z",
        "label_usable_at": "2026-06-02T00:00:00Z",
        "manager_regime_id": "regime-1",
        "minutes_label": 90,
        "player_id": "player-1",
        "player_key": "player-1",
        "position": "MID",
        "role_label": "START",
        "sequence_index": 1,
        "split": "TRAIN",
        "team_id": "team-1",
        "team_key": "team-1",
        "evidence_type": "SYNTHETIC",
    }


def test_completed_dataset_lineage_is_frozen(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
) -> None:
    value = {**dataset, "training_example_count": 1}
    example = _example()
    with postgres_session_factory.begin() as session:
        dataset_id = register_dataset_version(session, value, training_examples=[example])
        state = session.scalar(
            select(dataset_version.c.publication_state).where(
                dataset_version.c.dataset_version_id == dataset_id
            )
        )
        assert state == "COMPLETE"
        register_model_version(session, {**model, "dataset_version_sha256": value_hash(value)})
        for statement in (
            insert(dataset_training_example).values(
                dataset_version_id=dataset_id,
                example_id="rogue",
                fixture_id="fixture-rogue",
                fixture_key="fixture-rogue",
                feature_cutoff=datetime(2026, 6, 1, tzinfo=UTC),
                label_usable_at=datetime(2026, 6, 2, tzinfo=UTC),
                manager_regime_id="regime-1",
                minutes_label=90,
                player_id="player-rogue",
                player_key="player-rogue",
                position="MID",
                role_label="START",
                sequence_index=2,
                split="TRAIN",
                team_id="team-1",
                team_key="team-1",
                evidence_type="SYNTHETIC",
                lineage_sha256="a" * 64,
                source_lineage={},
            ),
            update(dataset_training_example)
            .where(dataset_training_example.c.dataset_version_id == dataset_id)
            .values(evidence_type="MUTATED"),
            delete(dataset_training_example).where(
                dataset_training_example.c.dataset_version_id == dataset_id
            ),
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(statement)


def value_hash(value: dict[str, object]) -> str:
    from dmf_pulse.availability.registry import dataset_version_semantic_sha256

    return dataset_version_semantic_sha256(value)
