"""Explicit capped D1 source/offline evidence archive; no runtime discovery."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001P-L1-D1"


def build():
    names = {
        "PLANS.md",
        "scripts/build_team_strength_d1_review_pack.py",
        "scripts/verify_team_strength_l1_wheel.py",
        "src/dmf_pulse/private_v1/service.py",
        "src/dmf_pulse/private_v1/team_strength_comparison.py",
        "src/dmf_pulse/private_v1/team_strength_comparison_models.py",
        "src/dmf_pulse/private_v1/team_strength_diagnostics.py",
        "src/dmf_pulse/private_v1/team_strength_live.py",
        "src/dmf_pulse/private_v1/team_strength_live_authority.py",
        "tests/unit/private_v1/team_strength_d1_parent_support.py",
        "tests/unit/private_v1/test_team_strength_d1_controls.py",
        "tests/unit/private_v1/test_team_strength_d1_diagnostics.py",
        "tests/unit/private_v1/test_team_strength_d1_markets.py",
        "tests/unit/private_v1/test_team_strength_shadow_cases.py",
        "tests/unit/private_v1/test_team_strength_shadow_comparison.py",
        "tests/unit/private_v1/test_team_strength_l1.py",
        "tests/unit/private_v1/test_team_strength_l1_e2e.py",
    }
    # Only this offline ticket's documentation and coverage summary may be added.
    for pattern in (
        f"tickets/{TICKET}/*.md",
        f"tickets/{TICKET}/ticket.yaml",
        f"evidence/tickets/{TICKET}/*.md",
        f"evidence/tickets/{TICKET}/coverage-summary.json",
    ):
        names.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern))
    if len(names) > 35:
        raise ValueError("D1 archive entry cap exceeded")
    contents = {}
    for name in sorted(names):
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("unsafe review path")
        body = path.read_bytes()
        if len(body) > 1024 * 1024:
            raise ValueError("D1 archive entry too large")
        contents[name] = body
    if sum(map(len, contents.values())) > 5 * 1024 * 1024:
        raise ValueError("D1 archive too large")
    manifest = {
        "ticket": TICKET,
        "private_live_material": False,
        "files": [
            {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in contents.items()
        ],
    }
    output = ROOT / "review_pack" / f"{TICKET}.zip"
    output.parent.mkdir(exist_ok=True)
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
        for name, body in contents.items():
            if archive.read(name) != body:
                raise ValueError("D1 archive verification failed")
    return {
        "status": "PASS",
        "files": len(contents),
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
