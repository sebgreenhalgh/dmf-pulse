"""Offline exact-object preservation proof for the 001P lineage checkpoint."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PRIVATE = "f39ba4ee3ea748cf60c5743e48f7f68cc6784a71"
PUBLIC = "6b96f5b85692fb3ec368ee261ad93a554128e017"
COMMON = "99418f3316277f4dae347d80358d5dd5a09655b2"
ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--integration-commit", default="508049a560c0ebc9fad7b65e8be1d9a837b7646f")
    args = parser.parse_args()
    assert git("merge-base", PRIVATE, PUBLIC) == COMMON
    integrated = git("rev-parse", args.integration_commit + "^{commit}")
    public_paths = git("diff", "--name-only", COMMON, PUBLIC).splitlines()
    integration_files = {
        "PLANS.md",
        "pyproject.toml",
        "evidence/tickets/PRC-013/current_manifest.json",
    }
    preserved = [path for path in public_paths if path not in integration_files]
    mismatches = [
        path
        for path in preserved
        if git("rev-parse", f"{PUBLIC}:{path}") != git("rev-parse", f"{integrated}:{path}")
    ]
    assert not mismatches, "public commit-owned content changed"
    private_paths = (
        "src/dmf_pulse/private_v1",
        "src/dmf_pulse/availability",
        "src/dmf_pulse/fpl_points",
        "src/dmf_pulse/optimisation",
        "src/dmf_pulse/cli/private_v1.py",
        "src/dmf_pulse/cli/pulse.py",
        "src/dmf_pulse/cli/app.py",
    )
    private_diff = git("diff", "--name-only", PRIVATE, integrated, "--", *private_paths)
    assert not private_diff, "private baseline content changed before the shadow seam"
    report = {
        "status": "PASS",
        "scope": "001P.01_LINEAGE_ONLY_NOT_COMPARISON_ACCEPTANCE",
        "private_parent": PRIVATE,
        "public_source": PUBLIC,
        "common_base": COMMON,
        "integrated_head": integrated,
        "public_sequence": git("rev-list", "--reverse", f"{COMMON}..{PUBLIC}").splitlines(),
        "integrated_sequence": git(
            "rev-list", "--reverse", f"{PRIVATE}..{integrated}"
        ).splitlines(),
        "public_preserved_file_count": len(preserved),
        "public_mismatches": mismatches,
        "private_preserved_paths": private_paths,
        "private_mismatches": private_diff.splitlines(),
        "conflict_resolution": "RETAIN_BOTH_PLANS_AND_PACKAGE_RESOURCES_REGENERATE_CURRENT_MANIFEST",
        "provider_calls": 0,
        "production_activation": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
