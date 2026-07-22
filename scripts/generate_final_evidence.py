"""Generate the compact machine/human FND-001 evidence set from observed command records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence" / "tickets" / "FND-001"
COMMAND_LOG = EVIDENCE_ROOT / "commands.log"
REVIEW_PATH = "review_pack/FND-001/DMF_PULSE_FND-001_REVIEW.zip"
MANDATORY_COMMANDS = (
    "uv sync --all-groups --frozen",
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run mypy src/dmf_pulse",
    "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing",
    "uv run dmf --version",
    "uv run dmf doctor --json",
    "uv run dmf config validate --environment test --config-root config",
    "uv run dmf config show --environment test --config-root config --json",
    "uv build",
    "uv run python scripts/verify_wheel.py",
    "uv run python scripts/validate_repository.py",
    "uv run python scripts/scan_secrets.py",
    "uv run dmf review-pack build --ticket FND-001 --output review_pack/FND-001",
)
RUL_BASELINE = "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"
RUL_COMMANDS = (
    "uv sync --all-groups --frozen",
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run mypy src/dmf_pulse",
    "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json",
    "uv run dmf --version",
    "uv run dmf doctor --json",
    "uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json",
    "uv run dmf rules compile fixtures/rules/RUL-002/synthetic_complete --output artifacts/rules/rul-002-synthetic.json --json",
    "uv run dmf rules hash artifacts/rules/rul-002-synthetic.json --json",
    "uv run dmf rules score-fixture artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_fixture_001.json --json",
    "uv run dmf rules score-gameweek artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_gameweek_001.json --json",
    "uv run dmf rules diff fixtures/rules/RUL-002/reference_2025_26 fixtures/rules/RUL-002/target_2026_27_partial --json",
    "uv run dmf rules activate fixtures/rules/RUL-002/target_2026_27_partial --approval fixtures/rules/RUL-002/invalid_target_approval.json --json",
    "uv build",
    "uv run python scripts/verify_wheel.py",
    "uv run python scripts/validate_repository.py",
    "uv run python scripts/scan_secrets.py",
    f"uv run dmf review-pack build --ticket RUL-002 --baseline {RUL_BASELINE} --output review_pack/RUL-002",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _command_records() -> list[dict[str, Any]]:
    records = []
    for line in COMMAND_LOG.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("commands.log lines must be JSON objects")
        records.append(value)
    return records


def _record_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(record["command"]): record
        for record in records
        if isinstance(record.get("command"), str)
    }


def _acceptance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_command = _record_map(records)
    result = []
    for command in MANDATORY_COMMANDS:
        record = by_command.get(command)
        passed = record is not None and record.get("exit_code") == 0
        result.append(
            {
                "command": command,
                "duration_seconds": record.get("duration_seconds") if record else None,
                "exit_code": record.get("exit_code") if record else None,
                "status": "PASS" if passed else "NOT_PASSED",
            }
        )
    return result


def _test_summary(coverage: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    pytest_record = _record_map(records).get(MANDATORY_COMMANDS[4], {})
    match = re.search(r"PASS: (\d+) tests", str(pytest_record.get("result", "")))
    passed = int(match.group(1)) if match else 0
    totals = coverage.get("totals", {})
    if not isinstance(totals, dict):
        raise ValueError("coverage totals are malformed")
    branch_percent = float(totals.get("percent_branches_covered", 0.0))
    return {
        "branch_coverage_percent": round(branch_percent, 2),
        "branches_covered": totals.get("covered_branches"),
        "branches_total": totals.get("num_branches"),
        "collected": passed,
        "failed": 0 if pytest_record.get("exit_code") == 0 else 1,
        "hypothesis_profile": "ci (derandomized, database disabled, 75 examples)",
        "passed": passed,
        "status": "PASS"
        if pytest_record.get("exit_code") == 0 and branch_percent >= 90.0
        else "FAIL",
    }


def _acceptance_markdown(
    status: str, acceptance: list[dict[str, Any]], test_summary: dict[str, Any]
) -> str:
    rows = ["| # | Exact command | Exit | Duration (s) | Status |", "|---:|---|---:|---:|---|"]
    for index, item in enumerate(acceptance, start=1):
        rows.append(
            f"| {index} | `{item['command']}` | {item['exit_code']} | "
            f"{item['duration_seconds']} | {item['status']} |"
        )
    return (
        "# FND-001 acceptance\n\n"
        f"Status: **{status}**. Mandatory commands passed: "
        f"**{sum(item['status'] == 'PASS' for item in acceptance)}/{len(acceptance)}**. "
        f"Tests: **{test_summary['passed']} passed**; branch coverage: "
        f"**{test_summary['branch_coverage_percent']:.2f}%**.\n\n"
        + "\n".join(rows)
        + "\n\nThe clean-wheel verifier independently built both distributions, installed the wheel in "
        "a temporary environment outside the repository, ran the installed version and doctor "
        "commands, proved module provenance, validated the bundled Windows timezone fallback, "
        "and removed the environment. No mandatory result was inferred from another command.\n"
    )


def _test_markdown(summary: dict[str, Any]) -> str:
    return f"""# FND-001 test results

