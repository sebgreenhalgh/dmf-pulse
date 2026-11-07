"""Run scoped feedback tiers; verify FULL only from every exact-commit CI job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKES = (
    "tests/unit/assurance/test_secret_scan.py",
    "tests/unit/ingestion/test_rights_and_fixtures.py",
    "tests/integration/package/test_import_side_effects.py",
)
FULL_JOBS = frozenset(
    {"Pre-flight", "Combined coverage gate", "Post-coverage acceptance", "Python 3.13 / Ubuntu"}
    | {f"Coverage shard {index} of 16" for index in range(16)}
)
BUDGETS = {"fast": 180, "focused": 900, "integration": 1800}


def _target(value: str, root: Path, prefix: str) -> str:
    path = Path(value)
    if (
        path.is_absolute()
        or ":" in value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or not value.startswith(prefix + "/")
        or not (root / path).resolve().is_relative_to(root.resolve())
        or not (root / path).exists()
        or ((root / path).is_file() and path.suffix != ".py")
    ):
        raise ValueError("explicit existing repository test/source paths required")
    return path.as_posix()


def partial_commands(
    tier: str,
    targets: Sequence[str],
    type_targets: Sequence[str],
    coverage_modules: Sequence[str],
    folder: Path,
    *,
    root: Path = ROOT,
) -> list[list[str]]:
    if tier not in BUDGETS or not targets:
        raise ValueError("partial tiers require explicit affected test modules/directories")
    selected = sorted({_target(value, root, "tests") for value in targets})
    typed = sorted({_target(value, root, "src") for value in type_targets})
    if tier == "integration" and not any(
        value.startswith("tests/integration/") for value in selected
    ):
        raise ValueError("INTEGRATION requires an explicit integration target")
    if not folder.resolve().is_relative_to((root / "review_pack").resolve()):
        raise ValueError("check artifacts must remain inside ignored review_pack")
    for module in coverage_modules:
        if not module.startswith("dmf_pulse.") or not all(
            part.isidentifier() for part in module.split(".")
        ):
            raise ValueError("coverage module must be a dmf_pulse import name")
    if tier == "fast" and coverage_modules:
        raise ValueError("FAST has no coverage instrumentation; use FOCUSED")
    commands = [
        ["uv", "run", "--frozen", "ruff", "format", "--check", "."],
        ["uv", "run", "--frozen", "ruff", "check", "."],
    ]
    if typed:
        commands.append(["uv", "run", "--frozen", "mypy", *typed])
    pytest = [
        "uv",
        "run",
        "--frozen",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={folder / 'pytest'}",
        "--durations=20",
        f"--junitxml={folder / 'junit.xml'}",
        *sorted(set(selected) | set(SMOKES)),
    ]
    if coverage_modules:
        pytest.extend(f"--cov={module}" for module in sorted(set(coverage_modules)))
        pytest.extend(
            [
                "--cov-branch",
                "--cov-fail-under=0",
                "--cov-report=term-missing",
                f"--cov-report=json:{folder / 'coverage.json'}",
            ]
        )
    commands.append(pytest)
    return commands


def require_full_run(payload: dict[str, object], head: str, *, workflow_id: int) -> None:
    if (
        payload.get("headSha") != head
        or payload.get("workflowName") != "dmf-pulse-ci"
        or payload.get("workflowDatabaseId") != workflow_id
        or payload.get("event") != "push"
    ):
        raise ValueError("FULL requires the authoritative workflow at this exact commit")
    if payload.get("status") != "completed" or payload.get("conclusion") != "success":
        raise ValueError("FULL workflow has not completed successfully")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != len(FULL_JOBS):
        raise ValueError("FULL mandatory job inventory is incomplete or changed")
    if (
        any(not isinstance(job, dict) for job in jobs)
        or {job.get("name") for job in jobs} != FULL_JOBS
        or any(
            job.get("status") != "completed" or job.get("conclusion") != "success" for job in jobs
        )
    ):
        raise ValueError("FULL requires every mandatory job without omissions or skips")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _source_state() -> dict[str, object]:
    head = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    diff = _git("diff", "--binary", "HEAD")
    untracked = {}
    for name in _git("ls-files", "--others", "--exclude-standard").splitlines():
        path = ROOT / name
        if (
            name.split("/", 1)[0]
            in {"src", "tests", "scripts", "config", "fixtures", ".github", "tickets"}
            and path.is_file()
        ):
            untracked[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "head": head,
        "clean": not status,
        "git_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "git_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "untracked_authored_file_sha256": untracked,
        "qualification": "partial feedback source snapshot; full acceptance requires clean exact-commit CI",
    }


def _write_receipt(folder: Path, receipt: dict[str, object]) -> None:
    (folder / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tier", choices=("fast", "focused", "integration", "full"))
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--type-target", action="append", default=[])
    parser.add_argument("--coverage-module", action="append", default=[])
    parser.add_argument("--ci-run", type=int)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    head = _git("rev-parse", "HEAD")
    folder = ROOT / "review_pack/dev-checks" / f"{args.tier}-{uuid.uuid4().hex[:12]}"
    if args.tier == "full":
        if not args.ci_run or args.target or args.type_target or args.coverage_module or args.plan:
            parser.error("FULL verifies --ci-run ID; partial selectors/plan are prohibited")
        if _git("status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError("FULL requires a clean worktree bound to CI")
        result = subprocess.run(
            [
                "gh",
                "run",
                "view",
                str(args.ci_run),
                "--repo",
                "sebgreenhalgh/dmf-pulse",
                "--json",
                "headSha,workflowName,workflowDatabaseId,event,status,conclusion,jobs,url",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=90,
        )
        payload = json.loads(result.stdout)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "ci.json").write_bytes(result.stdout)
        receipt = {"tier": "FULL", "head": head, "status": "RUNNING", "ci_run": args.ci_run}
        _write_receipt(folder, receipt)
        try:
            authority = subprocess.run(
                ["gh", "api", "repos/sebgreenhalgh/dmf-pulse/actions/workflows/ci.yml"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                timeout=30,
            )
            workflow = json.loads(authority.stdout)
            if workflow.get("path") != ".github/workflows/ci.yml":
                raise ValueError("FULL authoritative workflow path differs")
            require_full_run(payload, head, workflow_id=workflow["id"])
            if _git("rev-parse", "HEAD") != head or _git(
                "status", "--porcelain=v1", "--untracked-files=all"
            ):
                raise ValueError("FULL source changed during verification")
        except BaseException as error:
            receipt.update(status="INCOMPLETE_OR_FAILED", exception_family=type(error).__name__)
            _write_receipt(folder, receipt)
            raise
        receipt.update(
            status="PASS",
            mandatory_jobs=len(FULL_JOBS),
            event=payload["event"],
            workflow_id=workflow["id"],
            workflow_path=workflow["path"],
            production_activation_or_model_promotion=False,
        )
        _write_receipt(folder, receipt)
        print(
            json.dumps(
                {
                    "tier": "FULL",
                    "status": "PASS",
                    "head": head,
                    "ci_run": args.ci_run,
                    "mandatory_jobs": len(FULL_JOBS),
                    "production_activation_or_model_promotion": False,
                }
            )
        )
        return 0
    if args.ci_run:
        parser.error("--ci-run is only valid for FULL")
    source = _source_state()
    changed_source = _git("diff", "--name-only", "HEAD", "--", "src") or _git(
        "ls-files", "--others", "--exclude-standard", "--", "src"
    )
    type_targets = args.type_target or (["src/dmf_pulse"] if changed_source else [])
    commands = partial_commands(
        args.tier, args.target, type_targets, args.coverage_module, folder, root=ROOT
    )
    if args.plan:
        print(
            json.dumps(
                {"tier": args.tier.upper(), "commands": commands, "full_release_acceptance": False},
                indent=2,
            )
        )
        return 0
    folder.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    results = []
    receipt = {
        "tier": args.tier.upper(),
        "head": head,
        "source": source,
        "status": "RUNNING",
        "planned_steps": len(commands),
        "completed_steps": 0,
        "full_release_acceptance": False,
        "global_coverage_floor_applied": False,
        "type_check": "EXPLICIT_OR_CONSERVATIVE_SOURCE_TARGETS"
        if type_targets
        else "NOT_REQUESTED",
        "steps": results,
    }
    _write_receipt(folder, receipt)
    for index, command in enumerate(commands):
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                timeout=BUDGETS[args.tier],
            )
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as error:
            code, stdout, stderr = 124, error.stdout or b"", error.stderr or b""
        except OSError as error:
            code, stdout, stderr = 127, b"", type(error).__name__.encode()
        except KeyboardInterrupt:
            receipt.update(status="INTERRUPTED", completed_steps=len(results))
            _write_receipt(folder, receipt)
            raise
        (folder / f"{index}.stdout.log").write_bytes(stdout)
        (folder / f"{index}.stderr.log").write_bytes(stderr)
        results.append(
            {
                "command": command,
                "exit_code": code,
                "seconds": time.perf_counter() - started,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            }
        )
        receipt.update(status="FAIL" if code else "RUNNING", completed_steps=len(results))
        _write_receipt(folder, receipt)
        print(
            json.dumps(
                {
                    "step": index,
                    "exit_code": code,
                    "seconds": results[-1]["seconds"],
                    "artifacts": str(folder),
                }
            ),
            flush=True,
        )
        if code:
            return code if code > 0 else 1
    if _source_state() != source:
        receipt.update(status="SOURCE_CHANGED_DURING_CHECKS")
        _write_receipt(folder, receipt)
        return 2
    receipt.update(status="PARTIAL_FEEDBACK_PASS")
    _write_receipt(folder, receipt)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"checks refused: {error}", file=sys.stderr)
        raise SystemExit(2) from None
