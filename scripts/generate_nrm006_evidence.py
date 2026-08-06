"""Generate strict NRM-006 machine evidence and compact human review sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dmf_pulse.assurance.evidence import CodexResult, TicketEvidenceManifest
from dmf_pulse.assurance.manifests import build_repository_manifest
from dmf_pulse.assurance.review_pack import (
    NRM_MANDATORY_ACCEPTANCE_COMMANDS,
    NRM_REVIEW_FINAL_RESULT,
    NRM_REVIEW_WRITE_AHEAD_RESULT,
    NRM_TEARDOWN_FINAL_RESULT,
    NRM_TEARDOWN_WRITE_AHEAD_RESULT,
)
from dmf_pulse.assurance.secret_scan import scan_repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence/tickets/NRM-006"
REQUIRED_BASELINE = "e36ea84cda9e80191a9160d037f8e7035477b9b1"
REQUIRED_BRANCH = "stage/A6/NRM-006-odds-normalisation"
REVIEW_PATH = "review_pack/NRM-006/DMF_PULSE_NRM-006_REVIEW.zip"
PACK_MANIFEST_SHA256 = "6be2a825a90dfa89f7e5ce1da5475c144cb44cee265b33d75396cef3256966e4"
EXPECTED_MIGRATION_BASELINE = "20260725_0004"
EXPECTED_MIGRATION_HEAD = "20260803_0005"
EXPECTED_POSTGRES_VERSION = "18.4"
EXPECTED_OFFLINE_SQL = "evidence/tickets/NRM-006/offline_upgrade.sql"
CRITICAL_CATEGORIES = (
    "temporal_mapping",
    "usable_at",
    "retry_429",
    "completeness",
    "proportional",
    "power",
    "consensus",
    "persistence",
    "cli",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key is forbidden: {key}")
        value[key] = item
    return value


def _parse_json(value: str) -> Any:
    return json.loads(
        value,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = _parse_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON evidence is unavailable or malformed: {path.name}") from exc
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
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError("NRM-006 command log is unavailable") from exc
    for line_number, line in enumerate(lines, start=1):
        try:
            value = _parse_json(line)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"commands.log line {line_number} is malformed") from exc
        if not isinstance(value, dict):
            raise ValueError("commands.log lines must be JSON objects")
        records.append(value)
    return records


def _valid_duration(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and value >= 0
    )


def _acceptance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if [item.get("command") for item in records] != list(NRM_MANDATORY_ACCEPTANCE_COMMANDS):
        raise ValueError("NRM-006 requires exactly 32 ordered acceptance command records")
    rows: list[dict[str, Any]] = []
    required_keys = {"command", "duration_seconds", "exit_code", "result"}
    for index, record in enumerate(records, start=1):
        if set(record) != required_keys:
            raise ValueError(f"NRM-006 command {index} must use the four exact fields")
        duration = record["duration_seconds"]
        result = record["result"]
        exit_code = record["exit_code"]
        passed = (
            type(exit_code) is int
            and exit_code == 0
            and isinstance(result, str)
            and result.startswith("PASS:")
            and _valid_duration(duration)
            and result not in {NRM_REVIEW_WRITE_AHEAD_RESULT, NRM_TEARDOWN_WRITE_AHEAD_RESULT}
        )
        if index == 31:
            passed = passed and result == NRM_REVIEW_FINAL_RESULT
        elif index == 32:
            passed = passed and result == NRM_TEARDOWN_FINAL_RESULT
        rows.append(
            {
                "command": record["command"],
                "duration_seconds": duration,
                "exit_code": exit_code,
                "expected_exit_code": 0,
                "status": "PASS" if passed else "NOT_PASSED",
            }
        )
    return rows


def _coverage_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    coverage_path = EVIDENCE_ROOT / "coverage.json"
    critical_path = EVIDENCE_ROOT / "critical_coverage.json"
    coverage = _read_json(coverage_path)
    critical = _read_json(critical_path)
    if critical.get("coverage_json_sha256") != _sha256(coverage_path):
        raise ValueError("critical coverage does not bind the exact coverage JSON")
    if critical.get("coverage_path") != "evidence/tickets/NRM-006/coverage.json":
        raise ValueError("critical coverage records the wrong coverage path")

    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/verify_nrm006_critical_coverage.py"))
    checker = namespace.get("check_coverage")
    if not callable(checker):
        raise ValueError("NRM-006 critical coverage checker is unavailable")
    calculated = checker(coverage_path)
    if not isinstance(calculated, dict):
        raise ValueError("NRM-006 critical coverage checker returned malformed evidence")
    for key, expected in calculated.items():
        if critical.get(key) != expected:
            raise ValueError(f"critical coverage conflicts with coverage JSON: {key}")
    if critical.get("status") not in {"PASS", "FAIL"}:
        raise ValueError("critical coverage status is malformed")
    return critical, coverage


def _full_suite_passed(records: list[dict[str, Any]]) -> int:
    if len(records) < 27:
        return 0
    result = records[26].get("result")
    if not isinstance(result, str):
        return 0
    match = re.fullmatch(
        r"PASS:\s*(\d+)\s+tests;\s*0 skipped;\s*[0-9]+(?:\.[0-9]+)?% "
        r"combined coverage",
        result,
    )
    return int(match.group(1)) if match and int(match.group(1)) > 0 else 0


def _metric(report: dict[str, Any], key: str) -> float:
    value = report.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 100.0
    ):
        raise ValueError(f"critical coverage metric is malformed: {key}")
    return float(value)


def _tests(records: list[dict[str, Any]], critical: dict[str, Any]) -> dict[str, Any]:
    category_percentages = {
        category: _metric(critical, f"{category}_branch_coverage_percent")
        for category in CRITICAL_CATEGORIES
    }
    raw_oracles = critical.get("critical_oracles")
    if not isinstance(raw_oracles, dict) or set(raw_oracles) != set(CRITICAL_CATEGORIES):
        raise ValueError("critical coverage oracle categories are incomplete")
    oracles: list[str] = []
    seen: set[str] = set()
    for category in CRITICAL_CATEGORIES:
        items = raw_oracles.get(category)
        if not isinstance(items, list) or not items:
            raise ValueError(f"critical coverage oracles are incomplete: {category}")
        for item in items:
            if not isinstance(item, str) or not item:
                raise ValueError(f"critical coverage oracle is malformed: {category}")
            if item not in seen:
                seen.add(item)
                oracles.append(item)
    passed = _full_suite_passed(records)
    overall = _metric(critical, "overall_branch_coverage_percent")
    mathematical = _metric(critical, "mathematical_core_branch_coverage_percent")
    critical_minimum = min(category_percentages.values())
    errors = critical.get("errors")
    report_passed = (
        critical.get("status") == "PASS"
        and critical.get("ok") is True
        and errors == []
        and overall >= 90.0
        and critical_minimum >= 95.0
        and mathematical == 100.0
        and len(oracles) >= 10
        and passed > 0
    )
    result: dict[str, Any] = {
        "critical_branch_coverage_percent": critical_minimum,
        "critical_oracles": oracles,
        "failed": 0,
        "math_branch_coverage_percent": mathematical,
        "negative_control_method": (
            "boundary, malformed-input, temporal, retry, duplicate, completeness, "
            "numerical-fallback, rights, cache, and concurrency controls"
        ),
        "overall_branch_coverage_percent": overall,
        "overall_branches_covered": critical["overall_branches_covered"],
        "overall_branches_total": critical["overall_branches_total"],
        "passed": passed,
        "repository_combined_coverage_percent": _metric(
            critical, "repository_combined_coverage_percent"
        ),
        "repository_combined_units_covered": critical["repository_combined_units_covered"],
        "repository_combined_units_total": critical["repository_combined_units_total"],
        "skipped": 0,
        "status": "PASS" if report_passed else "FAIL",
    }
    for category, percentage in category_percentages.items():
        result[f"{category}_branch_coverage_percent"] = percentage
        result[f"{category}_branches_covered"] = critical[f"{category}_branches_covered"]
        result[f"{category}_branches_total"] = critical[f"{category}_branches_total"]
    return result


def _validate_migration(report: dict[str, Any]) -> None:
    database = report.get("database")
    offline = report.get("offline_sql")
    schema = report.get("schema")
    matrix = report.get("matrix")
    if (
        report.get("status") != "PASS"
        or report.get("ticket_id") != "NRM-006"
        or report.get("baseline_revision") != EXPECTED_MIGRATION_BASELINE
        or report.get("target_revision") != EXPECTED_MIGRATION_HEAD
        or report.get("revisions") != [EXPECTED_MIGRATION_HEAD]
        or report.get("revision_count") != 1
        or report.get("metadata_drift_check") != "PASS"
        or not isinstance(database, dict)
        or database.get("postgres_version") != EXPECTED_POSTGRES_VERSION
        or not isinstance(offline, dict)
        or offline.get("secret_free") is not True
        or offline.get("path") != EXPECTED_OFFLINE_SQL
        or not isinstance(schema, dict)
        or schema.get("alembic_revision") != EXPECTED_MIGRATION_HEAD
        or re.fullmatch(r"[0-9a-f]{64}", str(schema.get("schema_sha256"))) is None
        or not isinstance(matrix, list)
        or len(matrix) < 3
        or not all(isinstance(item, dict) and item.get("status") == "PASS" for item in matrix)
    ):
        raise ValueError("COMPLETE evidence requires the exact NRM-006 migration matrix")
    offline_path = REPOSITORY_ROOT / EXPECTED_OFFLINE_SQL
    if not offline_path.is_file():
        raise ValueError("COMPLETE evidence requires the NRM-006 offline upgrade SQL")
    if "sha256" in offline and offline["sha256"] != _sha256(offline_path):
        raise ValueError("migration evidence does not bind the exact offline upgrade SQL")
    if "bytes" in offline and offline["bytes"] != offline_path.stat().st_size:
        raise ValueError("migration evidence records the wrong offline SQL size")


def _validate_package(report: dict[str, Any]) -> None:
    wheel = report.get("wheel")
    if (
        report.get("status") != "PASS"
        or report.get("network_requests") != 0
        or report.get("cleaned_up") is not True
        or report.get("database_cleaned_up") is not True
        or not isinstance(wheel, dict)
        or wheel.get("distribution") != "dmf-pulse==0.2.0"
        or wheel.get("contains_confidence_gate_policy") is not True
        or wheel.get("contains_normalisation_policy") is not True
        or re.fullmatch(r"[0-9a-f]{64}", str(wheel.get("sha256"))) is None
    ):
        raise ValueError("COMPLETE evidence requires the exact clean-wheel NRM-006 report")


def _validate_acceptance_verification(report: dict[str, Any], head: str) -> None:
    git = report.get("git")
    package = report.get("package")
    if (
        report.get("status") != "PASS"
        or not isinstance(git, dict)
        or git.get("baseline") != REQUIRED_BASELINE
        or git.get("branch") != REQUIRED_BRANCH
        or git.get("clean") is not True
        or git.get("head") != head
        or not isinstance(package, dict)
        or package.get("network_requests") != 0
        or package.get("cleaned_up") is not True
    ):
        raise ValueError("COMPLETE evidence requires independent NRM-006 verification")


def _validate_git(code_commit: str) -> tuple[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
        raise ValueError("NRM-006 evidence requires a lowercase 40-character code commit")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "--verify", "HEAD")
    baseline = _git("rev-parse", "--verify", REQUIRED_BASELINE)
    if branch != REQUIRED_BRANCH or head != code_commit or baseline != REQUIRED_BASELINE:
        raise ValueError("NRM-006 evidence requires the exact branch, HEAD, and baseline")
    _git("merge-base", "--is-ancestor", REQUIRED_BASELINE, head)
    if _git("rev-list", "--merges", f"{REQUIRED_BASELINE}..{head}"):
        raise ValueError("NRM-006 evidence forbids merge commits since the baseline")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("NRM-006 evidence requires a clean working tree")
    return branch, head


def _hash_lines(paths: tuple[str, ...]) -> str:
    lines: list[str] = []
    for relative in paths:
        path = REPOSITORY_ROOT / relative
        if path.is_file():
            lines.append(f"- `{relative}` — {path.stat().st_size} bytes — `{_sha256(path)}`")
    return "\n".join(lines)


def _write_reports(tests: dict[str, Any], acceptance: list[dict[str, Any]], status: str) -> None:
    migration = _read_json(EVIDENCE_ROOT / "migration_matrix.json")
    package = _read_json(EVIDENCE_ROOT / "package_report.json")
    _write_text(
        EVIDENCE_ROOT / "PUBLIC_CONTRACTS.md",
        """# NRM-006 public contracts

