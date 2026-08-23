"""Plan, transport, and verify deterministic branch-coverage shards for CI.

The planner owns the semantic selector used by CI (``not performance``).  It
collects nodeids through pytest, keeps every test module intact, and uses a
static longest-processing-time partition.  Runtime history is deliberately
not consulted: a repository commit must always produce the same plan.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath

import pytest
from coverage import CoverageData

MARKER_EXPRESSION = "not performance"
SCHEMA_VERSION = "ci-coverage-shard-plan-v1"
SHARD_RESULT_SCHEMA_VERSION = "ci-coverage-shard-result-v1"
BRANCH_REPORT_SCHEMA_VERSION = "ci-coverage-branch-proof-v1"
ALGORITHM = "module-grouped-lpt-v1"
DEFAULT_FILE_WEIGHT = 5
DEFAULT_NODEID_WEIGHT = 1

# These total-file estimates are static balancing hints, not test-selection
# policy.  They are based on the repository's sealed OPT-010 runtime evidence
# and Actions runs 32600781430 / 32667375839.  In particular, a four-test
# assurance file took about 940 seconds under branch coverage while several
# one-gameweek optimiser modules took about 235-300 seconds each.
FILE_WEIGHT_OVERRIDES: Mapping[str, int] = {
    "tests/assurance/optimisation/test_r2c_artifact_validation.py": 1050,
    "tests/assurance/optimisation/test_surface.py": 270,
    "tests/contract/optimisation/test_r2a_contract_gates.py": 270,
    "tests/golden/optimisation/test_golden.py": 270,
    "tests/integration/availability/test_min007g_service.py": 45,
    "tests/integration/migrations/test_migrations.py": 65,
    "tests/integration/optimisation/test_integration.py": 340,
    "tests/property/optimisation/test_oracle_equivalence.py": 45,
    "tests/unit/availability/test_audit0073_cli_semantics.py": 45,
    "tests/unit/optimisation/test_r2b_semantics.py": 270,
    "tests/unit/optimisation/test_service.py": 650,
}

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_SHARD_METADATA_NAME = re.compile(r"^shard-(\d{2,})\.json$")
_SHARD_COVERAGE_NAME = re.compile(r"^coverage-data-shard-(\d{2,})$")


class ShardPlannerError(ValueError):
    """The shard plan, transport artifact, or coverage proof is invalid."""


class _CollectionPlugin:
    def __init__(self) -> None:
        self.nodeids: tuple[str, ...] = ()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.nodeids = tuple(item.nodeid for item in session.items)


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _digest_strings(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_git_sha(value: object, *, label: str = "git_sha") -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise ShardPlannerError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def _require_integer(
    value: object,
    *,
    label: str,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ShardPlannerError(f"{label} must be an integer >= {minimum}")
    return value


def _require_exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ShardPlannerError(f"{label} keys are invalid; missing={missing}, extra={extra}")


def normalize_nodeid(value: str) -> str:
    """Normalize only a nodeid's file prefix, preserving its test-id suffix."""

    if not isinstance(value, str) or not value:
        raise ShardPlannerError("nodeid must be a non-empty string")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ShardPlannerError("nodeid contains a forbidden control character")
    file_part, separator, test_part = value.partition("::")
    if not separator or not test_part:
        raise ShardPlannerError(f"nodeid has no test suffix: {value!r}")
    normalized_file = file_part.replace("\\", "/")
    if normalized_file.startswith("/") or _DRIVE_PATH.match(normalized_file):
        raise ShardPlannerError(f"nodeid file path must be repository-relative: {value!r}")
    raw_parts = normalized_file.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ShardPlannerError(f"nodeid file path is unsafe: {value!r}")
    path = PurePosixPath(*raw_parts)
    if not path.parts or path.parts[0] != "tests" or path.suffix != ".py":
        raise ShardPlannerError(f"nodeid file path must be a Python test under tests/: {value!r}")
    return f"{path.as_posix()}::{test_part}"


def _nodeid_file(nodeid: str) -> str:
    return nodeid.partition("::")[0]