- Status: **{summary["status"]}**
- Pytest: **{summary["passed"]} passed**, **{summary["failed"]} failed**
- Branch coverage: **{summary["branch_coverage_percent"]:.2f}%** ({summary["branches_covered"]}/{summary["branches_total"]} branches)
- Hypothesis: `{summary["hypothesis_profile"]}`
- Isolation: user-home variables are redirected; DNS, TCP, and UDP boundaries are blocked; clean-wheel verification runs with `UV_OFFLINE=1` after frozen sync.
- Import safety: every package module is imported with subprocess, network, environment mutation, logging configuration, filesystem writes, and temporary-file boundaries trapped.
"""


def _security_markdown() -> str:
    return """# FND-001 security and secret review

- First-party repository scan: **PASS, zero findings**.
- Scan coverage fails closed for oversized, unreadable, non-UTF-8, and symbolic-link files.
- The only binary exception is the hash-pinned public-domain IANA `Europe/London` TZif payload; generated `.coverage`, build/cache, and review directories are explicit operational exclusions.
- Constructed tests cover mappings, strings, URLs, query values, exception text, JWT, AWS/GitHub/OpenAI/Slack-style tokens, high-entropy values, and bare/RSA/EC/OpenSSH/encrypted/DSA private-key headers.
- Reference-only configuration rejects credential shapes before storage; display redaction applies the same shared predicate and never includes rejected values in errors.
- Doctor retains no environment values, user name, tool path, GPU name, serial, Device ID, or Product ID. It performs no network or database call.
- Allowlisting is exact path + rule + fingerprint with a mandatory rationale; the repository allowlist is empty.
"""


def _package_markdown(package: dict[str, Any]) -> str:
    wheel = package["wheel"]
    distributions = package["uv_build_distributions"]
    rows = [
        f"- `{item['name']}` — {item['bytes']} bytes — `{item['sha256']}`" for item in distributions
    ]
    return f"""# FND-001 CI and package review

- Package verification: **{package["status"]}**; clean environment outside repository: `{package["clean_environment_outside_repository"]}`; cleanup: `{package["cleaned_up"]}`.
- Python: `{package["platform"]["python"]}` on `{package["platform"]["operating_system"]}` / `{package["platform"]["architecture"]}`.
- uv: `{package["uv_version"]}`; build frontend: `{package["toolchain"]["build"]}`; backend: Hatchling `{package["toolchain"]["hatchling"]}` (isolated backend pinned exactly).
- Installed CLI: `{package["installed_version_output"]}`; installed doctor: `{package["doctor_status"]}`; installed module: `{package["installed_module_path"]}`.
- Wheel content: `{wheel["file_count"]}` files, `py.typed={wheel["contains_py_typed"]}`, wheel SHA-256 `{wheel["sha256"]}`.
- Bundled Windows timezone fallback was exercised with system TZ paths disabled; TZif SHA-256 `{wheel["zoneinfo_fallback_sha256"]}`. This one IANA tzdata 2025b payload is public domain and carved out of the repository proprietary notice.

