"""Validate the frozen OPT-010 branch, parent, and path scope."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--parent-revision", required=True)
    parser.add_argument("--ticket", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    ticket = yaml.safe_load(args.ticket.read_text(encoding="utf-8"))
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    merge_base = subprocess.check_output(
        ["git", "merge-base", "HEAD", args.parent_revision], cwd=root, text=True
    ).strip()
    allowed = set(ticket["allowed_files"]["create"] + ticket["allowed_files"]["modify"])
    allowed.update({"PLANS.md", "OPT-010_SOL_PLAN.md", "tickets/OPT-010/**"})
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", args.parent_revision], cwd=root, text=True
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True
    ).splitlines()
    paths = sorted(set(changed + untracked))
    forbidden = [
        path
        for path in paths
        if not any(
            path == item or (item.endswith("/**") and path.startswith(item[:-3]))
            for item in allowed
        )
    ]
    report = {
        "branch": branch,
        "head": head,
        "merge_base": merge_base,
        "expected_branch": ticket["expected_branch"],
        "required_base_commit": ticket["required_base_commit"],
        "paths": paths,
        "forbidden_paths": forbidden,
        "ok": branch == ticket["expected_branch"]
        and merge_base == ticket["required_base_commit"]
        and not forbidden,
    }
    output = root / "evidence/tickets/OPT-010/scope_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