def normalize_nodeids(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(normalize_nodeid(value) for value in values)
    duplicates = sorted(name for name, count in _counts(normalized).items() if count > 1)
    if duplicates:
        raise ShardPlannerError(f"eligible collection contains duplicate nodeids: {duplicates[:5]}")
    if not normalized:
        raise ShardPlannerError("eligible pytest collection is empty")
    return tuple(sorted(normalized))


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def collect_eligible_nodeids() -> tuple[str, ...]:
    """Collect the exact marker-selected population through pytest's own hooks."""

    plugin = _CollectionPlugin()
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = pytest.main(
            ["--collect-only", "-q", "-p", "no:cacheprovider", "-m", MARKER_EXPRESSION],
            plugins=[plugin],
        )
    if exit_code != pytest.ExitCode.OK:
        raise ShardPlannerError(f"pytest collection failed with exit code {int(exit_code)}")
    return normalize_nodeids(plugin.nodeids)


def _estimated_file_weight(path: str, nodeid_count: int) -> int:
    return FILE_WEIGHT_OVERRIDES.get(
        path,
        DEFAULT_FILE_WEIGHT + DEFAULT_NODEID_WEIGHT * nodeid_count,
    )


def _weight_model_sha256() -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "default_file_weight": DEFAULT_FILE_WEIGHT,
                "default_nodeid_weight": DEFAULT_NODEID_WEIGHT,
                "file_weight_overrides": dict(sorted(FILE_WEIGHT_OVERRIDES.items())),
            }
        )
    ).hexdigest()


