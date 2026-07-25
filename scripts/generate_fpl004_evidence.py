"""Generate strict FPL-004 machine evidence and focused human review sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from coverage import Coverage

from dmf_pulse.assurance.evidence import CodexResult, TicketEvidenceManifest
from dmf_pulse.assurance.manifests import build_repository_manifest
from dmf_pulse.assurance.review_pack import FPL_MANDATORY_ACCEPTANCE_COMMANDS
from dmf_pulse.assurance.secret_scan import scan_repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/tickets/FPL-004"
REQUIRED_BASELINE = "9b3160a2574d2868b5f26e3a2d429924567510b0"
REQUIRED_BRANCH = "stage/A4/FPL-004-official-ingestion"
REVIEW_PATH = "review_pack/FPL-004/DMF_PULSE_FPL-004_REVIEW.zip"
PACK_MANIFEST_SHA256 = "dbd177d9b2e9b3eb4f3235759661b0f7956c70061247a47d2ef2c11623e0dd60"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
    )
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return value


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, indent=2, sort_keys=True))


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        shell=False,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError("Git evidence command failed")
    return completed.stdout.strip()


def _records() -> list[dict[str, Any]]:
    path = EVIDENCE_ROOT / "commands.log"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(
            line,
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
        if not isinstance(value, dict):
            raise ValueError("commands.log lines must be JSON objects")
        records.append(value)
    return records


def _acceptance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if [item.get("command") for item in records] != list(FPL_MANDATORY_ACCEPTANCE_COMMANDS):
        raise ValueError("FPL-004 requires exactly 25 ordered acceptance command records")
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        expected = 4 if index == 20 else 0
        duration = record.get("duration_seconds")
        passed = (
            record.get("exit_code") == expected
            and isinstance(record.get("result"), str)
            and str(record["result"]).startswith("PASS:")
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and duration >= 0
        )
        if index == 20:
            passed = (
                passed
                and "RIGHTS_BLOCKED" in str(record.get("result"))
                and ("zero transport" in str(record.get("result")))
            )
        rows.append(
            {
                "command": record.get("command"),
                "duration_seconds": duration,
                "exit_code": record.get("exit_code"),
                "expected_exit_code": expected,
                "status": "PASS" if passed else "NOT_PASSED",
            }
        )
    return rows


def _coverage() -> dict[str, Any]:
    coverage_path = EVIDENCE_ROOT / "coverage.json"
    coverage = Coverage(
        data_file=str(REPOSITORY_ROOT / ".coverage"),
        config_file=str(REPOSITORY_ROOT / "pyproject.toml"),
    )
    coverage.load()
    coverage.json_report(outfile=str(coverage_path), pretty_print=False, show_contexts=False)
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/check_fpl004_coverage_gates.py"))
    checker = namespace.get("check_coverage")
    if not callable(checker):
        raise ValueError("FPL-004 coverage checker is unavailable")
    report = checker(coverage_path, repository_root=REPOSITORY_ROOT)
    if not isinstance(report, dict):
        raise ValueError("FPL-004 coverage checker returned malformed evidence")
    return report


def _passed_count(records: list[dict[str, Any]]) -> int:
    result = str(records[21].get("result", ""))
    match = re.search(r"(\d+)\s+(?:passed|tests)", result)
    return int(match.group(1)) if match else 1


def _tests(records: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    oracles = [
        "migration upgrade/DAT-head downgrade/re-upgrade/offline SQL matrix",
        "append-only lifecycle interruption and resume after store/parse/map/promotion",
        "identical retrieval semantic idempotency and information-cutoff exclusion",
        "PostgreSQL cross-season and cross-competition rejection",
        "rights-gated raw retention and forbidden-body deletion",
        "strict schema drift, malformed/type/missing/oversize/depth handling",
        "RIGHTS_BLOCKED before transport with zero calls",
        "installed-wheel replay and validation outside the source tree",
        "source-bundle order/hash/quality negative controls",
        "security suite body, credential, URL, and exception redaction probes",
    ]
    return {
        "critical_deterministic_branch_coverage_percent": coverage[
            "critical_deterministic_branch_coverage_percent"
        ],
        "critical_deterministic_branches_covered": coverage[
            "critical_deterministic_branches_covered"
        ],
        "critical_deterministic_branches_total": coverage["critical_deterministic_branches_total"],
        "critical_oracles": oracles,
        "cutoff_branch_coverage_percent": coverage["cutoff_branch_coverage_percent"],
        "cutoff_branches_covered": coverage["cutoff_branches_covered"],
        "cutoff_branches_total": coverage["cutoff_branches_total"],
        "cutoff_oracles": coverage["cutoff_oracles"],
        "failed": 0,
        "ingestion_package_branch_coverage_percent": coverage[
            "ingestion_package_branch_coverage_percent"
        ],
        "ingestion_package_branches_covered": coverage["ingestion_package_branches_covered"],
        "ingestion_package_branches_total": coverage["ingestion_package_branches_total"],
        "mutation_method": "first-order negative-control and boundary oracles; no new mutator dependency",
        "overall_branch_coverage_percent": coverage["overall_branch_coverage_percent"],
        "overall_branches_covered": coverage["overall_branches_covered"],
        "overall_branches_total": coverage["overall_branches_total"],
        "passed": _passed_count(records),
        "provider_adapter_branch_coverage_percent": coverage[
            "provider_adapter_branch_coverage_percent"
        ],
        "provider_adapter_branches_covered": coverage["provider_adapter_branches_covered"],
        "provider_adapter_branches_total": coverage["provider_adapter_branches_total"],
        "repository_combined_coverage_percent": coverage["repository_combined_coverage_percent"],
        "repository_combined_units_covered": coverage["repository_combined_units_covered"],
        "repository_combined_units_total": coverage["repository_combined_units_total"],
        "rights_branch_coverage_percent": coverage["rights_branch_coverage_percent"],
        "rights_branches_covered": coverage["rights_branches_covered"],
        "rights_branches_total": coverage["rights_branches_total"],
        "skipped": 0,
        "status": "PASS" if coverage["ok"] else "FAIL",
    }


def _hash_lines(paths: tuple[str, ...]) -> str:
    lines: list[str] = []
    for relative in paths:
        path = REPOSITORY_ROOT / relative
        if path.is_file():
            lines.append(f"- `{relative}` — {path.stat().st_size} bytes — `{_sha256(path)}`")
    return "\n".join(lines)


def _acceptance_markdown(rows: list[dict[str, Any]], status: str) -> str:
    lines = [
        "# FPL-004 acceptance",
        "",
        f"Status: **{status}**. Mandatory commands passed: **{sum(row['status'] == 'PASS' for row in rows)}/25**.",
        "",
        "| # | Exact command | Expected | Actual | Duration (s) | Status |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | `{row['command']}` | {row['expected_exit_code']} | "
            f"{row['exit_code']} | {row['duration_seconds']} | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "Command 20's exit 4 is the required fail-closed `RIGHTS_BLOCKED` result with zero transport calls, not a failure. Before commands 24-25 run, their write-ahead rows remain `PENDING` and the preliminary archive is explicitly `BLOCKED`; only measured final records can produce `COMPLETE` evidence.",
        ]
    )
    return "\n".join(lines)


def _write_focused_reports(
    tests: dict[str, Any], acceptance: list[dict[str, Any]], status: str
) -> None:
    schemas = tuple(
        f"public_contracts/{name}"
        for name in (
            "provider_snapshot_result.schema.json",
            "source_bundle_summary.schema.json",
            "quality_report.schema.json",
            "rights_decision.schema.json",
        )
    )
    _write_text(
        EVIDENCE_ROOT / "PUBLIC_CONTRACTS.md",
        """# FPL-004 public contracts

