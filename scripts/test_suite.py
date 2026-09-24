"""Plan, run, and inventory the explicit DMF Pulse test cadences."""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/testing/cadence.json"
_TICKET = re.compile(r"\b[A-Z][A-Z0-9]+-\d+[A-Z0-9-]*\b")
_IGNORED_FIXTURES = {
    "_session_faker",
    "event_loop_policy",
    "isolate_home_and_network",
    "monkeypatch",
    "patch_all",
    "request",
    "tmp_path",
    "tmp_path_factory",
}
_CONFIG_KEYS = {
    "deep_assurance_modules",
    "fast_excluded_markers",
    "fast_excluded_roots",
    "fast_roots",
    "full_marker_expression",
    "policy",
    "schema_version",
}


class TestSuiteError(ValueError):
    """The cadence contract or generated plan is invalid."""


@dataclass(frozen=True)
class CollectedTest:
    nodeid: str
    path: str
    markers: tuple[str, ...]
    fixtures: tuple[str, ...]


class _CollectionPlugin:
    def __init__(self) -> None:
        self.tests: tuple[CollectedTest, ...] = ()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        records: list[CollectedTest] = []
        for item in session.items:
            path = item.nodeid.partition("::")[0].replace("\\", "/")
            records.append(
                CollectedTest(
                    nodeid=item.nodeid.replace("\\", "/"),
                    path=path,
                    markers=tuple(sorted({marker.name for marker in item.iter_markers()})),
                    fixtures=tuple(sorted(set(getattr(item, "fixturenames", ())))),
                )
            )
        self.tests = tuple(records)


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _safe_relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TestSuiteError(f"{label} must be a non-empty string")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TestSuiteError(f"{label} must be a safe repository-relative path")
    return path.as_posix()


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != _CONFIG_KEYS:
        raise TestSuiteError("cadence config has invalid top-level keys")
    if value["schema_version"] != "dmf-test-cadence-v1":
        raise TestSuiteError("cadence config has an unsupported schema_version")
    if value["full_marker_expression"] != "not performance":
        raise TestSuiteError("full cadence must preserve the Phase-1 non-performance selector")
    for key in ("fast_roots", "fast_excluded_roots", "deep_assurance_modules"):
        raw = value[key]
        if not isinstance(raw, list) or not raw:
            raise TestSuiteError(f"{key} must be a non-empty list")
        normalized = [_safe_relative_path(item, label=key) for item in raw]
        if normalized != sorted(set(normalized)):
            raise TestSuiteError(f"{key} must be sorted and unique")
        value[key] = normalized
    markers = value["fast_excluded_markers"]
    if not isinstance(markers, list) or markers != sorted(set(markers)):
        raise TestSuiteError("fast_excluded_markers must be a sorted unique list")
    if not all(isinstance(marker, str) and marker for marker in markers):
        raise TestSuiteError("fast_excluded_markers contains an invalid marker")
    policy = value["policy"]
    if not isinstance(policy, dict) or set(policy) != {"checkpoint", "fast", "full", "nightly"}:
        raise TestSuiteError("policy must document all four cadences")
    if not all(isinstance(description, str) and description for description in policy.values()):
        raise TestSuiteError("every cadence policy must be a non-empty string")
    return value


def collect_tests(marker_expression: str | None = None) -> tuple[CollectedTest, ...]:
    plugin = _CollectionPlugin()
    arguments = ["--collect-only", "-q", "-p", "no:cacheprovider"]
    if marker_expression is not None:
        arguments.extend(("-m", marker_expression))
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = pytest.main(arguments, plugins=[plugin])
    if exit_code != pytest.ExitCode.OK:
        details = (stdout.getvalue() + stderr.getvalue()).strip()
        raise TestSuiteError(f"pytest collection failed with exit code {int(exit_code)}: {details}")
    nodeids = [test.nodeid for test in plugin.tests]
    if len(nodeids) != len(set(nodeids)):
        raise TestSuiteError("pytest collection returned duplicate nodeids")
    return tuple(sorted(plugin.tests, key=lambda test: test.nodeid))


