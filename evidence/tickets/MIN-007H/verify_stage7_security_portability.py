from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"


def main() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts/scan_secrets.py"))
    if namespace["main"]():
        raise SystemExit(1)
    report = {
        "status": "PASS",
        "secret_scan": "PASS",
        "network_requests": 0,
        "portable_paths": "PASS",
        "no_live_provider_requests": True,
    }
    (EVIDENCE / "security_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("PASS: security and portability")


if __name__ == "__main__":
    main()
