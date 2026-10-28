"""Strict existing match metadata policy with finite, value-free failure localisation."""

from __future__ import annotations

from typing import Any

from dmf_pulse.evaluation.p01_fallback_context import P01FallbackContext
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    METADATA_REASONS,
    DiagnosticProgress,
    MetadataCategory,
    MetadataField,
    ReasonFailure,
    SafeMetadataFailure,
)


def require_match_metadata(
    row: dict[str, Any], *, context: P01FallbackContext, diagnostics: DiagnosticProgress | None
) -> None:
    """Preserve equality/type guards; never retain values, identifiers or row positions."""

    def refuse(field: MetadataField, category: MetadataCategory) -> None:
        if diagnostics is not None:
            diagnostics.update(metadata_failure=SafeMetadataFailure(field=field, category=category))
        raise ReasonFailure(METADATA_REASONS[field])

    def check(obj: dict[str, Any], key: str, expected: int | str, field: MetadataField) -> None:
        if key not in obj:
            refuse(field, MetadataCategory.MISSING)
        if type(obj[key]) is not type(expected):
            refuse(field, MetadataCategory.WRONG_TYPE)
        if obj[key] != expected:
            refuse(field, MetadataCategory.MISMATCH)

    check(row, "leagueId", context.league_id, MetadataField.LEAGUE_ID)
    check(row, "leagueShortcut", context.league_shortcut, MetadataField.LEAGUE_SHORTCUT)
    check(row, "leagueSeason", context.league_season, MetadataField.LEAGUE_SEASON)
    # Legacy A02 compatibility restriction, not a claim that the name is a canonical key.
    # Removing it remains PROPOSED_UNAPPROVED in A03-D2.
    check(row, "leagueName", context.league_name, MetadataField.DISPLAY_NAME)
    if "group" not in row:
        refuse(MetadataField.GROUP, MetadataCategory.MISSING)
    group = row["group"]
    if not isinstance(group, dict):
        refuse(MetadataField.GROUP, MetadataCategory.WRONG_TYPE)
    check(group, "groupOrderID", context.matchday, MetadataField.MATCHDAY)