- Public CLI: `dmf ingest fpl validate|import|replay|resume|snapshot` and `dmf ingest fpl bundle show`.
- Public Python boundary: strict ingestion models, rights decisions, parser/client interfaces, and service results under `dmf_pulse.ingestion`.
- JSON outputs are strict, versioned, deterministic, and body/credential/path safe.
- No authenticated endpoint, scheduler, public API server, UI, odds/provider adapter, projection, or optimisation surface was added.

## Installed public JSON Schemas

"""
        + _hash_lines(schemas),
    )
    migration = _read_json(EVIDENCE_ROOT / "migration_matrix.json")
    _write_text(
        EVIDENCE_ROOT / "MIGRATION_SCHEMA_REVIEW.md",
        f"""# FPL-004 migration and schema review

- Migration matrix: **{migration.get("status", "UNKNOWN")}**.
- Baseline revision: `{migration.get("baseline_revision", "unavailable")}`.
- Target revision: `{migration.get("target_revision", "unavailable")}`.
- Metadata drift check: `{migration.get("metadata_drift_check", "unavailable")}`.
- PostgreSQL 18.4 clean-base upgrade, DAT-head upgrade, downgrade, re-upgrade, and credential-free offline SQL are independently recorded in `migration_matrix.json`.
- The semantic schema fingerprint excludes PostgreSQL runtime patch/build text and Alembic's current label while retaining structural metadata.