- Library contracts expose exact Decimal operator normalisation, consensus, uncertainty, confidence, and immutable lineage models.
- CLI contracts expose `dmf ingest odds replay`, `dmf market observations`, and `dmf market normalise` with strict JSON and typed exit outcomes.
- Success and degraded normalisation return exit 0; insufficient data returns exit 2; rights, quality, or temporal blocks return exit 4; unexpected failure returns exit 1.
- Complete public probability vectors use exactly 12 fractional digits and sum to `1.000000000000`.
- No public raw-odds redistribution interface is introduced.

## Frozen public schemas

"""
        + _hash_lines(
            tuple(
                f"public_contracts/{name}"
                for name in (
                    "probability.schema.json",
                    "normalised_operator_market.schema.json",
                    "market_normalisation_result.schema.json",
                    "market_consensus.schema.json",
                )
            )
        ),
    )
    _write_text(
        EVIDENCE_ROOT / "MIGRATION_SCHEMA_REVIEW.md",
        f"""# NRM-006 migration and schema review

- Matrix status: **{migration.get("status", "UNKNOWN")}**; exact baseline `{migration.get("baseline_revision", "unavailable")}`; target `{migration.get("target_revision", "unavailable")}`.
- PostgreSQL version: `{migration.get("database", {}).get("postgres_version", "unavailable")}`; deterministic schema SHA-256: `{migration.get("schema", {}).get("schema_sha256", "unavailable")}`.
- The single reversible revision adds immutable normalisation, operator-vector, consensus, policy, input-signature, and post-commit publication-attestation structures after `20260725_0004`.
- Clean-base upgrade, inherited-head upgrade, two downgrade/re-upgrade cycles, metadata drift, and secret-free offline SQL are recorded in `migration_matrix.json`.
- Database constraints and triggers enforce probability bounds, complete-vector identity, lineage, exact-signature reuse, and publication immutability where relationally feasible.

