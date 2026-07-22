"""Validate the governed repository and its installed authority manifests."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

DMFP_IDS = {f"DMFP-{index:02d}" for index in range(21)}
ZERO_COST_DMFP_04 = "DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt"
ZERO_COST_DMFP_04_SHA256 = "7a29960e3d6dba3f4ed0b4e0d5819e0d8e2ddbd70b79dcf6376b310b59368b85"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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


def _read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing file: {path.as_posix()}")
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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
    decision_ids: set[str] = set()
    statuses: dict[str, str] = {}
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
        if status not in {"ACCEPTED", "PROVISIONAL"}:
            errors.append(f"{label}: malformed decision status {status!r}")
        elif isinstance(status, str):
            statuses[decision_id] = status
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{label}: summary must be non-empty")
    if statuses.get("ADR-IMPL-002") != "PROVISIONAL":
        errors.append("decision_manifest: ADR-IMPL-002 must remain PROVISIONAL")
    return decision_ids


def _validate_authority_manifest(
    root: Path, document_ids: set[str], decision_ids: set[str], errors: list[str]
) -> None:
    path = root / "specs" / "manifests" / "authority_manifest.json"
    manifest = _read_json(path, errors)
    _expect_manifest_version(manifest.get("manifest_version"), path.as_posix(), errors)
    scopes = manifest.get("scopes")
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
    if runtime_names != {"pydantic", "pyyaml", "typer"}:
        errors.append(f"pyproject.toml: unexpected runtime dependencies: {sorted(runtime_names)}")
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
            if versions != ["0.1.0"]:
                errors.append("src/dmf_pulse/__init__.py must be the sole 0.1.0 version source")

    lock = _read_toml(root / "uv.lock", errors)
    packages = lock.get("package", [])
    locked_names = (
        {str(item.get("name", "")).casefold() for item in packages if isinstance(item, dict)}
        if isinstance(packages, list)
        else set()
    )
    forbidden = {
        "alembic",
        "fastapi",
        "highspy",
        "jax",
        "numpy",
        "numpyro",
        "pandas",
        "polars",
        "psycopg",
        "pymc",
        "pyomo",
        "scipy",
        "sqlalchemy",
        "torch",
    }
    if locked_names & forbidden:
        errors.append(f"uv.lock contains forbidden packages: {sorted(locked_names & forbidden)}")
    if "dmf-pulse" not in locked_names:
        errors.append("uv.lock does not contain the dmf-pulse project")


def _validate_ci_contract(root: Path, errors: list[str]) -> None:
    ci_path = root / ".github/workflows/ci.yml"
    windows_path = root / ".github/workflows/windows-smoke.yml"
    try:
        ci = ci_path.read_text(encoding="utf-8")
        windows = windows_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    required_ci_fragments = (
        "permissions:\n  contents: read",
        "pull_request:",
        "push:",
        "persist-credentials: false",
        "uv sync --all-groups --frozen",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run mypy src/dmf_pulse",
        "uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing",
        "uv build",
        "uv run python scripts/verify_wheel.py",
        "uv run python scripts/validate_repository.py",
        "uv run python scripts/scan_secrets.py",
    )
    for fragment in required_ci_fragments:
        if fragment not in ci:
            errors.append(f"ci.yml missing required contract fragment: {fragment}")
    prohibited = ("pull_request_target:", "contents: write", "${{ secrets.")
    for fragment in prohibited:
        if fragment in ci or fragment in windows:
            errors.append(f"workflow contains prohibited privilege/secret fragment: {fragment}")
    if "workflow_dispatch:" not in windows or "schedule:" not in windows:
        errors.append("windows-smoke.yml must be scheduled and manually dispatchable")
    if "permissions:\n  contents: read" not in windows:
        errors.append("windows-smoke.yml must use contents: read permission")


def _validate_current_manifest(root: Path, errors: list[str]) -> None:
    path = root / "evidence/tickets/FND-001/current_manifest.json"
    if not path.is_file():
        return
    source_root = root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    try:
        from dmf_pulse.assurance.manifests import (
            RepositoryManifest,
            validate_repository_manifest,
        )

        expected = RepositoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
        errors.extend(validate_repository_manifest(root, expected))
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"current manifest is malformed: {type(exc).__name__}")


def _validate_final_evidence(root: Path, errors: list[str]) -> None:
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
    if not isinstance(percent, (int, float)) or percent < 90:
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


def validate_repository(root: Path) -> list[str]:
    """Return deterministic actionable validation errors for ``root``."""

    errors: list[str] = []
    document_ids = _validate_document_manifest(root, errors)
    decision_ids = _validate_decision_manifest(root, errors)
    _validate_authority_manifest(root, document_ids, decision_ids, errors)
    _validate_baseline(root, errors)
    if (root / "pyproject.toml").is_file():
        _validate_package_contract(root, errors)
        _validate_ci_contract(root, errors)
        _validate_current_manifest(root, errors)
        _validate_final_evidence(root, errors)
    return sorted(set(errors))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_repository(root)
    result = {
        "error_count": len(errors),
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }
    report_path = root / "evidence/tickets/FND-001/repository_validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
