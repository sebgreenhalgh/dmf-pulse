from __future__ import annotations

import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    os.environ.setdefault("DMF_ENVIRONMENT", "TEST")
    os.environ.setdefault("PGPASSWORD", "changeme")
    os.environ.setdefault(
        "DMF_TEST_DATABASE_URL", "postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test"
    )
    namespace = runpy.run_path(str(ROOT / "scripts/verify_wheel.py"))
    report = namespace["verify_wheel"](
        report_path=ROOT / "evidence/tickets/MIN-007H/installed_wheel_report.json"
    )
    print("PASS: installed wheel verification", report["wheel"]["name"], report["wheel"]["sha256"])


if __name__ == "__main__":
    main()
