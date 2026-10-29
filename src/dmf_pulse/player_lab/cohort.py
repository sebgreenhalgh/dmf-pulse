"""Complete preregistered player populations and original synthetic custody.

This companion protocol does not change any accepted v1 artifact or admit real
sources. The in-memory clock is an owned synthetic simulation, never proof of
the issue time of a real forecast.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.player_lab.contracts import (
    Experiment,
    FinalPlayerOutcome,
    FrozenForecast,
    PlayerForecast,
    PlayerKey,
    Sealed,
    SourceRef,
)
from dmf_pulse.player_lab.evaluation import MemoryLedger
from dmf_pulse.player_lab.rights import require_sources


class CohortProtocol(Sealed):
    schema_version: Literal["player-cohort-protocol-v1"] = "player-cohort-protocol-v1"
    cohort_id: str
    classification: Literal["OWNED_SYNTHETIC_FULL_REGISTERED_POPULATION"] = (
        "OWNED_SYNTHETIC_FULL_REGISTERED_POPULATION"
    )
    registered_at: datetime
    experiment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: tuple[PlayerKey, ...]
    model_ids: tuple[str, ...]
    sources: tuple[SourceRef, ...]
    inclusion: Literal["ALL_REGISTERED_PLAYERS_EACH_REGISTERED_GAMEWEEK"] = (
        "ALL_REGISTERED_PLAYERS_EACH_REGISTERED_GAMEWEEK"
    )
    missingness: Literal["BLOCK_ENTIRE_COHORT_NO_OUTCOME_DEPENDENT_DROPS"] = (
        "BLOCK_ENTIRE_COHORT_NO_OUTCOME_DEPENDENT_DROPS"
    )
    correction_policy: Literal["ONE_EXPLICIT_COMPLETE_REVISION_PER_GAMEWEEK"] = (
        "ONE_EXPLICIT_COMPLETE_REVISION_PER_GAMEWEEK"
    )
    baseline_policy: Literal["B0_B5_AVAILABILITY_SEPARATE_FROM_ZERO_DIAGNOSTIC"] = (
        "B0_B5_AVAILABILITY_SEPARATE_FROM_ZERO_DIAGNOSTIC"
    )
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"

    @model_validator(mode="after")
    def complete_population(self) -> Self:
        ids = tuple(item.target_id() for item in self.targets)
        if not ids or ids != tuple(sorted(set(ids))):
            raise ValueError("canonical nonzero unique target population required")
        if self.model_ids != tuple(sorted(set(self.model_ids))) or len(self.model_ids) != 2:
            raise ValueError("two canonical preregistered models required")
        if len({item.season for item in self.targets}) != 1:
            raise ValueError("one season per cohort")
        populations = {
            gw: {item.player_id for item in self.targets if item.gameweek == gw}
            for gw in {item.gameweek for item in self.targets}
        }
        if any(value != next(iter(populations.values())) for value in populations.values()):
            raise ValueError("every registered player required in every registered Gameweek")
        if not self.sources:
            raise ValueError("explicit dependency scope required")
        return self


class ForecastCohort(Sealed):
    schema_version: Literal["player-forecast-cohort-v1"] = "player-forecast-cohort-v1"
    protocol: CohortProtocol
    experiment: Experiment
    forecasts: tuple[FrozenForecast, ...]

    @model_validator(mode="after")
    def exact_registered_population(self) -> Self:
        protocol, experiment = self.protocol, self.experiment
        target_ids = tuple(item.target_id() for item in protocol.targets)
        if (
            experiment.semantic_sha256 != protocol.experiment_sha256
            or experiment.registered_at != protocol.registered_at
            or experiment.target_ids != target_ids
            or experiment.dataset_mode != "SYNTHETIC"
            or protocol.model_ids
            != tuple(sorted((experiment.champion_id, experiment.challenger_id)))
        ):
            raise ValueError("cohort differs from original experiment")
        identities = tuple(
            (item.forecast.model_id, item.forecast.key.target_id()) for item in self.forecasts
        )
        expected = tuple((model, target) for model in protocol.model_ids for target in target_ids)
        if identities != expected:
            raise ValueError("complete canonical model/target product required")
        for item in self.forecasts:
            forecast = item.forecast
            if (
                forecast.dataset_mode != "SYNTHETIC"
                or forecast.key not in protocol.targets
                or forecast.generated_at < protocol.registered_at
                or forecast.sources != protocol.sources
            ):
                raise ValueError("forecast differs from frozen population or dependency scope")
        return self


class FinalCohort(Sealed):
    schema_version: Literal["player-final-cohort-v1"] = "player-final-cohort-v1"
    forecast_cohort_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labels: tuple[FinalPlayerOutcome, ...]

    @model_validator(mode="after")
    def one_complete_vintage(self) -> Self:
        targets = tuple(item.key.target_id() for item in self.labels)
        if not targets or targets != tuple(sorted(set(targets))):
            raise ValueError("canonical unique final-label targets required")
        for gameweek in {item.key.gameweek for item in self.labels}:
            group = tuple(item for item in self.labels if item.key.gameweek == gameweek)
            if len({(item.revision, item.source, item.finalized_at) for item in group}) != 1:
                raise ValueError("mixed correction vintages forbidden")
        return self


class CohortCustody(Protocol):
    def verify_cohort(self, value: ForecastCohort) -> None: ...
    def verify_frozen(self, value: FrozenForecast) -> None: ...
    def verify_experiment(self, value: Experiment) -> None: ...


class SyntheticCohortLedger:
    """Two-phase append-only original custody; unavailable for real issuance."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._ledger = MemoryLedger(clock=clock)
        self._protocol: CohortProtocol | None = None
        self._experiment: Experiment | None = None
        self._cohort: ForecastCohort | None = None

    def register(self, protocol: CohortProtocol, experiment: Experiment) -> None:
        protocol = CohortProtocol.model_validate_json(protocol.model_dump_json())
        experiment = Experiment.model_validate_json(experiment.model_dump_json())
        require_sources(protocol.sources, RightsCapability.DERIVED_STORAGE)
        if (
            self._protocol is not None
            or protocol.registered_at != self._clock()
            or experiment.registered_at != protocol.registered_at
            or experiment.semantic_sha256 != protocol.experiment_sha256
        ):
            raise ValueError("protocol requires original preregistration custody")
        self._ledger.register_experiment(experiment)
        self._protocol, self._experiment = protocol, experiment

    def freeze(self, value: PlayerForecast) -> FrozenForecast:
        if self._protocol is None or self._cohort is not None:
            raise ValueError("freeze requires open registered cohort")
        if (
            value.key not in self._protocol.targets
            or value.model_id not in self._protocol.model_ids
            or value.sources != self._protocol.sources
        ):
            raise ValueError("forecast not in preregistered population")
        return self._ledger.freeze(value)

    def close(self, cohort: ForecastCohort) -> None:
        cohort = ForecastCohort.model_validate_json(cohort.model_dump_json())
        if self._cohort is not None or (cohort.protocol, cohort.experiment) != (
            self._protocol,
            self._experiment,
        ):
            raise ValueError("cohort substitution or repeated closure forbidden")
        for forecast in cohort.forecasts:
            self._ledger.verify_frozen(forecast)
        self._cohort = cohort

    def verify_cohort(self, value: ForecastCohort) -> None:
        if self._cohort != value:
            raise ValueError("cohort lacks original custody")

    def verify_frozen(self, value: FrozenForecast) -> None:
        self._ledger.verify_frozen(value)

    def verify_experiment(self, value: Experiment) -> None:
        self._ledger.verify_experiment(value)

    def record_outcome(self, value: FinalPlayerOutcome) -> None:
        if self._cohort is None:
            raise ValueError("outcomes cannot precede completed forecast custody")
        self._ledger.record_outcome(value)
