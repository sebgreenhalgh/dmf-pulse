"""Build the exact 17-root archive from an explicit output path and Git range."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
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


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--final-commit", default="HEAD")
    args = parser.parse_args()
    target = args.final_commit
    revision = f"{BASE}..{target}"
    changed = subprocess.check_output(["git", "diff", "--name-only", revision], cwd=ROOT)
    diffstat = subprocess.check_output(["git", "diff", "--stat", revision], cwd=ROOT)
    patch = subprocess.check_output(["git", "diff", "--binary", revision], cwd=ROOT)
    final_sha = (
        subprocess.check_output(["git", "rev-parse", f"{target}^{{commit}}"], cwd=ROOT)
        .decode()
        .strip()
    )
    files = {
        "01_REVIEW_PROMPT.txt": (
            b"Perform a fresh independent Stage-7 acceptance review. Read all 17 root files and "
            b"independently verify the patch and evidence. First attack: (A) fail-closed ledger and "
            b"final-evidence mutation resistance, including declared artifact hashes; (B) exact "
            b"isolated installed-wheel public external-ID-701 CLI operation using packaged REPLAY "
            b"resources, with no checkout import/path; and (C) network measurement at that exact "
            b"installed public external-ID-701 boundary. Recheck the three findings already closed: "
            b"mathematical-core exclusions/reachability waivers, frozen semantic identity "
            b"recomputation, and exact full-stage changed-files/diffstat/patch plus ranged diff-check. "
            b"Return ACCEPT_STAGE_7 only if P0=0, P1=0, and there is no blocking P2.\n"
        ),
        "02_README.md": b"MIN-007 R7 + H3 final independent-review handoff.\n",
        "03_RESULT.md": (EVIDENCE / "RESULT.md").read_bytes(),
        "04_ACCEPTANCE_LEDGER.json": (EVIDENCE / "acceptance_ledger.json").read_bytes(),
        "05_FULL_TEST_SUMMARY.json": (EVIDENCE / "full_test_summary.json").read_bytes(),
        "06_COVERAGE_SUMMARY.json": (EVIDENCE / "coverage_summary.json").read_bytes(),
        "07_MATH_CORE_MANIFEST.json": (EVIDENCE / "math_core_manifest.json").read_bytes(),
        "08_MIGRATION_REPORT.json": (EVIDENCE / "migration_report.json").read_bytes(),
        "09_INSTALLED_WHEEL_REPORT.json": (EVIDENCE / "installed_wheel_report.json").read_bytes(),
        "10_FROZEN_IDENTITIES.json": (EVIDENCE / "frozen_identity_report.json").read_bytes(),
        "11_SECURITY_REPORT.json": (EVIDENCE / "security_report.json").read_bytes(),
        "12_AUDIT_CLOSURE_HISTORY.md": (EVIDENCE / "audit_closure_history.md").read_bytes(),
        "13_GIT_LOG.txt": subprocess.check_output(["git", "log", "-12", "--oneline"], cwd=ROOT),
        "14_CHANGED_FILES.txt": changed,
        "15_STAGE7_DIFFSTAT.txt": diffstat,
        "16_STAGE7.patch": patch,
    }
    manifest = {
        "root_file_count": 17,
        "stage_base": BASE,
        "final_commit": final_sha,
        "roots": NAMES,
        "changed_file_count": len([line for line in changed.decode().splitlines() if line]),
        "patch_sha256": digest(patch),
        "wheel_sha256": json.loads(
            (EVIDENCE / "installed_wheel_report.json").read_text(encoding="utf-8")
        )["sha256"],
        "frozen_identities": json.loads(
            (EVIDENCE / "frozen_identity_report.json").read_text(encoding="utf-8")
        )["identities"],
        "files": {
            name: {"sha256": digest(data), "size": len(data)} for name, data in files.items()
        },
    }
    files["17_REVIEW_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in NAMES:
            archive.writestr(name, files[name])
    print(f"PASS: {args.output} roots=17 sha256={digest(args.output.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
