from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "evidence/tickets/MIN-007H/acceptance_ledger.json"


def main():
    data = json.loads(LEDGER.read_text())
    records = data.get("records", [])
    if len(records) != 31 or any(r.get("number") != i for i, r in enumerate(records, 1)):
        raise SystemExit("ledger numbering")
    if any(r.get("status") != "PASS" for r in records[:22]):
        raise SystemExit("completed ledger gate is not PASS")
    print("Acceptance ledger through command 22: PASS")


if __name__ == "__main__":
    main()
