"""Independently validate exact plan/ledger structure and subprocess facts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=EVIDENCE / "acceptance_ledger.json")
    parser.add_argument("--plan", type=Path, default=EVIDENCE / "assurance_plan.json")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    gates = plan["gates"]
    records = ledger.get("records", [])
    if (
        ledger.get("plan_sha256") != hashlib.sha256(args.plan.read_bytes()).hexdigest()
        or ledger.get("gate_count") != len(gates)
        or len(records) != len(gates)
    ):
        raise SystemExit("ledger plan/count mismatch")
    seen = set()
    for number, (gate, record) in enumerate(zip(gates, records, strict=True), 1):
        if (
            record.get("number") != number
            or record.get("id") != gate["id"]
            or record.get("command") != gate["command"]
            or gate["id"] in seen
        ):
            raise SystemExit(f"ledger gate mismatch: {number}")
        seen.add(gate["id"])
        if (
            not isinstance(record.get("exit_code"), int)
            or record["exit_code"] != 0
            or record.get("status") != "PASS"
        ):
            raise SystemExit(f"gate failed: {gate['id']}")
        start = datetime.fromisoformat(str(record["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(record["end"]).replace("Z", "+00:00"))
        if (
            end < start
            or float(record.get("duration_seconds", -1)) < 0
            or len(str(record.get("stdout_sha256"))) != 64
            or len(str(record.get("stderr_sha256"))) != 64
        ):
            raise SystemExit(f"invalid timing/hash: {gate['id']}")
        for name, entry in record.get("artifacts", {}).items():
            path = EVIDENCE / name
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
                or path.stat().st_size != entry["size"]
            ):
                raise SystemExit(f"artifact hash mismatch: {name}")
    if ledger.get("status") != "PASS":
        raise SystemExit("ledger status FAIL")
    print(f"PASS: {len(records)} exact pre-commit gates with zero exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
