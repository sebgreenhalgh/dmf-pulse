"""Validate exact archive roots, hashes, and byte-equal Git range evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "253baf3f19661a5704bb1fad2f7ac60e1db288eb"
NAMES = (
    "01_REVIEW_PROMPT.txt",
    "02_README.md",
    "03_RESULT.md",
    "04_ACCEPTANCE_LEDGER.json",
    "05_FULL_TEST_SUMMARY.json",
    "06_COVERAGE_SUMMARY.json",
    "07_MATH_CORE_MANIFEST.json",
    "08_MIGRATION_REPORT.json",
    "09_INSTALLED_WHEEL_REPORT.json",
    "10_FROZEN_IDENTITIES.json",
    "11_SECURITY_REPORT.json",
    "12_AUDIT_CLOSURE_HISTORY.md",
    "13_GIT_LOG.txt",
    "14_CHANGED_FILES.txt",
    "15_STAGE7_DIFFSTAT.txt",
    "16_STAGE7.patch",
    "17_REVIEW_MANIFEST.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--final-commit", default="HEAD")
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as archive:
        if archive.testzip() is not None or tuple(archive.namelist()) != NAMES:
            raise SystemExit("archive roots/CRC mismatch")
        manifest = json.loads(archive.read("17_REVIEW_MANIFEST.json"))
        if manifest.get("root_file_count") != 17 or manifest.get("roots") != list(NAMES):
            raise SystemExit("manifest root mismatch")
        for name in NAMES[:-1]:
            data = archive.read(name)
            entry = manifest["files"][name]
            if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
                raise SystemExit(f"archive hash mismatch: {name}")
        revision = f"{BASE}..{args.final_commit}"
        changed = subprocess.check_output(["git", "diff", "--name-only", revision], cwd=ROOT)
        diffstat = subprocess.check_output(["git", "diff", "--stat", revision], cwd=ROOT)
        patch = subprocess.check_output(["git", "diff", "--binary", revision], cwd=ROOT)
        if (
            archive.read("14_CHANGED_FILES.txt") != changed
            or archive.read("15_STAGE7_DIFFSTAT.txt") != diffstat
            or archive.read("16_STAGE7.patch") != patch
        ):
            raise SystemExit("Git range bytes mismatch")
        subprocess.run(["git", "diff", "--check", revision], cwd=ROOT, check=True)
    print("PASS: exact 17-root archive and ranged Git evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
