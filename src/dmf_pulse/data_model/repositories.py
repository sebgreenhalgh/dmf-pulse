"""Explicit-session repositories for canonical, temporal, and provenance records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.types.range import Range
from pydantic import ValidationError
from sqlalchemy import RowMapping, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dmf_pulse.data_model.errors import DataModelError, translate_database_error
from dmf_pulse.data_model.models import (
    AliasType,
    AsOfScope,
    AssignmentStatus,
    EntityType,
    FixtureStatus,
    MappingMethod,
    MappingStatus,
    RegistrationType,
    SquadStatus,
    TemporalRange,
    require_utc,
)
from dmf_pulse.data_model.tables import (
    canonical_entity,
    competition,
    data_provider,
    entity_alias,
    external_identifier,
    fixture,
    fixture_gameweek_assignment,
    fixture_revision,
    gameweek,
    player,
    player_team_membership,
    raw_blob,
    raw_blob_deletion,
    ruleset_activation,
    ruleset_artifact,
    season,
    source_snapshot,
    team,
)
from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import (
    ActivationReceipt,
    ApprovalRecord,
    CompiledRuleset,
    RulesetStatus,
)


def _range(value: TemporalRange) -> Range[datetime]:
    return Range(value.start, value.end, bounds="[)")


def _utc_text(value: datetime) -> str:
    return require_utc(value).isoformat().replace("+00:00", "Z")


def _range_value(value: Range[datetime]) -> dict[str, str | None]:
    if value.isempty or value.lower is None:
        raise DataModelError("TEMPORAL_RANGE_INVALID", "stored temporal range is invalid")
    return {
        "bounds": value.bounds,
        "end": _utc_text(value.upper) if value.upper is not None else None,
        "start": _utc_text(value.lower),
    }


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise DataModelError("DATABASE_RESULT_INVALID", "database returned an invalid identifier")
    return value


def _validate_usable_snapshot(
    session: Session,
    snapshot_id: UUID,
    *,
    known_at: datetime,
    provider_id: UUID | None = None,
) -> None:
    row = (
        session.execute(
            select(
                source_snapshot.c.provider_id,
                source_snapshot.c.usable_at,
                source_snapshot.c.validation_status,
            ).where(source_snapshot.c.source_snapshot_id == snapshot_id)
        )
        .mappings()
        .one_or_none()
    )
    known = require_utc(known_at)
    if (
        row is None
        or row["validation_status"] != "USABLE"
        or row["usable_at"] is None
        or require_utc(row["usable_at"]) > known
        or (provider_id is not None and row["provider_id"] != provider_id)
    ):
        raise DataModelError(
            "PROVENANCE_INTEGRITY", "source snapshot was not usable at the fact's known time"
        )


def commit_session(session: Session) -> None:
    try:
        session.commit()
    except DBAPIError as exc:
        session.rollback()
        raise translate_database_error(exc) from exc


def _as_of_statement(table: Any, scope: AsOfScope) -> Any:
    return select(table).where(
        table.c.valid_during.op("@>")(scope.valid_at),
        table.c.system_during.op("@>")(scope.known_at),
    )


def _temporal_result(
    row: RowMapping,
    *,
    canonical_column: str,
    version_column: str,
    scope: AsOfScope,
) -> dict[str, Any]:
    return {
        "canonical_id": str(row[canonical_column]),
        "fact_version_id": str(row[version_column]),
        "known_at": _utc_text(scope.known_at),
        "source_snapshot_id": (
            str(row["source_snapshot_id"])
            if "source_snapshot_id" in row and row["source_snapshot_id"] is not None
            else str(row["evidence_source_snapshot_id"])
            if "evidence_source_snapshot_id" in row
            and row["evidence_source_snapshot_id"] is not None
            else None
        ),
        "system_range": _range_value(row["system_during"]),
        "valid_at": _utc_text(scope.valid_at),
        "valid_range": _range_value(row["valid_during"]),
    }


class CanonicalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_entity(self, entity_type: EntityType, **attributes: object) -> UUID:
        table_map = {
            EntityType.COMPETITION: (competition, "competition_id"),
            EntityType.SEASON: (season, "season_id"),
            EntityType.GAMEWEEK: (gameweek, "gameweek_id"),
            EntityType.TEAM: (team, "team_id"),
            EntityType.PLAYER: (player, "player_id"),
            EntityType.FIXTURE: (fixture, "fixture_id"),
            EntityType.DATA_PROVIDER: (data_provider, "provider_id"),
        }
        target, id_column = table_map[entity_type]
        reserved = {id_column, "entity_type"} & attributes.keys()
        if reserved:
            raise DataModelError(
                "ENTITY_ATTRIBUTES_INVALID", "canonical identity attributes are reserved"
            )
        try:
            entity_id = self.session.execute(
                insert(canonical_entity)
                .values(entity_type=entity_type.value)
                .returning(canonical_entity.c.entity_id)
            ).scalar_one()
            values = {id_column: entity_id, "entity_type": entity_type.value, **attributes}
            self.session.execute(insert(target).values(**values))
            return _uuid(entity_id)
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def get_entity(self, entity_id: UUID) -> RowMapping | None:
        return (
            self.session.execute(
                select(canonical_entity).where(canonical_entity.c.entity_id == entity_id)
            )
            .mappings()
            .one_or_none()
        )


class AliasRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_version(
        self,
        *,
        canonical_entity_id: UUID,
        raw_text: str,
        normalized_nfc: str,
        match_key: str,
        alias_type: AliasType,
        valid_range: TemporalRange,
        known_at: datetime,
        language: str | None = None,
        script: str | None = None,
        provider_id: UUID | None = None,
        source_snapshot_id: UUID | None = None,
        confidence: Decimal | None = None,
        is_preferred: bool = False,
    ) -> UUID:
        """Insert an explicitly scoped alias without treating its text as identity."""

        known = require_utc(known_at)
        if source_snapshot_id is not None:
            _validate_usable_snapshot(
                self.session,
                source_snapshot_id,
                known_at=known,
                provider_id=provider_id,
            )
        try:
            return _uuid(
                self.session.execute(
                    insert(entity_alias)
                    .values(
                        canonical_entity_id=canonical_entity_id,
                        raw_text=raw_text,
                        normalized_nfc=normalized_nfc,
                        match_key=match_key,
                        language=language,
                        script=script,
                        alias_type=alias_type.value,
                        provider_id=provider_id,
                        valid_during=_range(valid_range),
                        system_during=Range(known, None, bounds="[)"),
                        source_snapshot_id=source_snapshot_id,
                        confidence=confidence,
                        is_preferred=is_preferred,
                    )
                    .returning(entity_alias.c.alias_id)
                ).scalar_one()
            )
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc


class ExternalIdentifierRepository:
    CONSTRAINT = "core.ex_external_identifier_current_accepted"

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_version(
        self,
        *,
        canonical_entity_id: UUID,
        provider_id: UUID,
        provider_product: str,
        identifier_namespace: str,
        entity_type: EntityType,
        external_id_text: str,
        valid_range: TemporalRange,
        known_at: datetime,
        mapping_status: MappingStatus,
        mapping_method: MappingMethod = MappingMethod.DETERMINISTIC,
        first_seen_at: datetime,
        last_seen_at: datetime,
        raw_example: str | None = None,
        evidence_source_snapshot_id: UUID | None = None,
    ) -> UUID:
        known = require_utc(known_at)
        if evidence_source_snapshot_id is not None:
            _validate_usable_snapshot(
                self.session,
                evidence_source_snapshot_id,
                known_at=known,
                provider_id=provider_id,
            )
        try:
            return _uuid(
                self.session.execute(
                    insert(external_identifier)
                    .values(
                        canonical_entity_id=canonical_entity_id,
                        provider_id=provider_id,
                        provider_product=provider_product,
                        identifier_namespace=identifier_namespace,
                        entity_type=entity_type.value,
                        external_id_text=external_id_text,
                        valid_during=_range(valid_range),
                        system_during=Range(known, None, bounds="[)"),
                        mapping_status=mapping_status.value,
                        mapping_method=mapping_method.value,
                        evidence_source_snapshot_id=evidence_source_snapshot_id,
                        first_seen_at=require_utc(first_seen_at),
                        last_seen_at=require_utc(last_seen_at),
                        raw_example=raw_example,
                    )
                    .returning(external_identifier.c.external_identifier_id)
                ).scalar_one()
            )
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def supersede(
        self,
        old_version_id: UUID,
        *,
        known_at: datetime,
        provider_product: str,
        identifier_namespace: str,
        external_id_text: str,
        valid_range: TemporalRange,
        mapping_status: MappingStatus,
        evidence_source_snapshot_id: UUID,
        last_seen_at: datetime,
        mapping_method: MappingMethod = MappingMethod.DETERMINISTIC,
        raw_example: str | None = None,
    ) -> UUID:
        known = require_utc(known_at)
        try:
            old = (
                self.session.execute(
                    select(external_identifier)
                    .where(external_identifier.c.external_identifier_id == old_version_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if old is None or old["superseded_by_mapping_id"] is not None:
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
                )
            if evidence_source_snapshot_id == old["evidence_source_snapshot_id"]:
                raise DataModelError(
                    "PROVENANCE_INTEGRITY",
                    "a correction requires a distinct source snapshot",
                )
            _validate_usable_snapshot(
                self.session,
                evidence_source_snapshot_id,
                known_at=known,
                provider_id=old["provider_id"],
            )
            old_system: Range[datetime] = old["system_during"]
            if (
                old_system.upper is not None
                or old_system.lower is None
                or known <= old_system.lower
            ):
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
                )
            self.session.execute(text(f"SET CONSTRAINTS {self.CONSTRAINT} DEFERRED"))
            new_id = self.session.execute(
                insert(external_identifier)
                .values(
                    canonical_entity_id=old["canonical_entity_id"],
                    provider_id=old["provider_id"],
                    provider_product=provider_product,
                    identifier_namespace=identifier_namespace,
                    entity_type=old["entity_type"],
                    external_id_text=external_id_text,
                    valid_during=_range(valid_range),
                    system_during=Range(known, None, bounds="[)"),
                    mapping_status=mapping_status.value,
                    mapping_method=mapping_method.value,
                    evidence_source_snapshot_id=evidence_source_snapshot_id,
                    first_seen_at=old["first_seen_at"],
                    last_seen_at=require_utc(last_seen_at),
                    raw_example=raw_example,
                )
                .returning(external_identifier.c.external_identifier_id)
            ).scalar_one()
            self.session.execute(
                update(external_identifier)
                .where(external_identifier.c.external_identifier_id == old_version_id)
                .values(
                    system_during=Range(old_system.lower, known, bounds="[)"),
                    superseded_by_mapping_id=new_id,
                )
            )
            self.session.execute(text(f"SET CONSTRAINTS {self.CONSTRAINT} IMMEDIATE"))
            return _uuid(new_id)
        except DataModelError:
            raise
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def get_as_of(
        self,
        canonical_entity_id: UUID,
        scope: AsOfScope,
        *,
        provider_id: UUID | None = None,
        provider_product: str | None = None,
        identifier_namespace: str | None = None,
    ) -> dict[str, Any]:
        statement = _as_of_statement(external_identifier, scope).where(
            external_identifier.c.canonical_entity_id == canonical_entity_id
        )
        if provider_id is not None:
            statement = statement.where(external_identifier.c.provider_id == provider_id)
        if provider_product is not None:
            statement = statement.where(external_identifier.c.provider_product == provider_product)
        if identifier_namespace is not None:
            statement = statement.where(
                external_identifier.c.identifier_namespace == identifier_namespace
            )
        rows = self.session.execute(statement).mappings().all()
        if not rows:
            raise DataModelError("AS_OF_NOT_FOUND", "external identifier was not found as-of")
        if len(rows) != 1:
            raise DataModelError(
                "AS_OF_AMBIGUOUS", "external identifier scope matches multiple facts"
            )
        row = rows[0]
        result = _temporal_result(
            row,
            canonical_column="canonical_entity_id",
            version_column="external_identifier_id",
            scope=scope,
        )
        result.update(
            {
                "external_id": row["external_id_text"],
                "mapping_status": row["mapping_status"],
                "namespace": row["identifier_namespace"],
                "provider_product": row["provider_product"],
            }
        )
        return result


class PlayerMembershipRepository:
    CONSTRAINT = "football.ex_player_team_membership_current"

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_version(
        self,
        *,
        player_id: UUID,
        team_id: UUID,
        season_id: UUID,
        registration_type: RegistrationType,
        squad_status: SquadStatus,
        valid_range: TemporalRange,
        known_at: datetime,
        source_snapshot_id: UUID | None = None,
        shirt_number: int | None = None,
    ) -> UUID:
        if source_snapshot_id is not None:
            _validate_usable_snapshot(
                self.session, source_snapshot_id, known_at=require_utc(known_at)
            )
        try:
            return _uuid(
                self.session.execute(
                    insert(player_team_membership)
                    .values(
                        player_id=player_id,
                        team_id=team_id,
                        season_id=season_id,
                        registration_type=registration_type.value,
                        squad_status=squad_status.value,
                        shirt_number=shirt_number,
                        valid_during=_range(valid_range),
                        system_during=Range(require_utc(known_at), None, bounds="[)"),
                        source_snapshot_id=source_snapshot_id,
                    )
                    .returning(player_team_membership.c.membership_id)
                ).scalar_one()
            )
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def supersede(
        self,
        old_version_id: UUID,
        *,
        team_id: UUID,
        season_id: UUID,
        valid_range: TemporalRange,
        known_at: datetime,
        squad_status: SquadStatus,
        source_snapshot_id: UUID,
        shirt_number: int | None = None,
    ) -> UUID:
        known = require_utc(known_at)
        try:
            old = (
                self.session.execute(
                    select(player_team_membership)
                    .where(player_team_membership.c.membership_id == old_version_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if old is None or old["superseded_by_membership_id"] is not None:
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
                )
            if source_snapshot_id == old["source_snapshot_id"]:
                raise DataModelError(
                    "PROVENANCE_INTEGRITY",
                    "a correction requires a distinct source snapshot",
                )
            _validate_usable_snapshot(self.session, source_snapshot_id, known_at=known)
            old_system: Range[datetime] = old["system_during"]
            if (
                old_system.upper is not None
                or old_system.lower is None
                or known <= old_system.lower
            ):
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
                )
            self.session.execute(text(f"SET CONSTRAINTS {self.CONSTRAINT} DEFERRED"))
            new_id = self.session.execute(
                insert(player_team_membership)
                .values(
                    player_id=old["player_id"],
                    team_id=team_id,
                    season_id=season_id,
                    registration_type=old["registration_type"],
                    squad_status=squad_status.value,
                    shirt_number=shirt_number,
                    valid_during=_range(valid_range),
                    system_during=Range(known, None, bounds="[)"),
                    source_snapshot_id=source_snapshot_id,
                )
                .returning(player_team_membership.c.membership_id)
            ).scalar_one()
            self.session.execute(
                update(player_team_membership)
                .where(player_team_membership.c.membership_id == old_version_id)
                .values(
                    system_during=Range(old_system.lower, known, bounds="[)"),
                    superseded_by_membership_id=new_id,
                )
            )
            self.session.execute(text(f"SET CONSTRAINTS {self.CONSTRAINT} IMMEDIATE"))
            return _uuid(new_id)
        except DataModelError:
            raise
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def get_as_of(
        self,
        player_id: UUID,
        registration_type: RegistrationType,
        scope: AsOfScope,
    ) -> dict[str, Any]:
        row = (
            self.session.execute(
                _as_of_statement(player_team_membership, scope).where(
                    player_team_membership.c.player_id == player_id,
                    player_team_membership.c.registration_type == registration_type.value,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DataModelError("AS_OF_NOT_FOUND", "player membership was not found as-of")
        result = _temporal_result(
            row,
            canonical_column="player_id",
            version_column="membership_id",
            scope=scope,
        )
        result.update(
            {
                "registration_type": row["registration_type"],
                "squad_status": row["squad_status"],
                "team_id": str(row["team_id"]),
            }
        )
        return result


class FixtureRepository:
    REVISION_CONSTRAINT = "football.ex_fixture_revision_current"
    ASSIGNMENT_CONSTRAINT = "football.ex_fixture_gameweek_assignment_current"

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_revision(
        self,
        *,
        fixture_id: UUID,
        revision_number: int,
        kickoff_at: datetime | None,
        fixture_status: FixtureStatus,
        valid_range: TemporalRange,
        known_at: datetime,
        observed_at: datetime,
        source_snapshot_id: UUID | None,
        venue: str | None = None,
    ) -> UUID:
        if source_snapshot_id is not None:
            _validate_usable_snapshot(
                self.session, source_snapshot_id, known_at=require_utc(known_at)
            )
        try:
            return _uuid(
                self.session.execute(
                    insert(fixture_revision)
                    .values(
                        fixture_id=fixture_id,
                        revision_number=revision_number,
                        kickoff_at=require_utc(kickoff_at) if kickoff_at is not None else None,
                        fixture_status=fixture_status.value,
                        venue=venue,
                        valid_during=_range(valid_range),
                        system_during=Range(require_utc(known_at), None, bounds="[)"),
                        observed_at=require_utc(observed_at),
                        source_snapshot_id=source_snapshot_id,
                    )
                    .returning(fixture_revision.c.fixture_revision_id)
                ).scalar_one()
            )
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def revise(
        self,
        old_version_id: UUID,
        *,
        revision_number: int,
        kickoff_at: datetime | None,
        fixture_status: FixtureStatus,
        valid_range: TemporalRange,
        known_at: datetime,
        observed_at: datetime,
        venue: str | None = None,
        source_snapshot_id: UUID | None = None,
    ) -> UUID:
        values: dict[str, object] = {
            "revision_number": revision_number,
            "kickoff_at": require_utc(kickoff_at) if kickoff_at is not None else None,
            "fixture_status": fixture_status.value,
            "valid_during": _range(valid_range),
            "observed_at": require_utc(observed_at),
            "venue": venue,
        }
        values["source_snapshot_id"] = source_snapshot_id
        return self._supersede(
            fixture_revision,
            old_version_id,
            id_column="fixture_revision_id",
            pointer_column="superseded_by_revision_id",
            constraint=self.REVISION_CONSTRAINT,
            known_at=known_at,
            values=values,
        )

    def assign_gameweek(
        self,
        *,
        fixture_id: UUID,
        gameweek_id: UUID | None,
        assignment_status: AssignmentStatus,
        valid_range: TemporalRange,
        known_at: datetime,
        source_snapshot_id: UUID | None = None,
        supersedes: UUID | None = None,
    ) -> UUID:
        if supersedes is not None:
            if source_snapshot_id is None:
                raise DataModelError(
                    "PROVENANCE_INTEGRITY", "a correction requires a source snapshot"
                )
            values: dict[str, object] = {
                "gameweek_id": gameweek_id,
                "assignment_status": assignment_status.value,
                "valid_during": _range(valid_range),
                "source_snapshot_id": source_snapshot_id,
            }
            return self._supersede(
                fixture_gameweek_assignment,
                supersedes,
                id_column="assignment_id",
                pointer_column="superseded_by_assignment_id",
                constraint=self.ASSIGNMENT_CONSTRAINT,
                known_at=known_at,
                values=values,
                expected_lineage={"fixture_id": fixture_id},
            )
        if source_snapshot_id is not None:
            _validate_usable_snapshot(
                self.session, source_snapshot_id, known_at=require_utc(known_at)
            )
        try:
            return _uuid(
                self.session.execute(
                    insert(fixture_gameweek_assignment)
                    .values(
                        fixture_id=fixture_id,
                        gameweek_id=gameweek_id,
                        assignment_status=assignment_status.value,
                        valid_during=_range(valid_range),
                        system_during=Range(require_utc(known_at), None, bounds="[)"),
                        source_snapshot_id=source_snapshot_id,
                    )
                    .returning(fixture_gameweek_assignment.c.assignment_id)
                ).scalar_one()
            )
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def _supersede(
        self,
        table: Any,
        old_version_id: UUID,
        *,
        id_column: str,
        pointer_column: str,
        constraint: str,
        known_at: datetime,
        values: dict[str, object],
        expected_lineage: Mapping[str, object] | None = None,
    ) -> UUID:
        known = require_utc(known_at)
        try:
            old = (
                self.session.execute(
                    select(table).where(table.c[id_column] == old_version_id).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if old is None or old[pointer_column] is not None:
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
                )
            if expected_lineage is not None and any(
                old[key] != value for key, value in expected_lineage.items()
            ):
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal lineage does not match"
                )
            old_system: Range[datetime] = old["system_during"]
            if (
                old_system.upper is not None
                or old_system.lower is None
                or known <= old_system.lower
            ):
                raise DataModelError(
                    "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
                )
            if "source_snapshot_id" in table.c and (
                values.get("source_snapshot_id") is None
                or values["source_snapshot_id"] == old["source_snapshot_id"]
            ):
                raise DataModelError(
                    "PROVENANCE_INTEGRITY",
                    "a correction requires a distinct source snapshot",
                )
            _validate_usable_snapshot(
                self.session,
                _uuid(values["source_snapshot_id"]),
                known_at=known,
            )
            self.session.execute(text(f"SET CONSTRAINTS {constraint} DEFERRED"))
            successor_values = {
                column.name: old[column.name]
                for column in table.columns
                if column.name not in {id_column, pointer_column, "system_during", *values.keys()}
                and not column.server_default
            }
            successor_values.update(values)
            successor_values["system_during"] = Range(known, None, bounds="[)")
            new_id = self.session.execute(
                insert(table).values(**successor_values).returning(table.c[id_column])
            ).scalar_one()
            self.session.execute(
                update(table)
                .where(table.c[id_column] == old_version_id)
                .values(
                    system_during=Range(old_system.lower, known, bounds="[)"),
                    **{pointer_column: new_id},
                )
            )
            self.session.execute(text(f"SET CONSTRAINTS {constraint} IMMEDIATE"))
            return _uuid(new_id)
        except DataModelError:
            raise
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def get_revision_as_of(self, fixture_id: UUID, scope: AsOfScope) -> dict[str, Any]:
        row = (
            self.session.execute(
                _as_of_statement(fixture_revision, scope).where(
                    fixture_revision.c.fixture_id == fixture_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DataModelError("AS_OF_NOT_FOUND", "fixture revision was not found as-of")
        result = _temporal_result(
            row,
            canonical_column="fixture_id",
            version_column="fixture_revision_id",
            scope=scope,
        )
        result.update(
            {
                "fixture_status": row["fixture_status"],
                "kickoff": _utc_text(row["kickoff_at"]) if row["kickoff_at"] else None,
                "revision_number": row["revision_number"],
            }
        )
        return result

    def get_gameweek_as_of(self, fixture_id: UUID, scope: AsOfScope) -> dict[str, Any]:
        row = (
            self.session.execute(
                _as_of_statement(fixture_gameweek_assignment, scope).where(
                    fixture_gameweek_assignment.c.fixture_id == fixture_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DataModelError("AS_OF_NOT_FOUND", "fixture assignment was not found as-of")
        result = _temporal_result(
            row,
            canonical_column="fixture_id",
            version_column="assignment_id",
            scope=scope,
        )
        result.update(
            {
                "assignment_status": row["assignment_status"],
                "gameweek_id": str(row["gameweek_id"]) if row["gameweek_id"] else None,
            }
        )
        return result


class SourceObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_raw_blob(
        self,
        body: bytes,
        *,
        storage_policy: str,
        content_type: str | None,
        storage_uri: str | None = None,
        stored_blob_sha256: str | None = None,
    ) -> UUID:
        if storage_policy == "FORBIDDEN":
            raise DataModelError(
                "RAW_STORAGE_FORBIDDEN", "forbidden raw content cannot create a blob record"
            )
        if storage_policy == "DELETED":
            raise DataModelError(
                "RAW_BLOB_DELETED", "deleted raw content cannot be created or reused"
            )
        body_hash = hashlib.sha256(body).hexdigest()
        values = {
            "body_sha256": body_hash,
            "byte_size": len(body),
            "storage_policy": storage_policy,
            "content_type": content_type,
            "storage_uri": storage_uri,
            "stored_blob_sha256": stored_blob_sha256,
        }
        try:
            created = self.session.execute(
                postgresql_insert(raw_blob)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[raw_blob.c.body_sha256])
                .returning(raw_blob.c.raw_blob_id)
            ).scalar_one_or_none()
            if created is not None:
                return _uuid(created)
            existing = (
                self.session.execute(select(raw_blob).where(raw_blob.c.body_sha256 == body_hash))
                .mappings()
                .one()
            )
            deleted = self.session.execute(
                select(raw_blob_deletion.c.deletion_id).where(
                    raw_blob_deletion.c.raw_blob_id == existing["raw_blob_id"]
                )
            ).first()
            if deleted is not None:
                raise DataModelError(
                    "RAW_BLOB_DELETED", "deleted raw content cannot be created or reused"
                )
            if any(existing[key] != value for key, value in values.items()):
                raise DataModelError(
                    "IMMUTABLE_RECORD", "existing raw content has different immutable metadata"
                )
            return _uuid(existing["raw_blob_id"])
        except DataModelError:
            raise
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc

    def record_source_snapshot(
        self,
        *,
        provider_id: UUID,
        resource: str,
        request_fingerprint: str,
        request_started_at: datetime,
        received_at: datetime,
        usable_at: datetime | None,
        raw_blob_id: UUID | None,
        raw_storage_policy: str,
        body_sha256: str | None,
        rights_profile_key: str,
        validation_status: str,
        dataset_mode: str,
        ingestion_run_id: UUID | None = None,
        content_type: str | None = None,
        terms_version: str | None = None,
        provider_generated_at: datetime | None = None,
        source_updated_at: datetime | None = None,
        stored_at: datetime | None = None,
        parsed_at: datetime | None = None,
        mapped_at: datetime | None = None,
        http_status: int | None = None,
        schema_fingerprint: str | None = None,
    ) -> UUID:
        try:
            if (validation_status == "USABLE") != (usable_at is not None):
                raise DataModelError(
                    "PROVENANCE_INTEGRITY",
                    "usable_at must be present exactly when validation_status is USABLE",
                )
            if raw_blob_id is not None:
                raw = (
                    self.session.execute(
                        select(raw_blob).where(raw_blob.c.raw_blob_id == raw_blob_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    raw is None
                    or body_sha256 != raw["body_sha256"]
                    or raw_storage_policy != raw["storage_policy"]
                ):
                    raise DataModelError(
                        "PROVENANCE_INTEGRITY", "source snapshot raw provenance does not match"
                    )
                deleted = self.session.execute(
                    select(raw_blob_deletion.c.deletion_id).where(
                        raw_blob_deletion.c.raw_blob_id == raw_blob_id
                    )
                ).first()
                if deleted is not None:
                    raise DataModelError(
                        "RAW_BLOB_DELETED", "deleted raw content cannot back a source snapshot"
                    )
            return _uuid(
                self.session.execute(
                    insert(source_snapshot)
                    .values(
                        ingestion_run_id=ingestion_run_id,
                        provider_id=provider_id,
                        resource=resource,
                        request_fingerprint=request_fingerprint,
                        provider_generated_at=(
                            require_utc(provider_generated_at)
                            if provider_generated_at is not None
                            else None
                        ),
                        source_updated_at=(
                            require_utc(source_updated_at)
                            if source_updated_at is not None
                            else None
                        ),
                        request_started_at=require_utc(request_started_at),
                        received_at=require_utc(received_at),
                        stored_at=require_utc(stored_at) if stored_at is not None else None,
                        parsed_at=require_utc(parsed_at) if parsed_at is not None else None,
                        mapped_at=require_utc(mapped_at) if mapped_at is not None else None,
                        usable_at=require_utc(usable_at) if usable_at is not None else None,
                        http_status=http_status,
                        content_type=content_type,
                        raw_blob_id=raw_blob_id,
                        raw_storage_policy=raw_storage_policy,
                        body_sha256=body_sha256,
                        schema_fingerprint=schema_fingerprint,
                        terms_version=terms_version,
                        rights_profile_key=rights_profile_key,
                        validation_status=validation_status,
                        dataset_mode=dataset_mode,
                    )
                    .returning(source_snapshot.c.source_snapshot_id)
                ).scalar_one()
            )
        except DataModelError:
            raise
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc


def _validate_activation_values(values: Mapping[str, Any], content: Mapping[str, bytes]) -> None:
    verified = CompiledRuleset.model_validate(values["verified_ruleset.json"])
    active = CompiledRuleset.model_validate(values["active_ruleset.json"])
    approval = ApprovalRecord.model_validate(values["approval.json"])
    receipt = ActivationReceipt.model_validate(values["activation_receipt.json"])
    ensure_compiled_ruleset_integrity(verified)
    ensure_compiled_ruleset_integrity(active)
    identity = (verified.ruleset_id, verified.ruleset_version)
    if (
        identity != (active.ruleset_id, active.ruleset_version)
        or identity != (approval.ruleset_id, approval.ruleset_version)
        or identity != (receipt.ruleset_id, receipt.ruleset_version)
        or verified.status is not RulesetStatus.VERIFIED
        or active.status is not RulesetStatus.ACTIVE
        or not verified.production_eligible
        or verified.unknown_blockers
        or approval.approved is not True
        or approval.approved_by is None
        or not approval.approved_by.strip()
        or approval.approved_at is None
        or approval.ruleset_hash != verified.ruleset_hash
        or receipt.verified_ruleset_hash != verified.ruleset_hash
        or receipt.ruleset_hash != active.ruleset_hash
        or receipt.approval_sha256 != hashlib.sha256(content["approval.json"]).hexdigest()
        or receipt.activated_at != approval.approved_at
    ):
        raise ValueError("activation linkage differs")
    verified_body = verified.model_dump(mode="json")
    active_body = active.model_dump(mode="json")
    for field in ("ruleset_hash", "status"):
        verified_body.pop(field)
        active_body.pop(field)
    if verified_body != active_body:
        raise ValueError("active ruleset is not derived from verified ruleset")

    manifest = values["activation_manifest.json"]
    if not isinstance(manifest, dict) or set(manifest) != {
        "active_ruleset_hash",
        "children",
        "ruleset_id",
        "ruleset_version",
        "schema_version",
        "verified_ruleset_hash",
    }:
        raise ValueError("activation manifest shape differs")
    if (
        (manifest.get("ruleset_id"), manifest.get("ruleset_version")) != identity
        or manifest.get("schema_version") != "1.0"
        or manifest.get("verified_ruleset_hash") != verified.ruleset_hash
        or manifest.get("active_ruleset_hash") != active.ruleset_hash
    ):
        raise ValueError("activation manifest linkage differs")
    children = manifest.get("children")
    expected_children = {
        "verified_ruleset.json": verified.ruleset_hash,
        "active_ruleset.json": active.ruleset_hash,
        "approval.json": verified.ruleset_hash,
        "activation_receipt.json": active.ruleset_hash,
    }
    if not isinstance(children, dict) or set(children) != set(expected_children):
        raise ValueError("activation manifest children differ")
    for name, ruleset_hash in expected_children.items():
        record = children[name]
        if not isinstance(record, dict) or set(record) != {
            "ruleset_hash",
            "ruleset_id",
            "ruleset_version",
            "sha256",
        }:
            raise ValueError("activation child record differs")
        if (
            record.get("ruleset_id") != identity[0]
            or record.get("ruleset_version") != identity[1]
            or record.get("ruleset_hash") != ruleset_hash
            or record.get("sha256") != hashlib.sha256(content[name]).hexdigest()
        ):
            raise ValueError("activation child linkage differs")


def _read_activation_bundle(directory: Path) -> dict[str, Any]:
    required = {
        "verified_ruleset.json",
        "active_ruleset.json",
        "approval.json",
        "activation_receipt.json",
        "activation_manifest.json",
    }
    try:
        names = {entry.name for entry in directory.iterdir() if entry.is_file()}
        if names != required:
            raise ValueError("activation bundle files differ")
        content = {name: (directory / name).read_bytes() for name in required}
        values = {name: json.loads(raw.decode("utf-8")) for name, raw in content.items()}
        _validate_activation_values(values, content)
        return {"bytes": content, "values": values}
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
        RulesError,
    ) as exc:
        raise DataModelError(
            "RULESET_REGISTRY_INTEGRITY", "activation bundle failed integrity validation"
        ) from exc


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DataModelError("RULESET_REGISTRY_INTEGRITY", "activation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataModelError(
            "RULESET_REGISTRY_INTEGRITY", "activation timestamp is invalid"
        ) from exc
    return require_utc(parsed)


class RulesRegistryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def import_activation_bundle(self, directory: Path) -> UUID:
        bundle = _read_activation_bundle(directory)
        content: Mapping[str, bytes] = bundle["bytes"]
        values: Mapping[str, Mapping[str, Any]] = bundle["values"]
        verified = values["verified_ruleset.json"]
        active = values["active_ruleset.json"]
        approval = values["approval.json"]
        receipt = values["activation_receipt.json"]
        manifest = values["activation_manifest.json"]
        identity = (verified.get("ruleset_id"), verified.get("ruleset_version"))
        if (
            identity != (active.get("ruleset_id"), active.get("ruleset_version"))
            or identity != (approval.get("ruleset_id"), approval.get("ruleset_version"))
            or identity != (receipt.get("ruleset_id"), receipt.get("ruleset_version"))
            or identity != (manifest.get("ruleset_id"), manifest.get("ruleset_version"))
            or not all(isinstance(item, str) and item for item in identity)
        ):
            raise DataModelError(
                "RULESET_REGISTRY_INTEGRITY", "activation bundle identity is inconsistent"
            )
        ruleset_id, ruleset_version = identity
        source_hash = verified.get("ruleset_hash")
        if not isinstance(source_hash, str) or len(source_hash) != 64:
            raise DataModelError(
                "RULESET_REGISTRY_INTEGRITY", "activation bundle source hash is invalid"
            )
        try:
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {
                    "identity": json.dumps(
                        [ruleset_id, ruleset_version], separators=(",", ":"), ensure_ascii=True
                    )
                },
            )
            existing = (
                self.session.execute(
                    select(ruleset_artifact).where(
                        ruleset_artifact.c.ruleset_id == ruleset_id,
                        ruleset_artifact.c.ruleset_version == ruleset_version,
                    )
                )
                .mappings()
                .one_or_none()
            )
            artifact_hash = hashlib.sha256(content["verified_ruleset.json"]).hexdigest()
            if existing is not None:
                if (
                    existing["source_ruleset_hash"] != source_hash
                    or existing["artifact_sha256"] != artifact_hash
                ):
                    raise DataModelError(
                        "RULESET_REGISTRY_INTEGRITY",
                        "a conflicting ruleset bundle already exists",
                    )
                artifact_id = _uuid(existing["ruleset_artifact_id"])
            else:
                artifact_id = _uuid(
                    self.session.execute(
                        insert(ruleset_artifact)
                        .values(
                            ruleset_id=ruleset_id,
                            ruleset_version=ruleset_version,
                            schema_version=verified.get("schema_version"),
                            source_ruleset_hash=source_hash,
                            artifact_uri=(directory / "verified_ruleset.json").as_posix(),
                            artifact_sha256=artifact_hash,
                            ruleset_status=verified.get("status"),
                            registered_at=_parse_utc(receipt.get("activated_at")),
                        )
                        .returning(ruleset_artifact.c.ruleset_artifact_id)
                    ).scalar_one()
                )
            active_hash = active.get("ruleset_hash")
            approval_hash = hashlib.sha256(content["approval.json"]).hexdigest()
            manifest_hash = hashlib.sha256(content["activation_manifest.json"]).hexdigest()
            existing_activation = (
                self.session.execute(
                    select(ruleset_activation).where(
                        ruleset_activation.c.ruleset_artifact_id == artifact_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            activation_values = {
                "active_ruleset_hash": active_hash,
                "approval_sha256": approval_hash,
                "activation_manifest_sha256": manifest_hash,
                "approval_uri": (directory / "approval.json").as_posix(),
                "activation_manifest_uri": (directory / "activation_manifest.json").as_posix(),
                "approved_by": approval.get("approved_by"),
                "approved_at": _parse_utc(approval.get("approved_at")),
                "activated_at": _parse_utc(receipt.get("activated_at")),
            }
            if existing_activation is not None:
                content_keys = {
                    "active_ruleset_hash",
                    "activation_manifest_sha256",
                    "approval_sha256",
                    "approved_at",
                    "approved_by",
                    "activated_at",
                }
                if any(existing_activation[key] != activation_values[key] for key in content_keys):
                    raise DataModelError(
                        "RULESET_REGISTRY_INTEGRITY",
                        "a conflicting ruleset activation already exists",
                    )
                return _uuid(existing_activation["ruleset_activation_id"])
            return _uuid(
                self.session.execute(
                    insert(ruleset_activation)
                    .values(ruleset_artifact_id=artifact_id, **activation_values)
                    .returning(ruleset_activation.c.ruleset_activation_id)
                ).scalar_one()
            )
        except DataModelError:
            raise
        except DBAPIError as exc:
            raise translate_database_error(exc) from exc
