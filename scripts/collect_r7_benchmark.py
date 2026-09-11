"""Collect every declared R7 timing sample without selecting a best-run result."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from statistics import median


def summarize(paths):
    samples = []
    for path in paths:
        data = json.loads(path.read_bytes())
        assert data["squads"] == 847 and data["scenario_count"] == 256
        with path.open("rb") as source:
            artifact_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
        samples.append(
            {
                "artifact": path.name,
                "artifact_sha256": artifact_sha256,
                **{
                    key: data[key]
                    for key in (
                        "wall_seconds",
                        "cpu_seconds",
                        "squads_per_wall_second",
                        "semantic_sha256",
                        "work",
                    )
                },
            }
        )
    result = {"samples": samples}
    for metric in ("wall_seconds", "cpu_seconds"):
        values = [s[metric] for s in samples]
        result[metric] = {"median": median(values), "minimum": min(values), "maximum": max(values)}
    result["squads_per_median_wall_second"] = 847 / result["wall_seconds"]["median"]
    return result


def compare_pair(directory, baseline_name, current_name, keys):
    paths = (directory / baseline_name, directory / current_name)
    baseline, current = (json.loads(path.read_bytes()) for path in paths)
    assert all(baseline[key] == current[key] for key in keys)
    records = []
    for path in paths:
        with path.open("rb") as source:
            records.append(
                {"artifact": path.name, "sha256": hashlib.file_digest(source, "sha256").hexdigest()}
            )
    return {
        "all_selected_fields_exactly_equal": True,
        "compared_fields_without_nested_exclusions": keys,
        "artifacts": records,
        "equal_payload_json_sha256": hashlib.sha256(
            json.dumps(
                {key: current[key] for key in keys}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    r6 = summarize(
        [
            args.directory / name
            for name in ("repeated-r6-3.json", "isolated-r6-4.json", "isolated-r6-5.json")
        ]
    )
    r7 = summarize([args.directory / f"repeated-r7-{i}.json" for i in range(1, 4)])
    assert len({s["semantic_sha256"] for group in (r6, r7) for s in group["samples"]}) == 1
    payload = {
        "status": "PERFORMANCE_AND_TACTICAL_EQUALITY_ONLY_NOT_FULL_ACCEPTANCE",
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "method": "One separate 8-squad warm-up before each fresh 847-squad/256-scenario kernel; no coverage, profiler or network; source-isolated R6 shared helpers.",
        "excluded_samples": "R6 repeated samples 1/2 used current shared canonical helpers and are excluded from the baseline.",
        "timing_caveat": "Substantial baseline CPU/wall variation. Also report conservative fastest-R6 / slowest-R7 ratio; do not attribute slower baseline samples entirely to algorithm changes.",
        "r6": r6,
        "r7": r7,
        "median_wall_speedup": r6["wall_seconds"]["median"] / r7["wall_seconds"]["median"],
        "median_cpu_speedup": r6["cpu_seconds"]["median"] / r7["cpu_seconds"]["median"],
        "conservative_wall_speedup": r6["wall_seconds"]["minimum"] / r7["wall_seconds"]["maximum"],
        "conservative_cpu_speedup": r6["cpu_seconds"]["minimum"] / r7["cpu_seconds"]["maximum"],
        "frozen_differentials": {
            "structural_labelled_tactical_surrogate": compare_pair(
                args.directory,
                "r6-search-shape.json",
                "whole-public-search-shape.json",
                ("request", "candidates", "squads_by_node"),
            ),
            "real_stage10_stage11": compare_pair(
                args.directory,
                "frozen-physical-r6.json",
                "frozen-physical-r7.json",
                ("request", "candidates", "result"),
            ),
            "full_private_stack_synthetic_fixed_market_build_identity": compare_pair(
                args.directory,
                "fixed-service-r6.json",
                "fixed-service-r7.json",
                (
                    "execution_sha256",
                    "request",
                    "decision",
                    "optimiser_result",
                    "one_gameweek_result",
                    "projection_hashes",
                ),
            ),
        },
        "production_source_sha256": {
            name: hashlib.sha256(
                (Path(__file__).resolve().parents[1] / "src/dmf_pulse" / name).read_bytes()
            ).hexdigest()
            for name in (
                "optimisation/autosub_evaluator.py",
                "optimisation/multi_gameweek_service.py",
                "optimisation/tactics.py",
                "optimisation/multi_gameweek_solver.py",
                "private_v1/rolling.py",
                "private_v1/service.py",
            )
        },
    }
    assert payload["conservative_wall_speedup"] > 5
    assert r7["squads_per_median_wall_second"] > 12.45
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in payload.items() if k not in {"r6", "r7"}}, indent=2))


if __name__ == "__main__":
    main()
