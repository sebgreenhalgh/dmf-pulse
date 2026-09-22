"""Capped, hash-verified 001P source/synthetic-evidence archive; no live data."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001P"


def build() -> dict[str, object]:
    names = {
        "PLANS.md",
        "pyproject.toml",
        "src/dmf_pulse/private_v1/service.py",
        "src/dmf_pulse/private_v1/rolling.py",
        "scripts/ci_coverage_shards.py",
    }
    for pattern in (
        "src/dmf_pulse/private_v1/team_strength_*.py",
        "tests/unit/private_v1/*team_strength*.py",
        "scripts/*team_strength*shadow*.py",
        f"tickets/{TICKET}/*",
        f"evidence/tickets/{TICKET}/*",
    ):
        names.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern))
    if len(names) > 60:
        raise ValueError("review archive exceeds 60-entry source cap")
    payload = {}
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("unsafe review archive path")
        body = path.read_bytes()
        if len(body) > 2 * 1024 * 1024:
            raise ValueError("review entry exceeds 2MiB cap")
        payload[name] = body
    size = sum(map(len, payload.values()))
    if size > 8 * 1024 * 1024:
        raise ValueError("review payload exceeds 8MiB cap")
    manifest = {
        "ticket": TICKET,
        "synthetic_evidence_only": True,
        "files": [
            {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in payload.items()
        ],
    }
    output = ROOT / "review_pack" / f"{TICKET}.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in (
            *payload.items(),
            ("MANIFEST.json", json.dumps(manifest, sort_keys=True).encode()),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {*payload, "MANIFEST.json"}
        for row in manifest["files"]:
            body = archive.read(row["path"])
            if len(body) != row["bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
                raise ValueError("review archive authentication failed")
    return {
        "status": "PASS",
        "file_count": len(payload),
        "payload_bytes": size,
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "path": output.relative_to(ROOT).as_posix(),
        "entry_hashes_verified": True,
    }


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
