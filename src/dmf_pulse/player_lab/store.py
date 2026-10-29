"""Transactional PostgreSQL research custody, with rights checks before connection."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.dialects.postgresql import insert

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import player_research_artifact, player_research_pair
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.player_lab.contracts import (
    Experiment,
    FinalPlayerOutcome,
    FrozenForecast,
    Sealed,
    SourceRef,
)
from dmf_pulse.player_lab.demo import SyntheticEvaluation
from dmf_pulse.player_lab.evaluation import PlayerScorecard, compare_holdout, evaluate_players
from dmf_pulse.player_lab.rights import (
    require_qualified_forecast,
    require_qualified_outcome,
    require_sources,
)


def _refs(sources: Iterable[SourceRef]) -> list[dict[str, object]]:
    values = {
        canonical_sha256(item.model_dump(mode="json")): item.model_dump(mode="json")
        for item in sources
    }
    return [values[key] for key in sorted(values)]


@dataclass(frozen=True)
class _DatabaseCustody:
    forecasts: tuple[FrozenForecast, ...]
    experiment: Experiment

    def verify_frozen(self, value: FrozenForecast) -> None:
        if value not in self.forecasts:
            raise ValueError("forecast not in authenticated database custody")

    def verify_experiment(self, value: Experiment) -> None:
        if value != self.experiment:
            raise ValueError("experiment not in authenticated database custody")


class PostgresResearchLedger:
    """No connection or storage side effects at construction/import."""

    def __init__(self, engine_factory: Callable[[], Engine]) -> None:
        self._engine_factory = engine_factory

    @staticmethod
    def _put(
        connection: Connection,
        value: Sealed,
        *,
        kind: str,
        sources: list[dict[str, object]],
        target: str | None = None,
        model: str | None = None,
        experiment: str | None = None,
        revision: int = 0,
        supersedes: str | None = None,
    ) -> None:
        payload = value.model_dump(mode="json")
        connection.execute(
            insert(player_research_artifact)
            .values(
                artifact_sha256=value.semantic_sha256,
                kind=kind,
                dataset_mode="SYNTHETIC",
                target_id=target,
                model_id=model,
                experiment_sha256=experiment,
                revision=revision,
                supersedes_sha256=supersedes,
                source_refs=sources,
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
            raise ValueError("research content collision")

    def persist(self, evaluation: SyntheticEvaluation) -> str:
        # Every dependency is checked before invoking even the connection factory.
        evaluation.custody.verify_experiment(evaluation.experiment)
        for frozen in evaluation.forecasts:
            evaluation.custody.verify_frozen(frozen)
            require_qualified_forecast(frozen.forecast)
        for label in evaluation.labels:
            require_qualified_outcome(label)
        experiment = evaluation.experiment
        champion = tuple(
            item
            for item in evaluation.forecasts
            if item.forecast.model_id == experiment.champion_id
        )
        challenger = tuple(
            item
            for item in evaluation.forecasts
            if item.forecast.model_id == experiment.challenger_id
        )
        scorecard = evaluate_players(champion, evaluation.labels, custody=evaluation.custody)
        holdout = compare_holdout(
            experiment, champion, challenger, evaluation.labels, custody=evaluation.custody
        )
        if scorecard != evaluation.scorecard or holdout != evaluation.holdout:
            raise ValueError("supplied score differs from accepted metric kernels")
        sources = _refs(
            (
                *[source for item in champion for source in item.forecast.sources],
                *[item.source for item in evaluation.labels],
            )
        )
        engine = self._engine_factory()
        with engine.begin() as connection:
            self._put(connection, experiment, kind="EXPERIMENT", sources=[])
            for frozen in evaluation.forecasts:
                forecast = frozen.forecast
                self._put(
                    connection,
                    frozen,
                    kind="FORECAST",
                    sources=_refs(forecast.sources),
                    target=forecast.key.target_id(),
                    model=forecast.model_id,
                    experiment=experiment.semantic_sha256,
                )
            for label in evaluation.labels:
                self._put_label(connection, label)
            self._put(
                connection,
                scorecard,
                kind="SCORECARD",
                sources=sources,
                model=scorecard.model_id,
                experiment=experiment.semantic_sha256,
            )
            by_target = {item.key.target_id(): item for item in evaluation.labels}
            for frozen in champion:
                target = frozen.forecast.key.target_id()
                connection.execute(
                    insert(player_research_pair)
                    .values(
                        score_sha256=scorecard.semantic_sha256,
                        target_id=target,
                        forecast_sha256=frozen.semantic_sha256,
                        label_sha256=by_target[target].semantic_sha256,
                    )
                    .on_conflict_do_nothing()
                )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return scorecard.semantic_sha256

    @classmethod
    def _put_label(cls, connection: Connection, label: FinalPlayerOutcome) -> None:
        cls._put(
            connection,
            label,
            kind="LABEL",
            sources=_refs((label.source,)),
            target=label.key.target_id(),
            revision=label.revision,
            supersedes=label.supersedes_sha256,
        )

    def append_correction(self, label: FinalPlayerOutcome) -> None:
        label = FinalPlayerOutcome.model_validate_json(label.model_dump_json())
        require_qualified_outcome(label)
        if label.revision == 0:
            raise ValueError("correction needs explicit predecessor")
        engine = self._engine_factory()
        with engine.begin() as connection:
            self._put_label(connection, label)

    def evaluate_stored(self, score_sha256: str) -> PlayerScorecard:
        if len(score_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in score_sha256
        ):
            raise ValueError("invalid score identity")
        engine = self._engine_factory()
        with engine.connect() as connection:
            score_row = (
                connection.execute(
                    select(player_research_artifact).where(
                        player_research_artifact.c.artifact_sha256 == score_sha256,
                        player_research_artifact.c.kind == "SCORECARD",
                    )
                )
                .mappings()
                .one()
            )
            sources = tuple(
                SourceRef.model_validate_json(json.dumps(item)) for item in score_row["source_refs"]
            )
            require_sources(sources, RightsCapability.DERIVED_STORAGE)
            score = PlayerScorecard.model_validate_json(json.dumps(score_row["payload"]))
            rows = (
                connection.execute(
                    select(player_research_pair).where(
                        player_research_pair.c.score_sha256 == score_sha256
                    )
                )
                .mappings()
                .all()
            )

            def artifact(sha: str) -> Any:
                return connection.execute(
                    select(player_research_artifact.c.payload).where(
                        player_research_artifact.c.artifact_sha256 == sha
                    )
                ).scalar_one()

            experiment = Experiment.model_validate_json(
                json.dumps(artifact(score_row["experiment_sha256"]))
            )
            forecasts = tuple(
                FrozenForecast.model_validate_json(json.dumps(artifact(row["forecast_sha256"])))
                for row in rows
            )
            labels = tuple(
                FinalPlayerOutcome.model_validate_json(json.dumps(artifact(row["label_sha256"])))
                for row in rows
            )
        result = evaluate_players(
            forecasts, labels, custody=_DatabaseCustody(forecasts, experiment)
        )
        if result.semantic_sha256 != score.semantic_sha256:
            raise ValueError("stored score does not reproduce")
        return result
