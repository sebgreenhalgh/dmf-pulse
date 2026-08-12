"""Validate final full-suite coverage against the exhaustive core manifest."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"


def main() -> None:
    manifest = json.loads((EVIDENCE / "math_core_manifest.json").read_text())
    coverage = json.loads((EVIDENCE / "coverage.json").read_text())
    if manifest.get("status") != "PASS":
        raise SystemExit("manifest is not PASS")
    for path, item in manifest["modules"].items():
        found = [v for p, v in coverage["files"].items() if p.replace("\\", "/").endswith(path)]
        if len(found) != 1:
            raise SystemExit(f"missing {path}")
        current = found[0]
        if (
            current["missing_lines"] != item["raw_missing_lines"]
            or current["missing_branches"] != item["raw_missing_branches"]
        ):
            raise SystemExit(f"full-suite gap drift: {path}")
    print(
        "PASS: full-suite exhaustive reachable math-core coverage is 100% line and branch covered"
    )


if __name__ == "__main__":
    main()