## Reviewed inputs

{_hash_lines(("src/dmf_pulse/database/migrations/versions/20260803_0005_nrm006_normalisation.py", "src/dmf_pulse/data_model/tables.py", "scripts/test_migration_matrix.py"))}
""",
    )
    _write_text(
        EVIDENCE_ROOT / "ODD005_REMEDIATION.md",
        """# ODD-005 remediation closure

- Publication preparation, mapping, rights, and quality complete before activation; the activation transaction publishes one immutable batch atomically.
- Eligibility begins only from a separately persisted UTC attestation sampled after activation commit acknowledgement. Missing attestation remains excluded and repair can only sample a later value.
- Strict mapping uses one explicit UTC cutoff across valid time, system time, schedule usability, aliases, teams, fixtures, and operators.
- HTTP 429 handling preserves the inherited complete three-header quota rule, uses bounded injected sleeping, honours valid 1-60 second `Retry-After`, and never performs real sleeping in acceptance.
- Same-value observations from distinct retrieval snapshots remain distinct. Same-payload duplicates are counted and warned; conflicting duplicates quarantine.
- Synthetic fixture evidence cannot manufacture production-authoritative `official_fpl` mappings, while permitted official/manual evidence remains supported.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "TEMPORAL_MAPPING_USABLE_AT.md",
        """# Temporal mapping and usable-at review

- `usable_at` is a post-commit attestation keyed to the immutable publication batch, never provider time, receipt time, a pre-commit clock sample, or an artificial offset.
- Activation rollback creates no USABLE batch. Attestation failure leaves a durable but ineligible batch for conservative later repair.
- Receipt before cutoff with attestation after cutoff is typed `OBSERVED_NOT_USABLE` and cannot enter the earlier as-of result.
- Mapping-plan approval time and evidence class persist in lineage. Fixture, team, alias, label, schedule, and operator resolution all use the same mapping cutoff.
- A later mapping or fixture correction cannot alter an earlier strict-information replay.
- `verify_nrm006_temporal_canaries.py` binds and executes the frozen processing-crosses-cutoff and future-mapping synthetic scenarios with no external transport or real sleep.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "RETRY_DUPLICATE_PROVENANCE.md",
        """# Retry, duplicate, and provenance review

