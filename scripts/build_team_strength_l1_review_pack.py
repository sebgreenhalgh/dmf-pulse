"""Capped source/offline-evidence L1 archive; never collect runtime artifacts."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001P-L1"


def build():
    names = {
        "PLANS.md",
        "config/rights/odds_profiles.json",
        "src/dmf_pulse/ingestion/odds/client.py",
        "src/dmf_pulse/ingestion/openfootball/team_strength_current.py",
        "tests/unit/ingestion/openfootball/test_team_strength_current.py",
        "tests/unit/private_v1/l1_test_support.py",
        "scripts/ci_coverage_shards.py",
        "tests/unit/private_v1/test_a2_preparation.py",
        "tests/unit/ingestion/test_horizon_probe.py",
        "tests/unit/ingestion/test_horizon_rights_approval.py",
    }
    for pattern in (
        "src/dmf_pulse/private_v1/team_strength_live*.py",
        "tests/unit/private_v1/test_team_strength_l1*.py",
        "scripts/*team_strength_l1*.py",
        f"tickets/{TICKET}/*",
        f"evidence/tickets/{TICKET}/*.md",
        f"evidence/tickets/{TICKET}/coverage-summary.json",
    ):
        names.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern))
    if len(names) > 40:
        raise ValueError("L1 review archive exceeds entry cap")
    contents = {}
    for name in sorted(names):
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("unsafe review path")
        body = path.read_bytes()
        if len(body) > 1024 * 1024:
            raise ValueError("review entry exceeds size cap")
        contents[name] = body
    if sum(map(len, contents.values())) > 5 * 1024 * 1024:
        raise ValueError("review payload exceeds size cap")
    manifest = {
        "ticket": TICKET,
        "live_private_material": False,
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
                raise ValueError("review archive verification failed")
    return {
        "status": "PASS",
        "files": len(contents),
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
