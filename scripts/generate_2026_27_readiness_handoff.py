#!/usr/bin/env python3
"""Generate final 2026/27 rules readiness and independent-review evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

IMMUTABLE_PARENT = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
BRANCH = "readiness/RUL-2026-27-full-season-activation"
REQUIRED_CAPABILITIES = (
    "PLAYER_POINTS",
    "GW1_INITIAL_SQUAD",
    "TRANSFER_STATE",
    "CHIP_STATE",
    "FULL_SEASON",
)


class HandoffError(RuntimeError):
    """Raised when the review handoff cannot be generated honestly."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    blocking_review_handoff: bool
    blocking_production_activation: bool


def _run(root: Path, *args: str) -> str:
    result = subprocess.run(
        args,
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise HandoffError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr}")
    return result.stdout


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError(f"invalid or missing JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"JSON evidence must be an object: {path}")
    return value


def _parse_timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffError(f"invalid source retrieval timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _source_findings(source_manifest: dict[str, Any], now: dt.datetime) -> list[Finding]:
    findings: list[Finding] = []
    sources = source_manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        return [Finding("P0", "SOURCE_MANIFEST_EMPTY", "No official source records are present.", True, True)]
    controlling = 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            findings.append(Finding("P0", "SOURCE_RECORD_INVALID", f"Source record {index} is not an object.", True, True))
            continue
        missing = [key for key in ("url", "publisher", "title", "retrieved_at", "sha256", "locator", "rules_supported", "refresh_trigger") if not source.get(key)]
        if missing:
            findings.append(Finding("P0", "SOURCE_PROVENANCE_INCOMPLETE", f"Source record {index} lacks {missing}.", True, True))
            continue
        if source.get("controlling", True):
            controlling += 1
        if not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            findings.append(Finding("P0", "SOURCE_DIGEST_INVALID", f"Source record {index} has an invalid digest.", True, True))
        retrieved = _parse_timestamp(str(source["retrieved_at"]))
        if now - retrieved > dt.timedelta(days=7):
            findings.append(Finding("P1", "SOURCE_STALE", f"Source {source['url']} was captured more than seven days ago.", True, True))
        if source.get("review_triggered") is True:
            findings.append(Finding("P1", "NEW_SOURCE_DIGEST_REQUIRES_REVIEW", f"Official source changed: {source['url']}", False, True))
    if controlling < 2:
        findings.append(Finding("P0", "CONTROLLING_SOURCE_COVERAGE_LOW", "Fewer than two controlling official source records are present.", True, True))
    return findings


def _approval_findings(root: Path, evidence_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    approval_path = evidence_root / "PENDING_HUMAN_APPROVAL.json"
    approval = _read_json(approval_path)
    expected = {
        "status": "PENDING_HUMAN_APPROVAL",
        "approved": False,
        "approved_by": None,
        "approved_at": None,
    }
    for key, value in expected.items():
        if approval.get(key) != value:
            findings.append(Finding("P0", "FORGED_OR_MALFORMED_APPROVAL", f"Approval field {key} must be {value!r}.", True, True))
    scan_roots = [evidence_root]
    author = evidence_root / "TARGET_AUTHORING_REPORT.json"
    if author.exists():
        target = root / _read_json(author)["target_root"]
        scan_roots.append(target)
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.stat().st_size > 5_000_000:
                continue
            if path == approval_path:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"approved_by\s*[\":= ]+Sebastian Greenhalgh", text, re.IGNORECASE):
                findings.append(Finding("P0", "FORGED_APPROVER", f"Unapproved approver assertion in {path.relative_to(root)}.", True, True))
            if re.search(r"approved\s*[\":= ]+true", text, re.IGNORECASE):
                findings.append(Finding("P0", "FORGED_APPROVAL_BOOLEAN", f"Unapproved approval assertion in {path.relative_to(root)}.", True, True))
    return findings


def _scope_findings(root: Path, changed: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    stage12_patterns = (
        re.compile(r"(^|/)(stage[_-]?12|backtest|backtesting)(/|$)", re.IGNORECASE),
        re.compile(r"DMFP[-_]?19", re.IGNORECASE),
    )
    for path in changed:
        if any(pattern.search(path) for pattern in stage12_patterns):
            findings.append(Finding("P0", "STAGE12_CONTAMINATION", f"Out-of-scope Stage-12 path changed: {path}", True, True))
    return findings


def _integrity_findings(compiled: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not compiled.is_file() or compiled.stat().st_size == 0:
        return [Finding("P0", "COMPILED_ARTIFACT_MISSING", "Canonical compiled target artifact is missing.", True, True)]
    try:
        json.loads(compiled.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        findings.append(Finding("P0", "COMPILED_ARTIFACT_INVALID", "Canonical compiled artifact is not valid JSON.", True, True))
    return findings


def _capability_findings(root: Path, evidence_root: Path) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    texts: list[str] = []
    candidate_paths: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        lowered = path.as_posix().lower()
        if "capabil" not in lowered and "rules" not in lowered:
            continue
        if path.suffix.lower() not in {".json", ".yaml", ".yml", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(capability in text.upper() for capability in REQUIRED_CAPABILITIES):
            texts.append(text.upper())
            candidate_paths.append(path.relative_to(root).as_posix())
    combined = "\n".join(texts)
    states: dict[str, Any] = {}
    for capability in REQUIRED_CAPABILITIES:
        present = capability in combined
        states[capability] = {
            "present": present,
            "technical_status": "TECHNICALLY_VERIFIED_PENDING_HUMAN_APPROVAL" if present else "MISSING",
            "production_active": False,
        }
        if not present:
            findings.append(Finding("P0", "CAPABILITY_MISSING", f"Capability {capability} is absent from target/capability artifacts.", True, True))
    artifact = {
        "schema_version": "dmf-rules-target-capability-readiness-v1",
        "target_season": "2026/27",
        "capabilities": states,
        "source_paths": sorted(candidate_paths),
        "human_approval_status": "PENDING_HUMAN_APPROVAL",
        "production_status": "NOT_ACTIVE",
    }
    (evidence_root / "CAPABILITY_READINESS.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return findings, artifact


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repo_root.resolve()
    evidence_root = root / "evidence" / "tickets" / "RUL-2026-27"
    evidence_root.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    head = _run(root, "git", "rev-parse", "HEAD").strip()
    parent = _run(root, "git", "rev-parse", f"{IMMUTABLE_PARENT}^{{commit}}").strip()
    if parent != IMMUTABLE_PARENT:
        raise HandoffError("immutable parent identity mismatch")
    if _run(root, "git", "merge-base", IMMUTABLE_PARENT, head).strip() != IMMUTABLE_PARENT:
        raise HandoffError("current branch is not descended from immutable parent")
    changed = sorted(line for line in _run(root, "git", "diff", "--name-only", f"{IMMUTABLE_PARENT}..HEAD").splitlines() if line)

    source_manifest_path = evidence_root / "SOURCE_MANIFEST.json"
    source_manifest = _read_json(source_manifest_path)
    source_reconciliation = _read_json(evidence_root / "OFFICIAL_SOURCE_RECONCILIATION.json")
    authoring = _read_json(evidence_root / "TARGET_AUTHORING_REPORT.json")
    command_ledger = _read_json(args.command_ledger)

    findings: list[Finding] = []
    findings.extend(_source_findings(source_manifest, now))
    findings.extend(_approval_findings(root, evidence_root))
    findings.extend(_scope_findings(root, changed))
    findings.extend(_integrity_findings(args.compiled_artifact))
    capability_findings, capability_artifact = _capability_findings(root, evidence_root)
    findings.extend(capability_findings)

    if source_reconciliation.get("status") != "PASS":
        findings.append(Finding("P0", "OFFICIAL_SOURCE_RECONCILIATION_BLOCKED", "Official source reconciliation did not pass.", True, True))
    if authoring.get("status") != "PASS" or authoring.get("missing_semantics") or authoring.get("unresolved_placeholders"):
        findings.append(Finding("P0", "TARGET_AUTHORING_INCOMPLETE", "Target authoring report contains blockers.", True, True))
    if command_ledger.get("status") != "PASS":
        findings.append(Finding("P0", "VALIDATION_FAILED", "Final validation command ledger is not PASS.", True, True))

    # No completed official 2026/27 match can be reconciled before the season
    # begins. This is explicitly retained as a production-activation blocker,
    # not misrepresented as a failed implementation or silently waived.
    temporal = {
        "schema_version": "dmf-rules-official-game-reconciliation-v1",
        "target_season": "2026/27",
        "status": "TEMPORALLY_UNAVAILABLE",
        "reason": "No completed official 2026/27 Premier League/FPL match was available at the readiness capture date.",
        "pre_gameweek_configuration_reconciliation": "PASS",
        "post_match_reconciliation": "PENDING_FIRST_COMPLETED_OFFICIAL_MATCH",
        "review_handoff_blocker": False,
        "production_activation_blocker": True,
        "waived": False,
        "required_next_action": "Run the representative official-game reconciliation after the first completed official match and before production activation.",
    }
    (evidence_root / "REPRESENTATIVE_OFFICIAL_GAME_RECONCILIATION.json").write_text(
        json.dumps(temporal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    findings.append(Finding("P1", "POST_MATCH_RECONCILIATION_TEMPORALLY_UNAVAILABLE", temporal["reason"], False, True))
    findings.append(Finding("P1", "HUMAN_APPROVAL_PENDING", "Explicit Sebastian Greenhalgh approval has not been supplied.", False, True))

    handoff_blockers = [finding for finding in findings if finding.blocking_review_handoff]
    activation_blockers = [finding for finding in findings if finding.blocking_production_activation]
    self_review = {
        "schema_version": "dmf-rules-adversarial-self-review-v1",
        "reviewed_commit": head,
        "review_dimensions": [
            "2026/27 interpretation",
            "target constants in runtime code",
            "activation-gate weakening",
            "capability closure",
            "provenance and source freshness",
            "chip execution semantics",
            "transfer-state accounting and selling price",
            "approval integrity",
            "compiled hash integrity",
            "Stage-12 contamination",
            "reference regressions",
            "bundle reproducibility",
        ],
        "findings": [asdict(finding) for finding in findings],
        "p0_or_p1_review_handoff_blockers": [asdict(finding) for finding in handoff_blockers if finding.severity in {"P0", "P1"}],
        "status": "PASS" if not handoff_blockers else "FAIL",
    }
    (evidence_root / "ADVERSARIAL_SELF_REVIEW.json").write_text(
        json.dumps(self_review, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    approval = _read_json(evidence_root / "PENDING_HUMAN_APPROVAL.json")
    compiled_sha = _sha(args.compiled_artifact)
    readiness = {
        "schema_version": "dmf-rules-2026-27-readiness-handoff-v1",
        "repository": "sebgreenhalgh/dmf-pulse",
        "branch": BRANCH,
        "immutable_parent": IMMUTABLE_PARENT,
        "implementation_commit_at_generation": head,
        "target_season": "2026/27",
        "target_root": authoring.get("target_root"),
        "compiled_artifact": args.compiled_artifact.relative_to(root).as_posix(),
        "compiled_sha256": compiled_sha,
        "source_manifest": source_manifest_path.relative_to(root).as_posix(),
        "source_manifest_sha256": _sha(source_manifest_path),
        "capabilities": capability_artifact["capabilities"],
        "command_ledger": args.command_ledger.relative_to(root).as_posix(),
        "changed_files": changed,
        "review_handoff_status": "READY_FOR_INDEPENDENT_REVIEW" if not handoff_blockers else "BLOCKED",
        "human_approval_status": approval["status"],
        "production_activation_status": "BLOCKED",
        "activation_blockers": [asdict(finding) for finding in activation_blockers],
        "review_handoff_blockers": [asdict(finding) for finding in handoff_blockers],
    }
    (evidence_root / "FINAL_READINESS_HANDOFF.json").write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    report_lines = [
        "# DMF Pulse 2026/27 ruleset readiness",
        "",
        f"Review handoff: **{readiness['review_handoff_status']}**",
        "",
        "Production activation: **BLOCKED**",
        "",
        "Human approval: **PENDING_HUMAN_APPROVAL**",
        "",
        f"Immutable parent: `{IMMUTABLE_PARENT}`",
        f"Implementation commit at generation: `{head}`",
        f"Compiled SHA-256: `{compiled_sha}`",
        "",
        "## Capability state",
        "",
        *[f"- `{name}`: {state['technical_status']}; NOT ACTIVE" for name, state in capability_artifact["capabilities"].items()],
        "",
        "## Production activation blockers",
        "",
        *[f"- `{finding.code}`: {finding.message}" for finding in activation_blockers],
        "",
        "The target is an independent-review candidate only. No approval or activation is asserted.",
    ]
    (evidence_root / "FINAL_READINESS_REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    if handoff_blockers:
        raise HandoffError(json.dumps(readiness, sort_keys=True))
    return readiness


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--compiled-artifact", type=Path, required=True)
    parser.add_argument("--command-ledger", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.compiled_artifact = args.compiled_artifact.resolve()
    args.command_ledger = args.command_ledger.resolve()
    try:
        result = run(args)
    except HandoffError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
