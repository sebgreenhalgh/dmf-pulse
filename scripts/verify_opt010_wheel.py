"""Verify the built wheel contains the OPT-010 package and CLI module."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def main() -> int:
    wheels = sorted(Path("dist").glob("*.whl"))
    if not wheels:
        print("no wheel found")
        return 1
    with zipfile.ZipFile(wheels[-1]) as archive:
        names = set(archive.namelist())
    required = {
        "dmf_pulse/optimisation/models.py",
        "dmf_pulse/optimisation/service.py",
        "dmf_pulse/cli/optimise.py",
    }
    report = {
        "wheel": str(wheels[-1]),
        "missing": sorted(required - names),
        "ok": required <= names,
    }
    output = Path("evidence/tickets/OPT-010/wheel_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