def select_cadence(
    cadence: str,
    tests: Iterable[CollectedTest],
    config: Mapping[str, object],
) -> tuple[str, ...]:
    records = tuple(tests)
    deep_modules = set(config["deep_assurance_modules"])
    collected_modules = {test.path for test in records}
    missing_deep_modules = sorted(deep_modules - collected_modules)
    if missing_deep_modules:
        raise TestSuiteError(
            f"deep-assurance config contains uncollected modules: {missing_deep_modules}"
        )
    if cadence == "full":
        selected = records
    elif cadence == "nightly":
        selected = tuple(
            test for test in records if test.path in deep_modules or "performance" in test.markers
        )
    elif cadence == "fast":
        roots = tuple(f"{root}/" for root in config["fast_roots"])
        excluded_roots = tuple(f"{root}/" for root in config["fast_excluded_roots"])
        excluded_markers = set(config["fast_excluded_markers"])
        selected = tuple(
            test
            for test in records
            if test.path.startswith(roots)
            and not test.path.startswith(excluded_roots)
            and test.path not in deep_modules
            and not excluded_markers.intersection(test.markers)
        )
    else:
        raise TestSuiteError(f"unsupported planned cadence: {cadence}")
    nodeids = tuple(sorted(test.nodeid for test in selected))
    if not nodeids:
        raise TestSuiteError(f"{cadence} cadence selected no tests")
    return nodeids


def build_plan(
    cadence: str,
    tests: Iterable[CollectedTest],
    config: Mapping[str, object],
) -> dict[str, object]:
    records = tuple(tests)
    nodeids = select_cadence(cadence, records, config)
    all_nodeids = {test.nodeid for test in records}
    if not set(nodeids).issubset(all_nodeids):
        raise TestSuiteError("cadence plan contains a node outside the collected population")
    digest = hashlib.sha256("\n".join(nodeids).encode("utf-8") + b"\n").hexdigest()
    return {
        "schema_version": "dmf-test-cadence-plan-v1",
        "cadence": cadence,
        "collected_count": len(records),
        "selected_count": len(nodeids),
        "nodeids_sha256": digest,
        "nodeids": list(nodeids),
    }


def _source_facts(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    fixtures: set[str] = set()
    assertions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("dmf_pulse"))
        elif (
            isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("dmf_pulse")
        ):
            imports.add(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "fixture"
                for decorator in node.decorator_list
            ):
                fixtures.add(node.name)
        elif isinstance(node, ast.Assert):
            assertions.add(hashlib.sha256(ast.dump(node.test).encode("utf-8")).hexdigest())
    lower = source.lower()
    return {
        "assertion_hashes": assertions,
        "declared_fixtures": fixtures,
        "historical_ownership": sorted(set(_TICKET.findall(source))),
        "model_fitting": bool(re.search(r"\b(fit|fitted|model_prepared|team_strength)\b", lower)),
        "optimiser_execution": "optimis" in lower
        or any("optimisation" in name for name in imports),
        "prepared_runner_context": bool(
            re.search(r"(one_command|prepared_rolling|rolling_execution|prepared-runner)", lower)
        ),
        "production_modules_touched": sorted(imports),
    }


