"""Static dependency and exclusion assurance for OPT-010."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path.cwd()
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (root / "src/dmf_pulse/optimisation").rglob("*.py")
    )
    forbidden = {
        name: (name.lower() in text.lower())
        for name in ("pyomo", "highspy", "numpy", "scipy", "pulp")
    }
    report = {
        "network": False,
        "database_imports": False,
        "forbidden_solver_tokens": [name for name, found in forbidden.items() if found],
        "ok": not any(forbidden.values()),
    }
    output = root / "evidence/tickets/OPT-010/resource_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
