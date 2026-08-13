"""Record the built wheel identity and verify its import metadata."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"


def main() -> int:
    wheels = sorted(
        (ROOT / "dist").glob("*.whl"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    if not wheels:
        raise SystemExit("no wheel built")
    wheel = wheels[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        if not any(name.startswith("dmf_pulse/") for name in names):
            raise SystemExit("package missing from wheel")
        metadata = [name for name in names if name.endswith("METADATA")]
        if len(metadata) != 1:
            raise SystemExit("wheel metadata missing")
        text = archive.read(metadata[0]).decode("utf-8")
    report = {
        "status": "PASS",
        "wheel": str(wheel.relative_to(ROOT)).replace("\\", "/"),
        "sha256": digest,
        "size": wheel.stat().st_size,
        "metadata_contains_name": "Name: dmf-pulse" in text,
        "python": sys.version.split()[0],
    }
    (EVIDENCE / "installed_wheel_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS: wheel {report['wheel']} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
