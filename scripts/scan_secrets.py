"""Run the first-party deterministic repository secret scanner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dmf_pulse.assurance.secret_scan import (  # noqa: E402
    SecretScanConfigurationError,
    scan_repository,
)


def main() -> int:
    try:
        findings = scan_repository(REPOSITORY_ROOT)
    except SecretScanConfigurationError as exc:
        result = {"error": str(exc), "finding_count": 0, "findings": [], "status": "FAIL"}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    result = {
        "finding_count": len(findings),
        "findings": [finding.as_dict() for finding in findings],
        "status": "PASS" if not findings else "FAIL",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
