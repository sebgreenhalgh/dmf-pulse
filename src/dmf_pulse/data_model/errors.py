"""Typed, secret-safe data-model failures and PostgreSQL translation."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError, IntegrityError

from dmf_pulse.database.errors import DatabaseError

OVERLAP_CONSTRAINTS = {
    "ex_external_identifier_current_accepted",
    "ex_entity_alias_current_preferred",
    "ex_player_team_membership_current",
    "ex_fixture_revision_current",
    "ex_fixture_gameweek_assignment_current",
}
ENTITY_TYPE_CONSTRAINTS = {
    "fk_competition_canonical_type",
    "fk_season_canonical_type",
    "fk_team_canonical_type",
    "fk_player_canonical_type",
    "fk_fixture_canonical_type",
    "fk_gameweek_canonical_type",
    "fk_provider_canonical_type",
    "fk_external_identifier_canonical_type",
}
TEMPORAL_RANGE_CONSTRAINTS = {
    "ck_external_identifier_valid_range",
    "ck_external_identifier_system_range",
    "ck_entity_alias_valid_range",
    "ck_entity_alias_system_range",
    "ck_membership_valid_range",
    "ck_membership_system_range",
    "ck_fixture_revision_valid_range",
    "ck_fixture_revision_system_range",
    "ck_assignment_valid_range",
    "ck_assignment_system_range",
}


class DataModelError(DatabaseError):
    """Public data-model failure with a stable code and no database text."""


def translate_database_error(error: DBAPIError) -> DataModelError:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    sqlstate = getattr(original, "sqlstate", None)
    message = getattr(diagnostic, "message_primary", "")
    if constraint in OVERLAP_CONSTRAINTS or sqlstate == "23P01":
        return DataModelError("TEMPORAL_OVERLAP", "a current temporal fact overlaps")
    if (
        constraint in ENTITY_TYPE_CONSTRAINTS and "update or delete" not in message.casefold()
    ) or message == "ENTITY_TYPE_MISMATCH":
        return DataModelError("ENTITY_TYPE_MISMATCH", "canonical entity type does not match")
    if constraint in TEMPORAL_RANGE_CONSTRAINTS or message == "TEMPORAL_RANGE_INVALID":
        return DataModelError("TEMPORAL_RANGE_INVALID", "temporal range is invalid")
    if message == "TEMPORAL_SUPERSESSION_CONFLICT":
        return DataModelError(
            "TEMPORAL_SUPERSESSION_CONFLICT", "temporal version cannot be superseded"
        )
    if message == "IMMUTABLE_RECORD":
        return DataModelError("IMMUTABLE_RECORD", "immutable record cannot be changed")
    if isinstance(error, IntegrityError):
        return DataModelError("DATABASE_CONSTRAINT_VIOLATION", "database constraint rejected data")
    return DataModelError("DATABASE_UNAVAILABLE", "database operation failed")