- A 429 response is retryable only with complete, valid quota evidence and remaining retry/deadline budget; otherwise it is typed non-retryable source unavailability.
- Valid integer `Retry-After` values from 1 through 60 seconds are honoured. Missing or invalid values use the deterministic bounded configured delay.
- Fake transports, scripted clocks, and injected sleepers record attempts and delays; acceptance makes no external request and performs no real wait.
- Retrieval snapshots preserve observation-event identity even when odds values are equal.
- Identical same-payload outcomes collapse only with `DUPLICATE_OUTCOME_DEDUPED` and an exact duplicate count; conflicting values quarantine.
- Synthetic FPL evidence stays synthetic or TEST_ONLY and cannot elevate itself to human-verified production authority.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "NORMALISATION_NUMERICS.md",
        """# Normalisation numerical review

- Source-scale Decimal odds must be greater than one. Computation uses a local precision-60, `ROUND_HALF_EVEN` context without mutating global Decimal state.
- Raw implied probability is `1 / decimal_odds`; booksum is the raw sum and overround is booksum minus one.
- Proportional probability is `q_i / sum(q)`. Power probability uses the unique positive exponent satisfying `sum(q_i ** alpha) = 1` with the frozen bracket and exactly 256 Decimal bisection iterations.
- Public vectors quantise to 12 places using HALF_EVEN. Any residual is assigned to the largest unrounded outcome, with HOME, DRAW, AWAY tie order.
- POWER is primary; PROPORTIONAL remains the sensitivity baseline. Explicit power failure emits `POWER_FALLBACK_PROPORTIONAL` and caps confidence at C.
- Frozen golden projections cover balanced, heavy-favourite, high-overround, duplicate, incomplete, retry, cutoff, reobservation, stale, and future-mapping cases.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "CONSENSUS_CONFIDENCE.md",
        """# Consensus, completeness, and confidence review