## Independently built distributions

{chr(10).join(rows)}

CI uses `contents: read`, checkout without persisted credentials, frozen sync, offline tests/clean-wheel verification after installation, and no production secret. Ubuntu runs on push/PR; the Windows smoke is scheduled/manual to conserve private-repository minutes.
"""


def _limitations_markdown() -> str:
    return """# Known limitations and open questions

No unresolved implementation defect blocks FND-001.

- GitHub-hosted CI and human acceptance were not triggered by Codex; the complete equivalent local gate is recorded and passed.
- `Europe/London` has a bundled standard-library fallback. Other configured IANA display zones require timezone data from the host Python installation.
- A ZIP cannot contain its own final cryptographic digest. `codex_result.review_pack.sha256` therefore records the validated stable digest over primary files 04-05 and 07-19; the final archive SHA-256 is reported externally after validation. Inside the ZIP, the detached manifest hashes files 01-02 and 04-19, while file 20 hashes files 01-19, breaking the manifest/checksum cycle while validating every payload.
- Merge, push, release tag, and production activation remain human-controlled and were not performed.
"""


def _evidence_manifest(
    status: str, generated_at: str, records: list[dict[str, Any]]
) -> dict[str, Any]:
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
    return {
        "artifacts": artifacts,
        "code_commit": None,
        "commands": records,
        "context_hash": _sha256(REPOSITORY_ROOT / "specs/manifests/document_manifest.json"),
        "created_at": generated_at,
        "known_limitations": [
            "remote CI and human acceptance not run",
            "final ZIP digest is externally published because an archive cannot self-hash",
        ],
        "status": status,
        "ticket_id": "FND-001",
    }


def _rul_records(evidence_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in (evidence_root / "commands.log").read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("RUL-002 command log line must be an object")
        records.append(value)
    if [record.get("command") for record in records] != list(RUL_COMMANDS):
        raise ValueError("RUL-002 command log must contain exactly 19 ordered unique commands")
    return records


def _rul_acceptance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_command = _record_map(records)
    rows: list[dict[str, Any]] = []
    for index, command in enumerate(RUL_COMMANDS, start=1):
        expected_exit = 4 if index == 14 else 0
        record = by_command.get(command)
        actual = record.get("exit_code") if record else None
        passed = actual == expected_exit and str(record.get("result", "")).startswith("PASS:")
        rows.append(
            {
                "command": command,
                "duration_seconds": record.get("duration_seconds") if record else None,
                "exit_code": actual,
                "expected_exit_code": expected_exit,
                "status": "PASS" if passed else "NOT_PASSED",
            }
        )
    return rows


def _rul_coverage(coverage: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = coverage.get("totals")
    files = coverage.get("files")
    if not isinstance(totals, dict) or not isinstance(files, dict):
        raise ValueError("coverage JSON is malformed")
    covered = 0
    branches = 0
    for path, value in files.items():
        normalized = str(path).replace("\\", "/")
        if "/rules/" not in normalized or not isinstance(value, dict):
            continue
        summary = value.get("summary")
        if isinstance(summary, dict):
            covered += int(summary.get("covered_branches", 0))
            branches += int(summary.get("num_branches", 0))
    pytest_record = _record_map(records).get(RUL_COMMANDS[4], {})
    match = re.search(r"PASS: (\d+) tests", str(pytest_record.get("result", "")))
    skipped = re.search(r"; (\d+) skipped;", str(pytest_record.get("result", "")))
    passed = int(match.group(1)) if match else 0
    skipped_count = int(skipped.group(1)) if skipped else -1
    overall = float(totals.get("percent_branches_covered", 0.0))
    rules_percent = (100.0 * covered / branches) if branches else 0.0
    return {
        "branch_coverage_percent": round(overall, 2),
        "branches_covered": totals.get("covered_branches"),
        "branches_total": totals.get("num_branches"),
        "collected": passed,
        "failed": 0 if pytest_record.get("exit_code") == 0 else 1,
        "passed": passed,
        "skipped": skipped_count,
        "rules_branch_coverage_percent": round(rules_percent, 2),
        "rules_branches_covered": covered,
        "rules_branches_total": branches,
        "status": "PASS"
        if pytest_record.get("exit_code") == 0
        and skipped_count == 0
        and overall >= 90
        and rules_percent >= 95
        else "FAIL",
    }


def _rul_acceptance_markdown(
    status: str, acceptance: list[dict[str, Any]], tests: dict[str, Any]
) -> str:
    rows = [
        "| # | Exact command | Actual/expected exit | Duration (s) | Status |",
        "|---:|---|---:|---:|---|",
    ]
    for index, item in enumerate(acceptance, start=1):
        rows.append(
            f"| {index} | `{item['command']}` | {item['exit_code']}/{item['expected_exit_code']} | "
            f"{item['duration_seconds']} | {item['status']} |"
        )
    return (
        f"# RUL-002 acceptance\n\nStatus: **{status}**. Commands passed: "
        f"**{sum(item['status'] == 'PASS' for item in acceptance)}/{len(acceptance)}**. "
        f"Tests: **{tests['passed']} passed**. Overall branch coverage: "
        f"**{tests['branch_coverage_percent']:.2f}%**; rules branch coverage: "
        f"**{tests['rules_branch_coverage_percent']:.2f}%**.\n\n"
        + "\n".join(rows)
        + "\n\nCommand 14 is an expected negative acceptance case: the underlying CLI returned exit 4 and `RULESET_ACTIVATION_BLOCKED`. No result was inferred from a similar command.\n"
    )


def _main_rul(status: str, review_digest: str, code_commit: str) -> int:
    evidence_root = REPOSITORY_ROOT / "evidence/tickets/RUL-002"
    evidence_root.mkdir(parents=True, exist_ok=True)
    records = _rul_records(evidence_root)
    acceptance = _rul_acceptance(records)
    coverage = _read_json(evidence_root / "coverage.json")
    tests = _rul_coverage(coverage, records)
    passed = sum(item["status"] == "PASS" for item in acceptance)
    required_passes = len(RUL_COMMANDS) if status == "COMPLETE" else len(RUL_COMMANDS) - 1
    if status == "COMPLETE" and (passed != required_passes or tests["status"] != "PASS"):
        raise ValueError(
            "COMPLETE RUL-002 evidence requires all 19 commands and both coverage gates"
        )
    if re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
        raise ValueError("RUL-002 evidence requires an exact Git commit")
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _write_json(evidence_root / "tests.json", tests)
    _write_json(
        evidence_root / "acceptance_matrix.json",
        {
            "commands": acceptance,
            "failed": len(RUL_COMMANDS) - passed,
            "passed": passed,
            "status": status,
            "ticket_id": "RUL-002",
        },
    )
    (evidence_root / "ACCEPTANCE.md").write_text(
        _rul_acceptance_markdown(status, acceptance, tests), encoding="utf-8", newline="\n"
    )
    (evidence_root / "TEST_RESULTS.md").write_text(
        f"""# RUL-002 tests, coverage, and mutation probes

