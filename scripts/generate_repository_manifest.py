"""Generate the deterministic FND-001 current repository manifest."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dmf_pulse.assurance.canonical import pretty_json  # noqa: E402
from dmf_pulse.assurance.manifests import (  # noqa: E402
    CURRENT_MANIFEST_PATH,
    build_repository_manifest,
)


def main() -> int:
    manifest = build_repository_manifest(REPOSITORY_ROOT)
    output = REPOSITORY_ROOT / CURRENT_MANIFEST_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(pretty_json(manifest), encoding="utf-8", newline="\n")
    print(f"wrote {len(manifest.files)} files to {CURRENT_MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