- Only latest eligible COMPLETE full-time pre-match HOME/DRAW/AWAY books are normalised; each canonical operator is processed independently without stale-fill.
- Consensus is the equal-weight arithmetic mean of eligible canonical-operator POWER vectors. Technical provider count and canonical operator count stay separate.
- Operator disagreement is maximum pairwise total-variation distance; method disagreement is the maximum POWER-versus-PROPORTIONAL distance; market disagreement is their maximum.
- Outcome bounds are the componentwise envelope over public POWER and PROPORTIONAL operator vectors.
- Freshness uses provider/operator observation time with the frozen 1,800-second limit.
- Confidence follows only the versioned policy. Any exclusion, warning, or fallback degrades status; no eligible book yields INSUFFICIENT without invented probabilities.
""",
    )
    _write_text(
        EVIDENCE_ROOT / "ASOF_CACHE_CONCURRENCY.md",
        """# As-of, cache, lineage, and concurrency review

- Every persisted result binds sorted immutable observation IDs, as-of time, mapping cutoff, policy ID/hash, and code identity into a deterministic dependency signature.
- Repeating the exact signature reuses immutable content. A new same-value observation creates new lineage; a corrected observation or policy creates a new result.
- Later observations, mappings, or fixture corrections do not change earlier as-of output.
- Cache reuse requires the exact dependency signature; fixture, Gameweek, or latest aliases alone cannot authorize reuse.
- PostgreSQL locks, uniqueness, constraints, and immutability triggers cover duplicate run creation and same-source correction races.
- Operator and consensus records preserve input signature, result hash, policy, code commit, mapping cutoff, as-of time, and source observation lineage.
""",
    )
    category_lines = "\n".join(
        f"- {category.replace('_', ' ').title()}: **{tests[f'{category}_branch_coverage_percent']:.2f}%**."
        for category in CRITICAL_CATEGORIES
    )
    _write_text(
        EVIDENCE_ROOT / "TESTS_AND_COVERAGE.md",
        f"""# Tests and coverage

