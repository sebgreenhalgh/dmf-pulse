"""Replay an owned, hash-qualified Stage-9 snapshot through prospective custody."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from typing import Literal, NamedTuple, Self

from pydantic import model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import GameweekPlayerProjectionSummary
from dmf_pulse.player_lab.actuals import FinalityContext
from dmf_pulse.player_lab.contracts import (
    FinalPlayerOutcome,
    FrozenForecast,
    PlayerForecast,
    PlayerKey,
    Sealed,
    Sha,
    SourceRef,
)
from dmf_pulse.player_lab.evaluation import MemoryLedger, PlayerScorecard, evaluate_players
from dmf_pulse.player_lab.rights import ingest_offline_actuals
from dmf_pulse.player_lab.snapshots import snapshot_projection

STAGE9_SOURCE_ID = "ACCEL002_OWNED_STAGE9_RUN"
STAGE9_OUTCOME_SOURCE_ID = "ACCEL002_OWNED_STAGE9_ACTUALS"


class Stage9SnapshotFixture(Sealed):
    """Captured output of the real synthetic one-command service, never live input."""

    schema_version: Literal["owned-stage9-snapshot-fixture-v1"] = "owned-stage9-snapshot-fixture-v1"
    classification: Literal["REPOSITORY_OWNED_SYNTHETIC_ONLY"] = "REPOSITORY_OWNED_SYNTHETIC_ONLY"
    origin: Literal["run_synthetic_recommendation(1, NullProgress())"] = (
        "run_synthetic_recommendation(1, NullProgress())"
    )
    key: PlayerKey
    official_player_id: int
    official_fixture_ids: tuple[int, ...]
    summary: GameweekPlayerProjectionSummary
    summary_sha256: Sha
    gameweek_result_sha256: Sha
    decision_sha256: Sha
    input_sha256: Sha
    code_sha: str
    generated_at: datetime
    information_cutoff: datetime
    deadline_at: datetime
    label_finality_cutoff: datetime
    position: Literal["GK", "DEF", "MID", "FWD"]
    expected_minutes: Decimal
    source: SourceRef

    @model_validator(mode="after")
    def exact_source_output(self) -> Self:
        if (
            self.summary_sha256 != canonical_sha256(self.summary.model_dump(mode="json"))
            or self.summary.player_id != str(self.key.player_id)
            or self.source.source_id != STAGE9_SOURCE_ID
            or self.official_player_id <= 0
            or self.official_fixture_ids != tuple(sorted(set(self.official_fixture_ids)))
            or len(self.official_fixture_ids) != len(self.key.fixture_ids)
        ):
            raise ValueError("owned Stage-9 summary or target identity differs")
        return self


class Stage9Evaluation(NamedTuple):
    fixture: Stage9SnapshotFixture
    forecast: PlayerForecast
    frozen: FrozenForecast
    label: FinalPlayerOutcome
    scorecard: PlayerScorecard
    custody: MemoryLedger


def load_stage9_fixture() -> Stage9SnapshotFixture:
    """Load only the packaged fixture whose complete bytes are registry-qualified."""

    root = files("dmf_pulse.player_lab.resources")
    registry = json.loads(root.joinpath("source-registry.json").read_text(encoding="utf-8"))
    record = registry["sources"][STAGE9_SOURCE_ID]
    body = root.joinpath("stage9-snapshot.json").read_bytes()
    if hashlib.sha256(body).hexdigest() != record["snapshot_sha256"]:
        raise ValueError("owned Stage-9 fixture byte identity differs")
    return Stage9SnapshotFixture.model_validate_json(body)


def snapshot_stage9_fixture(fixture: Stage9SnapshotFixture) -> PlayerForecast:
    """Use the production snapshot boundary, preserving its mean and 13 components."""

    fixture = Stage9SnapshotFixture.model_validate_json(fixture.model_dump_json())
    return snapshot_projection(
        fixture.summary,
        key=fixture.key,
        generated_at=fixture.generated_at,
        information_cutoff=fixture.information_cutoff,
        deadline_at=fixture.deadline_at,
        label_finality_cutoff=fixture.label_finality_cutoff,
        sources=(fixture.source,),
        input_sha256=fixture.input_sha256,
        code_sha=fixture.code_sha,
        position=fixture.position,
        expected_minutes=fixture.expected_minutes,
    )


def stage9_synthetic_evaluation() -> Stage9Evaluation:
    """Freeze actual Stage-9 output before opening a later owned synthetic label."""

    fixture = load_stage9_fixture()
    forecast = snapshot_stage9_fixture(fixture)
    now = forecast.generated_at + timedelta(minutes=1)
    ledger = MemoryLedger(clock=lambda: now)
    frozen = ledger.freeze(forecast)
    root = files("dmf_pulse.player_lab.resources")
    context = FinalityContext.model_validate_json(
        root.joinpath("stage9-outcome-context.json").read_bytes()
    )
    if context.source.source_id != STAGE9_OUTCOME_SOURCE_ID:
        raise ValueError("owned Stage-9 outcome source differs")
    now = context.usable_at
    actuals = ingest_offline_actuals(root.joinpath("stage9-actuals.json").read_bytes(), context)
    if len(actuals.labels) != 1 or actuals.labels[0].key != forecast.key:
        raise ValueError("owned Stage-9 outcome target differs")
    label = actuals.labels[0]
    ledger.record_outcome(label)
    scorecard = evaluate_players((frozen,), (label,), custody=ledger)
    return Stage9Evaluation(fixture, forecast, frozen, label, scorecard, ledger)
