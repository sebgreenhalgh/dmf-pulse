#!/usr/bin/env python3
"""Rebuild or verify deterministic PTS-009 schemas and test-only fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "fixtures/points/PTS-009"
REFERENCE_RULESET = FIXTURE_DIR / "reference_ruleset_test_only.json"


def _pretty(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _player(raw: dict[str, object]):
    from dmf_pulse.fpl_points.models import PlayerPosition
    from tests.support.factories import empty_bps, empty_defensive, event_player

    return event_player(
        str(raw["player_id"]),
        str(raw["team_id"]),
        PlayerPosition(str(raw["position"])),
        minutes=int(raw.get("minutes", 90)),
        goals_non_penalty=int(raw.get("goals_non_penalty", 0)),
        goals_penalty=int(raw.get("goals_penalty", 0)),
        assists=int(raw.get("assists", 0)),
        conceded=int(raw.get("conceded", 0)),
        saves=int(raw.get("saves", 0)),
        penalty_saves=int(raw.get("penalty_saves", 0)),
        penalty_misses=int(raw.get("penalty_misses", 0)),
        yellow=int(raw.get("yellow", 0)),
        red=int(raw.get("red", 0)),
        own_goals=int(raw.get("own_goals", 0)),
        defensive=empty_defensive(**dict(raw.get("defensive", {}))),
        bps=empty_bps(),
    )


def expected_resources() -> dict[Path, bytes]:
    from dmf_pulse.fpl_points.models import (
        FixtureProjectionResult,
        FixtureSimulationRequest,
        GameweekProjectionResult,
    )
    from tests.support.factories import event_fixture, make_request, reference_engine

    golden_path = FIXTURE_DIR / "golden_cases.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    engine = reference_engine()
    golden.update(
        ruleset_id=engine.identity.ruleset_id,
        ruleset_version=engine.identity.ruleset_version,
        ruleset_hash=engine.identity.ruleset_hash,
    )
    for case in golden["cases"]:
        fixture = event_fixture(
            home_goals=int(case["home_goals"]),
            away_goals=int(case["away_goals"]),
            players=tuple(_player(player) for player in case["players"]),
            fixture_id=f"GOLD-{case['case_id']}",
        )
        case["expected"] = {
            player_id: score.model_dump(mode="json")
            for player_id, score in sorted(engine.score_fixture(fixture).items())
        }
    return {
        FIXTURE_DIR / "fixture_request_example.json": _pretty(
            make_request(scenario_count=32).model_dump(mode="json")
        ),
        golden_path: _pretty(golden),
        FIXTURE_DIR / "schemas/fixture_request.schema.json": _pretty(
            FixtureSimulationRequest.model_json_schema()
        ),
        FIXTURE_DIR / "schemas/fixture_result.schema.json": _pretty(
            FixtureProjectionResult.model_json_schema()
        ),
        FIXTURE_DIR / "schemas/gameweek_result.schema.json": _pretty(
            GameweekProjectionResult.model_json_schema()
        ),
    }


def _manifest(resources: dict[Path, bytes]) -> bytes:
    all_resources = dict(resources)
    all_resources[REFERENCE_RULESET] = REFERENCE_RULESET.read_bytes()
    files = {
        path.relative_to(FIXTURE_DIR).as_posix(): {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for path, data in sorted(all_resources.items())
    }
    return _pretty({"files": files, "schema_version": "pts-009-fixture-manifest-v1"})


def validate(*, write: bool) -> list[str]:
    resources = expected_resources()
    resources[FIXTURE_DIR / "manifest.json"] = _manifest(resources)
    errors: list[str] = []
    for path, expected in resources.items():
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
        elif not path.is_file():
            errors.append(f"MISSING:{path.relative_to(ROOT).as_posix()}")
        elif path.read_bytes() != expected:
            errors.append(f"STALE:{path.relative_to(ROOT).as_posix()}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    errors = validate(write=args.write)
    print(
        json.dumps(
            {
                "errors": errors,
                "schema_version": "pts-009-resource-assurance-v1",
                "status": "PASS" if not errors else "FAIL",
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
