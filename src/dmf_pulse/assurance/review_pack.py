"""Deterministic capped review-pack construction and detached-manifest validation."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dmf_pulse.assurance.canonical import pretty_json, sha256_file
from dmf_pulse.assurance.evidence import (
    CodexResult,
    ReviewFile,
    ReviewManifest,
    validate_evidence_file,
)
from dmf_pulse.assurance.secret_scan import scan_repository, scan_text
from dmf_pulse.system import ProcessRunner, SubprocessProcessRunner

MAX_REVIEW_FILES: Final = 20
REVIEW_ZIP_NAME: Final = "DMF_PULSE_FND-001_REVIEW.zip"
MANIFEST_NAME: Final = "03_REVIEW_MANIFEST.json"
CHECKSUM_NAME: Final = "20_SHA256SUMS.txt"
PREFERRED_NAMES: Final = (
    "01_REVIEW_INDEX.md",
    "02_CODEX_RESULT.json",
    MANIFEST_NAME,
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "06_GIT_STATUS.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_RESULTS.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_TOOLCHAIN_DECISIONS.md",
    "12_DEPENDENCY_REPORT.md",
    "13_SECURITY_AND_SECRET_REVIEW.md",
    "14_CI_AND_PACKAGE_REVIEW.md",
    "15_KNOWN_LIMITATIONS_AND_OPEN_QUESTIONS.md",
    "16_AGENTS.md",
    "17_PYPROJECT.toml",
    "18_MAKEFILE.txt",
    "19_CI_YML.txt",
    CHECKSUM_NAME,
)
OPERATIONAL_EXCLUDED_PARTS: Final = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".coverage",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "coverage.xml",
    "review_pack",
}
VERBATIM_OR_GENERATED_DIFF_EXCLUSIONS: Final = {
    ".github/CODEOWNERS",
    ".codex/schemas/codex_result.schema.json",
    ".codex/schemas/evidence_manifest.schema.json",
    ".codex/schemas/review_manifest.schema.json",
    "docs/implementation/DMF_PULSE_CODEX_IMPLEMENTATION_PLAYBOOK_v1.txt",
    "specs/manifests/document_manifest.json",
    "tickets/FND-001/ACCEPTANCE.md",
    "tickets/FND-001/ticket.yaml",
    "uv.lock",
    "src/dmf_pulse/_data/zoneinfo/Europe/London",
}


class ReviewPackError(Exception):
    """An actionable review-pack contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error_object(self) -> dict[str, object]:
        return {"error": {"code": self.code, "message": self.message}, "ok": False}


@dataclass(frozen=True, slots=True)
class ReviewEntry:
    """One root-level review file before ZIP assembly."""

    name: str
    data: bytes
    purpose: str


@dataclass(frozen=True, slots=True)
class ReviewPackSummary:
    path: Path
    file_count: int
    sha256: str
    payload_sha256: str


def enforce_review_limit(entries: list[ReviewEntry]) -> None:
    """Reject duplicate, nested, or over-cap entry sets before writing anything."""

    if len(entries) > MAX_REVIEW_FILES:
        raise ReviewPackError(
            "REVIEW_PACK_FILE_LIMIT",
            f"review pack has {len(entries)} files; maximum is {MAX_REVIEW_FILES}",
        )
    names = [entry.name for entry in entries]
    if len(names) != len(set(names)):
        raise ReviewPackError("REVIEW_PACK_DUPLICATE_NAME", "review pack has duplicate names")
    if any(Path(name).name != name or "/" in name or "\\" in name for name in names):
        raise ReviewPackError("REVIEW_PACK_NESTED_PATH", "all review files must be at ZIP root")


def _is_operationally_excluded(path: Path) -> bool:
    return any(part in OPERATIONAL_EXCLUDED_PARTS for part in path.parts)


def _is_human_authored(relative: str) -> bool:
    if relative in VERBATIM_OR_GENERATED_DIFF_EXCLUSIONS:
        return False
    return not (
        relative.startswith("evidence/")
        or relative.startswith("specs/approved/")
        or relative.startswith("review_pack/")
    )


def _repository_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not _is_operationally_excluded(path.relative_to(root))
    ]


