"""Real paths of the existing PostgreSQL research ledger, with server-clock custody."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.operation.models import OperationError
from dmf_pulse.player_lab.contracts import FinalPlayerOutcome, Sealed, SourceRef, seal
from dmf_pulse.player_lab.real import (
    DeadlinePopulation,
    RealDeadlineRegistration,
    RealPlayerProtocol,
    RealPointForecast,
    RealPointFreeze,
    RealPointScorecard,
    _score_real_points,
    adapt_qualified_full_forecast,
)
from dmf_pulse.player_lab.real_rights import (
    HistoricalFreezeProof,
    real_source_registry,
    require_real_outcome,
    require_real_population,
    require_real_sources,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection, Engine


def _safe_api[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    def attempt(*args: P.args, **kwargs: P.kwargs) -> tuple[R | None, str | None]:
        from sqlalchemy.exc import SQLAlchemyError

        try:
            return function(*args, **kwargs), None
        except OperationError as error:
            return None, error.code
        except (SQLAlchemyError, EvaluationError, ValueError, OSError, TypeError):
            return None, "REAL_PLAYER_LEDGER_REJECTED"

    @wraps(function)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        result, error = attempt(*args, **kwargs)
        del args, kwargs
        if error is not None:
            raise OperationError(error)
        from typing import cast

        return cast(R, result)

    return checked


def protocol_intent_sha256(protocol: RealPlayerProtocol) -> str:
    return canonical_sha256(
        protocol.model_dump(mode="json", exclude={"semantic_sha256", "registered_at"})
    )


def _require_intent(protocol: RealPlayerProtocol, now: datetime) -> None:
    rows = [
        row
        for row in real_source_registry().accepted_protocol_intents
        if row.intent_sha256 == protocol_intent_sha256(protocol)
    ]
    if len(rows) != 1 or not rows[0].accepted_at <= now < rows[0].expires_at:
        raise OperationError("REAL_PLAYER_PROTOCOL_OWNER_ACCEPTANCE_REQUIRED")


def _clock(connection: Connection) -> datetime:
    from sqlalchemy import text

    from dmf_pulse.player_lab.real_integrity import require_real_database

    require_real_database(connection)

    value = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperationError("REAL_PLAYER_DATABASE_CLOCK_INVALID")
    return value.astimezone(UTC)


def _put(
    connection: Connection,
    value: Sealed,
    *,
    kind: str,
    sources: tuple[SourceRef, ...],
    protocol: str | None = None,
    target: str | None = None,
    model: str | None = None,
    revision: int = 0,
    supersedes: str | None = None,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    from dmf_pulse.data_model.tables import player_research_artifact

    value = type(value).model_validate_json(value.model_dump_json())
    payload = value.model_dump(mode="json")
    connection.execute(
        insert(player_research_artifact)
        .values(
            artifact_sha256=value.semantic_sha256,
            kind=kind,
            dataset_mode="PROSPECTIVE_REAL",
            target_id=target,
            model_id=model,
            experiment_sha256=protocol,
            revision=revision,
            supersedes_sha256=supersedes,
            source_refs=[source.model_dump(mode="json") for source in sources],
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=[player_research_artifact.c.artifact_sha256])
    )
    stored = connection.execute(
        select(player_research_artifact.c.payload).where(
            player_research_artifact.c.artifact_sha256 == value.semantic_sha256
        )
    ).scalar_one()
    if stored != payload:
        raise OperationError("REAL_PLAYER_ARTIFACT_COLLISION")


def _protocol(connection: Connection, digest: str) -> RealPlayerProtocol:
    from sqlalchemy import select

    from dmf_pulse.data_model.tables import player_research_artifact as table

    value = connection.execute(
        select(table.c.payload).where(
            table.c.artifact_sha256 == digest,
            table.c.kind == "EXPERIMENT",
            table.c.dataset_mode == "PROSPECTIVE_REAL",
        )
    ).scalar_one()
    result = RealPlayerProtocol.model_validate_json(json.dumps(value))
    if result.semantic_sha256 != digest:
        raise OperationError("REAL_PLAYER_PROTOCOL_CUSTODY_INVALID")
    return result


@_safe_api
def register_protocol(
    factory: Callable[[], Engine], proposal: RealPlayerProtocol
) -> RealPlayerProtocol:
    proposal = RealPlayerProtocol.model_validate_json(proposal.model_dump_json())
    now = datetime.now(UTC)
    require_real_sources(proposal.sources, now=now)
    _require_intent(proposal, now)
    engine = factory()
    with engine.begin() as connection:
        recorded = _clock(connection)
        require_real_sources(proposal.sources, now=recorded)
        _require_intent(proposal, recorded)
        values = {
            name: getattr(proposal, name)
            for name in type(proposal).model_fields
            if name != "semantic_sha256"
        }
        values["registered_at"] = recorded
        result = seal(RealPlayerProtocol.model_construct(**values, semantic_sha256="0" * 64))
        _put(connection, result, kind="EXPERIMENT", sources=result.sources)
    return result


def _external_proof(
    digest: str, kind: Literal["POINT_FORECAST", "DEADLINE_POPULATION"], now: datetime
) -> HistoricalFreezeProof:
    rows = [
        row
        for row in real_source_registry().historical_freezes
        if row.semantic_sha256 == digest and row.artifact_kind == kind and row.accepted_at <= now
    ]
    if len(rows) != 1:
        raise OperationError("REAL_PLAYER_EXTERNAL_PREDEADLINE_PROOF_REQUIRED")
    require_real_sources(rows[0].sources, now=now)
    return rows[0]


@_safe_api
def register_population(
    factory: Callable[[], Engine],
    protocol_sha256: str,
    population: DeadlinePopulation,
    *,
    external_proof_sha256: str | None = None,
    original_body: bytes | None = None,
) -> RealDeadlineRegistration:
    population = DeadlinePopulation.model_validate_json(population.model_dump_json())
    now = datetime.now(UTC)
    digest = canonical_sha256(population.model_dump(mode="json"))
    require_real_population(population.catalogue_source, digest, now=now)
    proof = (
        None
        if external_proof_sha256 is None
        else _external_proof(external_proof_sha256, "DEADLINE_POPULATION", now)
    )
    if proof is not None and (
        proof.artifact_semantic_sha256 != digest
        or proof.sources != (population.catalogue_source,)
        or original_body is None
        or hashlib.sha256(original_body).hexdigest() != proof.original_artifact_byte_sha256
        or DeadlinePopulation.model_validate_json(original_body) != population
    ):
        raise OperationError("REAL_PLAYER_EXTERNAL_POPULATION_MISMATCH")
    with factory().begin() as connection:
        recorded = _clock(connection)
        protocol = _protocol(connection, protocol_sha256)
        require_real_sources(protocol.sources, now=recorded)
        _require_intent(protocol, recorded)
        require_real_population(population.catalogue_source, digest, now=recorded)
        if population.gameweek not in protocol.gameweeks or any(
            row.season != protocol.season for row in population.targets
        ):
            raise OperationError("REAL_PLAYER_POPULATION_SCOPE_MISMATCH")
        if population.gameweek == protocol.gameweeks[0] and (
            population.deadline_at != protocol.first_deadline_at
            or population.official_deadline_evidence_sha256
            != protocol.first_deadline_evidence_sha256
        ):
            raise OperationError("REAL_PLAYER_OFFICIAL_DEADLINE_MISMATCH")
        if (proof is None) != (protocol.evaluation_classification == "PREREGISTERED_PROSPECTIVE"):
            raise OperationError("REAL_PLAYER_PROSPECTIVE_DESCRIPTIVE_CUSTODY_MISMATCH")
        result = seal(
            RealDeadlineRegistration.model_construct(
                protocol_sha256=protocol_sha256,
                population=population,
                registered_at=recorded,
                original_population_frozen_at=recorded
                if proof is None
                else proof.original_frozen_at,
                custody="DATABASE_PREDEADLINE"
                if proof is None
                else "QUALIFIED_EXTERNAL_HISTORICAL_IMPORT",
                external_custody_sha256=external_proof_sha256,
                semantic_sha256="0" * 64,
            )
        )
        _put(connection, result, kind="EXPERIMENT", sources=(population.catalogue_source,))
    return result


@_safe_api
def freeze_forecast(
    factory: Callable[[], Engine],
    protocol_sha256: str,
    population_sha256: str,
    forecast: RealPointForecast,
    *,
    external_proof_sha256: str | None = None,
    original_body: bytes | None = None,
) -> RealPointFreeze:
    now = datetime.now(UTC)
    require_real_sources(forecast.sources, now=now)
    forecast = RealPointForecast.model_validate_json(forecast.model_dump_json())
    proof = (
        None
        if external_proof_sha256 is None
        else _external_proof(external_proof_sha256, "POINT_FORECAST", now)
    )
    if proof is not None:
        if (
            original_body is None
            or hashlib.sha256(original_body).hexdigest() != proof.original_artifact_byte_sha256
            or proof.artifact_semantic_sha256 != forecast.semantic_sha256
            or proof.sources != forecast.sources
        ):
            raise OperationError("REAL_PLAYER_EXTERNAL_FORECAST_BYTES_MISMATCH")
        if proof.original_artifact_format == "PLAYER_FORECAST_V1":
            from dmf_pulse.player_lab.contracts import PlayerForecast

            original = PlayerForecast.model_validate_json(original_body)
            if (
                proof.information_grade is None
                or original.semantic_sha256 != proof.original_semantic_sha256
            ):
                raise OperationError("REAL_PLAYER_EXTERNAL_FORECAST_BYTES_MISMATCH")
            admitted = adapt_qualified_full_forecast(
                original, information_grade=proof.information_grade, now=now
            )
        elif proof.original_artifact_format == "QUALIFIED_POINT_ADAPTER_V1":
            admitted = RealPointForecast.model_validate_json(original_body)
        else:
            raise OperationError("REAL_PLAYER_EXTERNAL_FORECAST_FORMAT_UNSUPPORTED")
        if admitted != forecast:
            raise OperationError("REAL_PLAYER_EXTERNAL_FORECAST_BYTES_MISMATCH")
    with factory().begin() as connection:
        from sqlalchemy import select

        from dmf_pulse.data_model.tables import player_research_artifact as table

        recorded = _clock(connection)
        protocol = _protocol(connection, protocol_sha256)
        require_real_sources(forecast.sources, now=recorded)
        _require_intent(protocol, recorded)
        value = connection.execute(
            select(table.c.payload).where(
                table.c.artifact_sha256 == population_sha256,
                table.c.dataset_mode == "PROSPECTIVE_REAL",
                table.c.kind == "EXPERIMENT",
            )
        ).scalar_one()
        registration = RealDeadlineRegistration.model_validate_json(json.dumps(value))
        if (
            registration.protocol_sha256 != protocol_sha256
            or registration.semantic_sha256 != population_sha256
        ):
            raise OperationError("REAL_PLAYER_POPULATION_CUSTODY_INVALID")
        if (proof is None) != (protocol.evaluation_classification == "PREREGISTERED_PROSPECTIVE"):
            raise OperationError("REAL_PLAYER_PROSPECTIVE_DESCRIPTIVE_CUSTODY_MISMATCH")
        result = seal(
            RealPointFreeze.model_construct(
                forecast=forecast,
                population_registration_sha256=population_sha256,
                recorded_at=recorded,
                original_frozen_at=recorded if proof is None else proof.original_frozen_at,
                custody="DATABASE_PREDEADLINE"
                if proof is None
                else "QUALIFIED_EXTERNAL_HISTORICAL_IMPORT",
                external_custody_sha256=external_proof_sha256,
                semantic_sha256="0" * 64,
            )
        )
        # Validate exact version/season/target/deadline/catalogue binding before write.
        from dmf_pulse.player_lab.real import real_coverage

        real_coverage(protocol, (registration,), (result,))
        _put(
            connection,
            result,
            kind="FORECAST",
            sources=forecast.sources,
            protocol=protocol_sha256,
            target=forecast.key.target_id(),
            model=forecast.model_id,
        )
    return result


@_safe_api
def append_label(factory: Callable[[], Engine], label: FinalPlayerOutcome) -> str:
    now = datetime.now(UTC)
    require_real_outcome(label, now=now)
    label = FinalPlayerOutcome.model_validate_json(label.model_dump_json())
    with factory().begin() as connection:
        require_real_outcome(label, now=_clock(connection))
        _put(
            connection,
            label,
            kind="LABEL",
            sources=(label.source,),
            target=label.key.target_id(),
            revision=label.revision,
            supersedes=label.supersedes_sha256,
        )
    return label.semantic_sha256


@dataclass(frozen=True)
class _DatabaseRealCustody:
    protocol: RealPlayerProtocol
    populations: tuple[RealDeadlineRegistration, ...]
    forecasts: tuple[RealPointFreeze, ...]

    def verify_protocol(self, value: RealPlayerProtocol) -> None:
        if value != self.protocol:
            raise OperationError("REAL_PLAYER_PROTOCOL_CUSTODY_INVALID")

    def verify_population(self, value: RealDeadlineRegistration) -> None:
        if value not in self.populations:
            raise OperationError("REAL_PLAYER_POPULATION_CUSTODY_INVALID")

    def verify_forecast(self, value: RealPointFreeze) -> None:
        if value not in self.forecasts:
            raise OperationError("REAL_PLAYER_FORECAST_CUSTODY_INVALID")


@_safe_api
def evaluate_stored(
    factory: Callable[[], Engine],
    protocol_sha256: str,
    model_id: str,
    *,
    expected_sources: tuple[SourceRef, ...],
    label_sha256s: tuple[str, ...],
) -> RealPointScorecard:
    from sqlalchemy import and_, or_, select, text
    from sqlalchemy.dialects.postgresql import insert

    from dmf_pulse.data_model.tables import player_research_artifact as table
    from dmf_pulse.data_model.tables import player_research_pair

    require_real_sources(expected_sources, now=datetime.now(UTC))
    if not label_sha256s or len(set(label_sha256s)) != len(label_sha256s):
        raise OperationError("REAL_PLAYER_EXPLICIT_COMPLETE_LABEL_VINTAGE_REQUIRED")
    with factory().begin() as connection:
        now = _clock(connection)
        require_real_sources(expected_sources, now=now)
        selector = and_(
            table.c.dataset_mode == "PROSPECTIVE_REAL",
            table.c.kind.in_(("EXPERIMENT", "FORECAST")),
            or_(
                table.c.artifact_sha256 == protocol_sha256,
                table.c.experiment_sha256 == protocol_sha256,
                table.c.payload["protocol_sha256"].astext == protocol_sha256,
            ),
        )
        metadata = (
            connection.execute(
                select(table.c.artifact_sha256, table.c.source_refs, table.c.target_id).where(
                    selector
                )
            )
            .mappings()
            .all()
        )
        if not metadata or len(metadata) > 100000:
            raise OperationError("REAL_PLAYER_COHORT_CUSTODY_INVALID")
        targets = {row["target_id"] for row in metadata if row["target_id"] is not None}
        label_metadata = (
            connection.execute(
                select(table.c.artifact_sha256, table.c.source_refs, table.c.target_id).where(
                    table.c.dataset_mode == "PROSPECTIVE_REAL",
                    table.c.kind == "LABEL",
                    table.c.target_id.in_(targets),
                    table.c.artifact_sha256.in_(label_sha256s),
                )
            )
            .mappings()
            .all()
        )
        metadata = [*metadata, *label_metadata]
        if {row["artifact_sha256"] for row in label_metadata} != set(label_sha256s):
            raise OperationError("REAL_PLAYER_EXPLICIT_COMPLETE_LABEL_VINTAGE_REQUIRED")
        for row in metadata:
            sources = tuple(
                SourceRef.model_validate_json(json.dumps(value)) for value in row["source_refs"]
            )
            if any(source not in expected_sources for source in sources):
                raise OperationError("REAL_PLAYER_EVALUATION_SOURCE_SCOPE_MISMATCH")
            require_real_sources(sources, now=now)
        rows = (
            connection.execute(
                select(table).where(
                    table.c.artifact_sha256.in_([row["artifact_sha256"] for row in metadata])
                )
            )
            .mappings()
            .all()
        )
        protocol = _protocol(connection, protocol_sha256)
        _require_intent(protocol, now)
        populations, forecasts, labels = [], [], []
        for row in rows:
            body = json.dumps(row["payload"])
            if row["kind"] == "EXPERIMENT" and row["artifact_sha256"] != protocol_sha256:
                populations.append(RealDeadlineRegistration.model_validate_json(body))
            elif row["kind"] == "FORECAST":
                forecasts.append(RealPointFreeze.model_validate_json(body))
            elif row["kind"] == "LABEL":
                labels.append(FinalPlayerOutcome.model_validate_json(body))
        populations.sort(key=lambda value: value.population.gameweek)
        frozen, registered = tuple(forecasts), tuple(populations)
        report = _score_real_points(
            protocol,
            registered,
            frozen,
            tuple(labels),
            model_id=model_id,
            custody=_DatabaseRealCustody(protocol, registered, frozen),
            evaluated_at=now,
        )
        closure = {
            canonical_sha256(source.model_dump(mode="json")): source for source in expected_sources
        }
        _put(
            connection,
            report,
            kind="SCORECARD",
            sources=tuple(closure[key] for key in sorted(closure)),
            protocol=protocol_sha256,
            model=model_id,
        )
        by_target = {row.key.target_id(): row for row in labels}
        for forecast in frozen:
            if forecast.forecast.model_id == model_id:
                connection.execute(
                    insert(player_research_pair)
                    .values(
                        score_sha256=report.semantic_sha256,
                        target_id=forecast.forecast.key.target_id(),
                        forecast_sha256=forecast.semantic_sha256,
                        label_sha256=by_target[forecast.forecast.key.target_id()].semantic_sha256,
                    )
                    .on_conflict_do_nothing()
                )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return report
