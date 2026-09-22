"""Explicit, capped Phase A source/evidence archive; no runtime collection."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001P-L2"
NAMES = (
    "config/rights/odds_profiles.json",
    "scripts/build_team_strength_l2_review_pack.py",
    "scripts/run_team_strength_l1.py",
    "scripts/verify_team_strength_l1_wheel.py",
    "src/dmf_pulse/private_v1/team_strength_live.py",
    "src/dmf_pulse/private_v1/team_strength_live_authority.py",
    "tests/unit/private_v1/test_team_strength_l2.py",
    "tests/unit/private_v1/test_team_strength_l1.py",
    "tests/unit/private_v1/test_team_strength_l1_cli.py",
    "tests/unit/private_v1/test_team_strength_l1_e2e.py",
    "tests/unit/private_v1/test_team_strength_d1_diagnostics.py",
    "tests/unit/ingestion/test_horizon_rights_approval.py",
    f"tickets/{TICKET}/HUMAN-APPROVAL.md",
    f"tickets/{TICKET}/ACCEPTANCE.md",
    f"tickets/{TICKET}/ticket.yaml",
    f"evidence/tickets/{TICKET}/PURPOSE-REVIEW.md",
    f"evidence/tickets/{TICKET}/PUBLIC-READINESS.md",
    f"evidence/tickets/{TICKET}/OFFLINE-ACCEPTANCE.md",
    f"evidence/tickets/{TICKET}/INDEPENDENT-REVIEW.md",
)


def build():
    if len(NAMES) != len(set(NAMES)) or len(NAMES) > 19:
        raise ValueError("L2 review entry cap exceeded")
    contents = {}
    for name in sorted(NAMES):
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("unsafe L2 review path")
        body = path.read_bytes()
        if len(body) > 1024 * 1024:
            raise ValueError("L2 review entry too large")
        contents[name] = body
    if sum(map(len, contents.values())) > 5 * 1024 * 1024:
        raise ValueError("L2 review payload too large")
    manifest = {
        "ticket": TICKET,
        "phase": "A_ONLY_NO_LIVE_EXECUTION",
        "private_live_material": False,
        "files": [
            {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in contents.items()
        ],
    }
    output = ROOT / "review_pack" / f"{TICKET}.zip"
    output.parent.mkdir(exist_ok=True)
    if output.is_symlink() or not output.resolve().is_relative_to(ROOT):
        raise ValueError("unsafe L2 review destination")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in (
            *contents.items(),
            ("MANIFEST.json", json.dumps(manifest, sort_keys=True).encode()),
        ):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, body, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(output) as archive:
        if len(archive.namelist()) != len(contents) + 1:
            raise ValueError("L2 review entry count differs")
        for name, body in contents.items():
            if archive.read(name) != body:
                raise ValueError("L2 review verification failed")
    return {
        "status": "PASS",
        "files": len(contents) + 1,
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
