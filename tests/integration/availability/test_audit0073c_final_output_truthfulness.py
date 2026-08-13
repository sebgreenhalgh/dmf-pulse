"""Adversarial database proofs for truthful MIN-007 finalisation."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.availability.persistence import (
    _core_output_hash,
    register_dataset_version,
    register_model_version,
    register_prediction_bundle,
)
from dmf_pulse.availability.projection import canonical_sha256
from dmf_pulse.availability.registry import canonical_semantic_sha256
from dmf_pulse.data_model.tables import player_minutes_projection, prediction_run

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _with_result_hash(value: dict[str, object]) -> dict[str, object]:
    body = {key: item for key, item in value.items() if key != "result_sha256"}
    return {**body, "result_sha256": canonical_sha256(body)}


def _with_player_hashes(value: dict[str, object]) -> dict[str, object]:
    players: list[dict[str, object]] = []
    for item in value["players"]:  # type: ignore[index]
        player = {key: raw for key, raw in item.items() if key != "projection_sha256"}
        players.append({**player, "projection_sha256": canonical_sha256(player)})
    return _with_result_hash({**value, "players": players})


def _output_hash(core: dict[str, object], final: dict[str, object]) -> str:
    return _core_output_hash(core, final)


def _insert_actual_final_rows(session: Session, run_id: object, final: dict[str, object]) -> None:
    for player in final["players"]:  # type: ignore[index]
        session.execute(
            insert(player_minutes_projection).values(
                prediction_run_id=run_id,
                player_id=player["player_id"],
                position=player["position"],
                p_start=Decimal(player["p_start"]),
                p_bench=Decimal(player["p_bench"]),
                p_out=Decimal(player["p_out_of_squad"]),
                minute_pmf=[Decimal(item) for item in player["minute_pmf"]],
                p_zero=Decimal(player["p_zero_minutes"]),
                p_60_plus=Decimal(player["p_60_plus"]),
                expected_minutes=Decimal(player["expected_minutes"]),
                confidence_grade=player["confidence_grade"],
                confidence_reasons=player["confidence_reasons"],
            )
        )


def _complete(
    session: Session,
    run_id: object,
    core: dict[str, object],
    final: dict[str, object],
    *,
    output_hash: str | None = None,
) -> None:
    session.execute(
        update(prediction_run)
        .where(prediction_run.c.prediction_run_id == run_id)
        .values(
            final_output_state="COMPLETE",
            final_output_count=len(final["players"]),  # type: ignore[arg-type]
            final_output_semantic_sha256=canonical_semantic_sha256(final),
            final_output_payload=final,
            output_semantic_sha256=output_hash or _output_hash(core, final),
        )
    )
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_direct_sql_finalisation_is_derived_from_durable_rows(
    postgres_session_factory: sessionmaker[Session],
    dataset: dict[str, object],
    model: dict[str, object],
    prediction: dict[str, object],
    bundle_parts: dict[str, list[dict[str, object]]],
    final_projection: dict[str, object],
) -> None:
    with postgres_session_factory.begin() as session:
        register_dataset_version(session, dataset)
        register_model_version(session, model, artifact={"artifact_sha256": "c" * 64})
        run_id = register_prediction_bundle(session, prediction, **bundle_parts)
        core = dict(
            session.execute(
                select(prediction_run.c.core_output_payload).where(
                    prediction_run.c.prediction_run_id == run_id
                )
            ).scalar_one()
        )
        session.execute(
            update(prediction_run)
            .where(prediction_run.c.prediction_run_id == run_id)
            .values(final_output_state="DRAFT")
        )
        _insert_actual_final_rows(session, run_id, final_projection)

        wrong_position = deepcopy(final_projection)
        wrong_position["players"][0]["position"] = "FWD"  # type: ignore[index]
        wrong_position = _with_player_hashes(wrong_position)

        wrong_expected = deepcopy(final_projection)
        wrong_expected["players"][0]["expected_minutes"] = "1.000000"  # type: ignore[index]
        wrong_expected = _with_player_hashes(wrong_expected)

        wrong_player_hash = deepcopy(final_projection)
        wrong_player_hash["players"][0]["projection_sha256"] = "0" * 64  # type: ignore[index]
        wrong_player_hash = _with_result_hash(wrong_player_hash)

        wrong_result_hash = deepcopy(final_projection)
        wrong_result_hash["result_sha256"] = "0" * 64

        wrong_position_prediction = {**prediction, "seed": "wrong-persisted-position"}
        wrong_position_run_id = register_prediction_bundle(
            session, wrong_position_prediction, **bundle_parts
        )
        session.execute(
            update(prediction_run)
            .where(prediction_run.c.prediction_run_id == wrong_position_run_id)
            .values(final_output_state="DRAFT")
        )
        _insert_actual_final_rows(session, wrong_position_run_id, wrong_position)
        wrong_position_core = dict(
            session.execute(
                select(prediction_run.c.core_output_payload).where(
                    prediction_run.c.prediction_run_id == wrong_position_run_id
                )
            ).scalar_one()
        )
        with pytest.raises(DBAPIError, match="FINAL_OUTPUT_ROW_MISMATCH"), session.begin_nested():
            _complete(session, wrong_position_run_id, wrong_position_core, wrong_position)

        cases = (
            ("FINAL_OUTPUT_PLAYER_PAYLOAD_MISMATCH", wrong_expected, None),
            ("FINAL_OUTPUT_PLAYER_PAYLOAD_MISMATCH", wrong_player_hash, None),
            ("FINAL_OUTPUT_RESULT_HASH_MISMATCH", wrong_result_hash, None),
            ("FINAL_OUTPUT_OUTPUT_HASH_MISMATCH", final_projection, "0" * 64),
        )
        for expected_error, supplied_final, supplied_output_hash in cases:
            with pytest.raises(DBAPIError, match=expected_error), session.begin_nested():
                _complete(
                    session,
                    run_id,
                    core,
                    supplied_final,
                    output_hash=supplied_output_hash,
                )

        _complete(session, run_id, core, final_projection)
        completed = session.execute(
            select(
                prediction_run.c.final_output_state,
                prediction_run.c.final_output_semantic_sha256,
                prediction_run.c.output_semantic_sha256,
            ).where(prediction_run.c.prediction_run_id == run_id)
        ).one()
        assert completed == (
            "COMPLETE",
            canonical_semantic_sha256(final_projection),
            _output_hash(core, final_projection),
        )
