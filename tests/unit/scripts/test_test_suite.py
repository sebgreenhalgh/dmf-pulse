from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/test_suite.py")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_suite", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _config() -> dict[str, object]:
    return {
        "schema_version": "dmf-test-cadence-v1",
        "full_marker_expression": "not performance",
        "fast_roots": ["tests/contract", "tests/property", "tests/security", "tests/unit"],
        "fast_excluded_markers": ["integration", "migration", "performance", "postgres"],
        "fast_excluded_roots": ["tests/unit/cross_boundary"],
        "deep_assurance_modules": ["tests/unit/test_deep.py"],
        "policy": {name: name for name in ("checkpoint", "fast", "full", "nightly")},
    }


def _tests(module: ModuleType):
    return (
        module.CollectedTest(
            "tests/unit/test_fast.py::test_a", "tests/unit/test_fast.py", ("unit",), ()
        ),
        module.CollectedTest(
            "tests/unit/test_deep.py::test_b", "tests/unit/test_deep.py", ("unit",), ()
        ),
        module.CollectedTest(
            "tests/integration/test_db.py::test_c",
            "tests/integration/test_db.py",
            ("integration", "postgres"),
            (),
        ),
        module.CollectedTest(
            "tests/performance/test_perf.py::test_d",
            "tests/performance/test_perf.py",
            ("performance",),
            (),
        ),
    )


def test_cadence_plans_are_complete_deterministic_and_transport_safe() -> None:
    module = _module()
    tests = _tests(module)
    assert module.select_cadence("fast", tests, _config()) == ("tests/unit/test_fast.py::test_a",)
    assert module.select_cadence("nightly", tests, _config()) == (
        "tests/performance/test_perf.py::test_d",
        "tests/unit/test_deep.py::test_b",
    )
    assert module.select_cadence("full", tests, _config()) == tuple(
        sorted(test.nodeid for test in tests)
    )
    forward = module.build_plan("fast", _tests(module), _config())
    reverse = module.build_plan("fast", reversed(_tests(module)), _config())
    assert forward == reverse
    assert forward["selected_count"] == 1
    assert len(forward["nodeids_sha256"]) == 64
    nodeids = (
        'tests/unit/test_ids.py::test_value[{"key": "two words"}]',
        "tests/unit/test_ids.py::test_value[path/with spaces]",
        "tests/unit/test_other.py::test_plain",
    )
    assert module.nodeids_to_module_paths(nodeids) == (
        "tests/unit/test_ids.py",
        "tests/unit/test_other.py",
    )
    assert module.fast_marker_expression(_config()) == (
        "not integration and not migration and not performance and not postgres"
    )


def test_config_mutations_fail_closed(tmp_path: Path) -> None:
    module = _module()
    mutations = (
        (lambda value: value.update(schema_version="wrong"), "schema_version"),
        (lambda value: value.update(full_marker_expression="unit"), "Phase-1"),
        (lambda value: value.update(fast_roots=["../tests"]), "safe repository-relative"),
        (lambda value: value.update(deep_assurance_modules=[]), "non-empty list"),
    )
    path = tmp_path / "cadence.json"
    for mutation, message in mutations:
        value = _config()
        mutation(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(module.TestSuiteError, match=message):
            module.load_config(path)
