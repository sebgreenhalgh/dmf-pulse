"""Fail-closed measurable Stage-8 fixture, schema and semantic acceptance validator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

from dmf_pulse.football_events.score_distribution import JointScoreDistribution
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionResult,
    ScoreDistributionService,
    load_score_distribution_request,
)


def _load_sibling_script(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"acceptance dependency is unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_COVERAGE_GATE = _load_sibling_script(
    "check_gcs008_coverage_gates.py", "gcs008_acceptance_coverage_gate"
)
_SCOPE_GATE = _load_sibling_script("validate_gcs008_scope.py", "gcs008_acceptance_scope_gate")
evaluate_coverage = _COVERAGE_GATE.evaluate
_git_changed_paths = _SCOPE_GATE._git_changed_paths
validate_changed_paths = _SCOPE_GATE.validate_changed_paths

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures/events/score/GCS-008"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
COVERAGE_PATH = REPOSITORY_ROOT / "evidence/tickets/GCS-008/coverage.json"
EXPECTED_STATUS = {
    "balanced_fixture.json": "PROJECTED",
    "high_total.json": "PROJECTED",
    "inconsistent_markets.json": "PROJECTED",
    "low_total.json": "PROJECTED",
    "market_missing.json": "PROJECTED",
    "postponed_fixture.json": "BLOCKED",
    "stage6_consensus_fixture.json": "PROJECTED",
    "strong_home_favourite.json": "PROJECTED",
}


class AcceptanceError(RuntimeError):
    """A measurable GCS-008 acceptance failure."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_manifest() -> int:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError("fixture manifest is unreadable") from exc
    entries = manifest.get("fixtures")
    if not isinstance(entries, list):
        raise AcceptanceError("fixture manifest entries are unavailable")
    observed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise AcceptanceError("fixture manifest contains a malformed entry")
        name = entry.get("file")
        expected = entry.get("sha256")
        rights = entry.get("rights_classification")
        source_mode = entry.get("source_mode")
        if not isinstance(name, str) or not isinstance(expected, str):
            raise AcceptanceError("fixture manifest identity is malformed")
        if rights != "INTERNAL_SYNTHETIC" or source_mode != "SYNTHETIC":
            raise AcceptanceError(f"fixture rights metadata is not synthetic: {name}")
        path = FIXTURE_ROOT / name
        if not path.is_file() or _sha256(path) != expected:
            raise AcceptanceError(f"fixture checksum mismatch: {name}")
        observed.add(name)
    required = set(EXPECTED_STATUS) | {"balanced_fixture.expected.json"}
    if observed != required:
        raise AcceptanceError("fixture manifest membership differs from the frozen family")
    return len(observed)


def _validate_schemas() -> int:
    resource_root = files("dmf_pulse.football_events.resources")
    expected: dict[str, dict[str, Any]] = {
        "score_distribution_request.schema.json": ScoreDistributionRequest.model_json_schema(),
        "joint_score_distribution.schema.json": JointScoreDistribution.model_json_schema(),
        "score_distribution_result.schema.json": ScoreDistributionResult.model_json_schema(),
    }
    repository_contracts = REPOSITORY_ROOT / "public_contracts"
    for name, schema in expected.items():
        try:
            packaged = json.loads(resource_root.joinpath(name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcceptanceError(f"packaged schema is unreadable: {name}") from exc
        if packaged != schema:
            raise AcceptanceError(f"packaged schema drift detected: {name}")
        try:
            repository = json.loads((repository_contracts / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcceptanceError(f"repository schema is unreadable: {name}") from exc
        if repository != schema:
            raise AcceptanceError(f"repository schema drift detected: {name}")
    source_policy = (REPOSITORY_ROOT / "config/models/score_baseline.yaml").read_bytes()
    packaged_policy = resource_root.joinpath("score_baseline.yaml").read_bytes()
    if source_policy != packaged_policy:
        raise AcceptanceError("source and packaged score policies differ")
    return len(expected)


def _validate_fixtures() -> tuple[int, int]:
    projected = 0
    blocked = 0
    for name, expected_status in EXPECTED_STATUS.items():
        request = load_score_distribution_request(FIXTURE_ROOT / name)
        first = ScoreDistributionService().project(request)
        second = ScoreDistributionService().project(request)
        if first != second:
            raise AcceptanceError(f"fixture is not deterministic: {name}")
        if first.status != expected_status:
            raise AcceptanceError(f"fixture status mismatch: {name}")
        if first.status == "PROJECTED":
            if first.distribution is None:
                raise AcceptanceError(f"projected fixture has no distribution: {name}")
            projected += 1
        else:
            if first.distribution is not None:
                raise AcceptanceError(f"blocked fixture emitted a distribution: {name}")
            blocked += 1
    balanced = ScoreDistributionService().project(
        load_score_distribution_request(FIXTURE_ROOT / "balanced_fixture.json")
    )
    if balanced.distribution is None:
        raise AcceptanceError("balanced fixture did not produce a distribution")
    golden = json.loads(
        (FIXTURE_ROOT / "balanced_fixture.expected.json").read_text(encoding="utf-8")
    )
    if balanced.distribution.model_dump(mode="json") != golden:
        raise AcceptanceError("balanced fixture differs from the reviewed golden output")
    return projected, blocked


def _validate_measured_state() -> tuple[dict[str, Any], int]:
    """Bind PASS to the real diff and repository-wide measured coverage."""

    coverage = evaluate_coverage(COVERAGE_PATH)
    changed = validate_changed_paths(_git_changed_paths())
    return coverage, len(changed)


def validate() -> dict[str, Any]:
    coverage, changed_file_count = _validate_measured_state()
    fixture_files = _validate_manifest()
    schema_files = _validate_schemas()
    projected, blocked = _validate_fixtures()
    return {
        "blocked_fixtures": blocked,
        "changed_file_count": changed_file_count,
        "coverage": coverage["aggregate"],
        "fixture_files_verified": fixture_files,
        "projected_fixtures": projected,
        "schema_files_verified": schema_files,
        "schema_version": "gcs008-acceptance-validation-v1",
        "status": "PASS",
    }


def main() -> int:
    try:
        report = validate()
    except (AcceptanceError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": {"code": "GCS008_ACCEPTANCE_FAILED", "message": str(exc)},
                    "schema_version": "gcs008-acceptance-validation-v1",
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