def build_empty_baseline_diff(root: Path) -> tuple[str, str]:
    """Build one deterministic new-file unified diff from the captured empty baseline."""

    baseline_path = root / "evidence" / "tickets" / "FND-001" / "baseline_manifest.json"
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewPackError(
            "BASELINE_INVALID", "baseline manifest is unavailable or invalid"
        ) from exc
    if not isinstance(baseline, dict) or baseline.get("repository_empty") is not True:
        raise ReviewPackError(
            "BASELINE_DIFF_UNSUPPORTED",
            "FND-001 deterministic diff requires its captured empty baseline",
        )

    chunks: list[str] = []
    changed_files = 0
    insertions = 0
    for path in _repository_files(root):
        relative = path.relative_to(root).as_posix()
        if not _is_human_authored(relative):
            continue
        try:
            data = path.read_bytes()
            if b"\x00" in data:
                raise UnicodeError
            text = data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReviewPackError(
                "BINARY_DIFF_PROHIBITED",
                f"human-authored diff input is not UTF-8 text: {relative}",
            ) from exc
        lines = text.splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
            [],
            lines,
            fromfile="/dev/null",
            tofile=f"b/{relative}",
            lineterm="\n",
        )
        for line in diff_lines:
            chunks.append(line if line.endswith("\n") else f"{line}\n")
        changed_files += 1
        insertions += len(lines)
    omissions = [
        "uv.lock (generated exact lock; hash/dependency summary in file 12)",
        "approved DMFP corpus and implementation playbook (verbatim governed inputs)",
        "bundled Europe/London TZif fallback (reviewed binary; hash in file 14)",
        "remote-derived CODEOWNERS metadata (installed in repository, omitted for pack privacy)",
        "document manifest and supplied schemas/ticket contracts (verbatim pack inputs)",
        "generated evidence, build outputs, caches, and review output",
    ]
    stat = (
        f"{changed_files} human-authored files changed, {insertions} insertions(+), 0 deletions(-)\n"
        "Omitted from patch:\n" + "".join(f"- {item}\n" for item in omissions)
    )
    return "".join(chunks), stat


def _run_git(root: Path, arguments: list[str], runner: ProcessRunner) -> str:
    executable = shutil.which("git")
    if executable is None:
        return "git unavailable\n"
    result = runner.run([executable, "-C", str(root), *arguments], timeout_seconds=5.0)
    if result.timed_out:
        return "git command timed out\n"
    if result.return_code != 0:
        return "git command failed\n"
    return result.stdout.replace("\r\n", "\n").rstrip() + "\n"


def _repository_head(root: Path, runner: ProcessRunner) -> str:
    value = _run_git(root, ["rev-parse", "--verify", "HEAD"], runner).strip()
    if len(value) == 40 and all(character in "0123456789abcdef" for character in value):
        return value
    return "UNAVAILABLE"


def _file_tree(root: Path) -> str:
    paths = [path.relative_to(root).as_posix() for path in _repository_files(root)]
    return "".join(f"{path}\n" for path in paths)