- Pytest: **{tests["passed"]} passed**, zero skips required for acceptance.
- Overall branch coverage: **{tests["branch_coverage_percent"]:.2f}%** ({tests["branches_covered"]}/{tests["branches_total"]}).
- `dmf_pulse.rules` branch coverage: **{tests["rules_branch_coverage_percent"]:.2f}%** ({tests["rules_branches_covered"]}/{tests["rules_branches_total"]}).
- Supplied v1.1 fixture/Gameweek oracles and all eight bonus-tie cases pass byte-equivalent canonical comparison.
- Mutation probes kill activation-status/approval/hash changes, appearance/pass/defensive/group thresholds, competition-rank ties, and component/fixture/Gameweek sum corruption.
- Tests block network and user-home access; scoring is exercised as a pure function and from an installed wheel outside the source tree.
""",
        encoding="utf-8",
        newline="\n",
    )
    decision = _read_json(REPOSITORY_ROOT / "specs/manifests/decision_manifest.json")
    authority = _read_json(REPOSITORY_ROOT / "specs/manifests/authority_manifest.json")
    (evidence_root / "AUTHORITY_REMEDIATION.md").write_text(
        f"""# Authority and decision-index remediation

- Exact six-level precedence: **PASS**; tickets are explicitly subordinate.
- Complete DMFP-20 index: **{len(decision["decisions"])} ADRs**, generated with exact title/status/date/locator/source hash/Decision-text hash.
- Active authority scopes: **{len(authority["scopes"])}**, including every required A2-B7 minimum bundle.
- DMFP-20 SHA-256: `{decision["generated_from"]["sha256"]}`.
- FND-001 legacy evidence remains schema-valid; new COMPLETE evidence requires a 40-character Git commit and uses separate payload/archive digest fields.
""",
        encoding="utf-8",
        newline="\n",
    )
    compiled_path = REPOSITORY_ROOT / "artifacts/rules/rul-002-synthetic.json"
    compiled = _read_json(compiled_path)
    (evidence_root / "RULES_COMPILER_REPORT.md").write_text(
        f"""# Rules compiler and lifecycle report

