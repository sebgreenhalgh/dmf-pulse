"""Owned admission-only fixtures; repeat literal distributions, never score them."""

import hashlib
import json
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.p01_frozen_view import P01FrozenScoringView
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    ParsedMatch,
    ParsedSnapshot,
    SourceLineage,
    seal,
)

AT = datetime(2026, 10, 6, tzinfo=UTC)


@lru_cache(maxsize=1)
def owned_view():
    directory = (
        Path(__file__).resolve().parents[2] / "fixtures/evaluation/a02_legacy_forecast_input"
    )
    manifest = json.loads((directory / "manifest.json").read_bytes())
    parts = []
    for row in manifest["parts"]:
        body = (directory / row["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == row["byte_sha256"]
        parts.append(body)
    raw = b"".join(parts)
    assert (
        hashlib.sha256(raw).hexdigest()
        == "1c2c0df07078456822c6cf40cb52fd6e97e551c0cdd6dd030851f72e0c5ffb0d"
    )
    literal = json.loads(raw)
    assert literal["dataset_mode"] == "RECONSTRUCTED"
    prototype = literal["forecasts"][0]
    literal["forecasts"] = [
        {**prototype, "fixture": row["fixture"], "scheduled_date": row["source_match_date"]}
        for row in literal["public_schedule"]["matches"][:10]
    ]
    literal["semantic_sha256"] = canonical_sha256(
        {key: value for key, value in literal.items() if key != "semantic_sha256"}
    )
    value = P01FrozenScoringView.model_validate_json(json.dumps(literal))
    assert all(str(row.fixture.fixture_id).startswith("00000000-") for row in value.forecasts)
    return value


def owned_snapshot(view, *, omit_last=False, changes=None, registry=None):
    source = seal(
        SourceLineage,
        **{
            **{name: getattr(view.public_schedule.lineage, name) for name in type(view.public_schedule.lineage).model_fields if name != "semantic_sha256"},
            "retrieval_started_at": AT,
            "received_at": AT,
            "validated_at": AT,
            "usable_at": AT,
        },
    )
    rows = []
    for index, row in enumerate(view.forecasts):
        values = dict(
            fixture=row.fixture,
            source_match_date=date(2026, 10, 4),
            source_round=1,
            home_goals=2,
            away_goals=1,
            finality="FULL_TIME",
            source_row_sha256="a" * 64,
            source_snapshot_sha256=source.semantic_sha256,
        )
        if index == 9 and changes:
            values.update(changes)
        rows.append(seal(ParsedMatch, **values))
    return seal(
        ParsedSnapshot,
        lineage=source,
        fixture_registry_sha256=registry or view.fixture_registry.semantic_sha256,
        matches=tuple(rows[:-1] if omit_last else rows),
    )
