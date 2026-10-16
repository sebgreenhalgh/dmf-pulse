"""Read frozen score inputs without fitting, freezing or regenerating draws.

The accepted full forecast validator rederives its random coordinates. A02
instead authenticates the literal externally pinned original bytes and semantic
identity, then validates every stored field using the original component types.
This view never creates or persists a forecast and offers no generative path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.evaluation.team_strength_prospective import PublicFixtureForecast
from dmf_pulse.football_events.team_strength_model import TeamStrengthModelArtifactV1
from dmf_pulse.football_events.team_strength_parameter_draws import ParameterDrawSetV1
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorResult
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MODE,
    FixtureRegistry,
    ParsedSnapshot,
    SealedEvidence,
    StrengthEvidenceError,
    TeamStrengthHistoricalDatasetV1,
    authenticate,
)


class P01FrozenScoringView(SealedEvidence):
    """Strict stored representation, admitted operationally only by P01 byte pin."""

    schema_version: Literal["public-team-strength-prospective-forecast-v1"]
    data_class: Literal["PUBLIC_OPENFOOTBALL_TEAM_ONLY"]
    status: Literal["SHADOW_NOT_MODEL_INPUT"]
    production_active: Literal[False]
    forecast_origin: datetime
    frozen_at: datetime
    dataset_mode: MODE
    artifact: TeamStrengthModelArtifactV1
    draw_set: ParameterDrawSetV1
    fixture_registry: FixtureRegistry
    public_schedule: ParsedSnapshot
    training_dataset: TeamStrengthHistoricalDatasetV1
    league_baseline: CurrentScorePriorResult | None
    forecasts: tuple[PublicFixtureForecast, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def stored_structure(self) -> Self:
        ids = tuple(row.fixture.fixture_id for row in self.forecasts)
        registered = {row.fixture_id: row for row in self.fixture_registry.fixtures}
        if (
            ids != tuple(sorted(set(ids)))
            or not self.artifact.usable_at <= self.forecast_origin <= self.frozen_at
            or self.fixture_registry.semantic_sha256 != self.artifact.model.fixture_registry_sha256
            or self.training_dataset.semantic_sha256 != self.artifact.model.training_dataset_sha256
            or self.dataset_mode != self.artifact.model.dataset_mode
            or any(registered.get(row.fixture.fixture_id) != row.fixture for row in self.forecasts)
            or any(row.scheduled_date <= self.frozen_at.date() for row in self.forecasts)
            or any(
                tuple(item.product for item in row.distributions)
                != (
                    "LEAGUE_BASELINE",
                    "PLUG_IN_TEAM_STRENGTH_SHADOW",
                    "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW",
                )
                for row in self.forecasts
            )
        ):
            raise ValueError("stored forecast structure or nongenerative lineage differs")
        return self


def _read_pinned_representation(
    raw: bytes, *, expected_byte_sha256: str, expected_semantic_sha256: str
) -> P01FrozenScoringView:
    """Internal primitive; operational caller supplies only the approved P01 pins."""
    if hashlib.sha256(raw).hexdigest() != expected_byte_sha256:
        raise StrengthEvidenceError("P01_FORECAST_BYTE_IDENTITY_MISMATCH")
    return authenticate(P01FrozenScoringView.model_validate_json(raw), expected_semantic_sha256)