def _plan_sha256(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("plan_sha256", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def build_plan(
    nodeids: Iterable[str],
    *,
    shard_count: int,
    git_sha: str,
) -> dict[str, object]:
    """Build a deterministic complete module-grouped LPT partition."""

    sha = _require_git_sha(git_sha)
    count = _require_integer(shard_count, label="shard_count", minimum=1)
    eligible = normalize_nodeids(nodeids)
    grouped: dict[str, list[str]] = {}
    for nodeid in eligible:
        grouped.setdefault(_nodeid_file(nodeid), []).append(nodeid)
    if count > len(grouped):
        raise ShardPlannerError(
            "shard_count cannot exceed the eligible test-file count while module grouping is required"
        )

    groups = [
        {
            "estimated_weight": _estimated_file_weight(path, len(file_nodeids)),
            "nodeids": tuple(file_nodeids),
            "path": path,
        }
        for path, file_nodeids in grouped.items()
    ]
    groups.sort(key=lambda item: (-int(item["estimated_weight"]), str(item["path"])))

    shard_groups: list[list[dict[str, object]]] = [[] for _ in range(count)]
    shard_weights = [0] * count
    for group in groups:
        shard_index = min(range(count), key=lambda index: (shard_weights[index], index))
        shard_groups[shard_index].append(group)
        shard_weights[shard_index] += int(group["estimated_weight"])

    shards: list[dict[str, object]] = []
    assigned: list[str] = []
    for shard_index, values in enumerate(shard_groups):
        shard_nodeids = tuple(
            sorted(
                nodeid
                for group in values
                for nodeid in group["nodeids"]  # type: ignore[union-attr]
            )
        )
        test_files = tuple(sorted(str(group["path"]) for group in values))
        assigned.extend(shard_nodeids)
        shards.append(
            {
                "estimated_weight": shard_weights[shard_index],
                "nodeid_count": len(shard_nodeids),
                "nodeid_sha256": _digest_strings(shard_nodeids),
                "nodeids": list(shard_nodeids),
                "shard_index": shard_index,
                "test_file_count": len(test_files),
                "test_files": list(test_files),
            }
        )

    assigned_counts = _counts(assigned)
    eligible_set = set(eligible)
    assigned_set = set(assigned)
    duplicate_count = sum(value - 1 for value in assigned_counts.values() if value > 1)
    omitted_count = len(eligible_set - assigned_set)
    unexpected_count = len(assigned_set - eligible_set)
    complete = duplicate_count == omitted_count == unexpected_count == 0
    if not complete:
        raise ShardPlannerError("planner produced an incomplete or overlapping partition")
    plan: dict[str, object] = {
        "algorithm": ALGORITHM,
        "eligible_nodeid_count": len(eligible),
        "eligible_nodeid_sha256": _digest_strings(eligible),
        "git_sha": sha,
        "marker_expression": MARKER_EXPRESSION,
        "partition": {
            "complete": True,
            "duplicate_nodeid_count": duplicate_count,
            "omitted_nodeid_count": omitted_count,
            "unexpected_nodeid_count": unexpected_count,
        },
        "plan_sha256": "",
        "schema_version": SCHEMA_VERSION,
        "shard_count": count,
        "shards": shards,
        "weight_model_sha256": _weight_model_sha256(),
    }
    plan["plan_sha256"] = _plan_sha256(plan)
    validate_plan(plan, expected_git_sha=sha)
    return plan


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ShardPlannerError(f"{label} must be an object")
    return value


def _string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ShardPlannerError(f"{label} must be an array of strings")
    return value


def validate_plan(
    value: object,
    *,
    expected_git_sha: str | None = None,
) -> dict[str, object]:
    """Validate every redundant plan invariant and return the typed mapping."""

    plan = _mapping(value, label="plan")
    _require_exact_keys(
        plan,
        {
            "algorithm",
            "eligible_nodeid_count",
            "eligible_nodeid_sha256",
            "git_sha",
            "marker_expression",
            "partition",
            "plan_sha256",
            "schema_version",
            "shard_count",
            "shards",
            "weight_model_sha256",
        },
        label="plan",
    )
    if plan["schema_version"] != SCHEMA_VERSION:
        raise ShardPlannerError("plan schema_version is unsupported")
    if plan["algorithm"] != ALGORITHM:
        raise ShardPlannerError("plan algorithm is unsupported")
    if plan["marker_expression"] != MARKER_EXPRESSION:
        raise ShardPlannerError("plan marker_expression is not the mandatory selector")
    sha = _require_git_sha(plan["git_sha"])
    if expected_git_sha is not None and sha != _require_git_sha(expected_git_sha):
        raise ShardPlannerError("plan git_sha does not match the expected commit")
    if plan["weight_model_sha256"] != _weight_model_sha256():
        raise ShardPlannerError("plan weight model does not match this repository commit")
    if plan["plan_sha256"] != _plan_sha256(plan):
        raise ShardPlannerError("plan_sha256 is inconsistent")
    shard_count = _require_integer(plan["shard_count"], label="plan.shard_count", minimum=1)
    shards_value = plan["shards"]
    if not isinstance(shards_value, list) or len(shards_value) != shard_count:
        raise ShardPlannerError("plan shards do not match shard_count")

    all_nodeids: list[str] = []
    file_owner: dict[str, int] = {}
    seen_indexes: set[int] = set()
    shard_indexes: list[int] = []
    for position, raw_shard in enumerate(shards_value):
        shard = _mapping(raw_shard, label=f"plan.shards[{position}]")
        _require_exact_keys(
            shard,
            {
                "estimated_weight",
                "nodeid_count",
                "nodeid_sha256",
                "nodeids",
                "shard_index",
                "test_file_count",
                "test_files",
            },
            label=f"plan.shards[{position}]",
        )
        index = _require_integer(shard["shard_index"], label=f"plan.shards[{position}].shard_index")
        shard_indexes.append(index)
        if index in seen_indexes:
            raise ShardPlannerError(f"plan contains duplicate shard index {index}")
        seen_indexes.add(index)
        nodeids = _string_list(shard["nodeids"], label=f"plan.shards[{position}].nodeids")
        if not nodeids:
            raise ShardPlannerError(f"plan shard {index} is empty")
        normalized = [normalize_nodeid(nodeid) for nodeid in nodeids]
        if normalized != nodeids or nodeids != sorted(nodeids):
            raise ShardPlannerError(f"plan shard {index} nodeids are not canonical and sorted")
        if len(set(nodeids)) != len(nodeids):
            raise ShardPlannerError(f"plan shard {index} contains duplicate nodeids")
        if _require_integer(
            shard["nodeid_count"], label=f"plan.shards[{position}].nodeid_count"
        ) != len(nodeids):
            raise ShardPlannerError(f"plan shard {index} nodeid_count is inconsistent")
        if shard["nodeid_sha256"] != _digest_strings(nodeids):
            raise ShardPlannerError(f"plan shard {index} nodeid digest is inconsistent")
        test_files = _string_list(shard["test_files"], label=f"plan.shards[{position}].test_files")
        derived_files = sorted({_nodeid_file(nodeid) for nodeid in nodeids})
        if test_files != derived_files:
            raise ShardPlannerError(f"plan shard {index} test_files are inconsistent")
        if _require_integer(
            shard["test_file_count"], label=f"plan.shards[{position}].test_file_count"
        ) != len(test_files):
            raise ShardPlannerError(f"plan shard {index} test_file_count is inconsistent")
        expected_weight = sum(
            _estimated_file_weight(
                path,
                sum(_nodeid_file(nodeid) == path for nodeid in nodeids),
            )
            for path in test_files
        )
        if (
            _require_integer(
                shard["estimated_weight"],
                label=f"plan.shards[{position}].estimated_weight",
                minimum=1,
            )
            != expected_weight
        ):
            raise ShardPlannerError(f"plan shard {index} estimated_weight is inconsistent")
        for path in test_files:
            previous = file_owner.setdefault(path, index)
            if previous != index:
                raise ShardPlannerError(f"test module {path} is split across shards")
        all_nodeids.extend(nodeids)

    if shard_indexes != list(range(shard_count)):
        raise ShardPlannerError("plan shard indexes must be canonical and contiguous")
    counts = _counts(all_nodeids)
    duplicate_count = sum(item - 1 for item in counts.values() if item > 1)
    if duplicate_count:
        raise ShardPlannerError("plan contains nodeids assigned to multiple shards")
    eligible = tuple(sorted(all_nodeids))
    if _require_integer(
        plan["eligible_nodeid_count"], label="plan.eligible_nodeid_count", minimum=1
    ) != len(eligible):
        raise ShardPlannerError("plan eligible_nodeid_count is inconsistent")
    if plan["eligible_nodeid_sha256"] != _digest_strings(eligible):
        raise ShardPlannerError("plan eligible nodeid digest is inconsistent")
    partition = _mapping(plan["partition"], label="plan.partition")
    _require_exact_keys(
        partition,
        {
            "complete",
            "duplicate_nodeid_count",
            "omitted_nodeid_count",
            "unexpected_nodeid_count",
        },
        label="plan.partition",
    )
    if partition != {
        "complete": True,
        "duplicate_nodeid_count": 0,
        "omitted_nodeid_count": 0,
        "unexpected_nodeid_count": 0,
    }:
        raise ShardPlannerError("plan does not assert a complete, disjoint partition")
    return dict(plan)


def _read_json(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShardPlannerError(f"{label} is unreadable JSON: {path}") from exc


def load_plan(path: Path, *, expected_git_sha: str | None = None) -> dict[str, object]:
    return validate_plan(_read_json(path, label="plan"), expected_git_sha=expected_git_sha)


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ShardPlannerError(f"existing output cannot be inspected: {path}") from exc
        if existing != content:
            raise ShardPlannerError(
                f"refusing to overwrite different existing output: {path}"
            ) from None


def _shard_width(shard_count: int) -> int:
    return max(2, len(str(shard_count - 1)))


def _shard_label(index: int, shard_count: int) -> str:
    return f"{index:0{_shard_width(shard_count)}d}"


def _require_directory_contents(directory: Path, expected: set[str], *, label: str) -> None:
    try:
        actual = {item.name for item in directory.iterdir()}
    except OSError as exc:
        raise ShardPlannerError(f"{label} cannot be inspected: {directory}") from exc
    if actual != expected:
        raise ShardPlannerError(
            f"{label} contents are invalid; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def write_plan_outputs(plan: object, output_dir: Path) -> tuple[Path, ...]:
    validated = validate_plan(plan)
    shards = validated["shards"]
    assert isinstance(shards, list)
    shard_count = int(validated["shard_count"])
    outputs = [output_dir / "plan.json"]
    _write_immutable(outputs[0], _canonical_json(validated))
    for raw_shard in shards:
        shard = _mapping(raw_shard, label="plan shard")
        index = int(shard["shard_index"])
        nodeids = _string_list(shard["nodeids"], label="plan shard nodeids")
        path = output_dir / f"shard-{_shard_label(index, shard_count)}.args"
        _write_immutable(path, "".join(f"{nodeid}\n" for nodeid in nodeids).encode("utf-8"))
        outputs.append(path)
    _require_directory_contents(output_dir, {path.name for path in outputs}, label="plan output")
    return tuple(outputs)


def _head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            encoding="ascii",
            errors="replace",
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShardPlannerError("Git HEAD could not be inspected") from exc
    if result.returncode != 0:
        raise ShardPlannerError("Git HEAD could not be inspected")
    return _require_git_sha(result.stdout.strip(), label="Git HEAD")


def _coverage_properties(path: Path) -> tuple[bool, int]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ShardPlannerError(f"coverage data is absent or empty: {path}")
    try:
        data = CoverageData(basename=str(path))
        data.read()
        has_arcs = data.has_arcs()
        measured_file_count = len(tuple(data.measured_files()))
    except Exception as exc:
        raise ShardPlannerError(f"coverage data is unreadable: {path}") from exc
    if not has_arcs:
        raise ShardPlannerError(f"coverage data is line-only rather than branch coverage: {path}")
    if measured_file_count == 0:
        raise ShardPlannerError(f"coverage data contains no measured files: {path}")
    return has_arcs, measured_file_count


def _selected_shard(plan: Mapping[str, object], shard_index: int) -> Mapping[str, object]:
    count = int(plan["shard_count"])
    index = _require_integer(shard_index, label="shard_index")
    if index >= count:
        raise ShardPlannerError(f"shard_index must be less than shard_count {count}")
    shards = plan["shards"]
    assert isinstance(shards, list)
    return _mapping(shards[index], label=f"plan shard {index}")


def materialize_shard(
    *,
    plan_path: Path,
    shard_index: int,
    coverage_data: Path,
    output_dir: Path,
    expected_git_sha: str | None = None,
) -> tuple[Path, Path]:
    """Validate and convert one hidden coverage data file into a visible artifact."""

    expected_sha = expected_git_sha or _head_sha()
    plan = load_plan(plan_path, expected_git_sha=expected_sha)
    shard = _selected_shard(plan, shard_index)
    _, measured_file_count = _coverage_properties(coverage_data)
    shard_count = int(plan["shard_count"])
    label = _shard_label(shard_index, shard_count)
    coverage_name = f"coverage-data-shard-{label}"
    metadata_name = f"shard-{label}.json"
    visible_coverage = output_dir / coverage_name
    try:
        coverage_bytes = coverage_data.read_bytes()
    except OSError as exc:
        raise ShardPlannerError(f"coverage data cannot be read: {coverage_data}") from exc
    _write_immutable(visible_coverage, coverage_bytes)
    metadata = {
        "assigned_nodeid_count": shard["nodeid_count"],
        "assigned_nodeid_sha256": shard["nodeid_sha256"],
        "coverage_data_file": coverage_name,
        "coverage_data_bytes": len(coverage_bytes),
        "coverage_data_sha256": hashlib.sha256(coverage_bytes).hexdigest(),
        "coverage_has_arcs": True,
        "eligible_nodeid_sha256": plan["eligible_nodeid_sha256"],
        "git_sha": plan["git_sha"],
        "marker_expression": MARKER_EXPRESSION,
        "measured_file_count": measured_file_count,
        "plan_sha256": plan["plan_sha256"],
        "schema_version": SHARD_RESULT_SCHEMA_VERSION,
        "shard_index": shard_index,
    }
    metadata_path = output_dir / metadata_name
    _write_immutable(metadata_path, _canonical_json(metadata))
    _require_directory_contents(
        output_dir,
        {coverage_name, metadata_name},
        label=f"shard {shard_index} artifact output",
    )
    return visible_coverage, metadata_path


def _validate_shard_metadata(
    value: object,
    *,
    path: Path,
    plan: Mapping[str, object],
    expected_index: int,
) -> Mapping[str, object]:
    metadata = _mapping(value, label=f"shard metadata {path}")
    _require_exact_keys(
        metadata,
        {
            "assigned_nodeid_count",
            "assigned_nodeid_sha256",
            "coverage_data_bytes",
            "coverage_data_file",
            "coverage_data_sha256",
            "coverage_has_arcs",
            "eligible_nodeid_sha256",
            "git_sha",
            "marker_expression",
            "measured_file_count",
            "plan_sha256",
            "schema_version",
            "shard_index",
        },
        label=f"shard metadata {path}",
    )
    if metadata["schema_version"] != SHARD_RESULT_SCHEMA_VERSION:
        raise ShardPlannerError(f"shard metadata schema is unsupported: {path}")
    index = _require_integer(metadata["shard_index"], label=f"{path}.shard_index")
    if index != expected_index:
        raise ShardPlannerError(f"shard metadata index does not match its filename: {path}")
    shard = _selected_shard(plan, index)
    expected = {
        "assigned_nodeid_count": shard["nodeid_count"],
        "assigned_nodeid_sha256": shard["nodeid_sha256"],
        "eligible_nodeid_sha256": plan["eligible_nodeid_sha256"],
        "git_sha": plan["git_sha"],
        "marker_expression": MARKER_EXPRESSION,
        "plan_sha256": plan["plan_sha256"],
    }
    for key, expected_value in expected.items():
        if metadata[key] != expected_value:
            raise ShardPlannerError(f"shard metadata {key} mismatch: {path}")
    if metadata["coverage_has_arcs"] is not True:
        raise ShardPlannerError(f"shard metadata does not prove branch data: {path}")
    _require_integer(
        metadata["measured_file_count"], label=f"{path}.measured_file_count", minimum=1
    )
    coverage_name = metadata["coverage_data_file"]
    if not isinstance(coverage_name, str):
        raise ShardPlannerError(f"shard coverage_data_file is invalid: {path}")
    expected_name = f"coverage-data-shard-{_shard_label(index, int(plan['shard_count']))}"
    if coverage_name != expected_name:
        raise ShardPlannerError(f"shard coverage_data_file is noncanonical: {path}")
    coverage_sha = metadata["coverage_data_sha256"]
    if not isinstance(coverage_sha, str) or re.fullmatch(r"[0-9a-f]{64}", coverage_sha) is None:
        raise ShardPlannerError(f"shard coverage_data_sha256 is invalid: {path}")
    _require_integer(
        metadata["coverage_data_bytes"], label=f"{path}.coverage_data_bytes", minimum=1
    )
    return metadata


def _artifact_payloads(
    artifact_root: Path,
    *,
    git_sha: str,
    shard_count: int,
) -> tuple[list[Path], list[Path]]:
    if not artifact_root.is_dir():
        raise ShardPlannerError(f"artifact root is absent: {artifact_root}")
    metadata: list[Path] = []
    coverage: list[Path] = []
    expected_directories = {f"coverage-shard-{git_sha}-{index}" for index in range(shard_count)}
    try:
        children = tuple(artifact_root.iterdir())
    except OSError as exc:
        raise ShardPlannerError(f"artifact root cannot be inspected: {artifact_root}") from exc
    actual_directories = {item.name for item in children if item.is_dir()}
    non_directories = sorted(item.name for item in children if not item.is_dir())
    if non_directories or actual_directories != expected_directories:
        raise ShardPlannerError(
            "downloaded artifact directories are invalid; "
            f"missing={sorted(expected_directories - actual_directories)}, "
            f"extra={sorted(actual_directories - expected_directories)}, "
            f"non_directories={non_directories}"
        )
    for index in range(shard_count):
        label = _shard_label(index, shard_count)
        directory = artifact_root / f"coverage-shard-{git_sha}-{index}"
        metadata_path = directory / f"shard-{label}.json"
        coverage_path = directory / f"coverage-data-shard-{label}"
        _require_directory_contents(
            directory,
            {metadata_path.name, coverage_path.name},
            label=f"downloaded shard {index} artifact",
        )
        metadata.append(metadata_path)
        coverage.append(coverage_path)
    return metadata, coverage


def verify_artifacts(
    *,
    plan_path: Path,
    artifact_root: Path,
    combine_dir: Path,
    git_sha: str,
    collected_nodeids: Iterable[str] | None = None,
) -> tuple[Path, ...]:
    """Recollect the population and stage an exact set of branch-data inputs."""

    expected_sha = _require_git_sha(git_sha)
    if _head_sha() != expected_sha:
        raise ShardPlannerError("Git HEAD does not match --git-sha")
    plan = load_plan(plan_path, expected_git_sha=expected_sha)
    fresh_nodeids = collect_eligible_nodeids() if collected_nodeids is None else collected_nodeids
    fresh_plan = build_plan(
        fresh_nodeids,
        shard_count=int(plan["shard_count"]),
        git_sha=expected_sha,
    )
    if _canonical_json(plan) != _canonical_json(fresh_plan):
        raise ShardPlannerError("stored shard plan does not match fresh pytest collection")

    shard_count = int(plan["shard_count"])
    metadata_paths, coverage_paths = _artifact_payloads(
        artifact_root,
        git_sha=expected_sha,
        shard_count=shard_count,
    )
    if len(metadata_paths) != shard_count or len(coverage_paths) != shard_count:
        raise ShardPlannerError(
            "coverage artifact count mismatch: "
            f"metadata={len(metadata_paths)}, coverage={len(coverage_paths)}, expected={shard_count}"
        )
    metadata_by_index: dict[int, Path] = {}
    coverage_by_index: dict[int, Path] = {}
    for path in metadata_paths:
        match = _SHARD_METADATA_NAME.fullmatch(path.name)
        assert match is not None
        index = int(match.group(1))
        if index in metadata_by_index:
            raise ShardPlannerError(f"duplicate shard metadata index: {index}")
        metadata_by_index[index] = path
    for path in coverage_paths:
        match = _SHARD_COVERAGE_NAME.fullmatch(path.name)
        assert match is not None
        index = int(match.group(1))
        if index in coverage_by_index:
            raise ShardPlannerError(f"duplicate shard coverage index: {index}")
        coverage_by_index[index] = path
    expected_indexes = set(range(shard_count))
    if set(metadata_by_index) != expected_indexes or set(coverage_by_index) != expected_indexes:
        raise ShardPlannerError(
            "coverage artifact shard indexes are missing or unexpected: "
            f"metadata={sorted(metadata_by_index)}, coverage={sorted(coverage_by_index)}"
        )

    staged: list[Path] = []
    expected_staged_names: set[str] = set()
    for index in range(shard_count):
        metadata_path = metadata_by_index[index]
        metadata = _validate_shard_metadata(
            _read_json(metadata_path, label="shard metadata"),
            path=metadata_path,
            plan=plan,
            expected_index=index,
        )
        coverage_path = coverage_by_index[index]
        if coverage_path.parent != metadata_path.parent:
            raise ShardPlannerError(
                f"shard {index} metadata and coverage escaped artifact boundary"
            )
        if coverage_path.name != metadata["coverage_data_file"]:
            raise ShardPlannerError(f"shard {index} coverage filename mismatch")
        if _sha256(coverage_path) != metadata["coverage_data_sha256"]:
            raise ShardPlannerError(f"shard {index} coverage digest mismatch")
        if coverage_path.stat().st_size != metadata["coverage_data_bytes"]:
            raise ShardPlannerError(f"shard {index} coverage byte count mismatch")
        _, measured_file_count = _coverage_properties(coverage_path)
        if measured_file_count != metadata["measured_file_count"]:
            raise ShardPlannerError(f"shard {index} measured-file count mismatch")
        staged_name = f".coverage.shard-{_shard_label(index, shard_count)}"
        staged_path = combine_dir / staged_name
        try:
            staged_bytes = coverage_path.read_bytes()
        except OSError as exc:
            raise ShardPlannerError(f"shard {index} coverage cannot be staged") from exc
        _write_immutable(staged_path, staged_bytes)
        staged.append(staged_path)
        expected_staged_names.add(staged_name)
    _require_directory_contents(combine_dir, expected_staged_names, label="coverage combine input")
    return tuple(staged)


def verify_branch_report(path: Path) -> dict[str, object]:
    """Fail closed unless coverage JSON explicitly contains populated branch data."""

    report = _mapping(_read_json(path, label="coverage report"), label="coverage report")
    meta = _mapping(report.get("meta"), label="coverage report meta")
    if meta.get("branch_coverage") is not True:
        raise ShardPlannerError("combined coverage report is line-only")
    totals = _mapping(report.get("totals"), label="coverage report totals")
    parsed: dict[str, int] = {}
    for key in ("covered_lines", "num_statements", "covered_branches", "num_branches"):
        parsed[key] = _require_integer(totals.get(key), label=f"coverage totals.{key}")
    if parsed["num_statements"] == 0:
        raise ShardPlannerError("combined coverage report has zero statements")
    if parsed["num_branches"] == 0:
        raise ShardPlannerError("combined coverage report has zero branches")
    if parsed["covered_lines"] > parsed["num_statements"]:
        raise ShardPlannerError("combined coverage line counts are impossible")
    if parsed["covered_branches"] > parsed["num_branches"]:
        raise ShardPlannerError("combined coverage branch counts are impossible")
    files = report.get("files")
    if not isinstance(files, dict) or not files:
        raise ShardPlannerError("combined coverage report contains no files")
    return {
        "covered_branches": parsed["covered_branches"],
        "num_branches": parsed["num_branches"],
        "schema_version": BRANCH_REPORT_SCHEMA_VERSION,
        "status": "PASS",
    }


def _command_plan(arguments: argparse.Namespace) -> dict[str, object]:
    git_sha = _require_git_sha(arguments.git_sha)
    if _head_sha() != git_sha:
        raise ShardPlannerError("Git HEAD does not match --git-sha")
    plan = build_plan(
        collect_eligible_nodeids(),
        shard_count=arguments.shard_count,
        git_sha=git_sha,
    )
    write_plan_outputs(plan, arguments.output_dir)
    return {
        "eligible_nodeid_count": plan["eligible_nodeid_count"],
        "eligible_nodeid_sha256": plan["eligible_nodeid_sha256"],
        "schema_version": SCHEMA_VERSION,
        "shard_count": plan["shard_count"],
        "status": "PASS",
    }


def _command_materialize(arguments: argparse.Namespace) -> dict[str, object]:
    visible, metadata = materialize_shard(
        plan_path=arguments.plan,
        shard_index=arguments.shard_index,
        coverage_data=arguments.coverage_data,
        output_dir=arguments.output_dir,
    )
    return {
        "coverage_data": visible.as_posix(),
        "metadata": metadata.as_posix(),
        "schema_version": SHARD_RESULT_SCHEMA_VERSION,
        "shard_index": arguments.shard_index,
        "status": "PASS",
    }


def _command_verify_artifacts(arguments: argparse.Namespace) -> dict[str, object]:
    staged = verify_artifacts(
        plan_path=arguments.plan,
        artifact_root=arguments.artifact_root,
        combine_dir=arguments.combine_dir,
        git_sha=arguments.git_sha,
    )
    return {
        "combine_input_count": len(staged),
        "schema_version": SHARD_RESULT_SCHEMA_VERSION,
        "status": "PASS",
    }


def _command_verify_branch_report(arguments: argparse.Namespace) -> dict[str, object]:
    return verify_branch_report(arguments.coverage_json)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--shard-count", type=int, required=True)
    plan.add_argument("--git-sha", required=True)
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.set_defaults(handler=_command_plan)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--plan", type=Path, required=True)
    materialize.add_argument("--shard-index", type=int, required=True)
    materialize.add_argument("--coverage-data", type=Path, required=True)
    materialize.add_argument("--output-dir", type=Path, required=True)
    materialize.set_defaults(handler=_command_materialize)

    verify = subparsers.add_parser("verify-artifacts")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--artifact-root", type=Path, required=True)
    verify.add_argument("--combine-dir", type=Path, required=True)
    verify.add_argument("--git-sha", required=True)
    verify.set_defaults(handler=_command_verify_artifacts)

    branch = subparsers.add_parser("verify-branch-report")
    branch.add_argument("coverage_json", type=Path)
    branch.set_defaults(handler=_command_verify_branch_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = arguments.handler(arguments)
    except ShardPlannerError as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "CI_COVERAGE_SHARD_VALIDATION_FAILED",
                        "message": str(exc),
                    },
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