def _load_timings(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    modules = value.get("modules") if isinstance(value, dict) else None
    if not isinstance(modules, list):
        raise TestSuiteError("timing profile must contain a modules list")
    result: dict[str, float] = {}
    for entry in modules:
        if not isinstance(entry, dict):
            raise TestSuiteError("timing profile module entry must be an object")
        module_path = _safe_relative_path(entry.get("path"), label="timing module path")
        seconds = entry.get("wall_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
            raise TestSuiteError("timing module wall_seconds must be non-negative")
        result[module_path] = float(seconds)
    return result


def build_inventory(
    tests: Iterable[CollectedTest],
    config: Mapping[str, object],
    *,
    timing_path: Path | None = None,
) -> dict[str, object]:
    records = tuple(tests)
    timings = _load_timings(timing_path)
    fast = set(select_cadence("fast", records, config))
    grouped: dict[str, list[CollectedTest]] = defaultdict(list)
    for test in records:
        grouped[test.path].append(test)
    facts = {path: _source_facts(ROOT / path) for path in grouped}
    assertion_owners: dict[str, set[str]] = defaultdict(set)
    for path, value in facts.items():
        for assertion_hash in value["assertion_hashes"]:
            assertion_owners[assertion_hash].add(path)
    modules: list[dict[str, object]] = []
    for path, module_tests in sorted(grouped.items()):
        value = facts[path]
        overlap = sorted(
            {
                owner
                for assertion_hash in value["assertion_hashes"]
                for owner in assertion_owners[assertion_hash]
                if owner != path
            }
        )
        markers = sorted({marker for test in module_tests for marker in test.markers})
        fixtures = sorted(
            {
                fixture
                for test in module_tests
                for fixture in test.fixtures
                if fixture not in _IGNORED_FIXTURES and not fixture.startswith("_")
            }
            | value["declared_fixtures"]
        )
        module_nodeids = {test.nodeid for test in module_tests}
        if module_nodeids.issubset(fast):
            disposition = "KEEP_FAST"
        elif "performance" in markers:
            disposition = "KEEP_ACCEPTANCE"
        else:
            disposition = "KEEP_ACCEPTANCE"
        category = PurePosixPath(path).parts[1] if len(PurePosixPath(path).parts) > 2 else "other"
        modules.append(
            {
                "path": path,
                "test_count": len(module_tests),
                "markers": markers,
                "broad_category": category,
                "approximate_runtime_seconds": timings.get(path),
                "runtime_source": "isolated_local_pytest" if path in timings else "not_profiled",
                "postgres_required": bool({"postgres", "migration"}.intersection(markers)),
                "optimiser_execution": value["optimiser_execution"],
                "real_model_fitting": value["model_fitting"],
                "prepared_runner_context": value["prepared_runner_context"],
                "major_fixtures_setup": fixtures,
                "production_modules_touched": value["production_modules_touched"],
                "historical_stage_ticket_ownership": value["historical_ownership"],
                "assertion_overlap_modules": overlap,
                "public_contract_required": bool(
                    {"contract", "golden", "security"}.intersection(markers)
                    or category in {"contract", "golden", "security"}
                    or "/cli/" in path
                    or path.endswith("test_cli.py")
                ),
                "unique_branch_coverage": {
                    "status": "NOT_ISOLATED",
                    "removal_rule": "No removal permitted without successor and counterfactual evidence",
                },
                "proposed_disposition": disposition,
            }
        )
    return {
        "schema_version": "dmf-test-module-inventory-v1",
        "collection": {
            "test_count": len(records),
            "module_count": len(grouped),
            "fast_count": len(fast),
            "performance_count": sum("performance" in test.markers for test in records),
        },
        "disposition_enum": [
            "KEEP_FAST",
            "KEEP_ACCEPTANCE",
            "KEEP_NIGHTLY",
            "CONSOLIDATE",
            "SHARE_SETUP",
            "REMOVE_REDUNDANT",
            "REVIEW_REQUIRED",
        ],
        "modules": modules,
    }


def _write_output(value: object, output: Path | None) -> None:
    rendered = _canonical_json(value)
    if output is None:
        sys.stdout.write(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")


def nodeids_to_module_paths(nodeids: Iterable[str]) -> tuple[str, ...]:
    paths = {
        _safe_relative_path(nodeid.partition("::")[0], label="nodeid path") for nodeid in nodeids
    }
    return tuple(sorted(paths))


def fast_marker_expression(config: Mapping[str, object]) -> str:
    return " and ".join(f"not {marker}" for marker in config["fast_excluded_markers"])


def _run_pytest(arguments: Sequence[str], pytest_args: Sequence[str]) -> int:
    command = [sys.executable, "-m", "pytest", *arguments, *pytest_args]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("cadence", choices=("fast", "full", "nightly"))
    plan.add_argument("--output", type=Path)
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--timings", type=Path)
    inventory.add_argument("--output", type=Path)
    run = subparsers.add_parser("run")
    run.add_argument("cadence", choices=("fast", "checkpoint", "full", "nightly"))
    run.add_argument("--target", action="append", default=[])
    run.add_argument("--pytest-arg", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    config = load_config(arguments.config)
    if arguments.command == "run" and arguments.cadence == "checkpoint":
        if not arguments.target:
            raise TestSuiteError("checkpoint cadence requires at least one --target")
        command = [
            sys.executable,
            "-m",
            "pytest",
            *arguments.target,
            "-m",
            "not performance",
            *arguments.pytest_arg,
        ]
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    tests = collect_tests()
    if arguments.command == "inventory":
        _write_output(
            build_inventory(tests, config, timing_path=arguments.timings), arguments.output
        )
        return 0
    plan = build_plan(arguments.cadence, tests, config)
    if arguments.command == "plan":
        _write_output(plan, arguments.output)
        return 0
    print(
        f"cadence={arguments.cadence} selected={plan['selected_count']} "
        f"collected={plan['collected_count']} sha256={plan['nodeids_sha256']}",
        flush=True,
    )
    if arguments.cadence == "fast":
        return _run_pytest(
            (
                *nodeids_to_module_paths(plan["nodeids"]),
                "-m",
                fast_marker_expression(config),
            ),
            arguments.pytest_arg,
        )
    if arguments.cadence == "full":
        first = _run_pytest(("-m", "not performance"), arguments.pytest_arg)
        return first if first else _run_pytest(("-m", "performance"), arguments.pytest_arg)
    deep_modules = tuple(config["deep_assurance_modules"])
    first = _run_pytest((*deep_modules, "-m", "not performance"), arguments.pytest_arg)
    return first if first else _run_pytest(("-m", "performance"), arguments.pytest_arg)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestSuiteError as error:
        print(f"test-suite error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
