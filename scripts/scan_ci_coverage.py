"""Lossless bounded scan transport for the exact generated CI coverage report.

The ordinary scanner runs unchanged. Complete JSON records are never split;
every root field is retained. The original report is restored even if scanning
fails. This script cannot change scanner limits, allowlists or coverage values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from dmf_pulse.assurance.secret_scan import (  # noqa: E402
    EXCLUDED_FILE_NAMES,
    EXCLUDED_PARTS,
    MAX_SCANNED_FILE_BYTES,
)

REPORT = Path("evidence/tickets/GCS-008/coverage.json")
PAGES = Path("evidence/tickets/GCS-008/coverage-secret-scan-pages")
MAX_INPUT_BYTES = 32 * 1024 * 1024
PAGE_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 4096
MAX_PAGES = 128
SCANNER_COMMAND = ["uv", "run", "python", "scripts/scan_secrets.py"]


class TransportError(ValueError):
    """A fixed, nonsecret transport refusal code."""


def require(value: object, code: str) -> None:
    if not value:
        raise TransportError(code)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def encode(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        require(key not in value, "DUPLICATE_COVERAGE_JSON_KEY")
        value[key] = item
    return value


def nonfinite(_value: str) -> Any:
    raise TransportError("NONFINITE_COVERAGE_JSON_NUMBER")


def decode(body: bytes) -> Any:
    return json.loads(body, object_pairs_hook=unique, parse_constant=nonfinite)


def plain(path: Path) -> None:
    for node in (path, *path.parents):
        require(not node.is_symlink() and not node.is_junction(), "REPARSE_SCAN_PATH_DENIED")


def write_new(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    require(path.read_bytes() == body, "SCAN_TRANSPORT_WRITE_CHANGED")


def pages_for(payload: dict[str, Any], limit: int) -> list[bytes]:
    require(512 <= limit <= min(PAGE_BYTES, MAX_SCANNED_FILE_BYTES), "INVALID_SCAN_PAGE_BOUND")
    records = payload.get("files")
    require(
        isinstance(records, dict)
        and 1 <= len(records) <= MAX_RECORDS
        and all(isinstance(k, str) and isinstance(v, dict) for k, v in records.items()),
        "COMPLETE_COVERAGE_FILE_RECORDS_REQUIRED",
    )
    header = {key: value for key, value in payload.items() if key != "files"}
    pages: list[bytes] = []
    current: dict[str, Any] = {}
    total_bytes = 0

    def append(body: bytes) -> None:
        nonlocal total_bytes
        require(
            len(pages) < MAX_PAGES and total_bytes + len(body) <= 2 * MAX_INPUT_BYTES,
            "COVERAGE_SCAN_PAGE_POPULATION_EXCEEDED",
        )
        pages.append(body)
        total_bytes += len(body)

    def page(value: dict[str, Any]) -> bytes:
        return encode(
            {"schema_version": "ci-coverage-scan-page-v1", "header": header, "file_records": value}
        )

    for name, record in records.items():
        candidate = {**current, name: record}
        if len(page(candidate)) > limit:
            require(current, "INDIVIDUAL_COVERAGE_RECORD_EXCEEDS_SCAN_PAGE")
            append(page(current))
            current = {name: record}
            require(len(page(current)) <= limit, "INDIVIDUAL_COVERAGE_RECORD_EXCEEDS_SCAN_PAGE")
        else:
            current = candidate
    append(page(current))
    reconstructed: dict[str, Any] = {}
    for body in pages:
        parsed = decode(body)
        require(encode(parsed["header"]) == encode(header), "COVERAGE_SCAN_HEADER_CHANGED")
        for name, record in parsed["file_records"].items():
            require(name not in reconstructed, "DUPLICATE_SCAN_PAGE_RECORD")
            reconstructed[name] = record
    require(
        encode({**header, "files": reconstructed}) == encode(payload),
        "COVERAGE_SCAN_RECONSTRUCTION_CHANGED",
    )
    return pages


@contextmanager
def coverage_scan_transport(
    root: Path, backup: Path, *, page_bytes: int = PAGE_BYTES
) -> Iterator[dict[str, Any]]:
    """Stage every record for the normal scanner, retaining exact original bytes."""
    root, backup = root.absolute(), backup.absolute()
    require(".." not in root.parts + backup.parts, "AMBIGUOUS_SCAN_PATH_DENIED")
    plain(root)
    plain(backup)
    require(root.is_dir() and backup.parent.is_dir(), "EXISTING_SCAN_DIRECTORIES_REQUIRED")
    require(not backup.is_relative_to(root), "OUTSIDE_CHECKOUT_COVERAGE_BACKUP_REQUIRED")
    report, folder = root / REPORT, root / PAGES
    plain(report)
    plain(folder)
    require(
        not (set(PAGES.parts) & EXCLUDED_PARTS) and "manifest.json" not in EXCLUDED_FILE_NAMES,
        "SCAN_PAGES_MUST_NOT_BE_EXCLUDED",
    )
    identity = report.lstat()
    require(
        stat.S_ISREG(identity.st_mode) and identity.st_size <= MAX_INPUT_BYTES,
        "BOUNDED_REGULAR_COVERAGE_REPORT_REQUIRED",
    )
    original = report.read_bytes()
    require(len(original) <= MAX_INPUT_BYTES, "COVERAGE_REPORT_GREW_BEYOND_BOUND")
    payload = decode(original)
    require(isinstance(payload, dict), "COVERAGE_REPORT_OBJECT_REQUIRED")
    receipt = {
        "schema_version": "ci-coverage-secret-scan-transport-v1",
        "original_sha256": digest(original),
        "original_bytes": len(original),
        "scanner_file_bound_bytes": MAX_SCANNED_FILE_BYTES,
        "semantic_sha256": digest(encode(payload)),
        "transport_used": len(original) > MAX_SCANNED_FILE_BYTES,
        "pages": [],
    }
    if len(original) <= MAX_SCANNED_FILE_BYTES:
        try:
            yield receipt
        finally:
            require(report.read_bytes() == original, "SCANNER_CHANGED_ORIGINAL_COVERAGE")
        return

    bodies = pages_for(payload, page_bytes)
    require(not folder.exists() and not backup.exists(), "CREATE_ONLY_SCAN_TRANSPORT_REQUIRED")
    page_records = [
        {"path": f"page-{i:03d}.json", "bytes": len(body), "sha256": digest(body)}
        for i, body in enumerate(bodies)
    ]
    receipt.update(pages=page_records, file_records=len(payload["files"]))
    manifest = encode(receipt)
    require(len(manifest) <= 65_536, "COVERAGE_SCAN_MANIFEST_EXCEEDS_BOUND")
    folder.mkdir()
    for row, body in zip(page_records, bodies, strict=True):
        write_new(folder / row["path"], body)
    write_new(folder / "manifest.json", manifest)
    write_new(backup, original)
    current = report.lstat()
    require(
        (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino)
        and report.read_bytes() == original,
        "COVERAGE_REPORT_CHANGED_BEFORE_SCAN",
    )
    removed = False
    try:
        report.unlink()
        removed = True
        yield receipt
    finally:
        if removed or not report.exists():
            plain(report)
            require(not report.exists(), "COVERAGE_RESTORATION_PATH_OCCUPIED")
            write_new(report, original)
            report.chmod(stat.S_IMODE(identity.st_mode))
        require(report.read_bytes() == original, "EXACT_COVERAGE_RESTORATION_REQUIRED")
        receipt["restored_original_sha256"] = digest(report.read_bytes())
        require(backup.read_bytes() == original, "COVERAGE_BACKUP_CHANGED")
        require((folder / "manifest.json").read_bytes() == manifest, "SCAN_MANIFEST_CHANGED")
        require(
            all(
                (folder / row["path"]).read_bytes() == body
                for row, body in zip(page_records, bodies, strict=True)
            ),
            "SCAN_PAGE_CHANGED",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained-original", type=Path, required=True)
    parser.add_argument("scanner_command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = arguments.scanner_command
    if command[:1] == ["--"]:
        command = command[1:]
    require(command == SCANNER_COMMAND, "ONLY_UNCHANGED_FIRST_PARTY_SCANNER_COMMAND_ALLOWED")
    uv = shutil.which("uv")
    require(uv is not None, "PINNED_CI_UV_COMMAND_UNAVAILABLE")
    with coverage_scan_transport(REPOSITORY_ROOT, arguments.retained_original) as receipt:
        result = subprocess.run(
            [uv, *SCANNER_COMMAND[1:]],
            cwd=REPOSITORY_ROOT,
            stdin=subprocess.DEVNULL,
            timeout=180,
            check=False,
        )
    print(json.dumps({**receipt, "scanner_actual_exit_code": result.returncode}, sort_keys=True))
    return result.returncode if result.returncode >= 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TransportError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_code": str(error)
                    if isinstance(error, TransportError)
                    else "CI_COVERAGE_SECRET_SCAN_FAILED",
                    "exception_family": type(error).__name__,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(2) from None
