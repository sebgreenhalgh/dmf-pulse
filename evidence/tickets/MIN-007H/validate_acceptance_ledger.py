"""Independently validate exact plan, ledger, and durable artifact facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PLAN_KEYS = {"contract", "gates"}
GATE_KEYS = {"id", "command", "artifacts"}
LEDGER_KEYS = {"contract", "scope", "plan_sha256", "gate_count", "records", "status"}
RECORD_KEYS = {
    "number",
    "id",
    "command",
    "start",
    "end",
    "duration_seconds",
    "exit_code",
    "status",
    "stdout_sha256",
    "stderr_sha256",
    "output_summary",
    "artifacts",
}
ARTIFACT_KEYS = {"sha256", "size"}


class ValidationError(ValueError):
    """A fail-closed ledger validation error."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValidationError(f"{label} must be an object with string keys")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValidationError(f"{label} fields mismatch")


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValidationError(f"{label} is not lowercase hexadecimal SHA-256")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{label} is not a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if parsed.tzinfo != UTC:
        raise ValidationError(f"{label} is not UTC")
    return parsed


def _artifact_path(artifact_root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != relative:
        raise ValidationError(f"artifact path is not canonical repository-relative: {relative}")
    resolved_root = artifact_root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValidationError(f"artifact escapes root: {relative}")
    return resolved


def validate(*, ledger_path: Path, plan_path: Path, artifact_root: Path) -> int:
    try:
        plan = _object(json.loads(plan_path.read_text(encoding="utf-8")), "plan")
        ledger = _object(json.loads(ledger_path.read_text(encoding="utf-8")), "ledger")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError("plan or ledger is unreadable") from exc
    _exact_keys(plan, PLAN_KEYS, "plan")
    _exact_keys(ledger, LEDGER_KEYS, "ledger")
    if not isinstance(plan["contract"], str) or not plan["contract"]:
        raise ValidationError("plan contract is invalid")
    gates = plan["gates"]
    records = ledger["records"]
    if not isinstance(gates, list) or not gates or not isinstance(records, list):
        raise ValidationError("plan gates or ledger records are invalid")
    if (
        ledger["contract"] != plan["contract"]
        or not isinstance(ledger["scope"], str)
        or not ledger["scope"]
        or _sha(ledger["plan_sha256"], "plan_sha256")
        != hashlib.sha256(plan_path.read_bytes()).hexdigest()
        or type(ledger["gate_count"]) is not int
        or ledger["gate_count"] != len(gates)
        or len(records) != len(gates)
    ):
        raise ValidationError("ledger plan/count mismatch")

    seen: set[str] = set()
    for number, (raw_gate, raw_record) in enumerate(zip(gates, records, strict=True), 1):
        gate = _object(raw_gate, f"gate {number}")
        record = _object(raw_record, f"record {number}")
        _exact_keys(gate, GATE_KEYS, f"gate {number}")
        _exact_keys(record, RECORD_KEYS, f"record {number}")
        gate_id = gate["id"]
        command = gate["command"]
        declared = gate["artifacts"]
        if (
            not isinstance(gate_id, str)
            or not gate_id
            or gate_id in seen
            or not isinstance(command, str)
            or not command
            or not isinstance(declared, list)
            or not all(isinstance(item, str) and item for item in declared)
            or len(set(declared)) != len(declared)
        ):
            raise ValidationError(f"invalid gate declaration: {number}")
        seen.add(gate_id)
        if (
            type(record["number"]) is not int
            or record["number"] != number
            or record["id"] != gate_id
            or record["command"] != command
        ):
            raise ValidationError(f"ledger gate mismatch: {number}")
        exit_code = record["exit_code"]
        status = record["status"]
        if type(exit_code) is not int or status not in {"PASS", "FAIL"}:
            raise ValidationError(f"gate result types invalid: {gate_id}")
        if status != ("PASS" if exit_code == 0 else "FAIL"):
            raise ValidationError(f"gate result is inconsistent: {gate_id}")
        if exit_code != 0 or status != "PASS":
            raise ValidationError(f"gate failed: {gate_id}")
        start = _timestamp(record["start"], f"{gate_id}.start")
        end = _timestamp(record["end"], f"{gate_id}.end")
        duration = record["duration_seconds"]
        if (
            end < start
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration < 0
        ):
            raise ValidationError(f"invalid timing: {gate_id}")
        stdout_sha = _sha(record["stdout_sha256"], f"{gate_id}.stdout_sha256")
        stderr_sha = _sha(record["stderr_sha256"], f"{gate_id}.stderr_sha256")
        summary = record["output_summary"]
        if not isinstance(summary, str) or len(summary) > 1500:
            raise ValidationError(f"invalid output summary: {gate_id}")
        both_empty = stdout_sha == EMPTY_SHA256 and stderr_sha == EMPTY_SHA256
        if (not summary) != both_empty:
            raise ValidationError(f"output summary does not match empty streams: {gate_id}")

        artifacts = _object(record["artifacts"], f"{gate_id}.artifacts")
        if set(artifacts) != set(declared):
            raise ValidationError(f"declared artifact set mismatch: {gate_id}")
        for relative in declared:
            entry = _object(artifacts[relative], f"artifact {relative}")
            _exact_keys(entry, ARTIFACT_KEYS, f"artifact {relative}")
            expected_sha = _sha(entry["sha256"], f"artifact {relative}.sha256")
            expected_size = entry["size"]
            if type(expected_size) is not int or expected_size < 0:
                raise ValidationError(f"artifact size invalid: {relative}")
            path = _artifact_path(artifact_root, relative)
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha
                or path.stat().st_size != expected_size
            ):
                raise ValidationError(f"artifact hash/size mismatch: {relative}")
    if ledger["status"] != "PASS":
        raise ValidationError("ledger status is not PASS")
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=EVIDENCE / "acceptance_ledger.json")
    parser.add_argument("--plan", type=Path, default=EVIDENCE / "assurance_plan.json")
    parser.add_argument("--artifact-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        count = validate(
            ledger_path=args.ledger,
            plan_path=args.plan,
            artifact_root=args.artifact_root,
        )
    except ValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"PASS: {count} exact pre-commit gates with verified declared artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