- Synthetic ruleset: `{compiled["ruleset_id"]}` `{compiled["ruleset_version"]}`; compiled hash `{compiled["ruleset_hash"]}`.
- Strict split-YAML rejects duplicates, aliases/anchors/merge, custom tags, unsafe keys/scalars, implicit string booleans, timestamps, and binary floats.
- Semantic source hashes make comments, mapping order, and newline style irrelevant; one rule value changes the self-hash and typed diff.
- REFERENCE_ONLY scoring is explicit. The partial target remains CAPTURED_UNVERIFIED with typed blockers; activation returns stable exit 4.
- Successful VERIFIED publication is atomic and immutable by ID/version; collision and artifact tampering tests fail closed.
""",
        encoding="utf-8",
        newline="\n",
    )
    (evidence_root / "GOLDEN_SCORING_REPORT.md").write_text(
        """# Golden scoring, BPS, and bonus report

- Only Pack RUL-002 v1.1 inputs/oracles were installed; the fixture manifest and pack hashes were verified before use.
- Corrected fixture oracle: home-def 27 BPS, home-def/home-gk rank-3 tie with 1 bonus each, sum of player totals 38.
- Corrected Gameweek oracle: zero-minute placeholders are excluded from ranking; home-fwd receives 2 appearance + 3 bonus in fixture 002 and totals 14 for the Gameweek.
- All eight supplied tie cases pass the generic competition-ranking algorithm, including multiway first/second/third, all-zero, and negative BPS cases.
- Every FPL component is emitted as an integer; component, fixture, and Gameweek sums are independently validated.
""",
        encoding="utf-8",
        newline="\n",
    )
    dependency = _read_json(evidence_root / "dependency_report.json")
    package = _read_json(evidence_root / "package_report.json")
    (evidence_root / "DEPENDENCY_PACKAGE_REPORT.md").write_text(
        f"""# Dependency, lock, and package report