- Status: **{tests["status"]}**; full suite: **{tests["passed"]} tests**, 0 failed, 0 skipped.
- Repository combined statement/branch coverage: **{tests["repository_combined_coverage_percent"]:.2f}%**.
- Overall branch coverage: **{tests["overall_branch_coverage_percent"]:.2f}%** ({tests["overall_branches_covered"]}/{tests["overall_branches_total"]}).
- Minimum critical-category branch coverage: **{tests["critical_branch_coverage_percent"]:.2f}%**.
- Mathematical-core branch coverage: **{tests["math_branch_coverage_percent"]:.2f}%**.
- Negative controls: {tests["negative_control_method"]}.

## Critical categories

{category_lines}

## Critical function oracles

"""
        + "\n".join(f"- {item}" for item in tests["critical_oracles"]),
    )
    _write_text(
        EVIDENCE_ROOT / "SECURITY_RIGHTS_WHEEL.md",
        f"""# Security, rights, and installed-wheel review

- Installed-wheel verifier: **{package.get("status", "UNKNOWN")}**; wheel SHA-256: `{package.get("wheel", {}).get("sha256", "unavailable")}`.
- The clean wheel imports and runs outside the source tree with the frozen normalisation policy and public schemas.
- Synthetic ingestion replay, observation query, and normalisation execute through the installed CLI; the report records `{package.get("network_requests", "unavailable")}` network requests.
- Temporary build/install state and the isolated PostgreSQL database are removed by the verifier.
- Unknown rights remain deny at transport, persistence, promotion, bundle, backup, export, training, and public-rendering boundaries.
- Acceptance uses hash-approved synthetic fixtures only and does not resolve or read a real provider credential.
- First-party secret scan outcome is recorded exactly in `security_scan.json`.
""",
    )
    passed = sum(item["status"] == "PASS" for item in acceptance)
    _write_text(
        EVIDENCE_ROOT / "KNOWN_LIMITATIONS.md",
        f"""# Known limitations

No unresolved P0/P1 implementation finding blocks NRM-006. Structured acceptance status is **{status}** and {passed}/32 mandatory command records pass.

