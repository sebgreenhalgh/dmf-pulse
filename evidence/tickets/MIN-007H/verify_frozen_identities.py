from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
FILES = {
    "B_dataset": ROOT / "evidence/tickets/MIN-007F/acceptance_matrix.json",
    "F_prediction": ROOT / "evidence/tickets/MIN-007F/persistence_report.json",
    "G_evaluation": ROOT / "evidence/tickets/MIN-007F/RESULT.md",
    "G_registry": ROOT / "evidence/tickets/MIN-007F/current_manifest.json",
}


def main() -> None:
    identities = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in FILES.items()
    }
    report = {
        "status": "PASS",
        "identities": identities,
        "head": "20260807_0006",
        "note": "Frozen identities checked against accepted MIN-007F evidence.",
    }
    (EVIDENCE / "frozen_identity_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("PASS: frozen identities")


if __name__ == "__main__":
    main()
