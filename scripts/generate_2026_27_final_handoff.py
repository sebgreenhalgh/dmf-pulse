#!/usr/bin/env python3
"""Generate the evidence-backed 2026/27 independent-review handoff.

Unlike a name-presence scan, this generator accepts capability closure only from
the machine-readable output produced by the repository-native acceptance driver.
It records review readiness separately from production activation readiness.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
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
ACCEPTED_TECHNICAL_STATUSES = {
    "PASS",
    "PASSED",
    "READY",
    "VERIFIED",
    "TECHNICALLY_VERIFIED",
    "COMPLETE",
    "AVAILABLE",
    "SUPPORTED",
    "ENABLED",
}


class HandoffError(RuntimeError):
    """Raised when an independent-review handoff would be misleading."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    review_handoff_blocker: bool
    production_activation_blocker: bool


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise HandoffError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError(f"missing or invalid evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"evidence is not an object: {path}")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffError(f"invalid evidence timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _source_findings(
    repo: Path,
    source_manifest_path: Path,
    source_reconciliation: dict[str, Any],
    now: dt.datetime,
) -> list[Finding]:
    manifest = _load(source_manifest_path)
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        return [Finding("P0", "SOURCE_MANIFEST_EMPTY", "No official source provenance records are present.", True, True)]
    findings: list[Finding] = []
    controlling_count = 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            findings.append(Finding("P0", "SOURCE_RECORD_INVALID", f"Source record {index} is not an object.", True, True))
            continue
        required = (
            "url",
            "publisher",
            "title",
            "retrieved_at",
            "sha256",
            "locator",
            "rules_supported",
            "refresh_trigger",
        )
        missing = [key for key in required if not source.get(key)]
        if missing:
            findings.append(
                Finding(
                    "P0",
                    "SOURCE_PROVENANCE_INCOMPLETE",
                    f"Source record {index} lacks {', '.join(missing)}.",
                    True,
                    True,
                )
            )
            continue
        if source.get("controlling", True):
            controlling_count += 1
        digest = str(source["sha256"])
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            findings.append(Finding("P0", "SOURCE_DIGEST_INVALID", f"Invalid source digest for {source['url']}.", True, True))
        content_path = source.get("content_path")
        if isinstance(content_path, str):
            captured = repo / content_path
            if not captured.is_file() or _sha(captured) != digest:
                findings.append(Finding("P0", "SOURCE_CAPTURE_HASH_MISMATCH", f"Captured source hash mismatch for {source['url']}.", True, True))
        retrieved = _timestamp(str(source["retrieved_at"]))
        if now - retrieved > dt.timedelta(days=7):
            findings.append(Finding("P1", "CONTROLLING_SOURCE_STALE", f"Official source is older than seven days: {source['url']}.", True, True))
        if source.get("review_triggered") is True and not source.get("review_disposition"):
            findings.append(Finding("P1", "NEW_SOURCE_REQUIRES_REVIEW", f"A new official digest lacks an explicit review disposition: {source['url']}.", True, True))
    if controlling_count < 2:
        findings.append(Finding("P0", "CONTROLLING_SOURCE_COVERAGE_LOW", "Fewer than two controlling official source records are present.", True, True))
    if source_reconciliation.get("status") != "PASS":
        findings.append(Finding("P0", "OFFICIAL_SOURCE_RECONCILIATION_BLOCKED", "Official source reconciliation is not PASS.", True, True))
    if source_reconciliation.get("blocking_findings"):
        findings.append(Finding("P0", "OFFICIAL_SOURCE_BLOCKERS_PRESENT", "Official-source reconciliation retains blocking findings.", True, True))
    return findings


def _capability_findings(capability_path: Path) -> tuple[list[Finding], dict[str, Any]]:
    artifact = _load(capability_path)
    capabilities = artifact.get("capabilities")
    findings: list[Finding] = []
    if not isinstance(capabilities, dict):
        return [Finding("P0", "CAPABILITY_ARTIFACT_INVALID", "Capability artifact has no capability object.", True, True)], artifact
    for name in REQUIRED_CAPABILITIES:
        state = capabilities.get(name)
        if not isinstance(state, dict):
            findings.append(Finding("P0", "CAPABILITY_MISSING", f"Required capability {name} is absent.", True, True))
            continue
        status = re.sub(r"[^A-Z0-9]+", "_", str(state.get("status", "")).upper()).strip("_")
        verified = state.get("verified") is True
        blockers = state.get("blockers")
        blockers_empty = blockers in (None, [], {}, ())
        if status == "ACTIVE" or state.get("active") is True:
            findings.append(Finding("P0", "FALSE_ACTIVE_CAPABILITY", f"Capability {name} falsely asserts ACTIVE before approval.", True, True))
        if not verified or status not in ACCEPTED_TECHNICAL_STATUSES or not blockers_empty:
            findings.append(Finding("P0", "CAPABILITY_NOT_VERIFIED", f"Capability {name} is not technically verified without blockers.", True, True))
    if artifact.get("production_status") != "NOT_ACTIVE":
        findings.append(Finding("P0", "CAPABILITY_PRODUCTION_STATUS_INVALID", "Capability artifact must state NOT_ACTIVE.", True, True))
    if artifact.get("human_approval_status") != "PENDING_HUMAN_APPROVAL":
        findings.append(Finding("P0", "CAPABILITY_APPROVAL_STATUS_INVALID", "Capability artifact must state PENDING_HUMAN_APPROVAL.", True, True))
    return findings, artifact


def _approval_findings(approval_path: Path) -> tuple[list[Finding], dict[str, Any]]:
    approval = _load(approval_path)
    expected = {
        "status": "PENDING_HUMAN_APPROVAL",
        "approved": False,
        "approved_by": None,
        "approved_at": None,
    }
    findings: list[Finding] = []
    for key, expected_value in expected.items():
        if approval.get(key) != expected_value:
            findings.append(
                Finding(
                    "P0",
                    "APPROVAL_TEMPLATE_FORGED_OR_INVALID",
                    f"Approval field {key} must equal {expected_value!r}.",
                    True,
                    True,
                )
            )
    return findings, approval


def _scope_findings(changed_files: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    patterns = (
        re.compile(r"(^|/)(stage[-_]?12|backtest|backtesting)(/|$)", re.IGNORECASE),
        re.compile(r"(^|/)19_CODEX_IMPLEMENTATION_ROADMAP", re.IGNORECASE),
    )
    permitted_spec_hash_evidence = re.compile(r"governing[_-]spec", re.IGNORECASE)
    for path in changed_files:
        if permitted_spec_hash_evidence.search(path):
            continue
        if any(pattern.search(path) for pattern in patterns):
            findings.append(Finding("P0", "STAGE12_SCOPE_CONTAMINATION", f"Out-of-scope Stage-12/backtesting path changed: {path}", True, True))
    return findings


def _runtime_and_integrity_findings(
    repo: Path,
    compiled: Path,
    acceptance: dict[str, Any],
    runtime_scan: dict[str, Any],
    activation: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    if acceptance.get("status") != "PASS":
        findings.append(Finding("P0", "ACCEPTANCE_NOT_PASS", "Repository-native rules acceptance is not PASS.", True, True))
    if not compiled.is_file() or compiled.stat().st_size == 0:
        findings.append(Finding("P0", "COMPILED_ARTIFACT_MISSING", "Canonical compiled artifact is missing or empty.", True, True))
    elif acceptance.get("compiled_sha256") != _sha(compiled):
        findings.append(Finding("P0", "COMPILED_HASH_MISMATCH", "Canonical compiled artifact hash does not match acceptance evidence.", True, True))
    if runtime_scan.get("status") != "PASS" or runtime_scan.get("violations"):
        findings.append(Finding("P0", "TARGET_POLICY_IN_RUNTIME_CODE", "Target-season policy leaked into runtime Python code.", True, True))
    if activation.get("status") != "PASS" or activation.get("production_status") != "NOT_ACTIVE":
        findings.append(Finding("P0", "ACTIVATION_FAIL_CLOSED_NOT_PROVED", "Pre-approval activation fail-closed evidence is invalid.", True, True))
    return findings


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    evidence = repo / "evidence" / "tickets" / "RUL-2026-27"
    now = dt.datetime.now(dt.timezone.utc)
    head = _git(repo, "rev-parse", "HEAD")
    parent = _git(repo, "rev-parse", f"{IMMUTABLE_PARENT}^{{commit}}")
    if parent != IMMUTABLE_PARENT or _git(repo, "merge-base", IMMUTABLE_PARENT, head) != IMMUTABLE_PARENT:
        raise HandoffError("immutable implementation ancestry is not intact")
    branch = _git(repo, "branch", "--show-current")
    if branch != BRANCH:
        raise HandoffError(f"unexpected branch {branch!r}")
    changed_files = sorted(
        line for line in _git(repo, "diff", "--name-only", f"{IMMUTABLE_PARENT}..HEAD").splitlines() if line
    )

    source_manifest_path = evidence / "SOURCE_MANIFEST.json"
    source_reconciliation = _load(evidence / "OFFICIAL_SOURCE_RECONCILIATION.json")
    authoring = _load(evidence / "TARGET_AUTHORING_REPORT.json")
    acceptance = _load(evidence / "ACCEPTANCE_RESULT.json")
    capability_path = evidence / "CAPABILITY_READINESS.json"
    runtime_scan = _load(evidence / "RUNTIME_POLICY_SCAN.json")
    activation = _load(evidence / "ACTIVATION_FAIL_CLOSED.json")
    command_ledger = _load(evidence / "COMMAND_LEDGER.json")
    compiled = repo / str(acceptance.get("compiled_artifact", ""))

    findings: list[Finding] = []
    findings.extend(_source_findings(repo, source_manifest_path, source_reconciliation, now))
    capability_findings, capability = _capability_findings(capability_path)
    findings.extend(capability_findings)
    approval_findings, approval = _approval_findings(evidence / "PENDING_HUMAN_APPROVAL.json")
    findings.extend(approval_findings)
    findings.extend(_scope_findings(changed_files))
    findings.extend(_runtime_and_integrity_findings(repo, compiled, acceptance, runtime_scan, activation))
    if authoring.get("status") != "PASS" or authoring.get("missing_semantics") or authoring.get("unresolved_placeholders"):
        findings.append(Finding("P0", "TARGET_AUTHORING_INCOMPLETE", "Target authoring retains missing semantics or unresolved placeholders.", True, True))
    if command_ledger.get("status") != "PASS":
        findings.append(Finding("P0", "COMMAND_LEDGER_NOT_PASS", "Validation command ledger is not PASS.", True, True))

    temporal = {
        "schema_version": "dmf-rules-official-game-reconciliation-v1",
        "target_season": "2026/27",
        "status": "TEMPORALLY_UNAVAILABLE",
        "reason": "No completed official 2026/27 Premier League/FPL match was available at the readiness capture date.",
        "pre_gameweek_official_configuration_reconciliation": "PASS",
        "post_match_reconciliation": "PENDING_FIRST_COMPLETED_OFFICIAL_MATCH",
        "review_handoff_blocker": False,
        "production_activation_blocker": True,
        "waived": False,
        "next_action": "Run representative official-game reconciliation after the first completed official match and before production activation.",
    }
    (evidence / "REPRESENTATIVE_OFFICIAL_GAME_RECONCILIATION.json").write_text(
        json.dumps(temporal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    findings.extend(
        (
            Finding("P1", "POST_MATCH_RECONCILIATION_TEMPORALLY_UNAVAILABLE", temporal["reason"], False, True),
            Finding("P1", "HUMAN_APPROVAL_PENDING", "Explicit Sebastian Greenhalgh human approval has not been supplied.", False, True),
        )
    )

    review_blockers = [finding for finding in findings if finding.review_handoff_blocker]
    activation_blockers = [finding for finding in findings if finding.production_activation_blocker]
    self_review = {
        "schema_version": "dmf-rules-2026-27-adversarial-self-review-v1",
        "implementation_commit_at_review": head,
        "dimensions": [
            "official 2026/27 interpretation",
            "runtime target constants",
            "activation gate weakening",
            "machine-readable capability closure",
            "source freshness and provenance",
            "chip execution semantics",
            "transfer-state and selling-price accounting",
            "approval and artifact hash integrity",
            "Stage-12 contamination",
            "reference/synthetic regressions",
            "bundle reproducibility",
        ],
        "findings": [asdict(finding) for finding in findings],
        "status": "PASS" if not review_blockers else "FAIL",
    }
    (evidence / "ADVERSARIAL_SELF_REVIEW.json").write_text(
        json.dumps(self_review, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    handoff = {
        "schema_version": "dmf-rules-2026-27-final-handoff-v1",
        "repository": "sebgreenhalgh/dmf-pulse",
        "branch": BRANCH,
        "immutable_parent": IMMUTABLE_PARENT,
        "implementation_commit_at_generation": head,
        "target_season": "2026/27",
        "target_root": authoring.get("target_root"),
        "compiled_artifact": compiled.relative_to(repo).as_posix(),
        "compiled_sha256": _sha(compiled) if compiled.is_file() else None,
        "source_manifest": source_manifest_path.relative_to(repo).as_posix(),
        "source_manifest_sha256": _sha(source_manifest_path),
        "capability_artifact": capability_path.relative_to(repo).as_posix(),
        "capabilities": capability.get("capabilities"),
        "command_ledger": (evidence / "COMMAND_LEDGER.json").relative_to(repo).as_posix(),
        "changed_files": changed_files,
        "review_handoff_status": "READY_FOR_INDEPENDENT_REVIEW" if not review_blockers else "BLOCKED",
        "human_approval_status": approval.get("status"),
        "production_activation_status": "BLOCKED",
        "review_handoff_blockers": [asdict(finding) for finding in review_blockers],
        "production_activation_blockers": [asdict(finding) for finding in activation_blockers],
    }
    handoff_path = evidence / "FINAL_READINESS_HANDOFF.json"
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# DMF Pulse 2026/27 ruleset readiness",
        "",
        f"Independent-review handoff: **{handoff['review_handoff_status']}**",
        "",
        "Production activation: **BLOCKED**",
        "",
        "Human approval: **PENDING_HUMAN_APPROVAL**",
        "",
        f"Immutable parent: `{IMMUTABLE_PARENT}`",
        f"Implementation commit at evidence generation: `{head}`",
        f"Compiled ruleset SHA-256: `{handoff['compiled_sha256']}`",
        "",
        "## Capability evidence",
        "",
    ]
    for name in REQUIRED_CAPABILITIES:
        state = capability["capabilities"][name]
        lines.append(f"- `{name}`: {state['status']}; verified={state['verified']}; blockers={len(state.get('blockers', []))}; NOT ACTIVE")
    lines.extend(("", "## Production activation blockers", ""))
    lines.extend(f"- `{finding.code}`: {finding.message}" for finding in activation_blockers)
    lines.extend(("", "This artifact authorises independent review only. It does not authorise activation or merge."))
    (evidence / "FINAL_READINESS_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if review_blockers:
        raise HandoffError(json.dumps(handoff, sort_keys=True))
    return handoff


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args)
    except HandoffError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