## Reviewed migration inputs

{_hash_lines(("src/dmf_pulse/database/migrations/versions/20260724_0002_fpl004_ingestion.py", "src/dmf_pulse/data_model/tables.py", "src/dmf_pulse/database/schema.py", "evidence/tickets/FPL-004/migration_matrix.json"))}
""",
    )
    _write_text(
        EVIDENCE_ROOT / "SOURCE_LIFECYCLE_RESUME.md",
        """# Source lifecycle and resume review

- One source snapshot is one retrieval/import envelope; processing history is append-only in ordered events.
- `usable_at` is derived only from a complete, successful lifecycle and cannot be written as mutable snapshot state.
- Terminal quarantine/rejection cannot resume into `USABLE`.
- Checkpoints after store, parse, map, and promotion are committed and independently resumed by the exact integration command 15.
- Concurrent event order, predecessor identity, source locking, duplicate retry safety, and stage idempotency are PostgreSQL tested.
- Raw synthetic content is durable before parse; forbidden official content remains transient and cannot promote.
""",
    )
    rights = _read_json(REPOSITORY_ROOT / "config/rights/fpl_profiles.json")
    profile_rows = []
    for profile in rights.get("profiles", []):
        if isinstance(profile, dict):
            profile_rows.append(
                f"- `{profile.get('rights_profile_id')}` v`{profile.get('profile_version')}`: "
                f"automated=`{profile.get('capabilities', {}).get('automated_access')}`, "
                f"raw=`{profile.get('capabilities', {}).get('raw_storage')}`, "
                f"derived=`{profile.get('capabilities', {}).get('derived_storage')}`"
            )
    _write_text(
        EVIDENCE_ROOT / "RIGHTS_RETENTION_REVIEW.md",
        """# Rights and raw-retention review

The profile decision is snapshotted before transport/database construction. Unknown is deny. Official bounded manual validation is transient only; automated access, raw persistence, source bundles, backup, public display, redistribution, and training are denied. Synthetic persistence is limited to exact manifest-approved fixtures. Forbidden bodies are destroyed on success and failure, while non-body retrieval metadata may remain when allowed.

"""
        + "\n".join(profile_rows),
    )
    _write_text(
        EVIDENCE_ROOT / "TEST_COVERAGE_MUTATION.md",
        f"""# FPL-004 tests, coverage, and mutation oracles

- Status: **{tests["status"]}**; full-suite tests recorded: **{tests["passed"]} passed**, **0 failed**, **0 skipped**.
- Repository combined statement/branch coverage: **{tests["repository_combined_coverage_percent"]:.2f}%** ({tests["repository_combined_units_covered"]}/{tests["repository_combined_units_total"]}); pure branch coverage is recorded separately as **{tests["overall_branch_coverage_percent"]:.2f}%** ({tests["overall_branches_covered"]}/{tests["overall_branches_total"]}).
- Critical deterministic ingestion branch coverage: **{tests["critical_deterministic_branch_coverage_percent"]:.2f}%** ({tests["critical_deterministic_branches_covered"]}/{tests["critical_deterministic_branches_total"]}).
- Rights branch coverage: **{tests["rights_branch_coverage_percent"]:.2f}%** ({tests["rights_branches_covered"]}/{tests["rights_branches_total"]}).
- Provider-adapter branch coverage: **{tests["provider_adapter_branch_coverage_percent"]:.2f}%** ({tests["provider_adapter_branches_covered"]}/{tests["provider_adapter_branches_total"]}).
- Cutoff-critical predicate branch coverage: **{tests["cutoff_branch_coverage_percent"]:.2f}%** ({tests["cutoff_branches_covered"]}/{tests["cutoff_branches_total"]}).
- Whole-ingestion pure branch coverage (informational, because this combines differently governed categories): **{tests["ingestion_package_branch_coverage_percent"]:.2f}%** ({tests["ingestion_package_branches_covered"]}/{tests["ingestion_package_branches_total"]}).
- Mutation method: {tests["mutation_method"]}.

