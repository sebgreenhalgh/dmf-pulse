"""Explicit-session PostgreSQL persistence for MIN-007F availability outputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dmf_pulse.availability.registry import (
    canonical_semantic_sha256,
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
    prediction_input_signature_sha256,
)
from dmf_pulse.data_model.errors import DataModelError, translate_database_error
from dmf_pulse.data_model.tables import (
    conditional_minute_pmf,
    dataset_training_example,
    dataset_version,
    lineup_scenario,
    lineup_scenario_member,
    model_evaluation,
    model_version,
    player_minutes_projection,
    prediction_dependency,
    prediction_hard_eligibility,
    prediction_run,
    role_marginal,
)


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be a mapping")


def _utc(value: object, *, label: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataModelError(
                "AVAILABILITY_INPUT_INVALID", f"{label} must be RFC3339 UTC"
            ) from exc
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be timezone-aware UTC")
    return value.astimezone(UTC)


def _uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be a UUID") from exc
    raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be a UUID")


def _decimal(value: object, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be an exact Decimal")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (str, int)):
        try:
            result = Decimal(value)
        except Exception as exc:  # pragma: no cover - Decimal exception types vary
            raise DataModelError(
                "AVAILABILITY_INPUT_INVALID", f"{label} must be an exact Decimal"
            ) from exc
    else:
        raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be an exact Decimal")
    if not result.is_finite():
        raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be finite")
    return result


def _validate_scenario_marginal_coherence(
    role_marginals: Sequence[object], scenarios: Sequence[object]
) -> None:
    """Check the complete scenario/marginal player graph before any inserts."""

    marginal_positions: dict[str, str] = {}
    for item in role_marginals:
        value = _mapping(item, label="role marginal")
        player_id = str(value.get("player_id", ""))
        position = str(value.get("position", ""))
        if not player_id or player_id in marginal_positions:
            raise DataModelError(
                "SCENARIO_MARGINAL_COHERENCE", "role marginal player identities are not unique"
            )
        marginal_positions[player_id] = position
    if not marginal_positions:
        if scenarios:
            raise DataModelError("SCENARIO_MARGINAL_COHERENCE", "prediction has no role marginals")
        return
    for item in scenarios:
        scenario = _mapping(item, label="lineup scenario")
        members = scenario.get("members", ())
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
            raise DataModelError(
                "AVAILABILITY_INPUT_INVALID", "scenario members must be a sequence"
            )
        member_positions: dict[str, str] = {}
        for member in members:
            row = _mapping(member, label="scenario member")
            player_id = str(row.get("player_id", ""))
            if not player_id or player_id in member_positions:
                raise DataModelError(
                    "SCENARIO_MARGINAL_COHERENCE", "scenario member identities are not unique"
                )
            member_positions[player_id] = str(row.get("position", ""))
        if set(member_positions) != set(marginal_positions):
            raise DataModelError(
                "SCENARIO_MARGINAL_COHERENCE",
                "scenario member players must equal the role-marginal players",
            )
        if any(
            marginal_positions[player] != position for player, position in member_positions.items()
        ):
            raise DataModelError(
                "SCENARIO_MARGINAL_COHERENCE", "scenario member positions differ from marginals"
            )


def _hash(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise DataModelError("AVAILABILITY_INPUT_INVALID", f"{label} must be a lowercase SHA-256")
    return value


def _semantic_json(value: object) -> object:
    """Convert exact database values to the JSON scalar representation used for hashes."""

    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _semantic_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_semantic_json(item) for item in value]
    return value


def _safe_db_error(error: DBAPIError) -> DataModelError:
    return translate_database_error(error)


def _row_id(session: Session, table: Any, column: Any, statement: Any) -> UUID:
    value = session.execute(statement).scalar_one_or_none()
    if value is None:
        raise DataModelError(
            "DATABASE_RESULT_INVALID", f"{table.name} did not return an identifier"
        )
    if not isinstance(value, UUID):
        raise DataModelError(
            "DATABASE_RESULT_INVALID", f"{table.name} returned an invalid identifier"
        )
    return value


def _dataset_values(dataset: Mapping[str, Any], semantic_hash: str) -> dict[str, Any]:
    return {
        "dataset_semantic_sha256": semantic_hash,
        "dataset_key": str(dataset.get("dataset_key", "")),
        "schema_version": str(dataset.get("schema_version", "minutes-dataset-version-v1")),
        "competition_code": str(dataset.get("competition_code", "")),
        "season_code": str(dataset.get("season_code", "")),
        "training_cutoff": _utc(dataset.get("training_cutoff"), label="training_cutoff"),
        "source_dataset_sha256": (
            _hash(dataset["dataset_sha256"], label="dataset_sha256")
            if dataset.get("dataset_sha256") is not None
            else None
        ),
        "policy_sha256": _hash(dataset.get("policy_sha256"), label="policy_sha256"),
        "declared_training_example_count": int(dataset.get("training_example_count", 0)),
        "publication_state": "DRAFT",
    }


def register_dataset_version(
    session: Session,
    dataset: Mapping[str, Any],
    *,
    training_examples: Sequence[Mapping[str, Any]] | None = None,
    _atomic: bool = True,
) -> UUID:
    """Register one immutable dataset version and its optional complete lineage."""

    if _atomic:
        with session.begin_nested():
            return register_dataset_version(
                session, dataset, training_examples=training_examples, _atomic=False
            )

    value = _mapping(dataset, label="dataset")
    semantic_hash = dataset_version_semantic_sha256(value)
    values = _dataset_values(value, semantic_hash)
    try:
        statement = (
            postgresql_insert(dataset_version)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[dataset_version.c.dataset_semantic_sha256])
            .returning(dataset_version.c.dataset_version_id)
        )
        identifier = session.execute(statement).scalar_one_or_none()
        if identifier is None:
            identifier = session.execute(
                select(dataset_version.c.dataset_version_id).where(
                    dataset_version.c.dataset_semantic_sha256 == semantic_hash
                )
            ).scalar_one()
        if not isinstance(identifier, UUID):
            raise DataModelError("DATABASE_RESULT_INVALID", "dataset version identifier is invalid")
        existing_state = session.execute(
            select(dataset_version.c.publication_state).where(
                dataset_version.c.dataset_version_id == identifier
            )
        ).scalar_one()
        if training_examples is not None:
            if existing_state == "COMPLETE":
                _verify_frozen_training_examples(session, identifier, training_examples)
            else:
                for example in training_examples:
                    _insert_training_example(session, identifier, example)
        expected = int(values["declared_training_example_count"])
        actual = session.execute(
            select(func.count())
            .select_from(dataset_training_example)
            .where(dataset_training_example.c.dataset_version_id == identifier)
        ).scalar_one()
        if expected != int(actual):
            raise DataModelError(
                "DATASET_LINEAGE_INCOMPLETE",
                "dataset lineage count does not match the declared count",
            )
        if existing_state == "DRAFT":
            session.execute(
                dataset_version.update()
                .where(dataset_version.c.dataset_version_id == identifier)
                .values(publication_state="COMPLETE")
            )
        return identifier
    except DataModelError:
        raise
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def _insert_training_example(
    session: Session, dataset_id: UUID, example: Mapping[str, Any]
) -> UUID:
    value = _mapping(example, label="training example")
    lineage_hash = canonical_semantic_sha256(value)
    values = {
        "dataset_version_id": dataset_id,
        "example_id": str(value.get("example_id", "")),
        "fixture_id": str(value.get("fixture_id", "")),
        "fixture_key": str(value.get("fixture_key", value.get("fixture_id", ""))),
        "feature_cutoff": _utc(value.get("feature_cutoff"), label="feature_cutoff"),
        "label_usable_at": _utc(value.get("label_usable_at"), label="label_usable_at"),
        "manager_regime_id": str(value.get("manager_regime_id", "")),
        "minutes_label": int(value.get("minutes_label", -1)),
        "player_id": str(value.get("player_id", "")),
        "player_key": str(value.get("player_key", value.get("player_id", ""))),
        "position": str(value.get("position", "")),
        "role_label": str(value.get("role_label", "")),
        "sequence_index": int(value.get("sequence_index", 0)),
        "split": str(value.get("split", "TRAIN")),
        "team_id": str(value.get("team_id", "")),
        "team_key": str(value.get("team_key", "")),
        "evidence_type": str(value.get("evidence_type", "")),
        "lineage_sha256": lineage_hash,
        "source_lineage": value,
    }
    statement = (
        postgresql_insert(dataset_training_example)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[
                dataset_training_example.c.dataset_version_id,
                dataset_training_example.c.example_id,
            ]
        )
        .returning(dataset_training_example.c.training_example_id)
    )
    identifier = session.execute(statement).scalar_one_or_none()
    if identifier is None:
        existing = session.execute(
            select(
                dataset_training_example.c.training_example_id,
                dataset_training_example.c.lineage_sha256,
            ).where(
                dataset_training_example.c.dataset_version_id == dataset_id,
                dataset_training_example.c.example_id == values["example_id"],
            )
        ).one()
        if existing.lineage_sha256 != lineage_hash:
            raise DataModelError(
                "DATASET_LINEAGE_COLLISION", "training example identity has different lineage"
            )
        identifier = existing.training_example_id
    if not isinstance(identifier, UUID):
        raise DataModelError("DATABASE_RESULT_INVALID", "training example identifier is invalid")
    return identifier


def _verify_frozen_training_examples(
    session: Session, dataset_id: UUID, examples: Sequence[Mapping[str, Any]]
) -> None:
    """Verify an exact replay without attempting to mutate frozen lineage."""

    for example in examples:
        value = _mapping(example, label="training example")
        example_id = str(value.get("example_id", ""))
        row = session.execute(
            select(dataset_training_example.c.lineage_sha256).where(
                dataset_training_example.c.dataset_version_id == dataset_id,
                dataset_training_example.c.example_id == example_id,
            )
        ).scalar_one_or_none()
        if row is None or row != canonical_semantic_sha256(value):
            raise DataModelError(
                "DATASET_LINEAGE_COLLISION", "completed dataset lineage differs from replay"
            )


def register_model_version(
    session: Session,
    model: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any] | None = None,
    _atomic: bool = True,
) -> UUID:
    """Register one immutable model artifact version bound to a dataset hash."""

    if _atomic:
        with session.begin_nested():
            return register_model_version(session, model, artifact=artifact, _atomic=False)

    value = _mapping(model, label="model")
    semantic_hash = model_version_semantic_sha256(value)
    values = {
        "model_semantic_sha256": semantic_hash,
        "model_key": str(value.get("model_key", "")),
        "schema_version": str(value.get("schema_version", "minutes-model-version-v1")),
        "dataset_version_sha256": _hash(
            value.get("dataset_version_sha256"), label="dataset_version_sha256"
        ),
        "role_artifact_sha256": _hash(
            value.get("role_artifact_sha256"), label="role_artifact_sha256"
        ),
        "minute_artifact_sha256": _hash(
            value.get("minute_artifact_sha256"), label="minute_artifact_sha256"
        ),
        "policy_sha256": _hash(value.get("policy_sha256"), label="policy_sha256"),
        "model_family": str(value.get("model_family", "")),
        "code_identity": str(value.get("code_identity", "")),
        "artifact": dict(artifact or value.get("artifact", {})),
    }
    try:
        dataset_row = session.execute(
            select(
                dataset_version.c.dataset_version_id,
                dataset_version.c.declared_training_example_count,
                dataset_version.c.publication_state,
            ).where(dataset_version.c.dataset_semantic_sha256 == values["dataset_version_sha256"])
        ).one_or_none()
        if dataset_row is None:
            raise DataModelError("DATASET_NOT_FOUND", "model dataset provenance is not registered")
        if dataset_row.publication_state != "COMPLETE":
            raise DataModelError(
                "DATASET_INCOMPLETE", "model cannot reference draft dataset provenance"
            )
        lineage_count = session.execute(
            select(func.count())
            .select_from(dataset_training_example)
            .where(dataset_training_example.c.dataset_version_id == dataset_row.dataset_version_id)
        ).scalar_one()
        if int(lineage_count) != int(dataset_row.declared_training_example_count):
            raise DataModelError(
                "DATASET_INCOMPLETE", "model cannot reference incomplete dataset provenance"
            )
        identifier = session.execute(
            postgresql_insert(model_version)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[model_version.c.model_semantic_sha256])
            .returning(model_version.c.model_version_id)
        ).scalar_one_or_none()
        if identifier is None:
            existing = (
                session.execute(
                    select(model_version).where(
                        model_version.c.model_semantic_sha256 == semantic_hash
                    )
                )
                .mappings()
                .one()
            )
            for field in (
                "model_key",
                "schema_version",
                "dataset_version_sha256",
                "role_artifact_sha256",
                "minute_artifact_sha256",
                "policy_sha256",
                "model_family",
                "code_identity",
            ):
                if existing[field] != values[field]:
                    raise DataModelError(
                        "MODEL_IDENTITY_COLLISION",
                        "model identity maps to different semantic fields",
                    )
            if canonical_semantic_sha256(
                _semantic_json(existing["artifact"])
            ) != canonical_semantic_sha256(_semantic_json(values["artifact"])):
                raise DataModelError(
                    "MODEL_IDENTITY_COLLISION", "model identity maps to different artifact content"
                )
            identifier = existing["model_version_id"]
        if not isinstance(identifier, UUID):
            raise DataModelError("DATABASE_RESULT_INVALID", "model version identifier is invalid")
        return identifier
    except DataModelError:
        raise
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def register_model_evaluation(
    session: Session,
    model_version_id: UUID,
    evaluation: object,
    *,
    status: str = "COMPLETE",
) -> UUID:
    """Register one immutable synthetic evaluation result."""

    try:
        from dmf_pulse.availability.pipeline import ModelEvaluationPublication
    except ImportError as exc:  # pragma: no cover - package import invariant
        raise DataModelError("EVALUATION_INVALID", "evaluation contract is unavailable") from exc
    if not isinstance(evaluation, ModelEvaluationPublication):
        raise DataModelError(
            "EVALUATION_PROVENANCE_REQUIRED",
            "evaluation persistence requires a model-bound publication envelope",
        )
    value = evaluation.evaluation.model_dump(mode="json")
    evaluated_model_sha = _hash(
        evaluation.model_version_semantic_sha256, label="evaluated model semantic sha256"
    )
    evaluated_artifact_sha = _hash(
        evaluation.model_artifact_sha256, label="evaluated model artifact sha256"
    )
    evaluated_family = evaluation.model_family
    semantic_hash = canonical_semantic_sha256(value)
    if status not in {"PENDING", "COMPLETE", "BLOCKED"}:
        raise DataModelError("EVALUATION_STATUS_INVALID", "evaluation status is invalid")
    try:
        target = (
            session.execute(
                select(model_version).where(model_version.c.model_version_id == model_version_id)
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            raise DataModelError("EVALUATION_MODEL_NOT_FOUND", "evaluation model is not registered")
        artifact = target["artifact"]
        expected_artifact = (
            artifact.get("artifact_sha256") if isinstance(artifact, Mapping) else None
        )
        if (
            evaluated_model_sha != target["model_semantic_sha256"]
            or evaluated_artifact_sha != expected_artifact
            or evaluated_family != target["model_family"]
        ):
            raise DataModelError(
                "EVALUATION_PROVENANCE_MISMATCH",
                "evaluation provenance does not bind to the target model",
            )
        identifier = session.execute(
            postgresql_insert(model_evaluation)
            .values(
                model_version_id=model_version_id,
                evaluation_semantic_sha256=semantic_hash,
                evaluated_model_semantic_sha256=evaluated_model_sha,
                evaluated_model_artifact_sha256=evaluated_artifact_sha,
                evaluated_model_family=evaluated_family,
                status=status,
                evaluation=value,
            )
            .on_conflict_do_nothing(index_elements=[model_evaluation.c.evaluation_semantic_sha256])
            .returning(model_evaluation.c.model_evaluation_id)
        ).scalar_one_or_none()
        if identifier is None:
            existing = (
                session.execute(
                    select(model_evaluation).where(
                        model_evaluation.c.evaluation_semantic_sha256 == semantic_hash
                    )
                )
                .mappings()
                .one()
            )
            if existing["model_version_id"] != model_version_id:
                raise DataModelError(
                    "EVALUATION_MODEL_CONFLICT", "evaluation identity is bound to another model"
                )
            if (
                existing["status"] != status
                or existing["evaluated_model_semantic_sha256"] != evaluated_model_sha
                or existing["evaluated_model_artifact_sha256"] != evaluated_artifact_sha
                or existing["evaluated_model_family"] != evaluated_family
                or canonical_semantic_sha256(existing["evaluation"]) != semantic_hash
            ):
                raise DataModelError(
                    "EVALUATION_CONFLICT", "evaluation identity has different status or content"
                )
            identifier = existing["model_evaluation_id"]
        if not isinstance(identifier, UUID):
            raise DataModelError("DATABASE_RESULT_INVALID", "evaluation identifier is invalid")
        return identifier
    except DataModelError:
        raise
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def _prediction_output_hash(
    prediction: Mapping[str, Any],
    role_marginals: Sequence[object],
    minute_pmfs: Sequence[object],
    scenarios: Sequence[object],
    final_projection: object | None = None,
) -> str:
    output: dict[str, Any] = {
        "role_marginals": [_mapping(value, label="role marginal") for value in role_marginals],
        "minute_pmfs": [_mapping(value, label="minute PMF") for value in minute_pmfs],
        "scenarios": [_mapping(value, label="scenario") for value in scenarios],
    }
    if final_projection is not None:
        output["final_projection"] = _mapping(final_projection, label="final projection")
    return canonical_semantic_sha256(_semantic_json(output))


def _persisted_core_payload(session: Session, prediction_run_id: UUID) -> dict[str, Any]:
    """Reconstruct the canonical core identity from rows actually persisted."""

    marginals = [
        {
            "player_id": row.player_id,
            "player_key": row.player_key,
            "position": row.position,
            "p_start": row.p_start,
            "p_bench": row.p_bench,
            "p_out": row.p_out,
        }
        for row in session.execute(
            select(role_marginal)
            .where(role_marginal.c.prediction_run_id == prediction_run_id)
            .order_by(role_marginal.c.role_marginal_id)
        ).mappings()
    ]
    pmfs = [
        {"player_id": row.player_id, "role": row.role, "minute_pmf": row.minute_pmf}
        for row in session.execute(
            select(conditional_minute_pmf)
            .where(conditional_minute_pmf.c.prediction_run_id == prediction_run_id)
            .order_by(conditional_minute_pmf.c.conditional_minute_pmf_id)
        ).mappings()
    ]
    scenarios: list[dict[str, Any]] = []
    for scenario in session.execute(
        select(lineup_scenario)
        .where(lineup_scenario.c.prediction_run_id == prediction_run_id)
        .order_by(lineup_scenario.c.scenario_index)
    ).mappings():
        scenarios.append(
            {
                "scenario_index": scenario["scenario_index"],
                "scenario_sha256": scenario["scenario_sha256"],
                "members": [
                    {
                        "player_id": member.player_id,
                        "role": member.role,
                        "position": member.position,
                    }
                    for member in session.execute(
                        select(lineup_scenario_member)
                        .where(
                            lineup_scenario_member.c.lineup_scenario_id
                            == scenario["lineup_scenario_id"]
                        )
                        .order_by(lineup_scenario_member.c.lineup_scenario_member_id)
                    ).mappings()
                ],
            }
        )
    return _canonical_core_payload(marginals, pmfs, scenarios)


def _canonical_core_payload(
    marginals: Sequence[object], pmfs: Sequence[object], scenarios: Sequence[object]
) -> dict[str, Any]:
    """Canonicalise core rows independently of database-generated UUID order."""

    marginal_rows = [
        {
            key: _mapping(item, label="role marginal")[key]
            for key in ("player_id", "player_key", "position", "p_start", "p_bench", "p_out")
        }
        for item in marginals
    ]
    pmf_rows = [
        {
            key: _mapping(item, label="minute PMF")[key]
            for key in ("player_id", "role", "minute_pmf")
        }
        for item in pmfs
    ]
    for row in marginal_rows:
        for field in ("p_start", "p_bench", "p_out"):
            if field in row:
                row[field] = _decimal(row[field], label=field)
    for row in pmf_rows:
        if "minute_pmf" in row:
            row["minute_pmf"] = [
                _decimal(item, label="minute PMF value") for item in row["minute_pmf"]
            ]
    scenario_rows: list[dict[str, Any]] = []
    for item in scenarios:
        source = _mapping(item, label="scenario")
        scenario = {
            "scenario_index": source["scenario_index"],
            "scenario_sha256": source["scenario_sha256"],
        }
        members = source.get("members", [])
        member_rows = [
            {
                key: _mapping(member, label="scenario member")[key]
                for key in ("player_id", "role", "position")
            }
            for member in members
        ]
        member_rows.sort(
            key=lambda row: (
                {"START": 0, "BENCH": 1, "OUT": 2}.get(str(row.get("role", "")), 9),
                str(row.get("player_id", "")),
            )
        )
        scenario_rows.append({**scenario, "members": member_rows})
    marginal_rows.sort(key=lambda row: str(row.get("player_id", "")))
    pmf_rows.sort(key=lambda row: (str(row.get("player_id", "")), str(row.get("role", ""))))
    scenario_rows.sort(key=lambda row: int(row.get("scenario_index", -1)))
    return {
        "role_marginals": _semantic_json(marginal_rows),
        "minute_pmfs": _semantic_json(pmf_rows),
        "scenarios": _semantic_json(scenario_rows),
    }


def _core_output_hash(payload: Mapping[str, Any], final: object | None = None) -> str:
    return canonical_semantic_sha256(
        _semantic_json(
            {
                "role_marginals": payload.get("role_marginals", []),
                "minute_pmfs": payload.get("minute_pmfs", []),
                "scenarios": payload.get("scenarios", []),
                **(
                    {"final_projection": _mapping(final, label="final projection")}
                    if final is not None
                    else {}
                ),
            }
        )
    )


def register_prediction_bundle(
    session: Session,
    prediction: Mapping[str, Any],
    *,
    role_marginals: Sequence[object] | None = None,
    minute_pmfs: Sequence[object] | None = None,
    scenarios: Sequence[object] | None = None,
    hard_eligibility: Sequence[object] | None = None,
    final_projection: object | None = None,
    _atomic: bool = True,
) -> UUID:
    """Publish one complete immutable prediction graph in the caller's transaction."""

    if _atomic:
        with session.begin_nested():
            return register_prediction_bundle(
                session,
                prediction,
                role_marginals=role_marginals,
                minute_pmfs=minute_pmfs,
                scenarios=scenarios,
                hard_eligibility=hard_eligibility,
                final_projection=final_projection,
                _atomic=False,
            )

    value = _mapping(prediction, label="prediction")
    marginal_values = tuple(role_marginals or value.get("role_marginals", ()))
    pmf_values = tuple(minute_pmfs or value.get("minute_pmfs", ()))
    scenario_values = tuple(scenarios or value.get("scenarios", ()))
    hard_values = tuple(
        value.get("hard_eligibility", ()) if hard_eligibility is None else hard_eligibility
    )
    # Explicit hard-eligibility rows are part of the input identity.  Allow
    # callers to supply them separately from the prediction envelope while
    # retaining the frozen canary hash when the envelope already carries the
    # same field.
    signature_value = value
    if hard_eligibility is not None:
        signature_value = {**value, "hard_eligibility": list(hard_values)}
    signature = prediction_input_signature_sha256(signature_value)
    core_input_payload = _canonical_core_payload(marginal_values, pmf_values, scenario_values)
    output_hash = _core_output_hash(core_input_payload, final_projection)
    declared_output_hash = value.get("output_semantic_sha256")
    if (
        declared_output_hash is not None
        and _hash(declared_output_hash, label="output_semantic_sha256") != output_hash
    ):
        raise DataModelError(
            "OUTPUT_IDENTITY_MISMATCH", "declared output identity does not match supplied bundle"
        )
    model_hash = value.get("model_version_sha256", value.get("model_semantic_sha256"))
    dataset_hash = value.get("dataset_version_sha256", value.get("dataset_semantic_sha256"))
    manager_context = _mapping(value.get("manager_context", {}), label="manager_context")
    run_values = {
        "prediction_input_signature_sha256": signature,
        "output_semantic_sha256": output_hash,
        "fixture_id": _uuid(value.get("fixture_id"), label="fixture_id"),
        "team_id": _uuid(value.get("team_id"), label="team_id"),
        "as_of": _utc(value.get("as_of"), label="as_of"),
        "feature_cutoff": _utc(value["feature_cutoff"], label="feature_cutoff")
        if value.get("feature_cutoff") is not None
        else None,
        "model_version_sha256": _hash(model_hash, label="model_version_sha256"),
        "dataset_version_sha256": _hash(dataset_hash, label="dataset_version_sha256"),
        "policy_sha256": _hash(value.get("policy_sha256"), label="policy_sha256"),
        "manager_regime_id": str(
            value.get("manager_regime_id", manager_context.get("manager_regime_id", ""))
        ),
        "manager_context": manager_context,
        "seed": str(value.get("seed", "")),
        "sample_count": int(value.get("sample_count", 0)),
        "dependency_count": len(value.get("source_dependencies", ())),
        "hard_eligibility_count": len(hard_values),
        "role_marginal_count": len(marginal_values),
        "minute_pmf_count": len(pmf_values),
        "scenario_count": len(scenario_values),
        "core_state": "DRAFT",
        "final_output_state": "NONE",
        "final_output_count": 0,
        "bench_size": int(value.get("bench_size", 0)),
        "bench_goalkeeper_slots": int(value.get("bench_goalkeeper_slots", 0)),
        "code_identity": str(value.get("code_identity", "")),
    }
    _validate_scenario_marginal_coherence(marginal_values, scenario_values)
    try:
        identifier = session.execute(
            postgresql_insert(prediction_run)
            .values(**run_values)
            .on_conflict_do_nothing(
                index_elements=[prediction_run.c.prediction_input_signature_sha256]
            )
            .returning(prediction_run.c.prediction_run_id)
        ).scalar_one_or_none()
        if identifier is None:
            existing = session.execute(
                select(
                    prediction_run.c.prediction_run_id, prediction_run.c.output_semantic_sha256
                ).where(prediction_run.c.prediction_input_signature_sha256 == signature)
            ).one()
            if existing.output_semantic_sha256 != output_hash:
                if final_projection is not None and isinstance(existing.prediction_run_id, UUID):
                    register_final_player_projections(
                        session, existing.prediction_run_id, final_projection
                    )
                raise DataModelError(
                    "PREDICTION_SIGNATURE_COLLISION",
                    "prediction signature maps to a different output",
                )
            if not isinstance(existing.prediction_run_id, UUID):
                raise DataModelError(
                    "DATABASE_RESULT_INVALID", "prediction run identifier is invalid"
                )
            return existing.prediction_run_id
        if not isinstance(identifier, UUID):
            raise DataModelError("DATABASE_RESULT_INVALID", "prediction run identifier is invalid")
        dependencies = value.get("source_dependencies", ())
        for ordinal, dependency in enumerate(dependencies):
            item = _mapping(dependency, label="prediction dependency")
            session.execute(
                insert(prediction_dependency).values(
                    prediction_run_id=identifier,
                    dependency_type=str(item.get("dependency_type", "")),
                    dependency_key=str(item.get("dependency_key", "")),
                    semantic_sha256=_hash(
                        item.get("semantic_sha256"), label="dependency semantic_sha256"
                    ),
                    ordinal=ordinal,
                )
            )
        for item in hard_values:
            raw = (
                _mapping(item, label="hard eligibility")
                if not isinstance(item, str)
                else {"player_id": item}
            )
            session.execute(
                insert(prediction_hard_eligibility).values(
                    prediction_run_id=identifier,
                    player_id=str(raw.get("player_id", "")),
                    reason=str(raw.get("reason", "")),
                    hard_ineligible=bool(raw.get("hard_ineligible", True)),
                )
            )
        for item in marginal_values:
            raw = _mapping(item, label="role marginal")
            session.execute(
                insert(role_marginal).values(
                    prediction_run_id=identifier,
                    player_id=str(raw.get("player_id", "")),
                    player_key=str(raw.get("player_key", "")),
                    position=str(raw.get("position", "")),
                    p_start=_decimal(raw.get("p_start"), label="p_start"),
                    p_bench=_decimal(raw.get("p_bench"), label="p_bench"),
                    p_out=_decimal(raw.get("p_out"), label="p_out"),
                )
            )
        for item in pmf_values:
            raw = _mapping(item, label="minute PMF")
            pmf = raw.get("minute_pmf", raw.get("pmf"))
            if not isinstance(pmf, Sequence) or isinstance(pmf, (str, bytes, bytearray)):
                raise DataModelError("AVAILABILITY_INPUT_INVALID", "minute PMF must be a sequence")
            session.execute(
                insert(conditional_minute_pmf).values(
                    prediction_run_id=identifier,
                    player_id=str(raw.get("player_id", "")),
                    role=str(raw.get("role", "")),
                    minute_pmf=[_decimal(entry, label="minute PMF value") for entry in pmf],
                )
            )
        for item in scenario_values:
            raw = _mapping(item, label="lineup scenario")
            scenario_id = session.execute(
                insert(lineup_scenario)
                .values(
                    prediction_run_id=identifier,
                    scenario_index=int(raw.get("scenario_index", -1)),
                    scenario_sha256=_hash(raw.get("scenario_sha256"), label="scenario_sha256"),
                )
                .returning(lineup_scenario.c.lineup_scenario_id)
            ).scalar_one()
            members = raw.get("members", ())
            if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
                raise DataModelError(
                    "AVAILABILITY_INPUT_INVALID", "scenario members must be a sequence"
                )
            for member in members:
                row = _mapping(member, label="scenario member")
                session.execute(
                    insert(lineup_scenario_member).values(
                        lineup_scenario_id=scenario_id,
                        prediction_run_id=identifier,
                        player_id=str(row.get("player_id", "")),
                        role=str(row.get("role", "")),
                        position=str(row.get("position", "")),
                    )
                )
        core_payload = _persisted_core_payload(session, identifier)
        actual_core_hash = _core_output_hash(core_payload)
        if actual_core_hash != _core_output_hash(core_input_payload):
            raise DataModelError(
                "OUTPUT_IDENTITY_MISMATCH",
                "persisted core identity differs from input",
            )
        session.execute(
            prediction_run.update()
            .where(prediction_run.c.prediction_run_id == identifier)
            .values(core_state="COMPLETE", core_output_payload=core_payload)
        )
        if final_projection is not None:
            register_final_player_projections(session, identifier, final_projection)
        return identifier
    except DataModelError:
        raise
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def register_final_player_projections(
    session: Session, prediction_run_id: UUID, projection: object, *, _atomic: bool = True
) -> None:
    """Persist the MIN-007G public player mixture in the F reserved table."""

    if _atomic:
        with session.begin_nested():
            register_final_player_projections(session, prediction_run_id, projection, _atomic=False)
        return

    value = _mapping(projection, label="final projection")
    players = value.get("players", ())
    if not isinstance(players, Sequence) or isinstance(players, (str, bytes, bytearray)):
        raise DataModelError("AVAILABILITY_INPUT_INVALID", "final projection players are invalid")
    run = (
        session.execute(
            select(prediction_run).where(prediction_run.c.prediction_run_id == prediction_run_id)
        )
        .mappings()
        .one_or_none()
    )
    if run is None:
        raise DataModelError("FINAL_PROJECTION_RUN_NOT_FOUND", "prediction run is not registered")
    if run["core_state"] != "COMPLETE":
        raise DataModelError("FINAL_PROJECTION_RUN_INCOMPLETE", "prediction core is not complete")
    final_hash = canonical_semantic_sha256(_semantic_json(value))
    if run["final_output_state"] == "COMPLETE":
        if (
            run["final_output_semantic_sha256"] != final_hash
            or canonical_semantic_sha256(_semantic_json(run["final_output_payload"] or {}))
            != final_hash
        ):
            raise DataModelError(
                "FINAL_OUTPUT_COLLISION", "final output identity maps to different content"
            )
        return
    if run["final_output_state"] != "NONE":
        raise DataModelError(
            "FINAL_OUTPUT_STATE_INVALID", "final output lifecycle state is invalid"
        )
    graph_counts = {
        "dependency_count": session.scalar(
            select(func.count())
            .select_from(prediction_dependency)
            .where(prediction_dependency.c.prediction_run_id == prediction_run_id)
        ),
        "hard_eligibility_count": session.scalar(
            select(func.count())
            .select_from(prediction_hard_eligibility)
            .where(prediction_hard_eligibility.c.prediction_run_id == prediction_run_id)
        ),
        "role_marginal_count": session.scalar(
            select(func.count())
            .select_from(role_marginal)
            .where(role_marginal.c.prediction_run_id == prediction_run_id)
        ),
        "minute_pmf_count": session.scalar(
            select(func.count())
            .select_from(conditional_minute_pmf)
            .where(conditional_minute_pmf.c.prediction_run_id == prediction_run_id)
        ),
        "scenario_count": session.scalar(
            select(func.count())
            .select_from(lineup_scenario)
            .where(lineup_scenario.c.prediction_run_id == prediction_run_id)
        ),
    }
    if (
        any(
            int(graph_counts[key] or 0) != int(run[key])
            for key in (
                "dependency_count",
                "hard_eligibility_count",
                "role_marginal_count",
                "minute_pmf_count",
                "scenario_count",
            )
        )
        or int(graph_counts["role_marginal_count"] or 0) == 0
    ):
        raise DataModelError(
            "FINAL_PROJECTION_RUN_INCOMPLETE", "final projection requires a complete run"
        )
    fixture_id = _uuid(value.get("fixture_id"), label="final projection fixture_id")
    team_id = _uuid(value.get("team_id"), label="final projection team_id")
    as_of = _utc(value.get("as_of"), label="final projection as_of")
    if fixture_id != run["fixture_id"] or team_id != run["team_id"] or as_of != run["as_of"]:
        raise DataModelError(
            "FINAL_PROJECTION_RUN_MISMATCH", "final projection team identity differs from run"
        )
    dataset_row = (
        session.execute(
            select(
                dataset_version.c.source_dataset_sha256,
                dataset_version.c.dataset_semantic_sha256,
            ).where(dataset_version.c.dataset_semantic_sha256 == run["dataset_version_sha256"])
        )
        .mappings()
        .one_or_none()
    )
    if dataset_row is None:
        raise DataModelError("FINAL_PROJECTION_DATASET_MISMATCH", "run dataset is not registered")
    expected_dataset = (
        dataset_row["source_dataset_sha256"] or dataset_row["dataset_semantic_sha256"]
    )
    if str(value.get("dataset_sha256", "")) != str(expected_dataset):
        raise DataModelError(
            "FINAL_PROJECTION_DATASET_MISMATCH", "final projection dataset differs from run"
        )
    model = (
        session.execute(
            select(model_version.c.artifact, model_version.c.model_family).where(
                model_version.c.model_semantic_sha256 == run["model_version_sha256"]
            )
        )
        .mappings()
        .one_or_none()
    )
    if model is None or not isinstance(model["artifact"], Mapping):
        raise DataModelError("FINAL_PROJECTION_MODEL_MISMATCH", "run model is not registered")
    expected_artifact = model["artifact"].get("artifact_sha256")
    if str(value.get("model_artifact_sha256", "")) != str(expected_artifact):
        raise DataModelError(
            "FINAL_PROJECTION_MODEL_MISMATCH", "final projection artifact differs from run model"
        )
    if str(value.get("model_family", "")) != str(model["model_family"]):
        raise DataModelError(
            "FINAL_PROJECTION_MODEL_MISMATCH", "final projection model family differs from run"
        )
    marginals = session.execute(
        select(role_marginal.c.player_id, role_marginal.c.position).where(
            role_marginal.c.prediction_run_id == prediction_run_id
        )
    ).all()
    marginal_positions = {str(row.player_id): str(row.position) for row in marginals}
    if len(marginal_positions) != len(marginals):
        raise DataModelError("FINAL_PROJECTION_PLAYER_MISMATCH", "run marginals contain duplicates")
    player_positions: dict[str, str] = {}
    for item in players:
        player = _mapping(item, label="final player projection")
        player_id = str(player.get("player_id", ""))
        if not player_id or player_id in player_positions:
            raise DataModelError("FINAL_PROJECTION_PLAYER_MISMATCH", "final players are not unique")
        player_positions[player_id] = str(player.get("position", ""))
    if set(player_positions) != set(marginal_positions):
        raise DataModelError(
            "FINAL_PROJECTION_PLAYER_MISMATCH", "final players must equal run role marginals"
        )
    if any(marginal_positions[player] != position for player, position in player_positions.items()):
        raise DataModelError(
            "FINAL_PROJECTION_PLAYER_MISMATCH", "final player positions differ from marginals"
        )
    try:
        session.execute(
            prediction_run.update()
            .where(prediction_run.c.prediction_run_id == prediction_run_id)
            .values(final_output_state="DRAFT")
        )
        for item in players:
            player = _mapping(item, label="final player projection")
            pmf = player.get("minute_pmf")
            if not isinstance(pmf, Sequence) or isinstance(pmf, (str, bytes, bytearray)):
                raise DataModelError("AVAILABILITY_INPUT_INVALID", "final minute PMF is invalid")
            confidence_reasons = player.get("confidence_reasons")
            if not isinstance(confidence_reasons, Sequence) or isinstance(
                confidence_reasons, (str, bytes, bytearray)
            ):
                raise DataModelError(
                    "AVAILABILITY_INPUT_INVALID", "final confidence reasons are invalid"
                )
            session.execute(
                postgresql_insert(player_minutes_projection)
                .values(
                    prediction_run_id=prediction_run_id,
                    player_id=str(player.get("player_id", "")),
                    position=str(player.get("position", "")),
                    p_start=_decimal(player.get("p_start"), label="p_start"),
                    p_bench=_decimal(player.get("p_bench"), label="p_bench"),
                    p_out=_decimal(player.get("p_out_of_squad"), label="p_out_of_squad"),
                    minute_pmf=[_decimal(entry, label="minute PMF") for entry in pmf],
                    p_zero=_decimal(player.get("p_zero_minutes"), label="p_zero_minutes"),
                    p_60_plus=_decimal(player.get("p_60_plus"), label="p_60_plus"),
                    expected_minutes=_decimal(
                        player.get("expected_minutes"), label="expected_minutes"
                    ),
                    confidence_grade=str(player.get("confidence_grade", "")),
                    confidence_reasons=[str(reason) for reason in confidence_reasons],
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        player_minutes_projection.c.prediction_run_id,
                        player_minutes_projection.c.player_id,
                    ]
                )
            )
        persisted_final_count = int(
            session.scalar(
                select(func.count())
                .select_from(player_minutes_projection)
                .where(player_minutes_projection.c.prediction_run_id == prediction_run_id)
            )
            or 0
        )
        if persisted_final_count != len(players):
            raise DataModelError("FINAL_OUTPUT_COLLISION", "persisted final row count differs")
        core_payload = run["core_output_payload"]
        if not isinstance(core_payload, Mapping):
            core_payload = _persisted_core_payload(session, prediction_run_id)
        combined_hash = _core_output_hash(core_payload, value)
        session.execute(
            prediction_run.update()
            .where(prediction_run.c.prediction_run_id == prediction_run_id)
            .values(
                final_output_state="COMPLETE",
                final_output_count=persisted_final_count,
                final_output_semantic_sha256=final_hash,
                final_output_payload=_semantic_json(value),
                output_semantic_sha256=combined_hash,
            )
        )
        # Flush only the final-output validator for immediate feedback.  The
        # scenario/core graph validators are intentionally deferred until the
        # caller's transaction boundary; changing all constraint modes here
        # leaks into unrelated publications in that transaction.
        session.execute(
            text("SET CONSTRAINTS football.trg_min007f_final_output_complete IMMEDIATE")
        )
        session.execute(text("SET CONSTRAINTS football.trg_min007f_final_output_complete DEFERRED"))
    except DataModelError:
        raise
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def get_prediction_run(session: Session, signature: str) -> dict[str, Any]:
    """Return one immutable run and its persisted dependency graph by signature."""

    row = (
        session.execute(
            select(prediction_run).where(
                prediction_run.c.prediction_input_signature_sha256 == signature,
                prediction_run.c.core_state == "COMPLETE",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DataModelError("PREDICTION_NOT_FOUND", "prediction signature was not found")
    result = dict(row)
    run_id = result["prediction_run_id"]
    result["dependencies"] = [
        dict(item)
        for item in session.execute(
            select(prediction_dependency)
            .where(prediction_dependency.c.prediction_run_id == run_id)
            .order_by(prediction_dependency.c.ordinal)
        ).mappings()
    ]
    result["hard_eligibility"] = [
        dict(item)
        for item in session.execute(
            select(prediction_hard_eligibility).where(
                prediction_hard_eligibility.c.prediction_run_id == run_id
            )
        ).mappings()
    ]
    result["role_marginals"] = [
        dict(item)
        for item in session.execute(
            select(role_marginal).where(role_marginal.c.prediction_run_id == run_id)
        ).mappings()
    ]
    result["minute_pmfs"] = [
        dict(item)
        for item in session.execute(
            select(conditional_minute_pmf).where(
                conditional_minute_pmf.c.prediction_run_id == run_id
            )
        ).mappings()
    ]
    scenarios: list[dict[str, Any]] = []
    for scenario in session.execute(
        select(lineup_scenario)
        .where(lineup_scenario.c.prediction_run_id == run_id)
        .order_by(lineup_scenario.c.scenario_index)
    ).mappings():
        value = dict(scenario)
        value["members"] = [
            dict(item)
            for item in session.execute(
                select(lineup_scenario_member).where(
                    lineup_scenario_member.c.lineup_scenario_id == scenario["lineup_scenario_id"]
                )
            ).mappings()
        ]
        scenarios.append(value)
    result["scenarios"] = scenarios
    if result.get("final_output_state") == "COMPLETE":
        result["final_players"] = [
            dict(item)
            for item in session.execute(
                select(player_minutes_projection).where(
                    player_minutes_projection.c.prediction_run_id == run_id
                )
            ).mappings()
        ]
    return result


def list_prediction_runs_as_of(
    session: Session,
    *,
    fixture_id: UUID | str,
    team_id: UUID | str,
    model_version_sha256: str,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """List immutable runs at or before a caller-supplied historical cutoff."""

    rows = session.execute(
        select(prediction_run)
        .where(
            prediction_run.c.fixture_id == _uuid(fixture_id, label="fixture_id"),
            prediction_run.c.team_id == _uuid(team_id, label="team_id"),
            prediction_run.c.model_version_sha256
            == _hash(model_version_sha256, label="model_version_sha256"),
            prediction_run.c.core_state == "COMPLETE",
            prediction_run.c.as_of <= _utc(cutoff, label="cutoff"),
        )
        .order_by(prediction_run.c.as_of.desc(), prediction_run.c.prediction_input_signature_sha256)
    ).mappings()
    return [dict(row) for row in rows]


def latest_unambiguous_prediction(
    session: Session,
    *,
    fixture_id: UUID | str,
    team_id: UUID | str,
    model_version_sha256: str,
    cutoff: datetime,
) -> dict[str, Any]:
    """Resolve the latest historical as-of run, rejecting same-cutoff ambiguity."""

    rows = list_prediction_runs_as_of(
        session,
        fixture_id=fixture_id,
        team_id=team_id,
        model_version_sha256=model_version_sha256,
        cutoff=cutoff,
    )
    if not rows:
        raise DataModelError("AS_OF_NOT_FOUND", "no prediction existed at the requested cutoff")
    latest_as_of = rows[0]["as_of"]
    latest = [row for row in rows if row["as_of"] == latest_as_of]
    signatures = {row["prediction_input_signature_sha256"] for row in latest}
    if len(signatures) != 1:
        raise DataModelError(
            "AMBIGUOUS_HISTORICAL_RUN", "multiple prediction signatures share the latest cutoff"
        )
    return get_prediction_run(session, next(iter(signatures)))


class AvailabilityPersistence:
    """Session-bound facade for the pure registry and immutable bundle operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def register_dataset_version(
        self,
        dataset: Mapping[str, Any],
        *,
        training_examples: Sequence[Mapping[str, Any]] | None = None,
    ) -> UUID:
        return register_dataset_version(self.session, dataset, training_examples=training_examples)

    def register_model_version(
        self, model: Mapping[str, Any], *, artifact: Mapping[str, Any] | None = None
    ) -> UUID:
        return register_model_version(self.session, model, artifact=artifact)

    def register_model_evaluation(
        self, model_version_id: UUID, evaluation: Mapping[str, Any], *, status: str = "COMPLETE"
    ) -> UUID:
        return register_model_evaluation(self.session, model_version_id, evaluation, status=status)

    def register_prediction_bundle(self, prediction: Mapping[str, Any], **parts: Any) -> UUID:
        return register_prediction_bundle(self.session, prediction, **parts)

    def register_final_player_projections(
        self, prediction_run_id: UUID, projection: object
    ) -> None:
        register_final_player_projections(self.session, prediction_run_id, projection)

    def get_prediction_run(self, signature: str) -> dict[str, Any]:
        return get_prediction_run(self.session, signature)

    def list_prediction_runs_as_of(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_prediction_runs_as_of(self.session, **kwargs)

    def latest_unambiguous_prediction(self, **kwargs: Any) -> dict[str, Any]:
        return latest_unambiguous_prediction(self.session, **kwargs)


__all__ = [
    "AvailabilityPersistence",
    "get_prediction_run",
    "latest_unambiguous_prediction",
    "list_prediction_runs_as_of",
    "register_dataset_version",
    "register_final_player_projections",
    "register_model_evaluation",
    "register_model_version",
    "register_prediction_bundle",
]
