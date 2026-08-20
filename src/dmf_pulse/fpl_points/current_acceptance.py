"""Fail-closed Checkpoint-2.5 review of the transient current projection handoff."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability import current_player_id
from dmf_pulse.fpl_points.current import CurrentFootballEventBundle
from dmf_pulse.fpl_points.current_points import CurrentFplPointsBundle
from dmf_pulse.ingestion.errors import IngestionError


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class CurrentProjectionAcceptanceReport(_FrozenModel):
    """Non-disclosing acceptance result; detailed official-FPL rows remain transient."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_PROJECTION_ACCEPTANCE"] = "GW1_CURRENT_PROJECTION_ACCEPTANCE"
    status: Literal["ACCEPTED_WITH_MATERIAL_LIMITATIONS", "BLOCKED"]
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    accepted_for_initial_squad: StrictBool
    blocker_codes: tuple[str, ...]
    warnings: tuple[str, ...] = Field(min_length=1)
    fixture_count: int = Field(gt=0)
    player_count: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    monte_carlo_stopping_result: Literal["PASS", "CONTINUE", "BLOCKED"]
    information_cutoff: datetime
    source_event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gameweek_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    player_points_capability_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    handcrafted_xp: Literal[False] = False
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_acceptance(self) -> CurrentProjectionAcceptanceReport:
        accepted = self.status == "ACCEPTED_WITH_MATERIAL_LIMITATIONS"
        if (
            self.accepted_for_initial_squad != accepted
            or accepted != (self.monte_carlo_stopping_result == "PASS")
            or bool(self.blocker_codes) == accepted
            or self.blocker_codes != tuple(sorted(set(self.blocker_codes)))
            or self.warnings != tuple(sorted(set(self.warnings)))
            or self.semantic_sha256 != _report_sha256(self)
        ):
            raise ValueError("current projection acceptance report is inconsistent")
        return self


def _report_sha256(value: CurrentProjectionAcceptanceReport) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def _revalidate(
    source: CurrentFootballEventBundle, projection: CurrentFplPointsBundle
) -> tuple[CurrentFootballEventBundle, CurrentFplPointsBundle]:
    try:
        return (
            CurrentFootballEventBundle.model_validate_json(source.model_dump_json()),
            CurrentFplPointsBundle.model_validate_json(projection.model_dump_json()),
        )
    except (ValueError, IngestionError) as exc:
        raise IngestionError(
            "PROJECTION_ACCEPTANCE_BLOCKED",
            "current projection inputs failed independent revalidation",
        ) from exc


def _official_player_material(source: CurrentFootballEventBundle) -> dict[str, tuple[Any, ...]]:
    availability = source.source_availability
    fpl = availability.source_market.source_input.fpl_input
    teams_by_hash = {team.identity.canonical_lookup_sha256: team for team in fpl.teams}
    projected_teams = {row.official_fpl_team_id: row for row in availability.team_projections}
    material: dict[str, tuple[Any, ...]] = {}
    for player in fpl.players:
        team = teams_by_hash.get(player.team_identity.canonical_lookup_sha256)
        if team is None or team.provider_team_id not in projected_teams:
            raise IngestionError(
                "PROJECTION_ACCEPTANCE_BLOCKED",
                "an official current player belongs to no projected target team",
            )
        team_projection = projected_teams[team.provider_team_id]
        player_id = str(current_player_id(player))
        if player_id in material:
            raise IngestionError(
                "PROJECTION_ACCEPTANCE_BLOCKED",
                "current official player identities collide",
            )
        stage7 = next(
            (
                row
                for row in team_projection.posterior_projection.players
                if row.player_id == player_id
            ),
            None,
        )
        if stage7 is None:
            raise IngestionError(
                "PROJECTION_ACCEPTANCE_BLOCKED",
                "an official current player has no Stage-7 projection",
            )
        material[player_id] = (player, team, team_projection, stage7)
    return material


def assess_current_projection(
    source: CurrentFootballEventBundle,
    projection: CurrentFplPointsBundle,
) -> CurrentProjectionAcceptanceReport:
    """Reconcile the full current path and expose only a hash/count acceptance result."""

    source, projection = _revalidate(source, projection)
    if (
        source.semantic_sha256 != projection.source_event_semantic_sha256
        or source.decision_information_at != projection.run_config.information_cutoff
    ):
        raise IngestionError(
            "PROJECTION_ACCEPTANCE_BLOCKED",
            "current projection is detached from its accepted event input or cutoff",
        )
    expected = _official_player_material(source)
    actual = {str(row.transient_player_id): row for row in projection.player_table}
    if set(expected) != set(actual) or len(actual) != len(projection.player_table):
        raise IngestionError(
            "PROJECTION_ACCEPTANCE_BLOCKED",
            "official-FPL and projected player universes differ",
        )
    for player_id, (player, team, team_projection, stage7) in expected.items():
        row = actual[player_id]
        if (
            row.official_fpl_player_id != player.provider_element_id
            or row.player_name != player.web_name
            or row.official_fpl_team_id != team.provider_team_id
            or row.team_name != team.official_name
            or row.position.value != player.position.value
            or row.current_price_tenths != player.current_price_tenths
            or row.transient_team_id != team_projection.transient_team_id
            or row.probability_appearance != stage7.p_appearance
            or row.probability_start != stage7.p_start
            or row.expected_minutes != stage7.expected_minutes
        ):
            raise IngestionError(
                "PROJECTION_ACCEPTANCE_BLOCKED",
                "current player identity, price, position, or minutes lineage differs",
            )

    diagnostics = projection.gameweek_projection.monte_carlo
    assert projection.gameweek_projection.result_sha256 is not None
    blockers = (
        ()
        if diagnostics.stopping_result == "PASS"
        else (f"UPSTREAM_MONTE_CARLO_{diagnostics.stopping_result}",)
    )
    warnings = tuple(
        sorted(
            {
                "CURRENT_PROJECTION_NON_PRODUCTION",
                "VERIFIED_RULESET_NOT_GLOBALLY_ACTIVE",
                *(
                    warning
                    for row in projection.player_table
                    for warning in row.uncertainty.limitations
                ),
            }
        )
    )
    values: dict[str, Any] = {
        "status": "BLOCKED" if blockers else "ACCEPTED_WITH_MATERIAL_LIMITATIONS",
        "accepted_for_initial_squad": not blockers,
        "blocker_codes": blockers,
        "warnings": warnings,
        "fixture_count": len(projection.fixture_projections),
        "player_count": len(projection.player_table),
        "scenario_count": len(projection.gameweek_projection.scenario_set.scenarios),
        "monte_carlo_stopping_result": diagnostics.stopping_result,
        "information_cutoff": projection.run_config.information_cutoff,
        "source_event_semantic_sha256": source.semantic_sha256,
        "projection_semantic_sha256": projection.semantic_sha256,
        "gameweek_result_sha256": projection.gameweek_projection.result_sha256,
        "ruleset_hash": projection.run_config.ruleset_hash,
        "player_points_capability_hash": projection.run_config.player_points_capability_hash,
    }
    provisional = CurrentProjectionAcceptanceReport.model_construct(
        **values, semantic_sha256="0" * 64
    )
    return CurrentProjectionAcceptanceReport(**values, semantic_sha256=_report_sha256(provisional))


__all__ = ["CurrentProjectionAcceptanceReport", "assess_current_projection"]