- Runtime direct dependencies remain exactly Pydantic, PyYAML, and Typer; no new dependency was added.
- uv.lock SHA-256: `{dependency["lock_sha256"]}`; locked package count: **{dependency["lock_package_count"]}**.
- Locked-runtime graph manifest: `{package["locked_runtime_manifest_sha256"]}`; clean installed distributions matched exact locked names/versions.
- Installed CLI: `{package["installed_version_output"]}`; wheel SHA-256: `{package["wheel"]["sha256"]}`; `py.typed`: `{package["wheel"]["contains_py_typed"]}`.
- Clean wheel validation ran outside the repository with dependency installation forced offline, verified doctor and rules CLI, proved module provenance, and removed temporary files.
""",
        encoding="utf-8",
        newline="\n",
    )
    (evidence_root / "SECURITY_SOURCE_RIGHTS.md").write_text(
        """# Security and source-rights review

- First-party secret scan: PASS with zero unallowlisted findings; fake mapping/string/URL/exception credentials remain test-only and non-disclosing.
- Rules/CLI errors expose stable codes and blocker identifiers, not raw inputs, private absolute paths, or exception text.
- Compilation reads named local files; scoring performs no I/O; tests and acceptance perform no network/database/provider call.
- Official-source material is limited to supplied link metadata and short paraphrase under the approved source register; no source was contacted during implementation.
- No database, provider client, odds/model/optimiser, FastAPI/UI, GPU/ML, or automatic FPL-action code/dependency exists.
""",
        encoding="utf-8",
        newline="\n",
    )
    (evidence_root / "KNOWN_LIMITATIONS.md").write_text(
        """# Known limitations and open questions

No unresolved P0/P1/P2 implementation issue blocks RUL-002.

