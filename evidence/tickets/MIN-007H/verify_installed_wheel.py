"""Verify the exact Stage-7 wheel through an isolated public CLI runtime."""

from __future__ import annotations

import json

from installed_wheel_runtime import ROOT, WheelRuntimeError, run_installed_wheel

EVIDENCE = ROOT / "evidence/tickets/MIN-007H"


def main() -> int:
    try:
        report = run_installed_wheel(network_guard=False, additional_contexts=True)
    except WheelRuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    (EVIDENCE / "installed_wheel_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS: isolated installed wheel public 701 PROJECTED; sha256={report['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
