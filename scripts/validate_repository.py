"""Validate the governed repository and its installed authority manifests."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

DMFP_IDS = {f"DMFP-{index:02d}" for index in range(21)}
ZERO_COST_DMFP_04 = "DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt"
ZERO_COST_DMFP_04_SHA256 = "7a29960e3d6dba3f4ed0b4e0d5819e0d8e2ddbd70b79dcf6376b310b59368b85"
STAGE_AUTHORITY_SHA256 = "d26605207bec6650f1452836c9fde2e627e6eccc1a8ba3dc30eb56c8e026dae2"
DMFP20_RELATIVE = "specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt"
ADR_HEADER = re.compile(r"^(ADR-[A-Z]+-\d{3})\s+[\u2013\u2014-]\s+(.+)$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:\s|$)")
MANIFEST_VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
MANDATORY_ACCEPTANCE_COMMANDS = (
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
CORE_REQUIRED_FILES = (
    ".codex/prompts/implement_foundation.txt",
    ".codex/prompts/review_ticket.txt",
    ".codex/schemas/codex_result.schema.json",
    ".codex/schemas/evidence_manifest.schema.json",
    ".codex/schemas/review_manifest.schema.json",
    ".github/CODEOWNERS",
    ".github/workflows/ci.yml",
    ".github/workflows/windows-smoke.yml",
    ".gitattributes",
    ".python-version",
    "AGENTS.md",
    "CHANGELOG.md",
    "CODE_REVIEW.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "config/base/application.yaml",
    "config/environments/development.yaml",
    "config/environments/test.yaml",
    "src/dmf_pulse/__init__.py",
    "src/dmf_pulse/py.typed",
    "tickets/FND-001/ACCEPTANCE.md",
    "tickets/FND-001/DEFINITION_OF_READY.md",
    "tickets/FND-001/ticket.yaml",
    "tickets/RUL-002/ACCEPTANCE.md",
    "tickets/RUL-002/ticket.yaml",
    "tickets/DAT-003/ACCEPTANCE.md",
    "tickets/DAT-003/DEFINITION_OF_READY.md",
    "tickets/DAT-003/ticket.yaml",
    "specs/manifests/stage_authority_requirements.json",
    "specs/manifests/runtime_lock_manifest.json",
    "src/dmf_pulse/rules/__init__.py",
    "src/dmf_pulse/cli/rules_cmd.py",
    "src/dmf_pulse/data_model/__init__.py",
    "src/dmf_pulse/database/__init__.py",
    "compose.test.yaml",
    "alembic.ini",
    ".codex/schemas/as_of_result.schema.json",
    ".codex/schemas/database_doctor.schema.json",
    ".codex/schemas/schema_manifest.schema.json",
    "uv.lock",
)
FINAL_EVIDENCE_FILES = (
    "evidence/tickets/FND-001/ACCEPTANCE.md",
    "evidence/tickets/FND-001/DEPENDENCY_REPORT.md",
    "evidence/tickets/FND-001/KNOWN_LIMITATIONS.md",
    "evidence/tickets/FND-001/PACKAGE_REVIEW.md",
    "evidence/tickets/FND-001/PLAN.md",
    "evidence/tickets/FND-001/SECURITY_REVIEW.md",
    "evidence/tickets/FND-001/TEST_RESULTS.md",
    "evidence/tickets/FND-001/acceptance_matrix.json",
    "evidence/tickets/FND-001/codex_result.json",
    "evidence/tickets/FND-001/commands.log",
    "evidence/tickets/FND-001/coverage.json",
    "evidence/tickets/FND-001/current_manifest.json",
    "evidence/tickets/FND-001/dependency_report.json",
    "evidence/tickets/FND-001/evidence_manifest.json",
    "evidence/tickets/FND-001/package_report.json",
    "evidence/tickets/FND-001/repository_validation_report.json",
    "evidence/tickets/FND-001/tests.json",
)
RUL_MANDATORY_ACCEPTANCE_COMMANDS = (
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
    "uv run dmf review-pack build --ticket RUL-002 --baseline 12049a7de23a4a8fcca3d219dbcab1bf5e1027ea --output review_pack/RUL-002",
)
RUL_FINAL_EVIDENCE_FILES = (
    "evidence/tickets/RUL-002/ACCEPTANCE.md",
    "evidence/tickets/RUL-002/AUTHORITY_REMEDIATION.md",
    "evidence/tickets/RUL-002/DEPENDENCY_PACKAGE_REPORT.md",
    "evidence/tickets/RUL-002/GOLDEN_SCORING_REPORT.md",
    "evidence/tickets/RUL-002/KNOWN_LIMITATIONS.md",
    "evidence/tickets/RUL-002/RULES_COMPILER_REPORT.md",
    "evidence/tickets/RUL-002/SECURITY_SOURCE_RIGHTS.md",
    "evidence/tickets/RUL-002/TEST_RESULTS.md",
    "evidence/tickets/RUL-002/acceptance_matrix.json",
    "evidence/tickets/RUL-002/codex_result.json",
    "evidence/tickets/RUL-002/commands.log",
    "evidence/tickets/RUL-002/coverage.json",
    "evidence/tickets/RUL-002/current_manifest.json",
    "evidence/tickets/RUL-002/dependency_report.json",
    "evidence/tickets/RUL-002/evidence_manifest.json",
    "evidence/tickets/RUL-002/package_report.json",
    "evidence/tickets/RUL-002/repository_validation_report.json",
    "evidence/tickets/RUL-002/tests.json",
)


def _read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except FileNotFoundError:
        errors.append(f"missing file: {path.as_posix()}")
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"malformed JSON: {path.as_posix()}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected JSON object: {path.as_posix()}")
        return {}
    return value


def _safe_repository_path(
    root: Path, raw_path: object, label: str, errors: list[str]
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(f"{label}: path must be a non-empty string")
        return None
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label}: path escapes repository: {raw_path}")
        return None
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_dmfp20_decisions(source_bytes: bytes) -> list[dict[str, object]]:
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    lines = source_bytes.decode("utf-8").splitlines()
    headers = [
        (index, match) for index, line in enumerate(lines) if (match := ADR_HEADER.match(line))
    ]
    decisions: list[dict[str, object]] = []
    for position, (start, match) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        block = lines[start:end]
        status_line = next((line for line in block if line.startswith("Status: ")), None)
        date_line = next((line for line in block if line.startswith("Decision date: ")), None)
        marker = block.index("Decision:") if "Decision:" in block else -1
        if status_line is None or date_line is None or marker < 0:
            raise ValueError(f"incomplete ADR block {match.group(1)}")
        decision_lines: list[str] = []
        for line in block[marker + 1 :]:
            if line == "Reason:":
                break
            decision_lines.append(line)
        decision_text = "\n".join(decision_lines).strip()
        decisions.append(
            {
                "decision_date": date_line.removeprefix("Decision date: ").strip(),
                "decision_sha256": hashlib.sha256(decision_text.encode("utf-8")).hexdigest(),
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
    return decisions


def _expect_manifest_version(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or MANIFEST_VERSION_PATTERN.fullmatch(value) is None:
        errors.append(f"{label}: malformed manifest_version {value!r}")


def _validate_document_manifest(root: Path, errors: list[str]) -> set[str]:
    path = root / "specs" / "manifests" / "document_manifest.json"
    manifest = _read_json(path, errors)
    _expect_manifest_version(manifest.get("manifest_version"), path.as_posix(), errors)
    raw_documents = manifest.get("documents")
    if not isinstance(raw_documents, list):
        errors.append(f"{path.as_posix()}: documents must be an array")
        return set()

    document_ids: set[str] = set()
    filenames: set[str] = set()
    for index, raw_document in enumerate(raw_documents):
        label = f"document_manifest.documents[{index}]"
        if not isinstance(raw_document, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        document_id = raw_document.get("document_id")
        filename = raw_document.get("filename")
        version = raw_document.get("version")
        status = raw_document.get("status")
        expected_bytes = raw_document.get("bytes")
        expected_hash = raw_document.get("sha256")
        if not isinstance(document_id, str) or not document_id:
            errors.append(f"{label}: missing document_id")
            continue
        if document_id in document_ids:
            errors.append(f"{label}: duplicate document_id {document_id}")
        document_ids.add(document_id)
        if not isinstance(filename, str) or not filename:
            errors.append(f"{label}: missing filename")
            continue
        if filename in filenames:
            errors.append(f"{label}: duplicate filename {filename}")
        filenames.add(filename)
        if not isinstance(version, str) or VERSION_PATTERN.match(version) is None:
            errors.append(f"{label}: malformed version {version!r}")
        if not isinstance(status, str) or not status.strip():
            errors.append(f"{label}: malformed status {status!r}")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            errors.append(f"{label}: bytes must be a non-negative integer")
        if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
            errors.append(f"{label}: malformed SHA-256 {expected_hash!r}")

        if document_id in DMFP_IDS:
            installed_path = root / "specs" / "approved" / filename
        elif document_id == "DMF-PULSE-CODEX-PLAYBOOK":
            installed_path = root / "docs" / "implementation" / filename
        else:
            errors.append(f"{label}: unexpected document_id {document_id}")
            continue
        if not installed_path.is_file():
            errors.append(
                f"{label}: installed file missing: {installed_path.relative_to(root).as_posix()}"
            )
            continue
        actual_bytes = installed_path.stat().st_size
        actual_hash = _sha256(installed_path)
        if isinstance(expected_bytes, int) and actual_bytes != expected_bytes:
            errors.append(
                f"{label}: byte mismatch for {filename}: expected {expected_bytes}, got {actual_bytes}"
            )
        if isinstance(expected_hash, str) and actual_hash != expected_hash:
            errors.append(
                f"{label}: hash mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
            )

    expected_ids = DMFP_IDS | {"DMF-PULSE-CODEX-PLAYBOOK"}
    if document_ids != expected_ids:
        missing = sorted(expected_ids - document_ids)
        unexpected = sorted(document_ids - expected_ids)
        if missing:
            errors.append(f"document_manifest: missing document IDs: {', '.join(missing)}")
        if unexpected:
            errors.append(f"document_manifest: unexpected document IDs: {', '.join(unexpected)}")

    dmfp_04_files = sorted((root / "specs" / "approved").glob("DMFP-04*"))
    if [item.name for item in dmfp_04_files] != [ZERO_COST_DMFP_04]:
        errors.append(
            "approved DMFP-04 must be the sole zero-paid-subscription v1.0 file; found: "
            + ", ".join(item.name for item in dmfp_04_files)
        )
    elif _sha256(dmfp_04_files[0]) != ZERO_COST_DMFP_04_SHA256:
        errors.append("approved DMFP-04 is not the sanctioned zero-paid-subscription v1.0 hash")
    return document_ids


def _validate_decision_manifest(root: Path, errors: list[str]) -> set[str]:
    path = root / "specs" / "manifests" / "decision_manifest.json"
    manifest = _read_json(path, errors)
    _expect_manifest_version(manifest.get("manifest_version"), path.as_posix(), errors)
    raw_decisions = manifest.get("decisions")
    if not isinstance(raw_decisions, list):
        errors.append(f"{path.as_posix()}: decisions must be an array")
        return set()
    try:
        expected_decisions = _extract_dmfp20_decisions((root / DMFP20_RELATIVE).read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"decision_manifest: DMFP-20 extraction failed: {type(exc).__name__}")
        expected_decisions = []
    if raw_decisions != expected_decisions:
        errors.append(
            "decision_manifest: entries do not exactly match deterministic DMFP-20 extraction"
        )
    decision_ids: set[str] = set()
    statuses: dict[str, str] = {}
    source_path = root / "specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt"
    source_hash = _sha256(source_path) if source_path.is_file() else None
    for index, raw_decision in enumerate(raw_decisions):
        label = f"decision_manifest.decisions[{index}]"
        if not isinstance(raw_decision, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        decision_id = raw_decision.get("id")
        status = raw_decision.get("status")
        summary = raw_decision.get("summary")
        if (
            not isinstance(decision_id, str)
            or re.fullmatch(r"ADR-[A-Z]+-\d{3}", decision_id) is None
        ):
            errors.append(f"{label}: malformed decision id {decision_id!r}")
            continue
        if decision_id in decision_ids:
            errors.append(f"{label}: duplicate decision id {decision_id}")
        decision_ids.add(decision_id)
        if not isinstance(status, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", status):
            errors.append(f"{label}: malformed decision status {status!r}")
        elif isinstance(status, str):
            statuses[decision_id] = status
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{label}: summary must be non-empty")
        title = raw_decision.get("title")
        decision_date = raw_decision.get("decision_date")
        decision_hash = raw_decision.get("decision_sha256")
        source = raw_decision.get("source")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{label}: title must be non-empty")
        if (
            not isinstance(decision_date, str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", decision_date) is None
        ):
            errors.append(f"{label}: decision_date must be YYYY-MM-DD")
        if not isinstance(decision_hash, str) or SHA256_PATTERN.fullmatch(decision_hash) is None:
            errors.append(f"{label}: malformed decision_sha256")
        if not isinstance(source, dict):
            errors.append(f"{label}: source must be an object")
        else:
            if (
                source.get("path")
                != "specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt"
            ):
                errors.append(f"{label}: source path must identify DMFP-20")
            if source.get("document_sha256") != source_hash:
                errors.append(f"{label}: source document hash mismatch")
            locator = source.get("locator")
            if not isinstance(locator, str) or decision_id not in locator:
                errors.append(f"{label}: source locator must identify the ADR")
    if len(decision_ids) != 94:
        errors.append(
            f"decision_manifest: expected complete 94-entry DMFP-20 register, got {len(decision_ids)}"
        )
    if statuses.get("ADR-IMPL-002") != "PROVISIONAL":
        errors.append("decision_manifest: ADR-IMPL-002 must remain PROVISIONAL")
    return decision_ids


def _validate_authority_manifest(
    root: Path, document_ids: set[str], decision_ids: set[str], errors: list[str]
) -> None:
    path = root / "specs" / "manifests" / "authority_manifest.json"
    manifest = _read_json(path, errors)
    _expect_manifest_version(manifest.get("manifest_version"), path.as_posix(), errors)
    requirements_path = root / "specs/manifests/stage_authority_requirements.json"
    requirements = _read_json(requirements_path, errors)
    if not requirements_path.is_file() or _sha256(requirements_path) != STAGE_AUTHORITY_SHA256:
        errors.append(
            "stage_authority_requirements.json does not match the pinned v1.1 stage contract"
        )
    if requirements.get("manifest_version") != "2.0":
        errors.append("stage_authority_requirements.json manifest_version must be 2.0")
    required_precedence = requirements.get("precedence")
    if manifest.get("precedence") != required_precedence:
        errors.append("authority_manifest: precedence does not match the exact stage contract")
    if manifest.get("ticket_policy") != requirements.get("ticket_policy"):
        errors.append("authority_manifest: ticket policy does not match the exact stage contract")
    required_scopes = requirements.get("required_scopes")
    scopes = manifest.get("scopes")
    active_scopes: dict[str, dict[str, Any]] = {}
    if not isinstance(scopes, list) or not scopes:
        errors.append(f"{path.as_posix()}: scopes must be a non-empty array")
    else:
        scope_names: set[str] = set()
        for index, raw_scope in enumerate(scopes):
            label = f"authority_manifest.scopes[{index}]"
            if not isinstance(raw_scope, dict):
                errors.append(f"{label}: entry must be an object")
                continue
            scope_name = raw_scope.get("scope")
            if not isinstance(scope_name, str) or not scope_name:
                errors.append(f"{label}: scope must be non-empty")
            elif scope_name in scope_names:
                errors.append(f"{label}: duplicate scope {scope_name}")
            else:
                scope_names.add(scope_name)
                active_scopes[scope_name] = raw_scope
            documents = raw_scope.get("documents")
            decisions = raw_scope.get("decisions")
            if not isinstance(documents, list) or not all(
                isinstance(item, str) for item in documents
            ):
                errors.append(f"{label}: documents must be an array of strings")
            else:
                for document_id in documents:
                    if document_id not in document_ids:
                        errors.append(f"{label}: stale document reference {document_id!r}")
            if not isinstance(decisions, list) or not all(
                isinstance(item, str) for item in decisions
            ):
                errors.append(f"{label}: decisions must be an array of strings")
            else:
                for decision_id in decisions:
                    if decision_id not in decision_ids:
                        errors.append(f"{label}: stale decision reference {decision_id!r}")
        if isinstance(required_scopes, dict):
            for scope_name, minimum in required_scopes.items():
                active = active_scopes.get(scope_name)
                if active is None:
                    errors.append(f"authority_manifest: required scope missing: {scope_name}")
                    continue
                if not isinstance(minimum, dict):
                    errors.append(f"stage authority requirement is malformed: {scope_name}")
                    continue
                for key in ("documents", "decisions"):
                    required_items = minimum.get(key)
                    active_items = active.get(key)
                    if isinstance(required_items, list) and isinstance(active_items, list):
                        if len(active_items) != len(set(active_items)):
                            errors.append(
                                f"authority_manifest: {scope_name} contains duplicate {key}"
                            )
                        omitted = sorted(set(required_items) - set(active_items))
                        if omitted:
                            errors.append(
                                f"authority_manifest: {scope_name} omits required {key}: {', '.join(omitted)}"
                            )
        else:
            errors.append("stage_authority_requirements.json: required_scopes must be an object")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append(f"{path.as_posix()}: sources must be a non-empty array")
        return
    for index, raw_source in enumerate(sources):
        label = f"authority_manifest.sources[{index}]"
        if not isinstance(raw_source, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        document_id = raw_source.get("document_id")
        if document_id is not None and document_id not in document_ids:
            errors.append(f"{label}: stale document reference {document_id!r}")
        candidate = _safe_repository_path(root, raw_source.get("path"), label, errors)
        if candidate is not None and not candidate.is_file():
            errors.append(f"{label}: stale path reference {raw_source.get('path')!r}")

    agents_path = root / "AGENTS.md"
    try:
        agents = agents_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        errors.append("AGENTS.md is unavailable for authority validation")
        return
    expected_precedence = required_precedence if isinstance(required_precedence, list) else []
    authority_section = agents.split("## Authority", maxsplit=1)
    authority_text = (
        authority_section[1].split("\n## ", maxsplit=1)[0] if len(authority_section) == 2 else ""
    )
    actual_precedence = []
    for line in authority_text.splitlines():
        match = re.fullmatch(r"([1-6])\. (.+)\.", line)
        if match:
            actual_precedence.append(match.group(2))
    if actual_precedence != expected_precedence:
        errors.append("AGENTS.md does not preserve the exact six-level authority precedence")
    ticket_policy = requirements.get("ticket_policy")
    if not isinstance(ticket_policy, str) or ticket_policy not in agents:
        errors.append("AGENTS.md does not preserve the exact subordinate ticket policy")


def _validate_baseline(root: Path, errors: list[str]) -> None:
    path = root / "evidence" / "tickets" / "FND-001" / "baseline_manifest.json"
    manifest = _read_json(path, errors)
    _expect_manifest_version(manifest.get("schema_version"), path.as_posix(), errors)
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append(f"{path.as_posix()}: files must be an array")
        return
    paths: list[str] = []
    for index, item in enumerate(files):
        label = f"baseline_manifest.files[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"{label}: path must be non-empty")
        else:
            paths.append(raw_path)
        if not isinstance(item.get("bytes"), int) or item.get("bytes", -1) < 0:
            errors.append(f"{label}: bytes must be a non-negative integer")
        digest = item.get("sha256")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            errors.append(f"{label}: malformed SHA-256")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        errors.append("baseline_manifest: file paths must be unique and sorted")
    if manifest.get("repository_empty") is not (len(files) == 0):
        errors.append("baseline_manifest: repository_empty does not match captured files")


def _read_toml(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing file: {path.relative_to(path.parents[1]).as_posix()}")
        return {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"malformed TOML: {path.as_posix()}: {exc}")
        return {}
    return value


def _dependency_name(requirement: object) -> str:
    if not isinstance(requirement, str):
        return ""
    return re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].casefold()


def _locked_dependency_request(item: object) -> tuple[str, frozenset[str]] | None:
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        return None
    raw_extras = item.get("extra", item.get("extras", []))
    if not isinstance(raw_extras, list) or not all(isinstance(extra, str) for extra in raw_extras):
        raise ValueError(f"locked dependency extras malformed: {item['name']}")
    return item["name"], frozenset(raw_extras)


def _resolve_locked_runtime_graph(
    packages: dict[str, dict[str, Any]], roots: list[object]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, set[str]]]:
    selected_dependencies: dict[str, list[dict[str, Any]]] = {}
    activated_extras: dict[str, set[str]] = {}
    pending = [request for item in roots if (request := _locked_dependency_request(item))]
    while pending:
        name, extras = pending.pop()
        prior_extras = activated_extras.setdefault(name, set())
        if name in selected_dependencies and extras.issubset(prior_extras):
            continue
        prior_extras.update(extras)
        package = packages.get(name)
        if not isinstance(package, dict):
            raise ValueError(f"locked runtime package missing: {name}")
        dependencies = package.get("dependencies", [])
        optional = package.get("optional-dependencies", {})
        if not isinstance(dependencies, list) or not isinstance(optional, dict):
            raise ValueError(f"locked dependencies malformed: {name}")
        expanded = list(dependencies)
        for extra in sorted(prior_extras):
            extra_dependencies = optional.get(extra)
            if not isinstance(extra_dependencies, list):
                raise ValueError(f"locked dependency extra is missing: {name}[{extra}]")
            expanded.extend(extra_dependencies)
        selected_dependencies[name] = expanded
        pending.extend(
            request for item in expanded if (request := _locked_dependency_request(item))
        )
    return selected_dependencies, activated_extras


def _runtime_lock_manifest(lock_path: Path, lock: dict[str, Any]) -> dict[str, object]:
    raw_packages = lock.get("package")
    if not isinstance(raw_packages, list):
        raise ValueError("uv.lock package table is missing")
    packages: dict[str, dict[str, Any]] = {
        item["name"]: item
        for item in raw_packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    project = packages.get("dmf-pulse")
    if not isinstance(project, dict) or not isinstance(project.get("dependencies"), list):
        raise ValueError("uv.lock project runtime dependencies are missing")
    roots = project["dependencies"]
    selected_dependencies, activated_extras = _resolve_locked_runtime_graph(packages, roots)
    selected = set(selected_dependencies)
    records = []
    for name in sorted(selected):
        package = packages[name]
        version = package.get("version")
        dependencies = selected_dependencies[name]
        if not isinstance(version, str):
            raise ValueError(f"locked runtime metadata malformed: {name}")
        records.append(
            {
                "activated_extras": sorted(activated_extras[name]),
                "dependencies": sorted(
                    [
                        {"marker": item.get("marker"), "name": item["name"]}
                        for item in dependencies
                        if isinstance(item, dict)
                        and isinstance(item.get("name"), str)
                        and item["name"] in selected
                    ],
                    key=lambda item: (item["name"], str(item["marker"])),
                ),
                "name": name,
                "version": version,
            }
        )
    return {
        "lock_sha256": _sha256(lock_path),
        "manifest_version": "1.1",
        "packages": records,
        "project": "dmf-pulse",
        "roots": sorted(item["name"] for item in roots if isinstance(item, dict)),
    }


def _validate_package_contract(root: Path, errors: list[str]) -> None:
    for relative in CORE_REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"required repository file missing: {relative}")
    pyproject = _read_toml(root / "pyproject.toml", errors)
    project = pyproject.get("project", {})
    build_system = pyproject.get("build-system", {})
    if not isinstance(project, dict) or not isinstance(build_system, dict):
        errors.append("pyproject.toml: project and build-system must be tables")
        return
    if project.get("name") != "dmf-pulse":
        errors.append("pyproject.toml: project name must be dmf-pulse")
    if project.get("requires-python") != ">=3.13,<3.14":
        errors.append("pyproject.toml: Python compatibility must be >=3.13,<3.14")
    if project.get("license") != "LicenseRef-Proprietary":
        errors.append("pyproject.toml: proprietary LicenseRef-Proprietary is required")
    if build_system.get("build-backend") != "hatchling.build":
        errors.append("pyproject.toml: build backend must be hatchling.build")
    if build_system.get("requires") != ["hatchling==1.31.0"]:
        errors.append("pyproject.toml: isolated build backend must pin hatchling==1.31.0")
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict) or scripts.get("dmf") != "dmf_pulse.cli.app:main":
        errors.append("pyproject.toml: dmf console command is missing or changed")
    dependencies = project.get("dependencies", [])
    runtime_names = (
        {_dependency_name(item) for item in dependencies}
        if isinstance(dependencies, list)
        else set()
    )
    expected_runtime = {"alembic", "psycopg", "pydantic", "pyyaml", "sqlalchemy", "typer"}
    if runtime_names != expected_runtime:
        errors.append(f"pyproject.toml: unexpected runtime dependencies: {sorted(runtime_names)}")
    if isinstance(dependencies, list):
        required_exact = {
            "SQLAlchemy==2.0.51",
            "alembic==1.18.5",
            "psycopg[binary]==3.3.4",
        }
        if not required_exact.issubset(set(dependencies)):
            errors.append(
                "pyproject.toml: DAT-003 database dependencies must use exact approved pins"
            )
    dependency_groups = pyproject.get("dependency-groups", {})
    dev_dependencies = (
        dependency_groups.get("dev", []) if isinstance(dependency_groups, dict) else []
    )
    dev_names = (
        {_dependency_name(item) for item in dev_dependencies}
        if isinstance(dev_dependencies, list)
        else set()
    )
    expected_dev = {
        "build",
        "coverage",
        "hatchling",
        "hypothesis",
        "mypy",
        "pytest",
        "pytest-cov",
        "ruff",
    }
    if dev_names != expected_dev:
        errors.append(f"pyproject.toml: unexpected development dependencies: {sorted(dev_names)}")
    python_version_path = root / ".python-version"
    if python_version_path.is_file():
        try:
            if python_version_path.read_text(encoding="utf-8").strip() != "3.13":
                errors.append(".python-version must contain 3.13")
        except (OSError, UnicodeError):
            errors.append(".python-version must be readable UTF-8")
    version_path = root / "src/dmf_pulse/__init__.py"
    if version_path.is_file():
        try:
            version_source = version_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("src/dmf_pulse/__init__.py must be readable UTF-8")
        else:
            versions = re.findall(
                r'^__version__\s*=\s*"([^"]+)"', version_source, flags=re.MULTILINE
            )
            if versions != ["0.2.0"]:
                errors.append("src/dmf_pulse/__init__.py must be the sole 0.2.0 version source")

    lock_path = root / "uv.lock"
    lock = _read_toml(lock_path, errors)
    packages = lock.get("package", [])
    locked_names = (
        {str(item.get("name", "")).casefold() for item in packages if isinstance(item, dict)}
        if isinstance(packages, list)
        else set()
    )
    forbidden = {
        "fastapi",
        "highspy",
        "jax",
        "numpy",
        "numpyro",
        "pandas",
        "polars",
        "pymc",
        "pyomo",
        "scipy",
        "torch",
    }
    if locked_names & forbidden:
        errors.append(f"uv.lock contains forbidden packages: {sorted(locked_names & forbidden)}")
    if {"sqlite", "pysqlite", "aiosqlite"} & locked_names:
        errors.append("uv.lock contains a prohibited SQLite dependency")
    if "dmf-pulse" not in locked_names:
        errors.append("uv.lock does not contain the dmf-pulse project")
    runtime_manifest = _read_json(root / "specs/manifests/runtime_lock_manifest.json", errors)
    try:
        expected_runtime_manifest = _runtime_lock_manifest(lock_path, lock)
    except (OSError, ValueError) as exc:
        errors.append(f"runtime lock graph cannot be derived: {type(exc).__name__}")
    else:
        if runtime_manifest != expected_runtime_manifest:
            errors.append("runtime_lock_manifest.json does not exactly match the uv.lock graph")


def _validate_dat_repository_contract(root: Path, errors: list[str]) -> None:
    compose_path = root / "compose.test.yaml"
    try:
        compose = compose_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        errors.append("compose.test.yaml must be readable UTF-8")
        return
    required = (
        "postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296",
        "POSTGRES_DB: dmf_pulse_test",
        "POSTGRES_USER: dmf_test",
        "POSTGRES_PASSWORD: changeme",
        "127.0.0.1:${DMF_TEST_POSTGRES_PORT:-55432}:5432",
        "pg_isready -U dmf_test -d dmf_pulse_test",
    )
    for fragment in required:
        if fragment not in compose:
            errors.append(f"compose.test.yaml missing DAT-003 contract fragment: {fragment}")
    prohibited_patterns = (
        re.compile(r"(?:^|\n)\s*(?:from\s+sqlite3\s+import|import\s+sqlite3\b)"),
        re.compile(r"sqlite(?:\+[^:]+)?://", re.IGNORECASE),
        re.compile(r"pytest\.mark\.sqlite\b"),
    )
    prohibited_suffixes = {".db", ".sqlite", ".sqlite3"}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(
            part
            in {
                ".git",
                ".hypothesis",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".venv",
                "review_pack",
                "evidence",
            }
            for part in relative.parts
        ):
            continue
        if path.is_file() and path.suffix.casefold() in prohibited_suffixes:
            errors.append(f"prohibited SQLite file exists: {relative.as_posix()}")
        if not path.is_file() or path.suffix.casefold() not in {".py", ".toml", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        selected_patterns = (
            prohibited_patterns[2:]
            if relative.parts and relative.parts[0] == "tests"
            else prohibited_patterns
        )
        if any(pattern.search(text) for pattern in selected_patterns):
            errors.append(f"prohibited SQLite dependency/driver/test marker: {relative.as_posix()}")


def _validate_ci_contract(root: Path, errors: list[str]) -> None:
    ci_path = root / ".github/workflows/ci.yml"
    windows_path = root / ".github/workflows/windows-smoke.yml"
    try:
        ci = ci_path.read_text(encoding="utf-8")
        windows = windows_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    common_ci_fragments = (
        "permissions:\n  contents: read",
        "pull_request:",
        "push:",
        "persist-credentials: false",
        "uv sync --all-groups --frozen",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run mypy src/dmf_pulse",
        "postgres:18.4-bookworm@sha256:",
        "uv run dmf data-model doctor --json",
        "uv run dmf data-model schema-manifest --json",
        "uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json",
        "uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json",
        "uv build",
        "uv run python scripts/validate_repository.py",
        "uv run python scripts/scan_secrets.py",
    )
    stage_ci_fragments = (
        (
            "uv run python scripts/test_migration_matrix.py --baseline-revision 20260724_0002 --target head",
            'uv run pytest -m "postgres and integration" tests/integration',
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/ODD-005/coverage.json",
            "uv run python scripts/check_odd005_coverage_gates.py",
            "uv run dmf specs validate",
            "uv run dmf ingest odds replay",
            "uv run dmf market observations",
            "uv run python scripts/verify_odd005_wheel.py",
            "uv run python scripts/verify_odd005_acceptance.py",
            "uv run python scripts/generate_odd005_evidence.py --status DRAFT",
            "uv run dmf evidence validate --ticket ODD-005",
        )
        if (root / "tickets/ODD-005/ticket.yaml").is_file()
        else (
            "uv run python scripts/test_migration_matrix.py --baseline-revision 20260723_0001 --target head",
            'uv run pytest -m "postgres or migration" tests/integration',
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/FPL-004/coverage.json",
            "uv run python scripts/check_fpl004_coverage_gates.py",
            "uv run dmf specs validate",
            "uv run dmf ingest fpl validate",
            "uv run python scripts/verify_fpl004_wheel.py",
            "uv run python scripts/verify_fpl004_acceptance.py",
        )
        if (root / "tickets/FPL-004/ticket.yaml").is_file()
        else (
            "uv run alembic upgrade head",
            'uv run pytest -m "postgres or migration"',
            "uv run alembic downgrade base",
            "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/DAT-003/coverage.json",
            "uv run python scripts/check_coverage_gates.py",
            "uv run python scripts/verify_wheel.py",
        )
    )
    required_ci_fragments = (*common_ci_fragments, *stage_ci_fragments)
    for fragment in required_ci_fragments:
        if fragment not in ci:
            errors.append(f"ci.yml missing required contract fragment: {fragment}")
    if "UV_CACHE_DIR:" not in ci or "UV_CACHE_DIR:" not in windows:
        errors.append("workflows must preserve one explicit uv cache across frozen/offline phases")
    prohibited = ("pull_request_target:", "contents: write", "${{ secrets.")
    for fragment in prohibited:
        if fragment in ci or fragment in windows:
            errors.append(f"workflow contains prohibited privilege/secret fragment: {fragment}")
    if "workflow_dispatch:" not in windows or "schedule:" not in windows:
        errors.append("windows-smoke.yml must be scheduled and manually dispatchable")
    if "permissions:\n  contents: read" not in windows:
        errors.append("windows-smoke.yml must use contents: read permission")


def _validate_current_manifest(root: Path, errors: list[str]) -> None:
    source_root = root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from dmf_pulse.assurance.manifests import (
        RepositoryManifest,
        validate_repository_manifest,
    )

    nrm_path = root / "evidence/tickets/NRM-006/current_manifest.json"
    min007f_path = root / "evidence/tickets/MIN-007F/current_manifest.json"
    odd_path = root / "evidence/tickets/ODD-005/current_manifest.json"
    fpl_path = root / "evidence/tickets/FPL-004/current_manifest.json"
    dat_path = root / "evidence/tickets/DAT-003/current_manifest.json"
    active_path = (
        min007f_path
        if min007f_path.is_file()
        else
        nrm_path
        if (root / "tickets/NRM-006/ticket.yaml").is_file()
        else odd_path
        if (root / "tickets/ODD-005/ticket.yaml").is_file()
        else fpl_path
        if (root / "tickets/FPL-004/ticket.yaml").is_file()
        else dat_path
    )
    for path in [active_path] if active_path.is_file() else []:
        try:
            expected = RepositoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
            errors.extend(validate_repository_manifest(root, expected))
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"current manifest is malformed: {type(exc).__name__}")


def _validate_final_evidence(root: Path, errors: list[str]) -> None:
    if (root / "tickets/DAT-003/ticket.yaml").is_file():
        # FND-001 is immutable historical evidence; its dependency/package reports describe
        # the A1 lock and must not be compared to the active DAT-003 lock.
        return
    result_path = root / "evidence/tickets/FND-001/codex_result.json"
    if not result_path.is_file():
        return
    for relative in FINAL_EVIDENCE_FILES:
        if not (root / relative).is_file():
            errors.append(f"final evidence file missing: {relative}")
    source_root = root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    try:
        from dmf_pulse.assurance.evidence import (
            CodexResult,
            EvidenceValidationError,
            ResultStatus,
            validate_evidence_file,
        )

        validated = validate_evidence_file(result_path)
    except (OSError, ValueError, EvidenceValidationError) as exc:
        errors.append(f"codex result evidence is invalid: {type(exc).__name__}")
        return
    if not isinstance(validated.model, CodexResult):
        errors.append("codex result evidence has the wrong contract kind")
        return
    result = validated.model
    if result.status is not ResultStatus.COMPLETE:
        return

    commands_path = root / "evidence/tickets/FND-001/commands.log"
    command_records: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(
            commands_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            value = json.loads(line)
            if not isinstance(value, dict):
                errors.append(f"commands.log line {line_number} must be a JSON object")
                continue
            command_records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"commands.log is malformed: {type(exc).__name__}")
    logged = {
        item.get("command"): item.get("exit_code")
        for item in command_records
        if isinstance(item.get("command"), str)
    }
    result_commands = {item.command: item.exit_code for item in result.commands}
    for command in MANDATORY_ACCEPTANCE_COMMANDS:
        if logged.get(command) != 0:
            errors.append(f"mandatory command is missing or failed in commands.log: {command}")
        if result_commands.get(command) != 0:
            errors.append(f"mandatory command is missing or failed in codex_result: {command}")

    tests = _read_json(root / "evidence/tickets/FND-001/tests.json", errors)
    if tests.get("status") != "PASS" or tests.get("failed") != 0:
        errors.append("tests.json must record PASS with zero failures")
    coverage = _read_json(root / "evidence/tickets/FND-001/coverage.json", errors)
    totals = coverage.get("totals")
    percent = totals.get("percent_branches_covered") if isinstance(totals, dict) else None
    if (
        not isinstance(percent, (int, float))
        or isinstance(percent, bool)
        or not math.isfinite(float(percent))
        or float(percent) < 90
    ):
        errors.append("coverage.json must record at least 90 percent branch coverage")

    acceptance = _read_json(root / "evidence/tickets/FND-001/acceptance_matrix.json", errors)
    if (
        acceptance.get("status") != "COMPLETE"
        or acceptance.get("failed") != 0
        or acceptance.get("passed") != len(MANDATORY_ACCEPTANCE_COMMANDS)
    ):
        errors.append("acceptance_matrix.json must record all 14 mandatory commands passed")

    dependency = _read_json(root / "evidence/tickets/FND-001/dependency_report.json", errors)
    for key, relative in (("lock_sha256", "uv.lock"), ("pyproject_sha256", "pyproject.toml")):
        target = root / relative
        if target.is_file() and dependency.get(key) != _sha256(target):
            errors.append(f"dependency_report.json {key} does not match {relative}")
    packages = dependency.get("packages")
    if not isinstance(packages, list) or dependency.get("lock_package_count") != len(packages):
        errors.append("dependency_report.json package count is inconsistent")

    package = _read_json(root / "evidence/tickets/FND-001/package_report.json", errors)
    wheel = package.get("wheel")
    toolchain = package.get("toolchain")
    distributions = package.get("uv_build_distributions")
    if package.get("status") != "PASS" or package.get("cleaned_up") is not True:
        errors.append("package_report.json must record PASS and temporary cleanup")
    if not isinstance(wheel, dict) or wheel.get("contains_py_typed") is not True:
        errors.append("package_report.json must prove wheel py.typed content")
    if package.get("installed_zoneinfo_fallback") is not True:
        errors.append("package_report.json must prove the installed Windows zoneinfo fallback")
    if not isinstance(toolchain, dict) or toolchain.get("hatchling") != "1.31.0":
        errors.append("package_report.json must record hatchling 1.31.0")
    distribution_names = (
        sorted(
            item.get("name")
            for item in distributions
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
        if isinstance(distributions, list)
        else []
    )
    if distribution_names != ["dmf_pulse-0.1.0-py3-none-any.whl", "dmf_pulse-0.1.0.tar.gz"]:
        errors.append("package_report.json must hash the exact wheel and sdist")
    if result.review_pack.file_count != 20 or result.review_pack.sha256 == "0" * 64:
        errors.append("codex_result review-pack reference must be a non-placeholder 20-file digest")

    evidence_name = "evidence_manifest.json"
    try:
        from dmf_pulse.assurance.evidence import TicketEvidenceManifest

        evidence_validated = validate_evidence_file(
            root / "evidence/tickets/FND-001" / evidence_name
        )
    except EvidenceValidationError as exc:
        errors.append(f"{evidence_name} is invalid: {exc.code}")
        return
    if not isinstance(evidence_validated.model, TicketEvidenceManifest):
        errors.append("evidence_manifest.json has the wrong contract kind")
        return
    evidence_model = evidence_validated.model
    if evidence_model.status != "COMPLETE":
        errors.append("evidence_manifest.json must record COMPLETE")
    artifact_paths = [item.path for item in evidence_model.artifacts]
    if artifact_paths != sorted(artifact_paths) or len(artifact_paths) != len(set(artifact_paths)):
        errors.append("evidence_manifest.json artifact paths must be unique and sorted")
    expected_artifacts = set(FINAL_EVIDENCE_FILES) - {
        "evidence/tickets/FND-001/evidence_manifest.json"
    }
    if not expected_artifacts <= set(artifact_paths):
        errors.append("evidence_manifest.json does not cover every required final evidence file")
    for index, artifact in enumerate(evidence_model.artifacts):
        label = f"evidence_manifest.artifacts[{index}]"
        candidate = _safe_repository_path(root, artifact.path, label, errors)
        if candidate is None:
            continue
        if not candidate.is_file():
            errors.append(f"{label}: artifact file is missing: {artifact.path}")
            continue
        if candidate.stat().st_size != artifact.bytes:
            errors.append(f"{label}: artifact byte mismatch: {artifact.path}")
        if _sha256(candidate) != artifact.sha256:
            errors.append(f"{label}: artifact hash mismatch: {artifact.path}")
    if evidence_model.commands != command_records:
        errors.append("evidence_manifest.json commands do not match commands.log")


def _validate_rul_fixtures(root: Path, errors: list[str]) -> None:
    manifest_path = root / "fixtures/rules/RUL-002/manifest.json"
    manifest = _read_json(manifest_path, errors)
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 23:
        errors.append("RUL-002 v1.1 fixture manifest must contain exactly 23 files")
        return
    seen: set[str] = set()
    for index, item in enumerate(files):
        label = f"RUL-002 fixture manifest files[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        raw_path = item.get("path")
        candidate = _safe_repository_path(root, raw_path, label, errors)
        if not isinstance(raw_path, str) or candidate is None:
            continue
        if raw_path in seen:
            errors.append(f"{label}: duplicate path")
        seen.add(raw_path)
        if not candidate.is_file():
            errors.append(f"{label}: fixture is missing")
            continue
        if candidate.stat().st_size != item.get("bytes"):
            errors.append(f"{label}: byte mismatch")
        if _sha256(candidate) != item.get("sha256"):
            errors.append(f"{label}: hash mismatch")
    expected_oracles = {
        "fixtures/rules/RUL-002/golden_fixture_001.expected.json": "8de33b939110dade145dba5093de4a3f4ee31da32a57358cce9adb58a51a9c54",
        "fixtures/rules/RUL-002/golden_gameweek_001.expected.json": "2cda3ac63666f5091b6b0d170b8c0fc978a7c90c011a8cc52b3dd842577da093",
    }
    for relative, digest in expected_oracles.items():
        if (root / relative).is_file() and _sha256(root / relative) != digest:
            errors.append(f"RUL-002 v1.1 corrected oracle hash mismatch: {relative}")


def _validate_rul_coverage(root: Path, errors: list[str]) -> None:
    coverage_path = root / "evidence/tickets/RUL-002/coverage.json"
    result_exists = (root / "evidence/tickets/RUL-002/codex_result.json").is_file()
    if not result_exists:
        return
    if not coverage_path.is_file():
        errors.append("RUL-002 coverage.json is missing from final evidence")
        return
    coverage = _read_json(coverage_path, errors)
    totals = coverage.get("totals")
    percent = totals.get("percent_branches_covered") if isinstance(totals, dict) else None
    if (
        not isinstance(percent, (int, float))
        or isinstance(percent, bool)
        or not math.isfinite(float(percent))
        or float(percent) < 90
    ):
        errors.append("RUL-002 overall branch coverage must be at least 90 percent")
    files = coverage.get("files")
    rules_covered = rules_total = 0
    if isinstance(files, dict):
        for filename, value in files.items():
            normalized = str(filename).replace("\\", "/")
            if "/dmf_pulse/rules/" not in f"/{normalized}" or not isinstance(value, dict):
                continue
            summary = value.get("summary")
            if isinstance(summary, dict):
                covered = summary.get("covered_branches")
                total = summary.get("num_branches")
                if (
                    isinstance(covered, int)
                    and not isinstance(covered, bool)
                    and isinstance(total, int)
                    and not isinstance(total, bool)
                    and 0 <= covered <= total
                ):
                    rules_covered += covered
                    rules_total += total
    if not rules_total or 100 * rules_covered / rules_total < 95:
        errors.append("RUL-002 rules branch coverage must be at least 95 percent")


def _validate_rul_evidence(root: Path, errors: list[str]) -> None:
    result_path = root / "evidence/tickets/RUL-002/codex_result.json"
    if not result_path.is_file():
        return
    source_root = root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    try:
        from dmf_pulse.assurance.evidence import (
            CodexResult,
            EvidenceValidationError,
            ResultStatus,
            TicketEvidenceManifest,
            validate_evidence_file,
        )

        validated = validate_evidence_file(result_path)
    except (OSError, ValueError, EvidenceValidationError) as exc:
        errors.append(f"RUL-002 codex result evidence is invalid: {type(exc).__name__}")
        return
    if not isinstance(validated.model, CodexResult) or validated.model.ticket_id != "RUL-002":
        errors.append("RUL-002 codex result has the wrong contract kind")
        return
    result = validated.model
    if result.status is not ResultStatus.COMPLETE:
        return
    for relative in RUL_FINAL_EVIDENCE_FILES:
        if not (root / relative).is_file():
            errors.append(f"RUL-002 final evidence file missing: {relative}")
    command_records: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(
            (root / "evidence/tickets/RUL-002/commands.log").read_text("utf-8").splitlines(),
            start=1,
        ):
            value = json.loads(
                line,
                parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
            )
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} is not an object")
            command_records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        errors.append("RUL-002 commands.log is malformed")
        return
    if len(command_records) != len(RUL_MANDATORY_ACCEPTANCE_COMMANDS):
        errors.append("RUL-002 commands.log must contain exactly 19 records")
    if [item.get("command") for item in command_records] != list(RUL_MANDATORY_ACCEPTANCE_COMMANDS):
        errors.append("RUL-002 commands.log must preserve exact command order and uniqueness")
    for index, command in enumerate(RUL_MANDATORY_ACCEPTANCE_COMMANDS, start=1):
        expected_exit = 4 if index == 14 else 0
        record = command_records[index - 1] if index <= len(command_records) else {}
        if set(record) != {"command", "duration_seconds", "exit_code", "result"}:
            errors.append(f"RUL-002 command {index} has an invalid record shape")
        duration = record.get("duration_seconds")
        result_text = record.get("result")
        if record.get("command") != command or record.get("exit_code") != expected_exit:
            errors.append(f"RUL-002 mandatory command missing or wrong exit: {command}")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            errors.append(f"RUL-002 command {index} lacks an exact nonnegative duration")
        if not isinstance(result_text, str) or not result_text.startswith("PASS:"):
            errors.append(f"RUL-002 command {index} lacks an explicit PASS result")
        if index == 14 and "RULESET_ACTIVATION_BLOCKED" not in str(result_text):
            errors.append("RUL-002 command 14 did not retain its exact blocking error code")
    result_commands = [item.model_dump(mode="json") for item in result.commands]
    if result_commands != command_records:
        errors.append("RUL-002 codex result commands do not exactly match commands.log")

    acceptance = _read_json(root / "evidence/tickets/RUL-002/acceptance_matrix.json", errors)
    if (
        acceptance.get("status") != "COMPLETE"
        or acceptance.get("passed") != 19
        or acceptance.get("failed") != 0
    ):
        errors.append("RUL-002 acceptance matrix must record all 19 commands passed")
    acceptance_commands = acceptance.get("commands")
    if not isinstance(acceptance_commands, list) or [
        item.get("command") for item in acceptance_commands if isinstance(item, dict)
    ] != list(RUL_MANDATORY_ACCEPTANCE_COMMANDS):
        errors.append("RUL-002 acceptance matrix command order is invalid")
    tests = _read_json(root / "evidence/tickets/RUL-002/tests.json", errors)
    if tests.get("status") != "PASS" or tests.get("failed") != 0 or tests.get("skipped") != 0:
        errors.append("RUL-002 tests.json must record PASS with zero failures and skips")

    manifest_path = root / "evidence/tickets/RUL-002/evidence_manifest.json"
    try:
        manifest_validated = validate_evidence_file(manifest_path)
    except EvidenceValidationError as exc:
        errors.append(f"RUL-002 evidence manifest is invalid: {exc.code}")
        return
    if (
        not isinstance(manifest_validated.model, TicketEvidenceManifest)
        or manifest_validated.model.ticket_id != "RUL-002"
    ):
        errors.append("RUL-002 evidence manifest has the wrong contract kind")
        return
    evidence_model = manifest_validated.model
    if (
        evidence_model.status != "COMPLETE"
        or evidence_model.code_commit != result.code_commit
        or evidence_model.commands != command_records
        or evidence_model.context_hash != _sha256(root / "specs/manifests/authority_manifest.json")
    ):
        errors.append("RUL-002 evidence manifest provenance is contradictory")
    artifacts = evidence_model.artifacts
    artifact_paths = [artifact.path for artifact in artifacts]
    if artifact_paths != sorted(set(artifact_paths)):
        errors.append("RUL-002 evidence artifact paths must be unique and sorted")
    evidence_root = root / "evidence/tickets/RUL-002"
    actual_paths = sorted(
        path.relative_to(root).as_posix()
        for path in evidence_root.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json"
    )
    if artifact_paths != actual_paths:
        errors.append("RUL-002 evidence manifest must cover every exact evidence artifact")
    required_artifacts = set(RUL_FINAL_EVIDENCE_FILES) - {
        "evidence/tickets/RUL-002/evidence_manifest.json"
    }
    if not required_artifacts <= set(artifact_paths):
        errors.append("RUL-002 evidence manifest omits required final evidence")
    for artifact in artifacts:
        candidate = _safe_repository_path(root, artifact.path, "RUL-002 evidence artifact", errors)
        if candidate is None or not candidate.is_file():
            errors.append(f"RUL-002 evidence artifact missing: {artifact.path}")
        elif candidate.stat().st_size != artifact.bytes or _sha256(candidate) != artifact.sha256:
            errors.append(f"RUL-002 evidence artifact mismatch: {artifact.path}")

    # RUL-002 is immutable historical evidence once DAT-003 is active. Its artifact
    # hashes remain validated above; current branch/worktree state belongs to DAT-003.


def _validate_dat_evidence(root: Path, errors: list[str]) -> None:
    result_path = root / "evidence/tickets/DAT-003/codex_result.json"
    if not result_path.is_file():
        return
    source_root = root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    try:
        from dmf_pulse.assurance.evidence import (
            CodexResult,
            ResultStatus,
            validate_evidence_file,
            validate_ticket_evidence,
        )
        from dmf_pulse.assurance.review_pack import (
            ReviewPackError,
            _validate_dat_complete_evidence,
        )

        if (root / "tickets/FPL-004/ticket.yaml").is_file():
            historical = validate_ticket_evidence(root, "DAT-003")
            if historical.status != "COMPLETE":
                errors.append("DAT-003 historical evidence does not record COMPLETE")
            return

        validated = validate_evidence_file(result_path)
        if not isinstance(validated.model, CodexResult) or validated.model.ticket_id != "DAT-003":
            errors.append("DAT-003 codex result has the wrong evidence kind")
            return
        result = validated.model
        if result.status is not ResultStatus.COMPLETE:
            return
        if result.code_commit is None:
            errors.append("DAT-003 COMPLETE result lacks its code commit")
            return
        _validate_dat_complete_evidence(root, result, result.code_commit)
    except ReviewPackError as exc:
        errors.append(f"DAT-003 final evidence is invalid: {exc.code}")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"DAT-003 final evidence is malformed: {type(exc).__name__}")


def validate_repository(root: Path) -> list[str]:
    """Return deterministic actionable validation errors for ``root``."""

    errors: list[str] = []
    document_ids = _validate_document_manifest(root, errors)
    decision_ids = _validate_decision_manifest(root, errors)
    _validate_authority_manifest(root, document_ids, decision_ids, errors)
    _validate_baseline(root, errors)
    if (root / "pyproject.toml").is_file():
        _validate_rul_fixtures(root, errors)
        _validate_package_contract(root, errors)
        _validate_dat_repository_contract(root, errors)
        _validate_ci_contract(root, errors)
        _validate_current_manifest(root, errors)
        _validate_final_evidence(root, errors)
        _validate_rul_coverage(root, errors)
        _validate_rul_evidence(root, errors)
        _validate_dat_evidence(root, errors)
    return sorted(set(errors))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_repository(root)
    result = {
        "error_count": len(errors),
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }
    active_ticket = (
        "NRM-006"
        if (root / "tickets/NRM-006/ticket.yaml").is_file()
        else "ODD-005"
        if (root / "tickets/ODD-005/ticket.yaml").is_file()
        else "FPL-004"
        if (root / "tickets/FPL-004/ticket.yaml").is_file()
        else "DAT-003"
        if (root / "tickets/DAT-003/ticket.yaml").is_file()
        else "RUL-002"
        if (root / "tickets/RUL-002/ticket.yaml").is_file()
        else "FND-001"
    )
    report_path = (
        root / "evidence" / "tickets" / active_ticket / "repository_validation_report.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
