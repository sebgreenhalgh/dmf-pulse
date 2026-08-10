"""Generate the MIN-007F repository manifest used by repository validation."""

from __future__ import annotations

from pathlib import Path

from dmf_pulse.assurance.manifests import build_repository_manifest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/tickets/MIN-007F/current_manifest.json"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_repository_manifest(ROOT, ticket_id="MIN-007F")
    TARGET.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
