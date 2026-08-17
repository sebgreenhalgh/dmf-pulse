"""Verify the final OPT-011 parent-to-head scope and anti-empty-delivery gates."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

DEFAULT_BASE = "49103e03bb1e7500aff5c15b90b136f2cc476405"
REQUIRED_PREFIXES = {
    "production": ("src/dmf_pulse/optimisation/", "src/dmf_pulse/rules/", "src/dmf_pulse/cli/"),
    "tests": ("tests/",),
    "fixtures": ("fixtures/optimisation/multi_gameweek/",),
}


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--head", default="HEAD")
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    names = tuple(
        line
        for line in _git(
            root, "diff", "--name-only", f"{arguments.base}..{arguments.head}"
        ).splitlines()
        if line
    )
    patch = _git(root, "diff", "--binary", f"{arguments.base}..{arguments.head}")
    categories = {
        label: sorted(path for path in names if path.startswith(prefixes))
        for label, prefixes in REQUIRED_PREFIXES.items()
    }
    production_python = [
        path
        for path in categories["production"]
        if path.endswith(".py") and path.startswith("src/dmf_pulse/")
    ]
    checks = {
        "diff_non_empty": bool(names and patch.strip()),
        "production_source_present": bool(production_python),
        "tests_present": bool(categories["tests"]),
        "fixtures_present": bool(categories["fixtures"]),
        "stage10_parent_is_ancestor": subprocess.run(
            ["git", "merge-base", "--is-ancestor", arguments.base, arguments.head],
            cwd=root,
            check=False,
        ).returncode
        == 0,
    }
    report = {
        "schema_version": "opt-011-scope-assurance-v1",
        "base": arguments.base,
        "head": _git(root, "rev-parse", arguments.head).strip(),
        "changed_file_count": len(names),
        "changed_files": list(names),
        "categories": categories,
        "checks": checks,
        "ok": all(checks.values()),
    }
    output = root / "evidence/tickets/OPT-011/scope_assurance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
