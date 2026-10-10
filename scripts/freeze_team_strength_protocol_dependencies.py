"""Pin unchanged 001U scoring/fitting dependency bytes before prospective results."""

import hashlib
import json
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json
from dmf_pulse.evaluation.team_strength_protocol import PARENT_SHA

ROOT = Path(__file__).resolve().parents[1]
FILES = tuple(
    sorted(
        (
            "src/dmf_pulse/evaluation/calibration.py",
            "src/dmf_pulse/evaluation/team_strength_mixture_analysis.py",
            "src/dmf_pulse/football_events/_decimal.py",
            "src/dmf_pulse/football_events/poisson.py",
            "src/dmf_pulse/football_events/score_prior_request.py",
            "src/dmf_pulse/football_events/team_strength_adapter.py",
            "src/dmf_pulse/football_events/team_strength_mixture.py",
            "src/dmf_pulse/ingestion/openfootball/config.py",
            "src/dmf_pulse/ingestion/openfootball/parser.py",
            "src/dmf_pulse/ingestion/openfootball/service.py",
            "src/dmf_pulse/ingestion/openfootball/team_strength_data.py",
            "src/dmf_pulse/ingestion/openfootball/team_strength_governance.py",
        )
    )
)


def main() -> None:
    value = {
        "accepted_parent": PARENT_SHA,
        "files": [(name, hashlib.sha256((ROOT / name).read_bytes()).hexdigest()) for name in FILES],
    }
    destination = ROOT / "config/evaluation/team_strength_epoch001_dependencies.json"
    body = pretty_json(value)
    if destination.exists():
        if destination.read_text(encoding="utf-8") != body:
            raise ValueError("accepted dependency bytes cannot be rewritten in the same epoch")
    else:
        with destination.open("x", encoding="utf-8", newline="\n") as output:
            output.write(body)
    print(
        json.dumps(
            {"dependency_manifest_sha256": canonical_sha256(value), "source_files": len(FILES)}
        )
    )


if __name__ == "__main__":
    main()