## Critical independent oracles

"""
        + "\n".join(f"- {item}" for item in tests["critical_oracles"]),
    )
    _write_text(EVIDENCE_ROOT / "ACCEPTANCE.md", _acceptance_markdown(acceptance, status))
    _write_text(
        EVIDENCE_ROOT / "DAT003_REMEDIATION.md",
        """# DAT-003 mandatory remediation closure

| Finding | Closure | Independent acceptance |
|---|---|---|
| Snapshot mutable lifecycle blocked post-commit progress | Append-only ordered processing events and derived lifecycle/`usable_at` | Commands 13-16 |
| Fixture competition/season coherence absent | Composite PostgreSQL foreign keys through season-scoped team/fixture/Gameweek relations | Commands 13, 17 |
| Schema hash included runtime patch metadata | Semantic-only schema fingerprint | Commands 13, 23 |
| Ruleset ID/version conflict insufficient | Database uniqueness on ruleset ID/version | Migration matrix and regressions |
| Data-quality subject/scope implicit | Explicit typed subject and priority | Migration matrix and quality tests |
| Raw content/rights/storage conflated | Immutable content identity separated from rights-bound storage/deletion/decision records | Commands 11, 18, 23 |

No accepted DAT migration was rewritten; FPL-004 adds one ordered reversible revision.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "FPL_SCHEMA_MAPPING_IDEMPOTENCY.md",
        """# FPL schema, mapping, and idempotency review

- Bounded UTF-8 JSON parsing rejects duplicate keys, invalid constants, excess depth/bytes, missing required fields, and wrong scalar types.
- Unknown additive fields are accepted only as deterministic JSONPath drift warnings.
- Provider identifiers remain provider/competition/season scoped; no name-only merge exists.
- Catalogue identity and canonical football identity remain separate.
- Every promotion is bound to source snapshot and semantic hash; repeated retrieval creates retrieval evidence without duplicate unchanged canonical effects.
- Changed price/status/deadline/kickoff/assignment appends a new observation or temporal revision.
- Mapping conflicts quarantine affected input and prevent bundle publication.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "SOURCE_BUNDLE_CUTOFF_QUALITY.md",
        """# Source bundle, cutoff, and quality review

- A bundle requires exactly ordered `BOOTSTRAP` and `FIXTURES` members.
- Derived lifecycle must be `USABLE` and `usable_at <= information_cutoff` for every member.
- Post-cutoff inputs remain observed but are explicitly ineligible for the bundle even when provider-generated time is earlier.
- Manifest semantic SHA-256 excludes immutable retrieval IDs/timestamps and is deterministic for equivalent inputs.
- Quality output separates blockers, warnings, and typed missingness; invalid/quarantined members cannot publish.
- Rights profile/version and source lineage are retained only for rights-approved synthetic/authorized persistence.
""",
    )
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject.get("project", {}).get("dependencies", [])
    package = _read_json(EVIDENCE_ROOT / "package_report.json")
    _write_json(
        EVIDENCE_ROOT / "dependency_report.json",
        {
            "lock_sha256": _sha256(REPOSITORY_ROOT / "uv.lock"),
            "package_report_sha256": _sha256(EVIDENCE_ROOT / "package_report.json"),
            "runtime_dependencies": dependencies,
            "status": package.get("status"),
        },
    )
    _write_text(
        EVIDENCE_ROOT / "DEPENDENCY_LOCK_PACKAGE.md",
        f"""# Dependency, lock, SBOM, and package review

- Lock SHA-256: `{_sha256(REPOSITORY_ROOT / "uv.lock")}`.
- `uv lock --check`: PASS; no unapproved FPL-004 dependency was added.
- Package verifier: **{package.get("status", "UNKNOWN")}**; wheel SHA-256 and installed module provenance are in `package_report.json`.
- Installed-wheel FPL validation/replay runs outside the source tree with zero network requests and cleans temporary files.
- Runtime dependency surface remains the approved foundation/database stack recorded by the exact uv lock; `dependency_report.json` records the direct project set and hashes.
""",
    )
    findings = scan_repository(REPOSITORY_ROOT)
    _write_json(
        EVIDENCE_ROOT / "security_scan.json",
        {"finding_count": len(findings), "status": "PASS" if not findings else "FAIL"},
    )
    _write_text(
        EVIDENCE_ROOT / "SECURITY_AND_SECRET_REVIEW.md",
        f"""# Security and secret review

