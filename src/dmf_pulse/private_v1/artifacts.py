"""Bounded, content-addressed synthetic replay artifacts for private V1."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import BaseModel, ValidationError

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateReplayFile,
    PrivateReplayManifest,
    PrivateV1Decision,
    PrivateV1ExecutionInput,
    seal_replay_manifest,
)

MAX_EXECUTION_INPUT_BYTES = 64 * 1024 * 1024
MAX_REPLAY_MANIFEST_BYTES = 256 * 1024
MAX_DECISION_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 512 * 1024


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PrivateV1Error("DUPLICATE_JSON_KEY", "private input contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise PrivateV1Error("MALFORMED_JSON", "private input is not strict JSON")


def _open_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= int(getattr(os, name, 0))
    return flags


@contextmanager
def _verified_reader(path: Path, *, maximum_bytes: int) -> Iterator[int]:
    descriptor: int | None = None
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise OSError("not a regular file")
        if before.st_size > maximum_bytes:
            raise PrivateV1Error("PAYLOAD_TOO_LARGE", "private input exceeds its byte limit")
        descriptor = os.open(path, _open_flags())
        opened = os.fstat(descriptor)
        after = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not os.path.samestat(before, opened)
            or stat.S_ISLNK(after.st_mode)
            or not os.path.samestat(after, opened)
        ):
            raise OSError("source changed while opening")
        yield descriptor
    except PrivateV1Error:
        raise
    except OSError:
        raise PrivateV1Error("SOURCE_UNAVAILABLE", "private input is unavailable") from None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _read_bytes(path: Path, *, maximum_bytes: int) -> bytes:
    with _verified_reader(path, maximum_bytes=maximum_bytes) as descriptor:
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    body = b"".join(chunks)
    if len(body) > maximum_bytes:
        raise PrivateV1Error("PAYLOAD_TOO_LARGE", "private input exceeds its byte limit")
    return body


def _load_model[ModelT: BaseModel](
    path: Path, model: type[ModelT], *, maximum_bytes: int
) -> ModelT:
    body = _read_bytes(path, maximum_bytes=maximum_bytes)
    try:
        parsed = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
        normalized = json.dumps(
            parsed,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return model.model_validate_json(normalized, strict=True)
    except PrivateV1Error:
        raise
    except (UnicodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
        raise PrivateV1Error("PRIVATE_INPUT_INVALID", "private input failed validation") from None


def load_execution_input(path: Path) -> PrivateV1ExecutionInput:
    return _load_model(
        path,
        PrivateV1ExecutionInput,
        maximum_bytes=MAX_EXECUTION_INPUT_BYTES,
    )


def load_private_input_model[ModelT: BaseModel](
    path: Path,
    model: type[ModelT],
    *,
    maximum_bytes: int = MAX_EXECUTION_INPUT_BYTES,
) -> ModelT:
    """Load one strict bounded operator-owned JSON model without retaining its bytes."""

    return _load_model(path, model, maximum_bytes=maximum_bytes)


def load_replay_manifest(path: Path) -> PrivateReplayManifest:
    return _load_model(
        path,
        PrivateReplayManifest,
        maximum_bytes=MAX_REPLAY_MANIFEST_BYTES,
    )


def load_private_decision(path: Path) -> PrivateV1Decision:
    return _load_model(path, PrivateV1Decision, maximum_bytes=MAX_DECISION_BYTES)


def _file_row(name: str, body: bytes) -> PrivateReplayFile:
    return PrivateReplayFile(
        relative_path=name,
        sha256=hashlib.sha256(body).hexdigest(),
        byte_count=len(body),
    )


def _write_new_file(path: Path, body: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT"):
        flags |= int(getattr(os, name, 0))
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(body):
            offset += os.write(descriptor, body[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_synthetic_replay_bundle(
    execution: PrivateV1ExecutionInput,
    decision: PrivateV1Decision,
    report: str,
    destination: Path,
) -> PrivateReplayManifest:
    """Atomically freeze one synthetic-only replay bundle.

    Real current FPL/manager state is deliberately rejected because the governing current
    source contract denies persistent raw and derived storage.
    """

    if execution.retention_class != "SYNTHETIC_REPLAY_ALLOWED":
        raise PrivateV1Error(
            "REPLAY_RETENTION_FORBIDDEN",
            "current source rights do not permit a persistent replay bundle",
        )
    if decision.lineage.execution_input_sha256 != execution.semantic_sha256:
        raise PrivateV1Error("REPLAY_LINEAGE_MISMATCH", "decision and execution input differ")
    try:
        report_bytes = report.encode("utf-8", errors="strict")
    except UnicodeError:
        raise PrivateV1Error("REPORT_INVALID", "private report is not valid UTF-8") from None
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise PrivateV1Error("PAYLOAD_TOO_LARGE", "private report exceeds its byte limit")
    destination = destination.resolve()
    parent = destination.parent
    if not parent.is_dir() or destination.exists():
        raise PrivateV1Error(
            "REPLAY_DESTINATION_INVALID",
            "replay destination must be a new directory below an existing parent",
        )
    input_bytes = canonical_json_bytes(execution)
    decision_bytes = canonical_json_bytes(decision)
    named = {
        "decision.json": decision_bytes,
        "input.json": input_bytes,
        "report.txt": report_bytes,
    }
    rows = tuple(_file_row(name, body) for name, body in sorted(named.items()))
    provisional = PrivateReplayManifest.model_construct(
        run_id=execution.run_id,
        code_sha=execution.code_sha,
        execution_input_semantic_sha256=execution.semantic_sha256,
        decision_semantic_sha256=decision.semantic_sha256,
        files=rows,
        manifest_sha256="0" * 64,
    )
    manifest = seal_replay_manifest(provisional)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
    try:
        for name, body in named.items():
            _write_new_file(temporary / name, body)
        _write_new_file(temporary / "manifest.json", canonical_json_bytes(manifest))
        os.replace(temporary, destination)
    except (OSError, PrivateV1Error):
        shutil.rmtree(temporary, ignore_errors=True)
        raise PrivateV1Error("REPLAY_WRITE_FAILED", "replay bundle could not be written") from None
    return manifest


def verify_replay_bundle(
    directory: Path,
) -> tuple[
    PrivateReplayManifest,
    PrivateV1ExecutionInput,
    PrivateV1Decision,
    str,
]:
    """Validate exact replay bytes and return typed, path-independent contents."""

    if directory.is_symlink():
        raise PrivateV1Error("REPLAY_BUNDLE_INVALID", "replay bundle is unavailable")
    directory = directory.resolve()
    if not directory.is_dir():
        raise PrivateV1Error("REPLAY_BUNDLE_INVALID", "replay bundle is unavailable")
    try:
        observed_names = tuple(sorted(item.name for item in directory.iterdir()))
    except OSError:
        raise PrivateV1Error("REPLAY_BUNDLE_INVALID", "replay bundle is unavailable") from None
    if observed_names != ("decision.json", "input.json", "manifest.json", "report.txt"):
        raise PrivateV1Error("REPLAY_BUNDLE_INVALID", "replay bundle file set is invalid")
    manifest = load_replay_manifest(directory / "manifest.json")
    expected_names = ("decision.json", "input.json", "report.txt")
    if tuple(item.relative_path for item in manifest.files) != expected_names:
        raise PrivateV1Error("REPLAY_BUNDLE_INVALID", "replay manifest file set is invalid")
    bodies: dict[str, bytes] = {}
    limits = {
        "decision.json": MAX_DECISION_BYTES,
        "input.json": MAX_EXECUTION_INPUT_BYTES,
        "report.txt": MAX_REPORT_BYTES,
    }
    for item in manifest.files:
        body = _read_bytes(directory / item.relative_path, maximum_bytes=limits[item.relative_path])
        if len(body) != item.byte_count or hashlib.sha256(body).hexdigest() != item.sha256:
            raise PrivateV1Error("REPLAY_HASH_MISMATCH", "replay artifact digest does not match")
        bodies[item.relative_path] = body
    execution = load_execution_input(directory / "input.json")
    decision = load_private_decision(directory / "decision.json")
    try:
        report = bodies["report.txt"].decode("utf-8", errors="strict")
    except UnicodeError:
        raise PrivateV1Error("REPLAY_BUNDLE_INVALID", "replay report is not UTF-8") from None
    if (
        execution.run_id != manifest.run_id
        or execution.code_sha != manifest.code_sha
        or execution.semantic_sha256 != manifest.execution_input_semantic_sha256
        or decision.semantic_sha256 != manifest.decision_semantic_sha256
    ):
        raise PrivateV1Error("REPLAY_LINEAGE_MISMATCH", "replay manifest lineage differs")
    return manifest, execution, decision, report


__all__ = [
    "load_execution_input",
    "load_private_decision",
    "load_private_input_model",
    "load_replay_manifest",
    "verify_replay_bundle",
    "write_synthetic_replay_bundle",
]
