#!/usr/bin/env python3
"""Build and verify the deterministic DMF Pulse 2026/27 rules review bundle.

The builder operates only on a checked-out Git commit, records the immutable
implementation parent and reviewed commit, excludes prohibited workspace data,
and verifies both the ZIP container and its internal SHA-256 manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

IMMUTABLE_PARENT = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
DEFAULT_BUNDLE_NAME = "DMF_PULSE_2026_27_RULESET_REVIEW_BUNDLE.zip"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PROHIBITED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "node_modules",
    "dist",
    "build",
    ".coverage",
}
PROHIBITED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".pem", ".key"}
ALWAYS_INCLUDE = (
    "AGENTS.md",
    "README.md",
    "2026_27_RULES_VERIFICATION_REPORT.md",
    "RULESET_READINESS.md",
    "ASSUMPTIONS_AND_DEVIATIONS.md",
    "pyproject.toml",
    "uv.lock",
)
REVIEW_PREFIXES = (
    "rules/",
    "config/rules/",
    "src/dmf_pulse/rules/",
    "tests/unit/rules/",
    "tests/contract/rules/",
    "tests/golden/rules/",
    "tests/property/rules/",
    "tests/integration/rules/",
    "fixtures/rules/",
    "evidence/rules/",
    "evidence/tickets/RUL-002/",
    "evidence/tickets/RUL-2026-27/",
    "docs/rules/",
    "schemas/rules/",
    "scripts/build_ruleset_review_bundle",
    "scripts/validate_ruleset_readiness",
)


class BundleError(RuntimeError):
    """Raised when bundle construction or verification fails."""


@dataclass(frozen=True)
class Assurance:
    bundle_exists: bool
    bundle_bytes: int
    bundle_sha256: str
    sha_file_matches: bool
    archive_test_passed: bool
    manifest_passed: bool
    prohibited_file_count: int
    final_commit: str
    immutable_parent: str
    remote_branch_verified: bool
    status: str
    errors: tuple[str, ...]


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
        raise BundleError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}"
        )
    return result.stdout


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix().lstrip("./")


def _prohibited(path: str) -> bool:
    normal = PurePosixPath(_normalise(path))
    if any(part in PROHIBITED_PARTS for part in normal.parts):
        return True
    return normal.suffix.lower() in PROHIBITED_SUFFIXES


def _tracked_files(root: Path, commit: str) -> set[str]:
    output = _run(root, "git", "ls-tree", "-r", "--name-only", commit)
    return {_normalise(line) for line in output.splitlines() if line.strip()}


def _changed_files(root: Path, parent: str, commit: str) -> list[str]:
    output = _run(root, "git", "diff", "--name-only", "--diff-filter=ACMRT", f"{parent}..{commit}")
    return sorted({_normalise(line) for line in output.splitlines() if line.strip()})


def _selected_files(root: Path, parent: str, commit: str) -> list[str]:
    tracked = _tracked_files(root, commit)
    selected = set(_changed_files(root, parent, commit))
    selected.update(path for path in ALWAYS_INCLUDE if path in tracked)
    selected.update(
        path
        for path in tracked
        if any(path.startswith(prefix) for prefix in REVIEW_PREFIXES)
    )
    return sorted(path for path in selected if path in tracked and not _prohibited(path))


def _git_file(root: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise BundleError(f"unable to read {path!r} at {commit}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def _zip_write(archive: zipfile.ZipFile, name: str, content: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(_normalise(name), FIXED_ZIP_TIME)
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    archive.writestr(info, content, compresslevel=9)


def _generated_documents(root: Path, parent: str, commit: str, files: Sequence[str]) -> dict[str, bytes]:
    branch = _run(root, "git", "branch", "--show-current").strip() or "DETACHED"
    status = _run(root, "git", "status", "--porcelain=v1").strip()
    if status:
        raise BundleError("bundle builder requires a clean working tree")
    diff = _run(root, "git", "diff", "--binary", "--full-index", f"{parent}..{commit}")
    changed = _changed_files(root, parent, commit)
    identities = {
        "schema_version": "dmf-rules-review-identities-v1",
        "repository": "sebgreenhalgh/dmf-pulse",
        "branch": branch,
        "immutable_parent": parent,
        "final_commit": commit,
    }
    readme = f"""# DMF Pulse 2026/27 ruleset independent review\n\nRepository: `sebgreenhalgh/dmf-pulse`\n\nReview branch: `{branch}`\n\nImmutable implementation parent: `{parent}`\n\nReviewed commit: `{commit}`\n\nProduction status: **NOT ACTIVE**\n\nHuman approval status: **PENDING_HUMAN_APPROVAL**\n\n## Review order\n\n1. Read `COMMIT_IDENTITIES.json`, `KNOWN_BLOCKERS.md`, and the readiness reports.\n2. Verify `MANIFEST.sha256`.\n3. Review `FINAL_DIFF.patch` against the immutable parent.\n4. Inspect target rules, compiled/capability artifacts, source provenance, tests, and command evidence.\n5. Re-run the repository-prescribed validation commands from the checked-out reviewed commit.\n6. Treat any approval or ACTIVE assertion as a critical defect.\n\nThe bundle is an independent-review handoff only. It does not authorise activation or merge.\n"""
    blocker_text = (
        "# Known blockers\n\n"
        "Production activation remains blocked until explicit Sebastian Greenhalgh human approval "
        "is supplied through the repository activation contract. Any temporally unavailable "
        "post-match official reconciliation remains recorded in the committed readiness evidence.\n"
    )
    return {
        "README_REVIEW.md": readme.encode(),
        "COMMIT_IDENTITIES.json": (json.dumps(identities, indent=2, sort_keys=True) + "\n").encode(),
        "CHANGED_FILES.txt": ("\n".join(changed) + "\n").encode(),
        "INCLUDED_FILES.txt": ("\n".join(files) + "\n").encode(),
        "FINAL_DIFF.patch": diff.encode(),
        "KNOWN_BLOCKERS.md": blocker_text.encode(),
    }


