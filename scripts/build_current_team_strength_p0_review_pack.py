"""Build a deterministic capped review ZIP for CURRENT-TEAM-STRENGTH-001A-P0."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "review_pack/CURRENT-TEAM-STRENGTH-001A-P0.zip"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
INCLUDED = (
    "tickets/CURRENT-TEAM-STRENGTH-001A-P0/ticket.yaml",
    "tickets/CURRENT-TEAM-STRENGTH-001A-P0/ACCEPTANCE.md",
    "config/rights/openfootball_profiles.json",
    "config/providers/openfootball_historical_team_identity.json",
    "config/models/current_team_strength_governance.json",
    "src/dmf_pulse/ingestion/openfootball/config.py",
    "src/dmf_pulse/ingestion/openfootball/team_strength_governance.py",
    "tests/unit/ingestion/openfootball/test_config.py",
    "tests/unit/ingestion/openfootball/test_team_strength_governance.py",
    "tests/unit/ingestion/openfootball/test_team_strength_governance_boundaries.py",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/HUMAN_APPROVAL.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/IDENTITY_REVIEW.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/TEMPORAL_POLICY.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/MATERIALITY_POLICY.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/RESEARCH_EVIDENCE.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/SCOPE_ASSURANCE.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/TEST_RESULTS.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/INDEPENDENT_REVIEW.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/FINAL_SELF_REVIEW.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/KNOWN_LIMITATIONS.md",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/COMMAND_LEDGER.txt",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/result.json",
    "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/repository_validation_report.json",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> dict[str, object]:
    payload: list[tuple[str, bytes]] = []
    total = 0
    for relative in INCLUDED:
        candidate = (ROOT / relative).resolve()
        if ROOT.resolve() not in candidate.parents or candidate.is_symlink():
            raise ValueError(f"unsafe review path: {relative}")
        data = candidate.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"review file exceeds cap: {relative}")
        total += len(data)
        if total > MAX_PAYLOAD_BYTES:
            raise ValueError("review payload exceeds cap")
        payload.append((relative, data))
    manifest = {
        "file_count": len(payload),
        "files": [
            {"bytes": len(data), "path": relative, "sha256": _sha256(data)}
            for relative, data in payload
        ],
        "max_payload_bytes": MAX_PAYLOAD_BYTES,
        "payload_bytes": total,
        "schema_version": "1.0",
        "ticket_id": "CURRENT-TEAM-STRENGTH-001A-P0",
    }
    manifest_data = (
        json.dumps(manifest, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zip_file:
        for name, data in (*payload, ("MANIFEST.json", manifest_data)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zip_file.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(OUTPUT)
    archive_sha256 = _sha256(OUTPUT.read_bytes())
    return {
        "archive_sha256": archive_sha256,
        "file_count": len(payload) + 1,
        "path": OUTPUT.relative_to(ROOT).as_posix(),
        "payload_bytes": total,
        "status": "PASS",
    }


def main() -> int:
    try:
        result = build()
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
