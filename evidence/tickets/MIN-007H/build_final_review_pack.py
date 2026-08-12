from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(
    r"C:/Users/sebgr/Documents/dmf-pulse-context/CodexPacks/DMF_PULSE_CODEX_PACK_007/MIN_007_FINAL_REVIEW.zip"
)
E = ROOT / "evidence/tickets/MIN-007H"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    files = {
        "01_REVIEW_PROMPT.txt": b"Fresh independent Stage-7 review required. Challenge every exact waiver, inventory, guard, validator, raw/reachable metric, and reachable behavior. Accept only P0=0/P1=0/no blocking P2.",
        "02_README.md": b"MIN-007H independent review handoff.",
        "03_RESULT.md": (E / "RESULT.md").read_bytes(),
        "04_ACCEPTANCE_LEDGER.json": (E / "acceptance_ledger.json").read_bytes(),
        "05_FULL_TEST_SUMMARY.json": (E / "full_test_summary.json").read_bytes(),
        "06_COVERAGE_SUMMARY.json": (E / "coverage_summary.json").read_bytes(),
        "07_MATH_CORE_MANIFEST.json": (E / "math_core_manifest.json").read_bytes(),
        "08_MIGRATION_REPORT.json": (E / "migration_report.json").read_bytes(),
        "09_INSTALLED_WHEEL_REPORT.json": (E / "installed_wheel_report.json").read_bytes(),
        "10_FROZEN_IDENTITIES.json": (E / "frozen_identity_report.json").read_bytes(),
        "11_SECURITY_REPORT.json": (E / "security_report.json").read_bytes(),
        "12_AUDIT_CLOSURE_HISTORY.md": (E / "audit_closure_history.md").read_bytes(),
        "13_GIT_LOG.txt": subprocess.check_output(["git", "log", "-8", "--oneline"], cwd=ROOT),
        "14_CHANGED_FILES.txt": (E / "stage7_changed_files.txt").read_bytes(),
        "15_STAGE7_DIFFSTAT.txt": (E / "stage7_diffstat.txt").read_bytes(),
        "16_STAGE7.patch": subprocess.check_output(
            ["git", "diff", "--binary", "253baf3f19661a5704bb1fad2f7ac60e1db288eb..HEAD"], cwd=ROOT
        ),
    }
    manifest = {
        "root_file_count": 17,
        "stage_base": "253baf3f19661a5704bb1fad2f7ac60e1db288eb",
        "files": {k: sha_bytes(v) for k, v in files.items()},
    }
    files["17_REVIEW_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    print(f"PASS: review archive {OUT} roots={len(files)} sha256={sha(OUT)}")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    main()