def _manifest(entries: dict[str, bytes]) -> bytes:
    lines = [f"{_sha256_bytes(content)}  {name}" for name, content in sorted(entries.items())]
    return ("\n".join(lines) + "\n").encode()


def _verify_archive(path: Path, expected_commit: str) -> tuple[bool, bool, int, list[str]]:
    errors: list[str] = []
    archive_ok = False
    manifest_ok = False
    prohibited: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                errors.append(f"archive CRC failure: {bad}")
            else:
                archive_ok = True
            names = archive.namelist()
            prohibited = [name for name in names if _prohibited(name)]
            if prohibited:
                errors.append(f"prohibited archive members: {prohibited}")
            if "MANIFEST.sha256" not in names:
                errors.append("MANIFEST.sha256 missing")
            else:
                manifest_lines = archive.read("MANIFEST.sha256").decode("utf-8").splitlines()
                manifest_errors: list[str] = []
                for line in manifest_lines:
                    if not line.strip():
                        continue
                    try:
                        expected, member = line.split("  ", 1)
                    except ValueError:
                        manifest_errors.append(f"malformed manifest line: {line!r}")
                        continue
                    if member not in names:
                        manifest_errors.append(f"manifest member missing: {member}")
                        continue
                    actual = _sha256_bytes(archive.read(member))
                    if actual != expected:
                        manifest_errors.append(f"manifest digest mismatch: {member}")
                if not manifest_errors:
                    manifest_ok = True
                else:
                    errors.extend(manifest_errors)
            identities = json.loads(archive.read("COMMIT_IDENTITIES.json"))
            if identities.get("final_commit") != expected_commit:
                errors.append("bundle final_commit does not match requested commit")
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"archive verification error: {exc}")
    return archive_ok, manifest_ok, len(prohibited), errors


def build(root: Path, output_dir: Path, parent: str, commit: str, bundle_name: str) -> Assurance:
    errors: list[str] = []
    root = root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    actual_commit = _run(root, "git", "rev-parse", f"{commit}^{{commit}}").strip()
    actual_parent = _run(root, "git", "rev-parse", f"{parent}^{{commit}}").strip()
    if actual_parent != IMMUTABLE_PARENT:
        raise BundleError(f"immutable parent mismatch: {actual_parent}")
    merge_base = _run(root, "git", "merge-base", actual_parent, actual_commit).strip()
    if merge_base != actual_parent:
        raise BundleError("reviewed commit is not descended from the immutable parent")

    files = _selected_files(root, actual_parent, actual_commit)
    entries = _generated_documents(root, actual_parent, actual_commit, files)
    for path in files:
        entries[f"repository/{path}"] = _git_file(root, actual_commit, path)
    entries["MANIFEST.sha256"] = _manifest(entries)

    bundle = output_dir / bundle_name
    temporary = bundle.with_suffix(bundle.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
        for name, content in sorted(entries.items()):
            executable = name.startswith("repository/scripts/") and content.startswith(b"#!")
            _zip_write(archive, name, content, executable)
    os.replace(temporary, bundle)

    digest = _sha256_file(bundle)
    sha_path = bundle.with_suffix(bundle.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {bundle.name}\n", encoding="utf-8", newline="\n")
    sha_file_matches = sha_path.read_text(encoding="utf-8").split()[0] == _sha256_file(bundle)
    archive_ok, manifest_ok, prohibited_count, verify_errors = _verify_archive(bundle, actual_commit)
    errors.extend(verify_errors)
    status = "PASS" if bundle.is_file() and bundle.stat().st_size > 0 and sha_file_matches and archive_ok and manifest_ok and prohibited_count == 0 and not errors else "FAIL"
    assurance = Assurance(
        bundle_exists=bundle.is_file(),
        bundle_bytes=bundle.stat().st_size if bundle.is_file() else 0,
        bundle_sha256=digest if bundle.is_file() else "",
        sha_file_matches=sha_file_matches,
        archive_test_passed=archive_ok,
        manifest_passed=manifest_ok,
        prohibited_file_count=prohibited_count,
        final_commit=actual_commit,
        immutable_parent=actual_parent,
        remote_branch_verified=False,
        status=status,
        errors=tuple(errors),
    )
    assurance_path = output_dir / "DMF_PULSE_2026_27_RULESET_BUNDLE_ASSURANCE.json"
    assurance_path.write_text(json.dumps(asdict(assurance), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if status != "PASS":
        raise BundleError(f"bundle assurance failed; see {assurance_path}")
    return assurance


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--parent", default=IMMUTABLE_PARENT)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--bundle-name", default=DEFAULT_BUNDLE_NAME)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        assurance = build(args.repo_root, args.output_dir, args.parent, args.commit, args.bundle_name)
    except BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(asdict(assurance), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
