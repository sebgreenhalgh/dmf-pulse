"""Git pre-push compare-and-delete guard; this script never mutates any ref."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

PROTECTED = {
    "refs/heads/main",
    "refs/heads/launch/GW10-real-pilot",
    "refs/heads/research/DMF-MODEL-QUALITY-001",
}
ZERO = "0" * 40


def verify_deletions(
    manifest: Mapping[str, object], remote_name: str, remote_url: str, payload: str
) -> None:
    if (
        set(manifest) != {"schema_version", "remote_name", "remote_url", "refs"}
        or manifest["schema_version"] != "branch-delete-guard-v1"
    ):
        raise ValueError("invalid reviewed deletion manifest")
    if (remote_name, remote_url) != (manifest["remote_name"], manifest["remote_url"]):
        raise ValueError("remote identity differs from reviewed deletion manifest")
    refs = manifest["refs"]
    if (
        not isinstance(refs, dict)
        or not refs
        or any(
            not isinstance(name, str)
            or not name.startswith("refs/heads/")
            or name in PROTECTED
            or not isinstance(sha, str)
            or re.fullmatch(r"[0-9a-f]{40}", sha) is None
            or sha == ZERO
            for name, sha in refs.items()
        )
    ):
        raise ValueError(
            "reviewed deletions must be non-protected branches with exact existing tips"
        )
    seen = set()
    for line in payload.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("malformed Git pre-push update")
        local_ref, local_sha, remote_ref, remote_sha = fields
        if (
            local_ref != "(delete)"
            or local_sha != ZERO
            or remote_ref in seen
            or refs.get(remote_ref) != remote_sha
        ):
            raise ValueError(
                "ref update is not the exact reviewed deletion or advertised tip changed"
            )
        seen.add(remote_ref)
    if seen != set(refs):
        raise ValueError("missing or extra reviewed deletion")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("remote_name")
    parser.add_argument("remote_url")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("deletion manifest must be an object")
    verify_deletions(manifest, args.remote_name, args.remote_url, sys.stdin.read())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError):
        print(
            "Reviewed branch deletion refused; no ref update authorized by this hook.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
