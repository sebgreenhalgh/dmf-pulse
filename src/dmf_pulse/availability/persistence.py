"""Explicit-session PostgreSQL persistence for MIN-007F availability outputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select
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
        return format(value, "f")
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
    }


def register_dataset_version(
    session: Session,
    dataset: Mapping[str, Any],
    *,
    training_examples: Sequence[Mapping[str, Any]] | None = None,
) -> UUID:
    """Register one immutable dataset version and its optional complete lineage."""

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
        if training_examples is not None:
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


def register_model_version(
    session: Session,
    model: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any] | None = None,
) -> UUID:
    """Register one immutable model artifact version bound to a dataset hash."""

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
        identifier = session.execute(
            postgresql_insert(model_version)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[model_version.c.model_semantic_sha256])
            .returning(model_version.c.model_version_id)
        ).scalar_one_or_none()
        if identifier is None:
            identifier = session.execute(
                select(model_version.c.model_version_id).where(
                    model_version.c.model_semantic_sha256 == semantic_hash
                )
            ).scalar_one()
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
    evaluation: Mapping[str, Any],
    *,
    status: str = "COMPLETE",
) -> UUID:
    """Register one immutable synthetic evaluation result."""

    value = _mapping(evaluation, label="evaluation")
    semantic_hash = canonical_semantic_sha256(value)
    try:
        identifier = session.execute(
            postgresql_insert(model_evaluation)
            .values(
                model_version_id=model_version_id,
                evaluation_semantic_sha256=semantic_hash,
                status=status,
                evaluation=value,
            )
            .on_conflict_do_nothing(index_elements=[model_evaluation.c.evaluation_semantic_sha256])
            .returning(model_evaluation.c.model_evaluation_id)
        ).scalar_one_or_none()
        if identifier is None:
            identifier = session.execute(
                select(model_evaluation.c.model_evaluation_id).where(
                    model_evaluation.c.evaluation_semantic_sha256 == semantic_hash
                )
            ).scalar_one()
        if not isinstance(identifier, UUID):
            raise DataModelError("DATABASE_RESULT_INVALID", "evaluation identifier is invalid")
        return identifier
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def _prediction_output_hash(
    prediction: Mapping[str, Any],
    role_marginals: Sequence[object],
    minute_pmfs: Sequence[object],
    scenarios: Sequence[object],
) -> str:
    declared = prediction.get("output_semantic_sha256")
    if declared is not None:
        return _hash(declared, label="output_semantic_sha256")
    return canonical_semantic_sha256(
        _semantic_json(
            {
                "role_marginals": [
                    _mapping(value, label="role marginal") for value in role_marginals
                ],
                "minute_pmfs": [_mapping(value, label="minute PMF") for value in minute_pmfs],
                "scenarios": [_mapping(value, label="scenario") for value in scenarios],
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
) -> UUID:
    """Publish one complete immutable prediction graph in the caller's transaction."""

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
    output_hash = _prediction_output_hash(value, marginal_values, pmf_values, scenario_values)
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
        "bench_size": int(value.get("bench_size", 0)),
        "bench_goalkeeper_slots": int(value.get("bench_goalkeeper_slots", 0)),
        "code_identity": str(value.get("code_identity", "")),
    }
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
        return identifier
    except DataModelError:
        raise
    except DBAPIError as exc:
        raise _safe_db_error(exc) from exc


def get_prediction_run(session: Session, signature: str) -> dict[str, Any]:
    """Return one immutable run and its persisted dependency graph by signature."""

    row = (
        session.execute(
            select(prediction_run).where(
                prediction_run.c.prediction_input_signature_sha256 == signature
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

    def register_prediction_bundle(
        self, prediction: Mapping[str, Any], **parts: Sequence[object]
    ) -> UUID:
        return register_prediction_bundle(self.session, prediction, **parts)

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
    "register_model_evaluation",
    "register_model_version",
    "register_prediction_bundle",
]
