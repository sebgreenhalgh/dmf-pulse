#!/usr/bin/env python3
"""Fail-closed Stage-9 scope and required-resource validator."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path

REQUIRED_FILES = (
    "src/dmf_pulse/fpl_points/__init__.py",
    "src/dmf_pulse/fpl_points/allocation.py",
    "src/dmf_pulse/fpl_points/artifacts.py",
    "src/dmf_pulse/fpl_points/errors.py",
    "src/dmf_pulse/fpl_points/evaluation.py",
    "src/dmf_pulse/fpl_points/gameweek.py",
    "src/dmf_pulse/fpl_points/gameweek_summaries.py",
    "src/dmf_pulse/fpl_points/models.py",
    "src/dmf_pulse/fpl_points/monte_carlo.py",
    "src/dmf_pulse/fpl_points/rules_adapter.py",
    "src/dmf_pulse/fpl_points/resources/__init__.py",
    "src/dmf_pulse/fpl_points/resources/event_allocation_baseline.yaml",
    "src/dmf_pulse/fpl_points/resources/fpl_points_simulation.yaml",
    "src/dmf_pulse/fpl_points/seed.py",
    "src/dmf_pulse/fpl_points/service.py",
    "src/dmf_pulse/fpl_points/summaries.py",
    "src/dmf_pulse/fpl_points/upstream.py",
    "src/dmf_pulse/cli/fpl_points.py",
    "src/dmf_pulse/cli/app.py",
    "config/models/event_allocation_baseline.yaml",
    "config/models/fpl_points_simulation.yaml",
    "fixtures/points/PTS-009/reference_ruleset_test_only.json",
    "fixtures/points/PTS-009/golden_cases.json",
    "fixtures/points/PTS-009/fixture_request_example.json",
    "fixtures/points/PTS-009/schemas/fixture_request.schema.json",
    "fixtures/points/PTS-009/schemas/fixture_result.schema.json",
    "fixtures/points/PTS-009/schemas/gameweek_result.schema.json",
    "fixtures/points/PTS-009/manifest.json",
    "scripts/assurance/check_stage9_artifact.py",
    "scripts/assurance/check_stage9_coverage.py",
    "scripts/assurance/check_stage9_resources.py",
    "scripts/assurance/check_stage9_scope.py",
    "scripts/verify_pts009_wheel.py",
    "tests/support/reference_rules.py",
    "tests/support/factories.py",
    "tests/unit/fpl_points/test_accepted_rules_adapter.py",
    "tests/unit/fpl_points/test_allocation.py",
    "tests/unit/fpl_points/test_evaluation_and_artifacts.py",
    "tests/unit/fpl_points/test_fail_closed_edges.py",
    "tests/unit/fpl_points/test_rules_and_scoring.py",
    "tests/unit/fpl_points/test_seed.py",
    "tests/unit/fpl_points/test_summaries_and_mc.py",
    "tests/property/fpl_points/test_properties.py",
    "tests/contract/fpl_points/test_upstream_contracts.py",
    "tests/contract/fpl_points/test_packaged_resources.py",
    "tests/integration/fpl_points/test_fixture_pipeline.py",
    "tests/golden/fpl_points/test_reference_goldens.py",
    "tests/assurance/fpl_points/test_assurance_mutations.py",
    "tests/performance/fpl_points/test_smoke_budget.py",
    "IMPLEMENTATION_PLAN.md",
    "IMPLEMENTATION_RESULT.md",
    "SPEC_RECONCILIATION.md",
    "UPSTREAM_CONTRACT_MAP.md",
    "RULESET_READINESS.md",
    "ASSUMPTIONS_AND_DEVIATIONS.md",
    "GW1_MVP_STATUS.md",
    "PR_DESCRIPTION.md",
    "PLANS.md",
    "CHANGED_FILES.txt",
    "APPLY_INSTRUCTIONS.md",
    "ACCEPTANCE_COMMANDS.ps1",
    "docs/stages/09/README.md",
    "evidence/stages/09/stage_acceptance.json",
    "evidence/stages/09/STAGE_ACCEPTANCE.md",
    "evidence/stages/09/coverage.json",
    "evidence/stages/09/repository_coverage.json",
    "evidence/tickets/GCS-008/current_manifest.json",
)

ACCEPTED_PARENT_REVISION = "9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272"

FORBIDDEN_PREFIXES = (
    "src/dmf_pulse/optimisation/",
    "src/dmf_pulse/optimization/",
    "src/dmf_pulse/squad/",
    "src/dmf_pulse/transfers/",
    "src/dmf_pulse/captaincy/",
    "src/dmf_pulse/chips/",
    "src/dmf_pulse/rank_strategy/",
    "src/dmf_pulse/prices/",
    "src/dmf_pulse/manager_state/",
    "src/dmf_pulse/manager/",
    "src/dmf_pulse/autosubs/",
    "src/dmf_pulse/transfers/",
    "src/dmf_pulse/effective_ownership/",
)
FORBIDDEN_ACCEPTED_RULE_MUTATIONS = (
    "src/dmf_pulse/rules/scoring.py",
    "src/dmf_pulse/rules/bps.py",
    "src/dmf_pulse/rules/bonus.py",
)
ALLOWED_ROOT_FILES = {
    "ACCEPTANCE_COMMANDS.ps1",
    "APPLY_INSTRUCTIONS.md",
    "ASSUMPTIONS_AND_DEVIATIONS.md",
    "CHANGED_FILES.txt",
    "GW1_MVP_STATUS.md",
    "IMPLEMENTATION_PLAN.md",
    "IMPLEMENTATION_RESULT.md",
    "PLANS.md",
    "PR_DESCRIPTION.md",
    "RULESET_READINESS.md",
    "SPEC_RECONCILIATION.md",
    "UPSTREAM_CONTRACT_MAP.md",
    "evidence/tickets/GCS-008/current_manifest.json",
    "tests/__init__.py",
    ".github/workflows/ci.yml",
    "pyproject.toml",
}
ALLOWED_PREFIXES = (
    "config/models/",
    "evidence/tickets/PTS-009-STATIC-FIX/",
    "docs/stages/09/",
    "evidence/stages/09/",
    "fixtures/points/PTS-009/",
    "scripts/assurance/check_stage9_",
    "scripts/verify_pts009_wheel.py",
    "src/dmf_pulse/cli/",
    "src/dmf_pulse/fpl_points/",
    "tests/assurance/fpl_points/",
    "tests/contract/fpl_points/",
    "tests/golden/fpl_points/",
    "tests/integration/fpl_points/",
    "tests/performance/fpl_points/",
    "tests/property/fpl_points/",
    "tests/support/",
    "tests/unit/fpl_points/",
)
FORBIDDEN_STAGE9_SYMBOLS = {
    "autosub",
    "benchboost",
    "captaincy",
    "effectiveownership",
    "managerstate",
    "optimizer",
    "squadoptimizer",
    "transferhit",
    "triplecaptain",
}


def _normalized_symbol(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _changed_files(root: Path) -> tuple[str, ...]:
    path = root / "CHANGED_FILES.txt"
    if not path.exists():
        return ()
    return tuple(
        line.strip().replace("\\", "/")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _git_changed_files(
    root: Path, parent_revision: str
) -> tuple[tuple[str, ...] | None, str | None]:
    """Resolve the real parent-to-working-tree diff, failing closed on git errors."""

    try:
        top_level = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if Path(top_level).resolve() != root.resolve():
            return None, "GIT_ROOT_MISMATCH"
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", parent_revision, "--"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "-uall"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return None, "GIT_DIFF_UNAVAILABLE"
    changed = {line.strip().replace("\\", "/") for line in diff if line.strip()}
    for line in status:
        if len(line) >= 4 and line[:2] == "??":
            changed.add(line[3:].replace("\\", "/"))
    return tuple(sorted(changed)), None


def validate_scope(root: Path, *, parent_revision: str = ACCEPTED_PARENT_REVISION) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(f"MISSING_REQUIRED_FILE:{relative}")
        elif path.stat().st_size == 0:
            errors.append(f"EMPTY_REQUIRED_FILE:{relative}")
    changed = _changed_files(root)
    if not changed:
        errors.append("CHANGED_FILES_EMPTY_OR_MISSING")
    if len(changed) != len(set(changed)):
        errors.append("CHANGED_FILES_DUPLICATE_ENTRY")
    changed_set = set(changed)
    actual, git_error = _git_changed_files(root, parent_revision)
    if git_error is not None:
        errors.append(git_error)
        scope_paths = changed
    else:
        assert actual is not None
        actual_set = set(actual)
        for relative in sorted(actual_set - changed_set):
            errors.append(f"SCOPE_DECLARATION_MISSING:{relative}")
        for relative in sorted(changed_set - actual_set):
            errors.append(f"SCOPE_DECLARATION_EXTRA:{relative}")
        scope_paths = actual
    for relative in REQUIRED_FILES:
        if relative != "CHANGED_FILES.txt" and relative not in changed_set:
            errors.append(f"REQUIRED_FILE_NOT_LISTED:{relative}")
    for relative in scope_paths:
        if relative.startswith(FORBIDDEN_PREFIXES):
            errors.append(f"STAGE10_PLUS_SCOPE_VIOLATION:{relative}")
        if relative in FORBIDDEN_ACCEPTED_RULE_MUTATIONS:
            errors.append(f"ACCEPTED_RULES_MUTATION:{relative}")
        if relative not in ALLOWED_ROOT_FILES and not relative.startswith(ALLOWED_PREFIXES):
            errors.append(f"UNDECLARED_STAGE9_SCOPE:{relative}")
        if not (root / relative).exists():
            errors.append(f"CHANGED_FILE_NOT_PRESENT:{relative}")
    for relative in REQUIRED_FILES:
        if relative.endswith(".py"):
            path = root / relative
            if not path.is_file():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except (OSError, UnicodeError, SyntaxError) as exc:
                errors.append(f"PYTHON_PARSE_FAILED:{relative}:{type(exc).__name__}")
                continue
            executable = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            )
            if executable == 0 and relative.endswith("/__init__.py") is False:
                errors.append(f"ZERO_EXECUTABLE_DEFINITIONS:{relative}")
            if relative.startswith("src/dmf_pulse/fpl_points/"):
                names = {
                    _normalized_symbol(node.id)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                }
                names.update(
                    _normalized_symbol(node.name)
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                )
                forbidden = sorted(names & FORBIDDEN_STAGE9_SYMBOLS)
                if forbidden:
                    errors.append(f"STAGE10_PLUS_SYMBOL:{relative}:{','.join(forbidden)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    errors = validate_scope(args.root.resolve())
    payload = {
        "schema_version": "pts-009-scope-assurance-v1",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
