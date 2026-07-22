"""Export checked-in JSON Schemas from the first-party evidence models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from dmf_pulse.assurance.evidence import (  # noqa: E402
    CodexResult,
    ReviewManifest,
    TicketEvidenceManifest,
)

SCHEMAS = {
    "codex_result.schema.json": CodexResult,
    "evidence_manifest.schema.json": TicketEvidenceManifest,
    "review_manifest.schema.json": ReviewManifest,
}


def main() -> int:
    output = ROOT / ".codex/schemas"
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        (output / filename).write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(f"generated {len(SCHEMAS)} evidence schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
