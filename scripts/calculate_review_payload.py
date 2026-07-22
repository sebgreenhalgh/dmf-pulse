"""Calculate the stable FND-001 primary review-payload digest without writing a ZIP."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dmf_pulse.assurance.review_pack import calculate_review_payload_digest  # noqa: E402


def main() -> int:
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    digest = calculate_review_payload_digest(REPOSITORY_ROOT, generated_at=generated_at)
    print(json.dumps({"payload_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