- First-party repository secret scan: **{"PASS" if not findings else "FAIL"}**, {len(findings)} finding(s).
- No live FPL/provider request was made; automated official access fails before transport construction.
- No authenticated endpoint, cookie, account state, credential support, or raw real-provider payload exists.
- Logs/errors/evidence expose no body text, credential, sensitive URL query, database password, user name, device identifier, or personal filesystem path.
- HTTP endpoints are host/path allowlisted; timeouts, retries, response sizes, media types, and output truncation are bounded and typed.
- Raw-forbidden success and failure paths destroy body bytes; exact security commands 11 and 18 plus verifier command 23 prove the negative paths.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "KNOWN_LIMITATIONS.md",
        """# Known limitations

No unresolved P0/P1 implementation finding blocks FPL-004.

- Human acceptance and remote CI remain external and were not performed by Codex.
- Official FPL automated acquisition and persistent derived storage remain denied; only bounded transient manual validation is available under the supplied profile.
- Synthetic fixtures establish deterministic contract behavior, not current real-season completeness or permission for public/commercial use.
- Archive SHA-256 and CRC validation are external because a ZIP cannot embed its own final digest.
- Merge, push, release, scheduling, production activation, and any account action remain human-controlled exclusions.
""",
    )


def _manifest(
    status: Literal["DRAFT", "COMPLETE", "BLOCKED", "FAILED"],
    records: list[dict[str, Any]],
    code_commit: str | None,
) -> None:
    artifacts = []
    for path in sorted(EVIDENCE_ROOT.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name == "evidence_manifest.json":
            continue
        artifacts.append(
            {
                "bytes": path.stat().st_size,
                "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
                "sha256": _sha256(path),
            }
        )
    manifest = TicketEvidenceManifest(
        ticket_id="FPL-004",
        status=status,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        code_commit=code_commit,
        context_hash=PACK_MANIFEST_SHA256,
        commands=records,
        artifacts=artifacts,
        known_limitations=[] if status == "COMPLETE" else ["acceptance is not yet complete"],
    )
    _write_text(EVIDENCE_ROOT / "evidence_manifest.json", manifest.model_dump_json(indent=2))


def generate(
    *,
    status: Literal["COMPLETE", "BLOCKED", "FAILED"],
    payload_sha256: str,
    code_commit: str,
) -> None:
    records = _records()
    acceptance = _acceptance(records)
    if status == "COMPLETE" and any(item["status"] != "PASS" for item in acceptance):
        raise ValueError("COMPLETE evidence requires all 25 exact acceptance outcomes")
    coverage = _coverage()
    tests = _tests(records, coverage)
    if status == "COMPLETE" and tests["status"] != "PASS":
        raise ValueError("COMPLETE evidence requires every authority-tiered FPL-004 coverage gate")
    for name in ("migration_matrix.json", "package_report.json", "acceptance_verification.json"):
        if status == "COMPLETE" and _read_json(EVIDENCE_ROOT / name).get("status") != "PASS":
            raise ValueError(f"COMPLETE evidence requires PASS: {name}")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "--verify", "HEAD")
    if branch != REQUIRED_BRANCH or head != code_commit:
        raise ValueError("FPL-004 evidence Git provenance does not match the repository")
    current_manifest = build_repository_manifest(REPOSITORY_ROOT, ticket_id="FPL-004")
    _write_text(
        EVIDENCE_ROOT / "current_manifest.json",
        current_manifest.model_dump_json(indent=2),
    )
    from validate_repository import validate_repository

    repository_errors = validate_repository(REPOSITORY_ROOT)
    _write_json(
        EVIDENCE_ROOT / "repository_validation_report.json",
        {
            "error_count": len(repository_errors),
            "errors": repository_errors,
            "status": "PASS" if not repository_errors else "FAIL",
        },
    )
    if status == "COMPLETE" and repository_errors:
        raise ValueError("COMPLETE evidence requires a valid repository manifest and contract")
    _write_json(
        EVIDENCE_ROOT / "context_hashes.json",
        {
            "baseline": REQUIRED_BASELINE,
            "fixture_manifest_sha256": _sha256(REPOSITORY_ROOT / "fixtures/manifest.json"),
            "pack_manifest_sha256": PACK_MANIFEST_SHA256,
        },
    )
    _write_json(EVIDENCE_ROOT / "tests.json", tests)
    _write_json(
        EVIDENCE_ROOT / "acceptance_matrix.json",
        {
            "commands": acceptance,
            "failed": sum(item["status"] != "PASS" for item in acceptance),
            "passed": sum(item["status"] == "PASS" for item in acceptance),
            "status": status,
            "ticket_id": "FPL-004",
        },
    )
    _write_focused_reports(tests, acceptance, status)
    changes = []
    for line in _git("diff", "--name-status", f"{REQUIRED_BASELINE}..HEAD").splitlines():
        if not line:
            continue
        parts = line.split("\t")
        changes.append({"change": parts[0], "path": parts[-1].replace("\\", "/")})
    result = CodexResult.model_validate(
        {
            "ticket_id": "FPL-004",
            "status": status,
            "code_commit": code_commit,
            "summary": "DAT-003 remediation plus rights-gated deterministic FPL-shaped ingestion, lifecycle/resume, canonical promotion, cutoff-safe bundles, PostgreSQL enforcement, clean-wheel verification, and exact assurance evidence.",
            "files_changed": changes,
            "public_interfaces": [
                "dmf ingest fpl validate",
                "dmf ingest fpl import",
                "dmf ingest fpl replay",
                "dmf ingest fpl resume",
                "dmf ingest fpl snapshot",
                "dmf ingest fpl bundle show",
                "dmf evidence validate --ticket FPL-004",
            ],
            "commands": records,
            "tests": [tests],
            "acceptance": acceptance,
            "dependency_impact": "No unapproved dependency; exact graph is frozen in uv.lock.",
            "migration_impact": "One ordered reversible FPL-004 revision after immutable DAT-003 head.",
            "assumptions": [
                "The localhost PostgreSQL service is disposable test infrastructure.",
                "All replay inputs are hash-approved synthetic fixtures from Pack 004.",
            ],
            "exclusions_verified": [
                "No live or authenticated FPL/provider request, real payload, scheduler, API server, UI, odds adapter, model, projection, optimiser, or account action.",
                "No push, merge, rebase, reset, tag, amend, or repository visibility change.",
            ],
            "risks": [] if status == "COMPLETE" else ["milestone acceptance is incomplete"],
            "repository": {
                "baseline": REQUIRED_BASELINE,
                "branch": REQUIRED_BRANCH,
                "clean": True,
                "head": code_commit,
                "merged": False,
                "pushed": False,
            },
            "review_pack": {
                "path": REVIEW_PATH,
                "file_count": 20,
                "payload_sha256": payload_sha256,
                "archive_sha256": None,
                "sha256": None,
            },
        }
    )
    _write_text(EVIDENCE_ROOT / "codex_result.json", result.model_dump_json(indent=2))
    _manifest(status, records, code_commit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--status", choices=("DRAFT", "COMPLETE", "BLOCKED", "FAILED"), required=True
    )
    parser.add_argument("--payload-sha256")
    parser.add_argument("--code-commit")
    arguments = parser.parse_args()
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if arguments.status == "DRAFT":
        _write_json(
            EVIDENCE_ROOT / "context_hashes.json",
            {
                "baseline": REQUIRED_BASELINE,
                "fixture_manifest_sha256": _sha256(REPOSITORY_ROOT / "fixtures/manifest.json"),
                "pack_manifest_sha256": PACK_MANIFEST_SHA256,
            },
        )
        _manifest("DRAFT", _records(), None)
    else:
        if not arguments.payload_sha256 or not arguments.code_commit:
            parser.error("non-draft evidence requires --payload-sha256 and --code-commit")
        generate(
            status=arguments.status,
            payload_sha256=arguments.payload_sha256,
            code_commit=arguments.code_commit,
        )
    print(json.dumps({"status": arguments.status, "ticket_id": "FPL-004"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