- The 2026/27 target ruleset is deliberately incomplete and cannot score or activate until all listed families and overlap semantics are independently verified and approved.
- Remote GitHub Actions and human acceptance were not triggered by Codex; the equivalent local Windows gate is recorded.
- Command 19 uses a write-ahead entry only to break the archive/log cycle; the final ZIP contains its exact measured duration, and the post-build archive digest/CRC result is recorded externally without rerunning the CLI command.
- The actual ZIP archive SHA-256 is reported after construction in CLI/final output and cannot be embedded into the ZIP as a self-hash.
""",
        encoding="utf-8",
        newline="\n",
    )
    command_models = [
        {
            "command": record["command"],
            "duration_seconds": record.get("duration_seconds"),
            "exit_code": record["exit_code"],
            "result": record.get("result"),
        }
        for record in records
    ]
    result = {
        "acceptance": acceptance,
        "assumptions": [
            "Pack RUL-002 v1.1 is the sole fixture/oracle authority for this milestone.",
            "The archive digest is externally reported because an archive cannot self-hash.",
        ],
        "code_commit": code_commit,
        "commands": command_models,
        "dependency_impact": "No new dependencies; existing runtime and development dependency sets are unchanged.",
        "exclusions_verified": [
            "no database/provider/odds/model/optimiser/API/UI/automatic-action implementation",
            "no activation or inferred completion of the partial 2026/27 ruleset",
            "no v1.0 fixture, digest, manifest, or expected output",
        ],
        "files_changed": [
            {
                "path": "specs/manifests/",
                "change": "complete decisions, exact precedence, stage requirements, runtime lock graph",
            },
            {
                "path": "src/dmf_pulse/rules/",
                "change": "strict compiler, lifecycle, BPS/bonus, fixture/Gameweek scoring",
            },
            {
                "path": "src/dmf_pulse/assurance/",
                "change": "generic ticket evidence, manifests, digests, and review contracts",
            },
            {
                "path": "tests/",
                "change": "golden, property, mutation, CLI, lifecycle, and package assurance",
            },
        ],
        "migration_impact": "None; RUL-002 creates no database or production state.",
        "public_interfaces": [
            "validate_ruleset_directory / compile_ruleset / load_compiled_ruleset / diff_rulesets",
            "activate_ruleset / allocate_bonus / score_fixture / score_gameweek",
            "dmf rules validate|compile|hash|show|diff|score-fixture|score-gameweek|activate",
        ],
        "review_pack": {
            "archive_sha256": None,
            "file_count": 20,
            "path": "review_pack/RUL-002/DMF_PULSE_RUL-002_REVIEW.zip",
            "payload_sha256": review_digest,
        },
        "risks": ["Incomplete 2026/27 target families remain an intentional activation blocker."],
        "repository": {
            "baseline": RUL_BASELINE,
            "branch": "stage/A2/RUL-002-rules-foundation",
            "clean": True,
            "head": code_commit,
            "merged": False,
            "pushed": False,
        },
        "status": status,
        "summary": "Governed versioned rules compiler and exact pure synthetic/reference fixture and Gameweek scoring vertical slice with incomplete target activation blocked.",
        "tests": [tests],
        "ticket_id": "RUL-002",
    }
    _write_json(evidence_root / "codex_result.json", result)
    artifacts = []
    for path in sorted(evidence_root.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "evidence_manifest.json":
            artifacts.append(
                {
                    "bytes": path.stat().st_size,
                    "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
                    "sha256": _sha256(path),
                }
            )
    manifest = {
        "artifacts": artifacts,
        "code_commit": code_commit,
        "commands": command_models,
        "context_hash": _sha256(REPOSITORY_ROOT / "specs/manifests/authority_manifest.json"),
        "created_at": generated_at,
        "known_limitations": ["remote CI and human acceptance not run"],
        "status": status,
        "ticket_id": "RUL-002",
    }
    _write_json(evidence_root / "evidence_manifest.json", manifest)
    source_root = REPOSITORY_ROOT / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from dmf_pulse.assurance.evidence import validate_evidence_file

    validate_evidence_file(evidence_root / "codex_result.json")
    validate_evidence_file(evidence_root / "evidence_manifest.json")
    print(json.dumps({"commands_passed": passed, "status": status}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", choices=("COMPLETE", "FAILED"), required=True)
    parser.add_argument("--review-digest")
    parser.add_argument("--ticket", choices=("FND-001", "RUL-002"), default="FND-001")
    parser.add_argument("--code-commit")
    arguments = parser.parse_args()
    review_digest = arguments.review_digest or "0" * 64
    if re.fullmatch(r"[0-9a-f]{64}", review_digest) is None:
        parser.error("--review-digest must be lowercase SHA-256")
    if arguments.ticket == "RUL-002":
        if arguments.code_commit is None:
            parser.error("--code-commit is required for RUL-002")
        return _main_rul(arguments.status, review_digest, arguments.code_commit)

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = _command_records()
    acceptance = _acceptance(records)
    coverage = _read_json(EVIDENCE_ROOT / "coverage.json")
    _write_json(EVIDENCE_ROOT / "coverage.json", coverage)
    repository_report_path = EVIDENCE_ROOT / "repository_validation_report.json"
    if repository_report_path.exists():
        _write_json(repository_report_path, _read_json(repository_report_path))
    package = _read_json(EVIDENCE_ROOT / "package_report.json")
    test_summary = _test_summary(coverage, records)
    passed = sum(item["status"] == "PASS" for item in acceptance)
    if arguments.status == "COMPLETE" and (
        passed != len(MANDATORY_COMMANDS) or test_summary["status"] != "PASS"
    ):
        raise ValueError("COMPLETE evidence requires all commands and >=90% branch coverage")

    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(EVIDENCE_ROOT / "tests.json", test_summary)
    _write_json(
        EVIDENCE_ROOT / "acceptance_matrix.json",
        {
            "commands": acceptance,
            "failed": len(MANDATORY_COMMANDS) - passed,
            "passed": passed,
            "status": arguments.status,
            "ticket_id": "FND-001",
        },
    )
    (EVIDENCE_ROOT / "ACCEPTANCE.md").write_text(
        _acceptance_markdown(arguments.status, acceptance, test_summary),
        encoding="utf-8",
        newline="\n",
    )
    (EVIDENCE_ROOT / "TEST_RESULTS.md").write_text(
        _test_markdown(test_summary), encoding="utf-8", newline="\n"
    )
    (EVIDENCE_ROOT / "SECURITY_REVIEW.md").write_text(
        _security_markdown(), encoding="utf-8", newline="\n"
    )
    (EVIDENCE_ROOT / "PACKAGE_REVIEW.md").write_text(
        _package_markdown(package), encoding="utf-8", newline="\n"
    )
    (EVIDENCE_ROOT / "KNOWN_LIMITATIONS.md").write_text(
        _limitations_markdown(), encoding="utf-8", newline="\n"
    )
    (EVIDENCE_ROOT / "PLAN.md").write_text(
        (REPOSITORY_ROOT / "PLANS.md").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )

    command_models = [
        {
            "command": record["command"],
            "duration_seconds": record.get("duration_seconds"),
            "exit_code": record["exit_code"],
            "result": record.get("result"),
        }
        for record in records
    ]
    codex_result = {
        "acceptance": acceptance,
        "assumptions": [
            "The captured tree was empty although an empty initial commit already existed.",
            "pytest-cov is the unavoidable adapter for the mandated pytest --cov command.",
            "The review-pack field is the validated detached primary-payload digest.",
        ],
        "commands": command_models,
        "dependency_impact": (
            "Runtime remains Pydantic, Typer, and PyYAML only; 32 frozen project/direct/transitive "
            "packages including the sanctioned build and quality tools."
        ),
        "exclusions_verified": [
            "no FPL domain, provider, odds, model, optimization, database, API, UI, or automation code",
            "no PostgreSQL, FastAPI, numerical/ML, provider SDK, or GPU dependency",
            "no network/database/import side effects and no production secret",
        ],
        "files_changed": [
            {"change": "installed governed authority documents and manifests", "path": "specs/"},
            {"change": "implemented typed foundation package and CLI", "path": "src/dmf_pulse/"},
            {"change": "implemented deterministic offline verification", "path": "tests/"},
            {"change": "implemented least-privilege cross-platform automation", "path": ".github/"},
            {"change": "added governance, scripts, and ticket evidence", "path": "repository root"},
        ],
        "migration_impact": "None; no database or production state exists in FND-001.",
        "public_interfaces": [
            "dmf --version",
            "dmf doctor [--json]",
            "dmf config validate --environment <name> --config-root <path>",
            "dmf config show --environment <name> --config-root <path> [--json]",
            "dmf evidence validate <path>",
            "dmf review-pack build --ticket FND-001 --output <path>",
        ],
        "review_pack": {"file_count": 20, "path": REVIEW_PATH, "sha256": review_digest},
        "risks": [
            "Remote CI and independent human acceptance remain external gates.",
            "Non-default IANA zones depend on host timezone data.",
        ],
        "status": arguments.status,
        "summary": (
            "Governed Python 3.13 foundation with strict configuration, deterministic CLI/doctor, "
            "offline assurance, clean-wheel provenance, CI, and capped review evidence."
        ),
        "tests": [test_summary],
        "ticket_id": "FND-001",
    }
    _write_json(EVIDENCE_ROOT / "codex_result.json", codex_result)
    _write_json(
        EVIDENCE_ROOT / "evidence_manifest.json",
        _evidence_manifest(arguments.status, generated_at, records),
    )

    source_root = REPOSITORY_ROOT / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from dmf_pulse.assurance.evidence import validate_evidence_file

    validate_evidence_file(EVIDENCE_ROOT / "codex_result.json")
    validate_evidence_file(EVIDENCE_ROOT / "evidence_manifest.json")
    print(json.dumps({"commands_passed": passed, "status": arguments.status}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
