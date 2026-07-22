"""Portable script wrapper around the first-party review-pack builder."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dmf_pulse.assurance.review_pack import ReviewPackError, build_review_pack  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", default="FND-001")
    parser.add_argument("--output", type=Path, default=Path("review_pack/FND-001"))
    parser.add_argument("--baseline")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        summary = build_review_pack(
            REPOSITORY_ROOT,
            ticket=arguments.ticket,
            output=arguments.output,
            generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            baseline=arguments.baseline,
        )
    except ReviewPackError as exc:
        print(json.dumps(exc.as_error_object(), indent=2, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "file_count": summary.file_count,
                "path": summary.path.as_posix(),
                "archive_sha256": summary.sha256,
                "payload_sha256": summary.payload_sha256,
                "status": "PASS",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