def _required_text(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as exc:
        raise ReviewPackError(
            "REVIEW_SOURCE_MISSING", f"required review source missing: {relative}"
        ) from exc


def _review_index(status: str, head: str, limitations: str) -> str:
    return f"""# FND-001 review index

DMF Pulse FND-001 built the governed Python 3.13 package, strict configuration/CLI/doctor, first-party assurance, offline tests, exact uv lock, and CI foundation. Acceptance status: **{status}**.

Repository HEAD at review build: `{head}`. The implementation baseline is the captured empty tree at `evidence/tickets/FND-001/baseline_manifest.json`; the existing empty initial commit was not manufactured or rewritten.

Read `02_CODEX_RESULT.json`, `10_ACCEPTANCE_MATRIX.md`, `04_FULL_DIFF.patch`, then the security/package reports. Reproduce with `uv sync --all-groups --frozen` followed by the literal commands in `tickets/FND-001/ACCEPTANCE.md`.

    The detached convention breaks the checksum circularity: `03_REVIEW_MANIFEST.json` hashes files 01-02 and 04-19; `20_SHA256SUMS.txt` hashes files 01-19, including the manifest, and excludes itself. The validator enforces both sets. `02_CODEX_RESULT.json` records a stable digest over primary implementation files 04-05 and 07-19; the actual archive hash is emitted externally because a ZIP cannot contain its own hash.

## Exact unresolved issues

{limitations.rstrip() or "None."}

Command execution and any failure are recorded individually in files 08 and 10. Human acceptance, merge, and tagging remain outside Codex completion.
"""


def _entry(name: str, text: str, purpose: str) -> ReviewEntry:
    normalized = text.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return ReviewEntry(name=name, data=normalized.encode("utf-8"), purpose=purpose)


def _sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


PRIMARY_PAYLOAD_NAMES: Final = {
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_RESULTS.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_TOOLCHAIN_DECISIONS.md",
    "12_DEPENDENCY_REPORT.md",
    "13_SECURITY_AND_SECRET_REVIEW.md",
    "14_CI_AND_PACKAGE_REVIEW.md",
    "15_KNOWN_LIMITATIONS_AND_OPEN_QUESTIONS.md",
    "16_AGENTS.md",
    "17_PYPROJECT.toml",
    "18_MAKEFILE.txt",
    "19_CI_YML.txt",
}


def _primary_payload_digest(payload: dict[str, bytes]) -> str:
    if set(payload) & PRIMARY_PAYLOAD_NAMES != PRIMARY_PAYLOAD_NAMES:
        raise ReviewPackError(
            "REVIEW_PRIMARY_PAYLOAD", "review primary payload coverage is incomplete"
        )
    ledger = "".join(
        f"{_sha256_bytes(payload[name])}  {name}\n" for name in sorted(PRIMARY_PAYLOAD_NAMES)
    )
    return _sha256_bytes(ledger.encode("utf-8"))


def calculate_review_payload_digest(
    root: Path,
    *,
    generated_at: str,
    process_runner: ProcessRunner | None = None,
) -> str:
    """Calculate the stable non-self-referential implementation-payload digest."""

    entries = _assemble_entries(
        root,
        generated_at=generated_at,
        process_runner=process_runner or SubprocessProcessRunner(),
    )
    return _primary_payload_digest({entry.name: entry.data for entry in entries})


def _assemble_entries(
    root: Path,
    *,
    generated_at: str,
    process_runner: ProcessRunner,
) -> list[ReviewEntry]:
    validated = validate_evidence_file(
        root / "evidence" / "tickets" / "FND-001" / "codex_result.json"
    )
    if not isinstance(validated.model, CodexResult):
        raise ReviewPackError(
            "CODEX_RESULT_INVALID", "codex_result.json has the wrong evidence kind"
        )
    result = validated.model
    diff, diff_stat = build_empty_baseline_diff(root)
    head = _repository_head(root, process_runner)
    limitations = _required_text(root, "evidence/tickets/FND-001/KNOWN_LIMITATIONS.md")

    entries = [
        _entry(
            "01_REVIEW_INDEX.md",
            _review_index(result.status.value, head, limitations),
            "review navigation",
        ),
        _entry("02_CODEX_RESULT.json", pretty_json(result), "structured implementation result"),
        _entry("04_FULL_DIFF.patch", diff, "all human-authored implementation changes"),
        _entry("05_DIFF_STAT.txt", diff_stat, "concise diff scope and generated omissions"),
        _entry(
            "06_GIT_STATUS.txt",
            _run_git(root, ["status", "--short", "--branch"], process_runner),
            "Git state",
        ),
        _entry("07_FILE_TREE.txt", _file_tree(root), "current non-operational repository tree"),
        _entry(
            "08_COMMANDS_LOG.txt",
            _required_text(root, "evidence/tickets/FND-001/commands.log"),
            "literal command evidence",
        ),
        _entry(
            "09_TEST_RESULTS.md",
            _required_text(root, "evidence/tickets/FND-001/TEST_RESULTS.md"),
            "test and coverage summary",
        ),
        _entry(
            "10_ACCEPTANCE_MATRIX.md",
            _required_text(root, "evidence/tickets/FND-001/ACCEPTANCE.md"),
            "mandatory acceptance matrix",
        ),
        _entry(
            "11_TOOLCHAIN_DECISIONS.md",
            _required_text(root, "docs/adr/ADR-FND-001-TOOLCHAIN.md"),
            "sanctioned toolchain realization",
        ),
        _entry(
            "12_DEPENDENCY_REPORT.md",
            _required_text(root, "evidence/tickets/FND-001/DEPENDENCY_REPORT.md"),
            "direct/transitive dependency report",
        ),
        _entry(
            "13_SECURITY_AND_SECRET_REVIEW.md",
            _required_text(root, "evidence/tickets/FND-001/SECURITY_REVIEW.md"),
            "security and secret review",
        ),
        _entry(
            "14_CI_AND_PACKAGE_REVIEW.md",
            _required_text(root, "evidence/tickets/FND-001/PACKAGE_REVIEW.md"),
            "CI, build, and clean-wheel review",
        ),
        _entry("15_KNOWN_LIMITATIONS_AND_OPEN_QUESTIONS.md", limitations, "unresolved issues"),
        _entry(
            "16_AGENTS.md",
            _required_text(root, "AGENTS.md"),
            "repository implementation constraints",
        ),
        _entry(
            "17_PYPROJECT.toml",
            _required_text(root, "pyproject.toml"),
            "package and quality configuration",
        ),
        _entry("18_MAKEFILE.txt", _required_text(root, "Makefile"), "optional command aliases"),
        _entry(
            "19_CI_YML.txt", _required_text(root, ".github/workflows/ci.yml"), "required Ubuntu CI"
        ),
    ]
    enforce_review_limit(entries)

    manifest_files = [
        ReviewFile(
            name=item.name,
            sha256=_sha256_bytes(item.data),
            bytes=len(item.data),
            purpose=item.purpose,
        )
        for item in entries
    ]
    manifest = ReviewManifest(
        ticket_id="FND-001",
        generated_at=generated_at,
        repository_head=head,
        baseline="evidence/tickets/FND-001/baseline_manifest.json",
        file_count=MAX_REVIEW_FILES,
        files=manifest_files,
        acceptance_status=result.status,
    )
    manifest_entry = _entry(MANIFEST_NAME, pretty_json(manifest), "detached payload manifest")
    entries.append(manifest_entry)
    entries.sort(key=lambda item: item.name)
    checksum_text = "".join(f"{_sha256_bytes(item.data)}  {item.name}\n" for item in entries)
    entries.append(_entry(CHECKSUM_NAME, checksum_text, "detached checksum ledger"))
    entries.sort(key=lambda item: item.name)
    enforce_review_limit(entries)
    if tuple(item.name for item in entries) != PREFERRED_NAMES:
        raise ReviewPackError(
            "REVIEW_PACK_LAYOUT", "review pack does not match the 20-file contract"
        )
    for item in entries:
        if scan_text(item.data.decode("utf-8"), path=item.name):
            raise ReviewPackError(
                "REVIEW_PACK_SECRET", f"secret-like content detected in {item.name}"
            )
    return entries


def _write_deterministic_zip(path: Path, entries: list[ReviewEntry]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in entries:
            info = zipfile.ZipInfo(entry.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entry.data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_review_pack(
    root: Path,
    *,
    ticket: str,
    output: Path,
    generated_at: str,
    process_runner: ProcessRunner | None = None,
) -> ReviewPackSummary:
    """Build, atomically place, and revalidate the FND-001 review ZIP."""

    if ticket != "FND-001":
        raise ReviewPackError("REVIEW_TICKET_UNSUPPORTED", "only ticket FND-001 is supported")
    repository_findings = scan_repository(root)
    if repository_findings:
        raise ReviewPackError(
            "REPOSITORY_SECRET",
            f"repository secret scan has {len(repository_findings)} finding(s)",
        )
    selected_runner = process_runner or SubprocessProcessRunner()
    entries = _assemble_entries(root, generated_at=generated_at, process_runner=selected_runner)
    payload_sha256 = _primary_payload_digest({entry.name: entry.data for entry in entries})
    result_entry = next(item for item in entries if item.name == "02_CODEX_RESULT.json")
    result = CodexResult.model_validate_json(result_entry.data)
    if result.status.value == "COMPLETE" and result.review_pack.sha256 != payload_sha256:
        raise ReviewPackError(
            "REVIEW_PAYLOAD_DIGEST",
            "codex_result review-pack digest does not match the detached primary payload",
        )
    output_path = output if output.suffix.casefold() == ".zip" else output / REVIEW_ZIP_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_zip: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".dmf-review-", suffix=".tmp", dir=output_path.parent, delete=False
        ) as handle:
            temporary_zip = Path(handle.name)
        _write_deterministic_zip(temporary_zip, entries)
        validate_review_zip(temporary_zip)
        os.replace(temporary_zip, output_path)
        temporary_zip = None
    finally:
        if temporary_zip is not None:
            temporary_zip.unlink(missing_ok=True)
    validate_review_zip(output_path)
    return ReviewPackSummary(
        path=output_path,
        file_count=len(entries),
        sha256=sha256_file(output_path),
        payload_sha256=payload_sha256,
    )


def _parse_checksums(value: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in value.splitlines():
        parts = line.split("  ", maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ReviewPackError("REVIEW_CHECKSUM_FORMAT", "checksum ledger is malformed")
        digest, name = parts
        if name in checksums:
            raise ReviewPackError("REVIEW_CHECKSUM_DUPLICATE", "checksum ledger has duplicates")
        checksums[name] = digest
    return checksums


def validate_review_zip(path: Path) -> ReviewPackSummary:
    """Validate root layout, cap, detached manifest, checksums, hashes, and archive policy."""

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > MAX_REVIEW_FILES:
                raise ReviewPackError(
                    "REVIEW_PACK_FILE_LIMIT",
                    f"review pack has {len(names)} files; maximum is {MAX_REVIEW_FILES}",
                )
            if len(names) != len(set(names)) or tuple(sorted(names)) != PREFERRED_NAMES:
                raise ReviewPackError("REVIEW_PACK_LAYOUT", "review ZIP root layout is invalid")
            if any(Path(name).name != name for name in names):
                raise ReviewPackError("REVIEW_PACK_NESTED_PATH", "review ZIP contains nested paths")
            if any(name.casefold().endswith((".zip", ".tar", ".gz", ".7z")) for name in names):
                raise ReviewPackError(
                    "REVIEW_PACK_NESTED_ARCHIVE", "nested archives are prohibited"
                )
            payload = {name: archive.read(name) for name in names}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReviewPackError(
            "REVIEW_ZIP_INVALID", "review ZIP is unavailable or malformed"
        ) from exc

    try:
        manifest_value = json.loads(payload[MANIFEST_NAME].decode("utf-8"))
        manifest = ReviewManifest.model_validate(manifest_value)
        checksums = _parse_checksums(payload[CHECKSUM_NAME].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPackError("REVIEW_METADATA_INVALID", "review metadata is malformed") from exc
    if manifest.file_count != len(payload):
        raise ReviewPackError("REVIEW_FILE_COUNT_MISMATCH", "manifest file_count is not ZIP count")
    expected_manifest_names = set(payload) - {MANIFEST_NAME, CHECKSUM_NAME}
    if {item.name for item in manifest.files} != expected_manifest_names:
        raise ReviewPackError(
            "REVIEW_MANIFEST_COVERAGE", "detached manifest coverage is incomplete"
        )
    for item in manifest.files:
        if item.bytes != len(payload[item.name]) or item.sha256 != _sha256_bytes(
            payload[item.name]
        ):
            raise ReviewPackError("REVIEW_MANIFEST_HASH", f"manifest mismatch for {item.name}")
    expected_checksum_names = set(payload) - {CHECKSUM_NAME}
    if set(checksums) != expected_checksum_names:
        raise ReviewPackError("REVIEW_CHECKSUM_COVERAGE", "checksum ledger coverage is incomplete")
    for name, digest in checksums.items():
        if digest != _sha256_bytes(payload[name]):
            raise ReviewPackError("REVIEW_CHECKSUM_HASH", f"checksum mismatch for {name}")
    result = CodexResult.model_validate_json(payload["02_CODEX_RESULT.json"])
    payload_sha256 = _primary_payload_digest(payload)
    if result.status.value == "COMPLETE" and result.review_pack.sha256 != payload_sha256:
        raise ReviewPackError(
            "REVIEW_PAYLOAD_DIGEST", "embedded result digest does not match primary payload"
        )
    return ReviewPackSummary(
        path=path,
        file_count=len(payload),
        sha256=sha256_file(path),
        payload_sha256=payload_sha256,
    )
