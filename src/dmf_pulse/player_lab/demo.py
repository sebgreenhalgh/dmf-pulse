"""Two-phase synthetic forecast custody/outcome demonstration; never a real cohort."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from typing import NamedTuple

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.player_lab.actuals import FinalityContext
from dmf_pulse.player_lab.contracts import (
    Experiment,
    FinalPlayerOutcome,
    FrozenForecast,
    PlayerForecast,
    SourceRef,
    seal,
)
from dmf_pulse.player_lab.evaluation import (
    MemoryLedger,
    PairedHoldout,
    PlayerScorecard,
    compare_holdout,
    evaluate_players,
)
from dmf_pulse.player_lab.rights import ingest_offline_actuals, profile_identity


class SyntheticEvaluation(NamedTuple):
    custody: MemoryLedger
    experiment: Experiment
    forecasts: tuple[FrozenForecast, ...]
    labels: tuple[FinalPlayerOutcome, ...]
    scorecard: PlayerScorecard
    holdout: PairedHoldout


def synthetic_forecasts() -> tuple[
    Experiment, tuple[PlayerForecast, ...], tuple[FinalityContext, ...]
]:
    root = files("dmf_pulse.player_lab.resources")
    registry = json.loads(root.joinpath("source-registry.json").read_text(encoding="utf-8"))
    inputs = json.loads(root.joinpath("forecast-inputs.json").read_text(encoding="utf-8"))
    source_id = "ACCEL002_SYNTHETIC_FORECAST_INPUTS"
    registered = registry["sources"][source_id]
    source = SourceRef(
        source_id=source_id,
        payload_sha256=registered["payload_sha256"],
        profile_id=registered["profile_id"],
        profile_sha256=profile_identity(load_rights_profiles()[registered["profile_id"]]),
        observed_at=datetime.fromisoformat(registered["observed_at"]),
        usable_at=datetime.fromisoformat(registered["usable_at"]),
    )
    contexts = tuple(
        FinalityContext.model_validate_json(root.joinpath(f"context-gw{gw}.json").read_bytes())
        for gw in inputs["gameweeks"]
    )
    champion_id, challenger_id = "SYNTHETIC_REGISTERED_CHAMPION", "SYNTHETIC_REGISTERED_CHALLENGER"
    experiment = seal(
        Experiment.model_construct(
            experiment_id="ACCEL002_SYNTHETIC_PLAYER_HOLDOUT",
            registered_at=datetime(2026, 8, 31, tzinfo=UTC),
            dataset_mode="SYNTHETIC",
            champion_id=champion_id,
            challenger_id=challenger_id,
            target_ids=tuple(
                sorted(player.key.target_id() for context in contexts for player in context.players)
            ),
            holdout_start_gameweek=3,
            semantic_sha256="0" * 64,
        )
    )
    forecasts = []
    for context in contexts:
        generated = datetime(2026, 9, 1, 12, tzinfo=UTC) + timedelta(
            days=(context.gameweek - 2) * 7
        )
        deadline = generated + timedelta(days=3, hours=5, minutes=30)
        for model_id, pmf_key in ((champion_id, "champion_pmf"), (challenger_id, "challenger_pmf")):
            pmf = {int(points): Decimal(value) for points, value in inputs[pmf_key].items()}
            mean = sum((Decimal(points) * mass for points, mass in pmf.items()), Decimal(0))
            for index, player in enumerate(context.players):
                components = dict.fromkeys(POINT_COMPONENT_NAMES, Decimal(0))
                components["appearance"] = Decimal(2)
                components["assists"] = mean - 2
                forecast = seal(
                    PlayerForecast.model_construct(
                        key=player.key,
                        dataset_mode="SYNTHETIC",
                        model_id=model_id,
                        model_version_ids=("SYNTHETIC_ANALYTIC_PMF_V1",),
                        code_sha="a" * 40,
                        ruleset_sha256=canonical_sha256(
                            {"synthetic_rule_fixture": "13_COMPONENT_RECONCILIATION_ONLY"}
                        ),
                        source_summary_sha256=canonical_sha256({"synthetic_pmf": inputs[pmf_key]}),
                        input_sha256=source.payload_sha256,
                        mean=mean,
                        pmf=pmf,
                        components=components,
                        expected_minutes=Decimal(inputs["minutes"][index]),
                        position=inputs["positions"][index],
                        generated_at=generated,
                        information_cutoff=generated,
                        deadline_at=deadline,
                        label_finality_cutoff=deadline + timedelta(days=14),
                        sources=(source,),
                        semantic_sha256="0" * 64,
                    )
                )
                forecasts.append(forecast)
    return experiment, tuple(forecasts), contexts


def synthetic_evaluation() -> SyntheticEvaluation:
    experiment, raw_forecasts, contexts = synthetic_forecasts()
    root = files("dmf_pulse.player_lab.resources")
    now = experiment.registered_at
    ledger = MemoryLedger(clock=lambda: now)
    ledger.register_experiment(experiment)
    forecasts = []
    for forecast in raw_forecasts:
        now = forecast.generated_at + timedelta(minutes=1)
        forecasts.append(ledger.freeze(forecast))
    # Forecast values and custody are fixed before any outcome body is opened.
    now = max(context.usable_at for context in contexts)
    labels = tuple(
        label
        for context in contexts
        for label in ingest_offline_actuals(
            root.joinpath(f"actuals-gw{context.gameweek}.json").read_bytes(), context
        ).labels
    )
    for label in labels:
        ledger.record_outcome(label)
    champion = tuple(item for item in forecasts if item.forecast.model_id == experiment.champion_id)
    challenger = tuple(
        item for item in forecasts if item.forecast.model_id == experiment.challenger_id
    )
    return SyntheticEvaluation(
        custody=ledger,
        experiment=experiment,
        forecasts=tuple(forecasts),
        labels=labels,
        scorecard=evaluate_players(champion, labels, custody=ledger),
        holdout=compare_holdout(experiment, champion, challenger, labels, custody=ledger),
    )
