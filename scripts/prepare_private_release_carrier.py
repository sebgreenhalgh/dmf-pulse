"""Explicit maintainer review packaging; no installation, activation or provider access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dmf_pulse.operation.enrollment import ReleasePermit
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.packages import read_metadata
from dmf_pulse.operation.wheel import prepare_release_carrier_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-wheel", type=Path, required=True)
    parser.add_argument(
        "--accepted-permit",
        type=Path,
        required=True,
        help="Authenticated record of a separate owner/reviewer release decision; not a draft approval.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New private review ZIP; installation remains a separate trusted transition.",
    )
    args = parser.parse_args()
    try:
        digest = prepare_release_carrier_review(
            args.base_wheel, read_metadata(args.accepted_permit, ReleasePermit), args.output
        )
    except OperationError as error:
        print(json.dumps({"status": "BLOCKED", "code": error.code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"review_zip_sha256": digest, "runtime_authority": "NOT_INSTALLED_REVIEW_ONLY"},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
