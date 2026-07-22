"""Generate the complete DMFP-20 decision index and active authority scope map."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DMFP20_RELATIVE = "specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt"
DMFP20 = ROOT / DMFP20_RELATIVE
REQUIREMENTS = ROOT / "specs/manifests/stage_authority_requirements.json"

HEADER = re.compile(r"^(ADR-[A-Z]+-\d{3})\s+[\u2013\u2014-]\s+(.+)$")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def extract_decisions(source: str, source_sha256: str) -> list[dict[str, object]]:
    """Extract every ADR block without filtering by lifecycle status."""

    lines = source.splitlines()
    headers = [(index, match) for index, line in enumerate(lines) if (match := HEADER.match(line))]
    decisions: list[dict[str, object]] = []
    for position, (start, match) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        block = lines[start:end]
        status_line = next((line for line in block if line.startswith("Status: ")), None)
        date_line = next((line for line in block if line.startswith("Decision date: ")), None)
        decision_marker = block.index("Decision:") if "Decision:" in block else -1
        if status_line is None or date_line is None or decision_marker < 0:
            raise ValueError(f"incomplete ADR block {match.group(1)}")
        decision_lines: list[str] = []
        for line in block[decision_marker + 1 :]:
            if line == "Reason:":
                break
            decision_lines.append(line)
        decision_text = "\n".join(decision_lines).strip()
        if not decision_text:
            raise ValueError(f"empty Decision text for {match.group(1)}")
        decisions.append(
            {
                "decision_date": date_line.removeprefix("Decision date: ").strip(),
                "decision_sha256": _sha256(decision_text.encode("utf-8")),
                "id": match.group(1),
                "source": {
                    "document_sha256": source_sha256,
                    "locator": f"{match.group(1)} lines {start + 1}-{end}",
                    "path": DMFP20_RELATIVE,
                },
                "status": status_line.removeprefix("Status: ").strip(),
                "summary": decision_text,
                "title": match.group(2).strip(),
            }
        )
    if not decisions or len({item["id"] for item in decisions}) != len(decisions):
        raise ValueError("DMFP-20 decision extraction is empty or contains duplicate IDs")
    return decisions


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    source_bytes = DMFP20.read_bytes()
    source = source_bytes.decode("utf-8")
    source_sha256 = _sha256(source_bytes)
    decisions = extract_decisions(source, source_sha256)
    previous = json.loads((ROOT / "specs/manifests/decision_manifest.json").read_text("utf-8"))
    decision_manifest = {
        "decisions": decisions,
        "generated_from": {
            "document_id": "DMFP-20",
            "path": DMFP20_RELATIVE,
            "sha256": source_sha256,
        },
        "manifest_version": "2.0",
        "pack_authorisations": previous.get("pack_authorisations", []),
    }
    requirements = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))
    scopes = [
        {"scope": name, **bundle}
        for name, bundle in sorted(requirements["required_scopes"].items())
    ]
    scopes.insert(
        0,
        {
            "scope": "FND-001",
            "documents": [
                "DMFP-00",
                "DMFP-04",
                "DMFP-17",
                "DMFP-19",
                "DMFP-20",
                "DMF-PULSE-CODEX-PLAYBOOK",
            ],
            "decisions": [
                "ADR-PROD-004",
                "ADR-GOV-001",
                "ADR-GOV-002",
                "ADR-GOV-004",
                "ADR-RES-001",
                "ADR-DATA-002",
                "ADR-SRC-001",
                "ADR-IMPL-001",
                "ADR-IMPL-002",
                "ADR-IMPL-003",
            ],
        },
    )
    authority_manifest = {
        "manifest_version": "2.0",
        "precedence": requirements["precedence"],
        "scopes": scopes,
        "sources": [
            {
                "document_id": "DMFP-20",
                "path": DMFP20_RELATIVE,
                "role": "complete decision register",
            },
            {
                "document_id": "DMFP-00",
                "path": "specs/approved/DMFP-00_MASTER_ARCHITECTURE_AND_PRODUCT_DEFINITION.txt",
                "role": "master architecture",
            },
            {
                "document_id": "DMF-PULSE-CODEX-PLAYBOOK",
                "path": "docs/implementation/DMF_PULSE_CODEX_IMPLEMENTATION_PLAYBOOK_v1.txt",
                "role": "implementation workflow",
            },
            {
                "path": "specs/manifests/stage_authority_requirements.json",
                "role": "required minimum scope bundles",
            },
            {"path": "tickets/RUL-002/ticket.yaml", "role": "subordinate execution contract"},
            {"path": "tickets/RUL-002/ACCEPTANCE.md", "role": "subordinate acceptance contract"},
        ],
        "ticket_policy": requirements["ticket_policy"],
    }
    _write(ROOT / "specs/manifests/decision_manifest.json", decision_manifest)
    _write(ROOT / "specs/manifests/authority_manifest.json", authority_manifest)
    print(f"generated {len(decisions)} decisions and {len(scopes)} authority scopes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
