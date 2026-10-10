"""Build and verify the capped protocol review bundle and evidence hashes."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001V-PROTOCOL"
EVIDENCE = ROOT / "evidence" / "tickets" / TICKET


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def main() -> None:
    for phase, expected_count in (
        ("QUALITY", 5),
        ("PACKAGE", 3),
        ("REPOSITORY", 5),
        ("SUPPLEMENTAL", 2),
    ):
        record = json.loads((EVIDENCE / f"COMMANDS-{phase}.json").read_bytes())
        if (
            len(record["commands"]) != expected_count
            or record["status"] != "PASS"
            or any(row["exit_code"] != 0 for row in record["commands"])
        ):
            raise ValueError("acceptance incomplete")
        for row in record["commands"]:
            if digest((EVIDENCE / row["log"]).read_bytes()) != row["log_sha256"]:
                raise ValueError("command log hash differs")
    evidence_files = {
        path.name: {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
        for path in sorted(EVIDENCE.iterdir())
        if path.is_file() and path.name not in {"EVIDENCE-MANIFEST.json", "REVIEW-PACK.json"}
    }
    (EVIDENCE / "EVIDENCE-MANIFEST.json").write_text(
        json.dumps({"files": evidence_files, "status": "PASS"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    paths = [
        f"tickets/{TICKET}/ticket.yaml",
        f"tickets/{TICKET}/PROTOCOL.md",
        f"tickets/{TICKET}/P02-FREEZE-TICKET.md",
        "config/evaluation/team_strength_prospective_protocol_v1.json",
        "config/evaluation/team_strength_p01_reference.json",
        "config/evaluation/team_strength_epoch001_dependencies.json",
        "src/dmf_pulse/evaluation/team_strength_protocol.py",
        "src/dmf_pulse/evaluation/team_strength_protocol_store.py",
        "src/dmf_pulse/evaluation/team_strength_campaign.py",
        "src/dmf_pulse/evaluation/team_strength_campaign_report.py",
        "src/dmf_pulse/cli/team_strength_protocol.py",
        "tests/unit/evaluation/test_team_strength_protocol.py",
        "tests/unit/evaluation/test_team_strength_campaign.py",
        "tests/unit/evaluation/test_team_strength_campaign_end_to_end.py",
        f"evidence/tickets/{TICKET}/INDEPENDENT-REVIEW.json",
        f"evidence/tickets/{TICKET}/P01-PRESERVATION.json",
        f"evidence/tickets/{TICKET}/COMMANDS-QUALITY.json",
        f"evidence/tickets/{TICKET}/COMMANDS-PACKAGE.json",
        f"evidence/tickets/{TICKET}/EVIDENCE-MANIFEST.json",
    ]
    payload = {name: (ROOT / name).read_bytes() for name in paths}
    manifest = {
        name: {"sha256": digest(body), "bytes": len(body)} for name, body in payload.items()
    }
    payload["MANIFEST.json"] = (
        json.dumps({"files": manifest, "excludes_self": True}, indent=2, sort_keys=True) + "\n"
    ).encode()
    if (
        len(payload) > 20
        or max(map(len, payload.values())) > 1_000_000
        or sum(map(len, payload.values())) > 5_000_000
    ):
        raise ValueError("review caps exceeded")
    destination = ROOT / "review_pack" / TICKET / "protocol-review.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(payload.items()):
            archive.writestr(name, body)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(payload):
            raise ValueError("review archive integrity differs")
        for name, row in manifest.items():
            if digest(archive.read(name)) != row["sha256"]:
                raise ValueError("review payload hash differs")
    result = {
        "status": "PASS",
        "file_count": len(payload),
        "uncompressed_bytes": sum(map(len, payload.values())),
        "archive_sha256": digest(destination.read_bytes()),
        "path": str(destination),
        "max_files": 20,
        "max_file_bytes": 1_000_000,
        "max_uncompressed_bytes": 5_000_000,
    }
    (EVIDENCE / "REVIEW-PACK.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
