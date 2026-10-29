"""Authenticated companion diagnostics composed from existing metric kernels."""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from dmf_pulse.evaluation.models import PointMetricResult
from dmf_pulse.evaluation.point_metrics import score_forecast
from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES
from dmf_pulse.player_lab.actuals import FinalityContext, LivePayload
from dmf_pulse.player_lab.contracts import (
    FinalPlayerOutcome,
    FrozenForecast,
    LabModel,
    Sealed,
    Sha,
    SourceRef,
    seal,
)
from dmf_pulse.player_lab.rights import ingest_offline_actuals, require_qualified_outcome


class FixtureMinutes(LabModel):
    fixture_id: UUID
    actual_minutes: Annotated[StrictInt, Field(ge=0, le=90)]
    observed_start: None = None
    start_status: Literal["UNAVAILABLE_EXPLICIT_START_LABEL"] = "UNAVAILABLE_EXPLICIT_START_LABEL"


class MinutesSidecar(Sealed):
    schema_version: Literal["player-minutes-diagnostic-sidecar-v1"] = (
        "player-minutes-diagnostic-sidecar-v1"
    )
    target_id: Sha
    outcome_sha256: Sha
    source: SourceRef
    fixtures: tuple[FixtureMinutes, ...]
    observed_minutes: Annotated[StrictInt, Field(ge=0)]
    evidence: Literal["EXACT_QUALIFIED_RAW_COUNTS_NOT_POINTS_INFERENCE"] = (
        "EXACT_QUALIFIED_RAW_COUNTS_NOT_POINTS_INFERENCE"
    )

    @model_validator(mode="after")
    def reconciled_counts(self) -> Self:
        identities = tuple(str(item.fixture_id) for item in self.fixtures)
        if identities != tuple(sorted(set(identities))) or self.observed_minutes != sum(
            item.actual_minutes for item in self.fixtures
        ):
            raise ValueError("minutes sidecar fixture counts do not reconcile")
        return self


class MinutesDiagnostics(LabModel):
    expected_count: int
    scored_count: int
    unavailable_forecast_count: int
    mean_minutes: PointMetricResult | None
    start_probability_status: Literal["UNAVAILABLE_FROZEN_PROBABILITIES_AND_START_LABELS"] = (
        "UNAVAILABLE_FROZEN_PROBABILITIES_AND_START_LABELS"
    )
    sixty_plus_status: Literal["UNAVAILABLE_FROZEN_FIXTURE_PROBABILITIES"] = (
        "UNAVAILABLE_FROZEN_FIXTURE_PROBABILITIES"
    )
    sidecars: tuple[MinutesSidecar, ...]


def qualified_minutes(label: FinalPlayerOutcome) -> MinutesSidecar:
    """Read original qualified count values; never fabricate starts from minutes."""
    label = FinalPlayerOutcome.model_validate_json(label.model_dump_json())
    require_qualified_outcome(label)
    root = files("dmf_pulse.player_lab.resources")
    registry = json.loads(root.joinpath("source-registry.json").read_bytes())
    record = registry["sources"][label.source.source_id]
    context = FinalityContext.model_validate_json(
        root.joinpath(record["context_resource"]).read_bytes()
    )
    body = root.joinpath(record["resource"]).read_bytes()
    quality = ingest_offline_actuals(body, context)
    if label not in quality.labels:
        raise ValueError("minutes sidecar differs from original outcome")
    canonical = next(item for item in context.players if item.key == label.key)
    payload = LivePayload.model_validate_json(body)
    player = next(item for item in payload.elements if item.id == canonical.official_id)
    fixtures = tuple(
        sorted(
            (
                FixtureMinutes(
                    fixture_id=context.fixture_mapping[item.fixture],
                    actual_minutes=next(
                        value.value for value in item.stats if value.identifier == "minutes"
                    ),
                )
                for item in player.explain
            ),
            key=lambda item: str(item.fixture_id),
        )
    )
    return seal(
        MinutesSidecar.model_construct(
            target_id=label.key.target_id(),
            outcome_sha256=label.semantic_sha256,
            source=label.source,
            fixtures=fixtures,
            observed_minutes=sum(item.actual_minutes for item in fixtures),
            semantic_sha256="0" * 64,
        )
    )


def component_metrics(
    forecasts: tuple[FrozenForecast, ...], labels: tuple[FinalPlayerOutcome, ...]
) -> dict[str, PointMetricResult]:
    """The caller first authenticates custody and exact joins; kernels do all math."""
    by_target = {item.key.target_id(): item for item in labels}
    return {
        component: score_forecast(
            tuple(item.forecast.components[component] for item in forecasts),
            tuple(
                Decimal(by_target[item.forecast.key.target_id()].components[component])
                for item in forecasts
            ),
        )
        for component in POINT_COMPONENT_NAMES
    }


def minutes_diagnostics(
    forecasts: tuple[FrozenForecast, ...], labels: tuple[FinalPlayerOutcome, ...]
) -> MinutesDiagnostics:
    by_target = {item.key.target_id(): item for item in labels}
    sidecars = tuple(
        qualified_minutes(by_target[item.forecast.key.target_id()]) for item in forecasts
    )
    eligible = tuple(
        (forecast.forecast.expected_minutes, sidecar.observed_minutes)
        for forecast, sidecar in zip(forecasts, sidecars, strict=True)
        if forecast.forecast.expected_minutes is not None
    )
    return MinutesDiagnostics(
        expected_count=len(forecasts),
        scored_count=len(eligible),
        unavailable_forecast_count=len(forecasts) - len(eligible),
        mean_minutes=score_forecast(
            tuple(pair[0] for pair in eligible), tuple(Decimal(pair[1]) for pair in eligible)
        )
        if eligible
        else None,
        sidecars=sidecars,
    )
