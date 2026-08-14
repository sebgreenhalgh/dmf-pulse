"""Fail closed when the GCS-008 branch or diff escapes its approved boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

REQUIRED_PARENT = "a5a0b66afd6e9645f971976d723e238824bee6a8"
EXPECTED_BRANCH = "stage/A8/GCS-008-goal-clean-sheet-distributions"
EXACT_ALLOWED = {
    ".gitignore",
    ".github/workflows/ci.yml",
    ".github/workflows/windows-smoke.yml",
    "ACCEPTANCE_COMMANDS.ps1",
    "APPLY_INSTRUCTIONS.md",
    "CHANGED_FILES.txt",
    "IMPLEMENTATION_PLAN.md",
    "IMPLEMENTATION_RESULT.md",
    "PLANS.md",
    "config/models/score_baseline.yaml",
    "docs/stages/GCS-008.md",
    "public_contracts/joint_score_distribution.schema.json",
    "public_contracts/score_distribution_request.schema.json",
    "public_contracts/score_distribution_result.schema.json",
    "scripts/check_gcs008_coverage_gates.py",
    "scripts/validate_gcs008_acceptance.py",
    "scripts/validate_gcs008_scope.py",
    "scripts/validate_repository.py",
    "scripts/verify_gcs008_wheel.py",
    "src/dmf_pulse/cli/app.py",
    "src/dmf_pulse/cli/events.py",
    "src/dmf_pulse/football_events/AGENTS.md",
    "src/dmf_pulse/football_events/__init__.py",
    "src/dmf_pulse/football_events/_decimal.py",
    "src/dmf_pulse/football_events/coherence.py",
    "src/dmf_pulse/football_events/evaluation.py",
    "src/dmf_pulse/football_events/market_constraints.py",
    "src/dmf_pulse/football_events/minutes_context.py",
    "src/dmf_pulse/football_events/poisson.py",
    "src/dmf_pulse/football_events/resources/__init__.py",
    "src/dmf_pulse/football_events/resources/joint_score_distribution.schema.json",
    "src/dmf_pulse/football_events/resources/score_baseline.yaml",
    "src/dmf_pulse/football_events/resources/score_distribution_request.schema.json",
    "src/dmf_pulse/football_events/resources/score_distribution_result.schema.json",
    "src/dmf_pulse/football_events/score_distribution.py",
    "src/dmf_pulse/football_events/score_grid.py",
    "src/dmf_pulse/football_events/score_prior.py",
    "src/dmf_pulse/football_events/score_projection.py",
    "src/dmf_pulse/football_events/service.py",
    "tests/unit/scripts/test_gcs008_coverage_gate.py",
    "tests/unit/scripts/test_gcs008_acceptance.py",
    "tests/unit/scripts/test_gcs008_scope.py",
    "tests/unit/scripts/test_gcs008_wheel.py",
}
ALLOWED_PREFIXES = (
    "evidence/tickets/GCS-008/",
    "fixtures/events/score/GCS-008/",
    "tests/contract/football_events/",
    "tests/golden/football_events/",
    "tests/integration/football_events/",
    "tests/property/football_events/",
    "tests/unit/football_events/",
    "tickets/GCS-008/",
)
FORBIDDEN_PREFIXES = (
    "alembic/",
    "migrations/",
    "src/dmf_pulse/availability/",
    "src/dmf_pulse/database/migrations/",
)
FORBIDDEN_EXACT = {"pyproject.toml", "uv.lock", "pylock.toml"}


class ScopeError(ValueError):
    """The observed repository state is outside the approved Stage-8 scope."""


def _normalized(path: str) -> str:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or str(candidate) in {"", "."}:
        raise ScopeError(f"changed path is unsafe: {path}")
    return candidate.as_posix()


def validate_changed_paths(paths: Iterable[str]) -> tuple[str, ...]:
    changed = tuple(sorted({_normalized(path) for path in paths if path.strip()}))
    if not changed:
        raise ScopeError("GCS-008 diff is empty")
    forbidden = [
        path for path in changed if path in FORBIDDEN_EXACT or path.startswith(FORBIDDEN_PREFIXES)
    ]
    if forbidden:
        raise ScopeError(f"frozen dependency or migration changed: {forbidden}")
    outside = [
        path
        for path in changed
        if path not in EXACT_ALLOWED and not path.startswith(ALLOWED_PREFIXES)
    ]
    if outside:
        raise ScopeError(f"changed path is outside GCS-008 scope: {outside}")
    return changed


def _run_git(arguments: Sequence[str], *, allow_failure: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScopeError("git repository state could not be inspected") from exc
    if result.returncode != 0 and not allow_failure:
        raise ScopeError("required parent or repository state is unavailable")
    return result.stdout


def _git_changed_paths() -> tuple[str, ...]:
    """Include committed, staged, unstaged, and untracked paths versus the parent."""

    _run_git(["cat-file", "-e", f"{REQUIRED_PARENT}^{{commit}}"])
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", REQUIRED_PARENT, "HEAD"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScopeError("required-parent ancestry could not be inspected") from exc
    if ancestor.returncode != 0:
        raise ScopeError("HEAD is not descended from the required parent")
    branch = _run_git(["branch", "--show-current"]).strip()
    effective_branch = (
        branch or os.environ.get("GITHUB_HEAD_REF", "") or os.environ.get("GITHUB_REF_NAME", "")
    )
    if effective_branch != EXPECTED_BRANCH:
        raise ScopeError(f"current branch must be {EXPECTED_BRANCH}")
    tracked = _run_git(["diff", "--name-only", REQUIRED_PARENT, "--"])
    untracked = _run_git(["ls-files", "--others", "--exclude-standard"])
    return tuple(line for line in (*tracked.splitlines(), *untracked.splitlines()) if line.strip())


def main() -> int:
    try:
        changed = validate_changed_paths(_git_changed_paths())
    except ScopeError as exc:
        print(
            json.dumps(
                {
                    "error": {"code": "GCS008_SCOPE_FAILED", "message": str(exc)},
                    "schema_version": "gcs008-scope-validation-v1",
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "branch": EXPECTED_BRANCH,
                "changed_file_count": len(changed),
                "required_parent": REQUIRED_PARENT,
                "schema_version": "gcs008-scope-validation-v1",
                "status": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
