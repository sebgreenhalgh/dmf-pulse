"""Read-only Stage-7 minutes provenance required by the Stage-8 score prior."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.football_events._decimal import (
    SHA256_PATTERN,
    canonical_json_sha256,
    format_utc,
    mapping,
    parse_utc,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TeamMinutesProjectionIdentity(_FrozenModel):
    """Immutable identity projection of an accepted Stage-7 team output.

    Stage 8 deliberately does not copy or reinterpret Stage-7 player mathematics. The
    upstream projection remains authoritative; this compact contract binds the score
    prior to its fixture, team, cutoff, model and semantic result identities.
    """

    schema_version: Literal["team-minutes-projection-v1"]
    fixture_id: str
    team_id: str
    as_of: datetime
    model_family: Literal["REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: Literal[256]
    scenario_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of(cls, value: object) -> datetime:
        return parse_utc(value, field_name="Stage-7 projection as_of")

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        for label, value in (("fixture_id", self.fixture_id), ("team_id", self.team_id)):
            try:
                UUID(value)
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"{label} must be a UUID") from exc
        return self

    @classmethod
    def from_projection(cls, projection: object) -> TeamMinutesProjectionIdentity:
        """Extract only accepted public identity fields from a Stage-7 projection."""

        body = mapping(projection, label="Stage-7 team minutes projection")
        return cls.model_validate(
            {
                "as_of": body.get("as_of"),
                "dataset_sha256": body.get("dataset_sha256"),
                "fixture_id": body.get("fixture_id"),
                "model_artifact_sha256": body.get("model_artifact_sha256"),
                "model_family": body.get("model_family"),
                "result_sha256": body.get("result_sha256"),
                "sample_count": body.get("sample_count"),
                "scenario_set_sha256": body.get("scenario_set_sha256"),
                "schema_version": body.get("schema_version"),
                "team_id": body.get("team_id"),
            }
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "as_of": format_utc(self.as_of),
            "dataset_sha256": self.dataset_sha256,
            "fixture_id": self.fixture_id,
            "model_artifact_sha256": self.model_artifact_sha256,
            "model_family": self.model_family,
            "result_sha256": self.result_sha256,
            "sample_count": self.sample_count,
            "scenario_set_sha256": self.scenario_set_sha256,
            "schema_version": self.schema_version,
            "team_id": self.team_id,
        }


class Stage7MinutesContext(_FrozenModel):
    """Home/away Stage-7 identities consumed by one Stage-8 fixture forecast."""

    schema_version: Literal["stage7-minutes-context-v1"] = "stage7-minutes-context-v1"
    home: TeamMinutesProjectionIdentity
    away: TeamMinutesProjectionIdentity

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if self.home.fixture_id != self.away.fixture_id:
            raise ValueError("Stage-7 home and away projections must share fixture_id")
        if self.home.team_id == self.away.team_id:
            raise ValueError("Stage-7 home and away projections must use distinct teams")
        if self.home.as_of != self.away.as_of:
            raise ValueError("Stage-7 home and away projections must share one as_of cutoff")
        return self

    @classmethod
    def from_projections(cls, home: object, away: object) -> Stage7MinutesContext:
        return cls.model_validate(
            {
                "home": TeamMinutesProjectionIdentity.from_projection(home),
                "away": TeamMinutesProjectionIdentity.from_projection(away),
            }
        )

    @property
    def source_as_of(self) -> datetime:
        return self.home.as_of

    @property
    def semantic_sha256(self) -> str:
        return canonical_json_sha256(self.public_dict())

    def public_dict(self) -> dict[str, Any]:
        return {
            "away": self.away.public_dict(),
            "home": self.home.public_dict(),
            "schema_version": self.schema_version,
        }


def validate_stage7_context(
    context: Stage7MinutesContext,
    *,
    fixture_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
    information_cutoff: datetime,
) -> None:
    """Fail closed unless Stage-7 identity and cutoff semantics match Stage 8."""

    if context.home.fixture_id != str(fixture_id):
        raise ValueError("Stage-7 minutes fixture_id does not match Stage-8 request")
    if context.home.team_id != str(home_team_id):
        raise ValueError("Stage-7 home team_id does not match Stage-8 request")
    if context.away.team_id != str(away_team_id):
        raise ValueError("Stage-7 away team_id does not match Stage-8 request")
    if context.source_as_of > information_cutoff:
        raise ValueError("POST_CUTOFF_MINUTES: Stage-7 projection is after Stage-8 cutoff")
    for identity in (context.home, context.away):
        for value in (
            identity.dataset_sha256,
            identity.model_artifact_sha256,
            identity.scenario_set_sha256,
            identity.result_sha256,
        ):
            if SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError("Stage-7 identity hash must be lowercase SHA-256")


__all__ = [
    "Stage7MinutesContext",
    "TeamMinutesProjectionIdentity",
    "validate_stage7_context",
]