- Human acceptance, merge, push, release, deployment, and provider-account or legal decisions remain external.
- Synthetic fixtures prove deterministic contracts, not current provider availability, prices, quota, or broader redistribution rights.
- Historical backfill, forecasting, minutes, event score grids, player props, optimiser logic, betting execution, and recommendations remain outside NRM-006.
- Archive SHA-256 and CRC validation are external because a ZIP cannot embed its own final digest.
""",
    )


def _context_hashes() -> dict[str, str]:
    paths = {
        "acceptance_contract_sha256": "tickets/NRM-006/ACCEPTANCE.md",
        "authority_manifest_sha256": "specs/manifests/authority_manifest.json",
        "confidence_gate_policy_sha256": "config/markets/confidence_gate_policy.json",
        "fixture_manifest_sha256": "fixtures/odds/NRM-006/manifest.json",
        "fixture_normalisation_policy_sha256": ("fixtures/odds/NRM-006/normalisation_policy.json"),
        "lock_sha256": "uv.lock",
        "market_consensus_schema_sha256": "public_contracts/market_consensus.schema.json",
        "market_normalisation_result_schema_sha256": (
            "public_contracts/market_normalisation_result.schema.json"
        ),
        "normalisation_policy_sha256": "config/markets/normalisation_policy.json",
        "normalised_operator_market_schema_sha256": (
            "public_contracts/normalised_operator_market.schema.json"
        ),
        "probability_schema_sha256": "public_contracts/probability.schema.json",
        "pyproject_sha256": "pyproject.toml",
        "ticket_sha256": "tickets/NRM-006/ticket.yaml",
    }
    hashes = {name: _sha256(REPOSITORY_ROOT / path) for name, path in paths.items()}
    hashes.update(baseline=REQUIRED_BASELINE, pack_manifest_sha256=PACK_MANIFEST_SHA256)
    return hashes


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
        ticket_id="NRM-006",
        status=status,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        code_commit=code_commit,
        context_hash=PACK_MANIFEST_SHA256,
        commands=records,
        artifacts=artifacts,
        known_limitations=[] if status == "COMPLETE" else ["acceptance is not yet complete"],
    )
    _write_text(EVIDENCE_ROOT / "evidence_manifest.json", manifest.model_dump_json(indent=2))


def _repository_validation() -> list[str]:
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/validate_repository.py"))
    validator = namespace.get("validate_repository")
    if not callable(validator):
        raise ValueError("repository validator is unavailable")
    errors = validator(REPOSITORY_ROOT)
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        raise ValueError("repository validator returned malformed evidence")
    return errors


def _changes() -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for line in _git("diff", "--name-status", f"{REQUIRED_BASELINE}..HEAD").splitlines():
        if line:
            parts = line.split("\t")
            changes.append({"change": parts[0], "path": parts[-1].replace("\\", "/")})
    return changes


def generate(
    *,
    status: Literal["COMPLETE", "BLOCKED", "FAILED"],
    payload_sha256: str,
    code_commit: str,
) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", payload_sha256) is None:
        raise ValueError("NRM-006 payload digest must be lowercase SHA-256")
    records = _records()
    acceptance = _acceptance(records)
    critical, _coverage = _coverage_evidence()
    tests = _tests(records, critical)
    migration = _read_json(EVIDENCE_ROOT / "migration_matrix.json")
    package = _read_json(EVIDENCE_ROOT / "package_report.json")
    verification = _read_json(EVIDENCE_ROOT / "acceptance_verification.json")
    _branch, head = _validate_git(code_commit)
    if status == "COMPLETE":
        if any(item["status"] != "PASS" for item in acceptance):
            raise ValueError("COMPLETE evidence requires all 32 exact acceptance outcomes")
        if tests["status"] != "PASS":
            raise ValueError("COMPLETE evidence requires every NRM-006 coverage gate")
        _validate_migration(migration)
        _validate_package(package)
        _validate_acceptance_verification(verification, head)

    current_manifest = build_repository_manifest(REPOSITORY_ROOT, ticket_id="NRM-006")
    _write_text(EVIDENCE_ROOT / "current_manifest.json", current_manifest.model_dump_json(indent=2))
    repository_errors = _repository_validation()
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
    _write_json(EVIDENCE_ROOT / "context_hashes.json", _context_hashes())
    _write_json(EVIDENCE_ROOT / "tests.json", tests)
    _write_json(
        EVIDENCE_ROOT / "acceptance_matrix.json",
        {
            "commands": acceptance,
            "failed": sum(item["status"] != "PASS" for item in acceptance),
            "passed": sum(item["status"] == "PASS" for item in acceptance),
            "status": status,
            "ticket_id": "NRM-006",
        },
    )
    _write_reports(tests, acceptance, status)
    result = CodexResult.model_validate(
        {
            "ticket_id": "NRM-006",
            "status": status,
            "code_commit": code_commit,
            "summary": (
                "Mandatory ODD-005 temporal, retry, duplicate, and provenance remediation "
                "plus deterministic Decimal odds normalisation, complete-book filtering, "
                "equal-operator consensus, confidence, immutable as-of persistence, exact "
                "cache lineage, installed-wheel verification, and capped review evidence."
            ),
            "files_changed": _changes(),
            "public_interfaces": [
                "dmf ingest odds replay",
                "dmf market observations",
                "dmf market normalise",
                "dmf evidence validate --ticket NRM-006",
            ],
            "commands": records,
            "tests": [tests],
            "acceptance": acceptance,
            "dependency_impact": (
                "No runtime dependency expansion; the existing frozen dependency graph remains "
                "authoritative in uv.lock."
            ),
            "migration_impact": (
                "One ordered reversible NRM-006 revision after 20260725_0004 adds publication "
                "attestation and immutable normalisation, consensus, policy, and lineage state."
            ),
            "assumptions": [
                "The localhost PostgreSQL 18.4 service is disposable test infrastructure.",
                "Every acceptance replay input is a hash-approved Pack 1.1 synthetic fixture.",
            ],
            "exclusions_verified": [
                "No live provider request, real credential, historical backfill, forecast, "
                "minutes model, event score grid, player prop, optimiser, execution, "
                "recommendation, API server, UI, or scheduler.",
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
    findings = scan_repository(REPOSITORY_ROOT)
    _write_json(
        EVIDENCE_ROOT / "security_scan.json",
        {"finding_count": len(findings), "status": "PASS" if not findings else "FAIL"},
    )
    if status == "COMPLETE" and findings:
        raise ValueError("COMPLETE evidence requires a zero-finding secret scan")
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
    print(json.dumps({"status": arguments.status, "ticket_id": "NRM-006"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
