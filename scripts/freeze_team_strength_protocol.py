"""One-time offline pre-result protocol generation; refuses to overwrite authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json
from dmf_pulse.evaluation.team_strength_protocol import (
    PARENT_SHA,
    ProspectiveProtocolV1,
    protocol_summary,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import seal

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "config/models/current_team_strength_governance.json",
    "src/dmf_pulse/evaluation/team_strength_prospective.py",
    "src/dmf_pulse/evaluation/team_strength_replay.py",
    "src/dmf_pulse/football_events/team_strength_model.py",
    "src/dmf_pulse/football_events/team_strength_numerics.py",
    "src/dmf_pulse/football_events/team_strength_parameter_draws.py",
)


def main() -> None:
    destination = ROOT / "config/evaluation/team_strength_prospective_protocol_v1.json"
    if destination.exists():
        raise ValueError("versioned protocol already frozen; explicit amendment required")
    manifest = tuple(
        (name, hashlib.sha256((ROOT / name).read_bytes()).hexdigest()) for name in FILES
    )
    code_sha = canonical_sha256({"git_sha": PARENT_SHA, "files": manifest})
    method_sha = canonical_sha256(
        {
            "accepted_code_sha256": code_sha,
            "methodology": "UNCHANGED_001U_MODEL_HYPERPARAMETERS_ENTRANT_UNCERTAINTY_SCORING_SUPPORT_36",
        }
    )
    protocol = seal(
        ProspectiveProtocolV1,
        protocol_version="1.0.0",
        evaluation_epoch="EVALUATION_EPOCH_001",
        created_at=datetime.now(UTC),
        code_sha256=code_sha,
        accepted_code_manifest=manifest,
        methodology_sha256=method_sha,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as output:
        output.write(pretty_json(protocol_summary(protocol)))
    print(json.dumps(protocol_summary(protocol), sort_keys=True))


if __name__ == "__main__":
    main()
