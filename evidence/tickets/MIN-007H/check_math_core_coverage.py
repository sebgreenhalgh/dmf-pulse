"""Independently compare full-suite coverage to the durable core manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
EXCLUSION = re.compile(
    r"pragma\s*:\s*no\s*(?:cover|branch)|coverage\s*:\s*(?:ignore|exclude)|no[-_ ]cover", re.I
)


def main() -> int:
    manifest = json.loads((EVIDENCE / "math_core_manifest.json").read_text(encoding="utf-8"))
    coverage = json.loads((EVIDENCE / "coverage.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or len(manifest.get("modules", {})) != 6:
        raise SystemExit("incomplete manifest")
    for path, item in manifest["modules"].items():
        source = ROOT / path
        if EXCLUSION.search(source.read_text(encoding="utf-8")):
            raise SystemExit(f"source exclusion: {path}")
        found = [v for key, v in coverage["files"].items() if key.replace("\\", "/").endswith(path)]
        if len(found) != 1 or found[0].get("excluded_lines", []) != []:
            raise SystemExit(f"coverage exclusion: {path}")
        if (
            found[0]["missing_lines"] != item["raw_missing_lines"]
            or found[0]["missing_branches"] != item["raw_missing_branches"]
        ):
            raise SystemExit(f"coverage drift: {path}")
        if (
            item["reachable"]["covered_lines"] != item["reachable"]["num_statements"]
            or item["reachable"]["covered_branches"] != item["reachable"]["num_branches"]
        ):
            raise SystemExit(f"reachable gap: {path}")
    print("PASS: full-suite raw/reachable math-core consistency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
