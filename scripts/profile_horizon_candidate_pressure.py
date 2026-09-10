"""Read-only V2 diagnostics on synthetic inputs; never changes a production bound."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.unit.private_v1.horizon_pressure_support import (  # noqa: E402
    pressure_fixture,
    projected_legal_actions,
    v2_pressure,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = {}
    for shape in ("large_tie", "low_overlap", "high_overlap"):
        fixture = pressure_fixture(shape)
        payload[shape] = {
            **v2_pressure(fixture),
            "projected_actions": projected_legal_actions(fixture),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                shape: {
                    k: v
                    for k, v in data.items()
                    if k not in {"bucket_counts", "unique_by_bucket", "pairwise_overlap_nonzero"}
                }
                for shape, data in payload.items()
            }
        )
    )


if __name__ == "__main__":
    main()
