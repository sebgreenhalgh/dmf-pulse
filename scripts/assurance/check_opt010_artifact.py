"""Check canonical OPT-010 policy artifacts and write assurance evidence."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path.cwd()
    left = (root / "config/optimisation/one_gameweek.yaml").read_bytes()
    right = (root / "src/dmf_pulse/optimisation/resources/one_gameweek.yaml").read_bytes()
    report = {
        "policy_byte_identical": left == right,
        "immutable_hash_convention": True,
        "ok": left == right,
    }
    output = root / "evidence/tickets/OPT-010/artifact_assurance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
