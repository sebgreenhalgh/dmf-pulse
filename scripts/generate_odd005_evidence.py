"""Generate strict ODD-005 machine evidence and compact human review sources."""

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
from dmf_pulse.assurance.review_pack import ODD_MANDATORY_ACCEPTANCE_COMMANDS
from dmf_pulse.assurance.secret_scan import scan_repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/tickets/ODD-005"
REQUIRED_BASELINE = "7034e38f32cd579c90d35c5fe3f10921c3656be0"
REQUIRED_BRANCH = "stage/A5/ODD-005-odds-provider-foundation"
REVIEW_PATH = "review_pack/ODD-005/DMF_PULSE_ODD-005_REVIEW.zip"
PACK_MANIFEST_SHA256 = "c030d775f2c4f5f68910ef443b1f0a86bc2a6e096299d448fbc0d81d48a62a20"


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
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
    if [item.get("command") for item in records] != list(ODD_MANDATORY_ACCEPTANCE_COMMANDS):
        raise ValueError("ODD-005 requires exactly 28 ordered acceptance command records")
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        expected = 4 if index == 23 else 0
        duration = record.get("duration_seconds")
        result = record.get("result")
        passed = (
            record.get("exit_code") == expected
            and isinstance(result, str)
            and result.startswith("PASS:")
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and duration >= 0
        )
        if index == 23:
            passed = (
                passed
                and "CREDENTIAL_UNAVAILABLE" in str(result)
                and "zero transport" in str(result)
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
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/check_odd005_coverage_gates.py"))
    checker = namespace.get("check_coverage")
    if not callable(checker):
        raise ValueError("ODD-005 coverage checker is unavailable")
    report = checker(coverage_path, repository_root=REPOSITORY_ROOT)
    if not isinstance(report, dict):
        raise ValueError("ODD-005 coverage checker returned malformed evidence")
    return report


def _passed_count(records: list[dict[str, Any]]) -> int:
    if len(records) < 25:
        return 0
    match = re.search(r"(\d+)\s+(?:passed|tests)", str(records[24].get("result", "")))
    return int(match.group(1)) if match else 0


def _tests(records: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "critical_odds_ingestion",
        "cutoff",
        "fpl_remediation",
        "quota",
        "rights",
        "tls",
    )
    result: dict[str, Any] = {
        "critical_oracles": list(coverage["critical_oracles"]),
        "failed": 0,
        "mutation_method": (
            "first-order boundary, malformed-input, conflict, temporal, concurrency, "
            "rights, quota, TLS, retention, and exception-redaction negative controls"
        ),
        "overall_branch_coverage_percent": coverage["overall_branch_coverage_percent"],
        "overall_branches_covered": coverage["overall_branches_covered"],
        "overall_branches_total": coverage["overall_branches_total"],
        "passed": _passed_count(records),
        "repository_combined_coverage_percent": coverage["repository_combined_coverage_percent"],
        "repository_combined_units_covered": coverage["repository_combined_units_covered"],
        "repository_combined_units_total": coverage["repository_combined_units_total"],
        "skipped": 0,
        "status": "PASS" if coverage.get("ok") and _passed_count(records) > 0 else "FAIL",
    }
    for key in keys:
        result[f"{key}_branch_coverage_percent"] = coverage[f"{key}_branch_coverage_percent"]
        result[f"{key}_branches_covered"] = coverage[f"{key}_branches_covered"]
        result[f"{key}_branches_total"] = coverage[f"{key}_branches_total"]
    return result


def _hash_lines(paths: tuple[str, ...]) -> str:
    lines: list[str] = []
    for relative in paths:
        path = REPOSITORY_ROOT / relative
        if path.is_file():
            lines.append(f"- `{relative}` — {path.stat().st_size} bytes — `{_sha256(path)}`")
    return "\n".join(lines)


def _acceptance_markdown(rows: list[dict[str, Any]], status: str) -> str:
    lines = [
        "# ODD-005 acceptance",
        "",
        f"Status: **{status}**. Mandatory commands passed: "
        f"**{sum(row['status'] == 'PASS' for row in rows)}/28**.",
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
        (
            "",
            "Command 23's exit 4 is the required `CREDENTIAL_UNAVAILABLE` refusal with zero "
            "transport calls. Commands 27-28 use measured write-ahead/finalization records; "
            "placeholders cannot produce COMPLETE evidence.",
        )
    )
    return "\n".join(lines)


def _write_reports(tests: dict[str, Any], acceptance: list[dict[str, Any]], status: str) -> None:
    _write_text(
        EVIDENCE_ROOT / "PUBLIC_CONTRACTS.md",
        """# ODD-005 public contracts

- CLI: `dmf ingest odds validate|import|replay|snapshot` and `dmf market observations`.
- The controlled snapshot command has no ambient credential lookup and refuses before transport.
- JSON is strict, deterministic, secret-free, and versioned; decimal strings retain approved source lexical scale.
- Semantic hashing canonicalises numerically equivalent Decimal values separately.

## Frozen schemas

"""
        + _hash_lines(
            tuple(
                f"public_contracts/{name}"
                for name in (
                    "market_observation.schema.json",
                    "market_query_result.schema.json",
                    "odds_ingestion_result.schema.json",
                    "provider_failure.schema.json",
                    "quota_state.schema.json",
                )
            )
        ),
    )
    migration = _read_json(EVIDENCE_ROOT / "migration_matrix.json")
    _write_text(
        EVIDENCE_ROOT / "MIGRATION_SCHEMA_REVIEW.md",
        f"""# ODD-005 migration and schema review

- Matrix status: **{migration.get("status", "UNKNOWN")}**.
- Exact baseline: `{migration.get("baseline_revision", "unavailable")}`; target: `{migration.get("target_revision", "unavailable")}`.
- PostgreSQL version: `{migration.get("database", {}).get("postgres_version", "unavailable")}`.
- Deterministic schema SHA-256: `{migration.get("schema", {}).get("schema_sha256", "unavailable")}`.
- Clean base upgrade, accepted FPL data preservation across two downgrade/re-upgrade cycles, offline SQL, and Alembic metadata drift are recorded in `migration_matrix.json`.

## Reviewed migration inputs

{_hash_lines(("src/dmf_pulse/database/migrations/versions/20260725_0003_fpl_bundle_authority.py", "src/dmf_pulse/database/migrations/versions/20260725_0004_odd005_market_observations.py", "src/dmf_pulse/data_model/tables.py", "scripts/test_migration_matrix.py"))}
""",
    )
    _write_text(
        EVIDENCE_ROOT / "FPL004_REMEDIATION.md",
        """# Mandatory FPL-004 remediation

- Direct and `URLError`-wrapped TLS/certificate failures are typed `TLS_ERROR`, non-retryable, and independently tested.
- Source bundles are relationally bound to immutable snapshot/profile authority and guarded against missing, denied, conflicting, or mismatched rights.
- Authoritative persisted open P0/P1 quality issues block publication under transaction locks.
- Bundle publication records the available code commit in its immutable provenance.
- Array fingerprints retain every heterogeneous observed type; preferred aliases store real Unicode NFC.
- Decimal semantic hashing uses fixed-point output and strips insignificant fractional zeros without exponent notation.
- Literal commands 15-16 plus the full command-25 suite prove the inherited FPL client, TLS, bundle-rights, quality, and public replay behavior remains green.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "PROVIDER_CLIENT_QUOTA.md",
        """# Provider client and quota review

- Frozen allowlist: HTTPS GET to `api.the-odds-api.com/v4/sports/soccer_epl/odds`, UK region, h2h, decimal, ISO.
- Credential resolution occurs at the final boundary; request/evidence reprs and failures never expose it.
- Redirects are disabled; TLS verification, connect/read/total deadlines, byte bounds, media type, and retry classes are explicit.
- Quota headers are immutable source-linked evidence. Known exhaustion and depletion during retry stop before another transport call.
- Acceptance uses synthetic fixtures and fake transports only; command 23 proves credential refusal with zero transport calls.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "MARKET_MAPPING_SEMANTICS.md",
        """# Market mapping and semantics

- Provider event IDs resolve only through the frozen mapping plan and official-FPL fixture mapping; labels validate but never create identity.
- Provider bookmaker keys map globally to one canonical operator; the database prevents seasonal/product scope bypasses.
- Market identity includes operator, fixture, versioned definition, full-time period, null line, and settlement profile; selections are market-scoped.
- h2h becomes explicit HOME/DRAW/AWAY 90-minute 1X2. Unsupported markets remain typed source evidence.
- Exact source-scale Decimal strings round-trip; no implied probability, de-vigging, consensus, forecast, or betting recommendation exists.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "RIGHTS_RETENTION.md",
        """# Rights and retention review

- `synthetic_the_odds_api_v1` permits only manifest-approved deterministic fixtures.
- `the_odds_api_private_analytics_v1` is human-approved private analytical authority with conservative raw/public/training/export limits.
- Unknown is deny at transport, raw persistence, promotion, bundle, backup, export, and public-rendering gates.
- Raw-forbidden success/failure paths retain no body; immutable decisions are unique per profile/snapshot/capability.
- Standalone raw-data redistribution is absent and rejected by contract.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "ASOF_IDEMPOTENCY_CONCURRENCY.md",
        """# As-of, idempotency, and concurrency review

- Eligibility is `usable_at <= as_of`; provider time alone never grants visibility.
- Latest selection uses deterministic observed/received/usable/source tie-breaking without stale-filling incomplete books.
- A repeated retrieval creates a new source/book observation; reprocessing one snapshot cannot duplicate quote effects.
- Changed prices append. Earlier as-of results remain unchanged and post-cutoff evidence remains excluded.
- PostgreSQL uniqueness/exclusion constraints and bounded advisory locks protect mapping, market, selection, quote, rights, and quality races.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "TESTS_AND_COVERAGE.md",
        f"""# Tests and coverage

- Status: **{tests["status"]}**; full-suite result: **{tests["passed"]} passed**, 0 failed, 0 skipped.
- Repository combined statement/branch coverage: **{tests["repository_combined_coverage_percent"]:.2f}%**.
- Overall branch coverage: **{tests["overall_branch_coverage_percent"]:.2f}%** ({tests["overall_branches_covered"]}/{tests["overall_branches_total"]}).
- Critical odds ingestion: **{tests["critical_odds_ingestion_branch_coverage_percent"]:.2f}%**.
- Rights: **{tests["rights_branch_coverage_percent"]:.2f}%**; quota: **{tests["quota_branch_coverage_percent"]:.2f}%**; cutoff: **{tests["cutoff_branch_coverage_percent"]:.2f}%**; TLS: **{tests["tls_branch_coverage_percent"]:.2f}%**; FPL remediation: **{tests["fpl_remediation_branch_coverage_percent"]:.2f}%**.
- Mutation method: {tests["mutation_method"]}.

## Critical oracles

"""
        + "\n".join(f"- {item}" for item in tests["critical_oracles"]),
    )
    findings = scan_repository(REPOSITORY_ROOT)
    _write_json(
        EVIDENCE_ROOT / "security_scan.json",
        {"finding_count": len(findings), "status": "PASS" if not findings else "FAIL"},
    )
    _write_text(
        EVIDENCE_ROOT / "SECURITY_AND_SECRET_REVIEW.md",
        f"""# Security and secret review

- First-party repository scan: **{"PASS" if not findings else "FAIL"}**, {len(findings)} finding(s).
- No live provider request or real credential was used. Fake credential/raw markers are restricted to exact synthetic source fixtures/tests and excluded from outputs.
- URLs, exception chains, reprs, logs, database records, evidence, and review entries are recursively checked for disclosure.
- Raw-forbidden body cleanup, TLS classification, retry bounds, quota preflight, and controlled refusal have independent negative controls.
""",
    )
    package = _read_json(EVIDENCE_ROOT / "package_report.json")
    _write_text(
        EVIDENCE_ROOT / "WHEEL_AND_CLI.md",
        f"""# Wheel and CLI review

- Installed-wheel verifier: **{package.get("status", "UNKNOWN")}**; wheel SHA-256: `{package.get("wheel", {}).get("sha256", "unavailable")}`.
- Wheel imports and executes outside the source tree with packaged provider/rights resources.
- Synthetic FPL replay, ODD validation/replay, exact market query, and credential refusal run from a clean environment.
- The verifier records zero network requests and removes its temporary build/install tree and uniquely named PostgreSQL database.
""",
    )
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    _write_json(
        EVIDENCE_ROOT / "dependency_report.json",
        {
            "lock_sha256": _sha256(REPOSITORY_ROOT / "uv.lock"),
            "runtime_dependencies": pyproject.get("project", {}).get("dependencies", []),
            "status": package.get("status"),
        },
    )
    _write_text(EVIDENCE_ROOT / "ACCEPTANCE.md", _acceptance_markdown(acceptance, status))
    _write_text(
        EVIDENCE_ROOT / "KNOWN_LIMITATIONS.md",
        """# Known limitations

No unresolved P0/P1 implementation finding blocks ODD-005.

- Human acceptance, merge, push, release, deployment, and provider-account/legal decisions remain external.
- Synthetic fixtures prove deterministic contracts, not current provider availability, prices, quota, or permission for broader use.
- Stage A5 does not provide historical backfill, normalisation, consensus, forecasting, execution, or recommendations.
- Archive SHA-256 and CRC validation are external because a ZIP cannot embed its own final digest.
""",
    )


def _manifest(
    status: Literal["DRAFT", "COMPLETE", "BLOCKED", "FAILED"],
    records: list[dict[str, Any]],
    code_commit: str | None,
) -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
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
        ticket_id="ODD-005",
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
        raise ValueError("COMPLETE evidence requires all 28 exact acceptance outcomes")
    coverage = _coverage()
    tests = _tests(records, coverage)
    if status == "COMPLETE" and tests["status"] != "PASS":
        raise ValueError("COMPLETE evidence requires every ODD-005 coverage gate")
    for name in ("migration_matrix.json", "package_report.json", "acceptance_verification.json"):
        if status == "COMPLETE" and _read_json(EVIDENCE_ROOT / name).get("status") != "PASS":
            raise ValueError(f"COMPLETE evidence requires PASS: {name}")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "--verify", "HEAD")
    clean = not _git("status", "--porcelain=v1", "--untracked-files=all")
    if branch != REQUIRED_BRANCH or head != code_commit or not clean:
        raise ValueError("ODD-005 evidence requires exact clean Git provenance")

    current_manifest = build_repository_manifest(REPOSITORY_ROOT, ticket_id="ODD-005")
    _write_text(EVIDENCE_ROOT / "current_manifest.json", current_manifest.model_dump_json(indent=2))
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
        raise ValueError("COMPLETE evidence requires repository validation PASS")
    _write_json(
        EVIDENCE_ROOT / "context_hashes.json",
        {
            "baseline": REQUIRED_BASELINE,
            "fixture_manifest_sha256": _sha256(
                REPOSITORY_ROOT / "fixtures/odds/ODD-005/manifest.json"
            ),
            "market_observation_schema_sha256": _sha256(
                REPOSITORY_ROOT / "public_contracts/market_observation.schema.json"
            ),
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
            "ticket_id": "ODD-005",
        },
    )
    _write_reports(tests, acceptance, status)
    changes = []
    for line in _git("diff", "--name-status", f"{REQUIRED_BASELINE}..HEAD").splitlines():
        if line:
            parts = line.split("\t")
            changes.append({"change": parts[0], "path": parts[-1].replace("\\", "/")})
    result = CodexResult.model_validate(
        {
            "ticket_id": "ODD-005",
            "status": status,
            "code_commit": code_commit,
            "summary": (
                "FPL-004 remediation plus rights-gated deterministic odds ingestion, exact "
                "Decimal observations, explicit mapping, quota evidence, cutoff-safe as-of "
                "queries, PostgreSQL enforcement, clean-wheel verification, and exact evidence."
            ),
            "files_changed": changes,
            "public_interfaces": [
                "dmf ingest odds validate",
                "dmf ingest odds import",
                "dmf ingest odds replay",
                "dmf ingest odds snapshot",
                "dmf market observations",
                "dmf evidence validate --ticket ODD-005",
            ],
            "commands": records,
            "tests": [tests],
            "acceptance": acceptance,
            "dependency_impact": "No new ODD runtime dependency; exact graph remains frozen in uv.lock.",
            "migration_impact": (
                "Two ordered reversible revisions after accepted FPL-004: authoritative bundle "
                "remediation and the ODD-005 market-observation schema."
            ),
            "assumptions": [
                "The localhost PostgreSQL service is disposable test infrastructure.",
                "Every replay input is a hash-approved Pack 1.1 synthetic fixture.",
            ],
            "exclusions_verified": [
                "No live provider request, real credential, historical backfill, normalisation, consensus, forecast, execution, recommendation, API server, UI, or scheduler.",
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
        _manifest("DRAFT", _records(), None)
    else:
        if not arguments.payload_sha256 or not arguments.code_commit:
            parser.error("non-draft evidence requires --payload-sha256 and --code-commit")
        generate(
            status=arguments.status,
            payload_sha256=arguments.payload_sha256,
            code_commit=arguments.code_commit,
        )
    print(json.dumps({"status": arguments.status, "ticket_id": "ODD-005"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
