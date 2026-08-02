"""ODD-005 review layout, ordering, provenance, and payload-safety tests."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from dmf_pulse.assurance.evidence import ODD_REQUIRED_BASELINE, ODD_REQUIRED_BRANCH
from dmf_pulse.assurance.review_pack import (
    ODD_PACK_MANIFEST_SHA256,
    ODD_PREFERRED_NAMES,
    ODD_REVIEW_ZIP_NAME,
    ReviewPackError,
    build_review_pack,
    validate_review_zip,
)
from dmf_pulse.system.process import ProcessResult


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


class OddGitRunner:
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds in {5, 30}
        if "--abbrev-ref" in command:
            return ProcessResult(return_code=0, stdout=ODD_REQUIRED_BRANCH + "\n")
        if "rev-parse" in command:
            return ProcessResult(return_code=0, stdout="a" * 40 + "\n")
        if "--merges" in command or "--porcelain=v1" in command or "merge-base" in command:
            return ProcessResult(return_code=0, stdout="")
        if "--stat" in command:
            return ProcessResult(return_code=0, stdout="2 files changed, 4 insertions(+)\n")
        if "--name-status" in command:
            return ProcessResult(return_code=0, stdout="A\tsrc/dmf_pulse/markets/models.py\n")
        if "diff" in command:
            return ProcessResult(
                return_code=0,
                stdout=(
                    "diff --git a/src/dmf_pulse/markets/models.py "
                    "b/src/dmf_pulse/markets/models.py\n+"
                    "+source_scale_preserved = True\n"
                ),
            )
        return ProcessResult(return_code=0, stdout="")


class OddCanaryRunner(OddGitRunner):
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        if "diff" in command and "--stat" not in command and "--name-status" not in command:
            marker = "ODD005_RAW_BODY_" + "CANARY_7c4f91"
            return ProcessResult(return_code=0, stdout=f"diff --git a/x b/x\n+{marker}\n")
        return super().run(command, timeout_seconds=timeout_seconds)


class OddStateRunner(OddGitRunner):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        if self.mode == "branch" and "--abbrev-ref" in command:
            return ProcessResult(return_code=0, stdout="wrong-branch\n")
        if self.mode == "head" and "rev-parse" in command and "--abbrev-ref" not in command:
            return ProcessResult(return_code=0, stdout="not-a-commit\n")
        if self.mode == "ancestry" and "merge-base" in command:
            return ProcessResult(return_code=1, stdout="")
        if self.mode == "merge" and "--merges" in command:
            return ProcessResult(return_code=0, stdout="b" * 40 + "\n")
        if self.mode == "dirty" and "--porcelain=v1" in command:
            return ProcessResult(return_code=0, stdout=" M src/example.py\n")
        return super().run(command, timeout_seconds=timeout_seconds)


def _result() -> dict[str, object]:
    return {
        "ticket_id": "ODD-005",
        "status": "FAILED",
        "code_commit": "a" * 40,
        "summary": "Synthetic ODD review fixture.",
        "files_changed": [{"path": "src/example.py", "change": "A"}],
        "public_interfaces": ["dmf ingest odds replay"],
        "commands": [],
        "tests": [],
        "acceptance": [],
        "dependency_impact": "none",
        "migration_impact": "two ordered revisions",
        "assumptions": [],
        "exclusions_verified": ["no live request"],
        "risks": ["synthetic fixture"],
        "repository": {
            "baseline": ODD_REQUIRED_BASELINE,
            "branch": ODD_REQUIRED_BRANCH,
            "clean": True,
            "head": "a" * 40,
            "merged": False,
            "pushed": False,
        },
        "review_pack": {
            "path": "review_pack/ODD-005/DMF_PULSE_ODD-005_REVIEW.zip",
            "file_count": 20,
            "payload_sha256": "0" * 64,
        },
    }


def _fixture(root: Path) -> None:
    evidence = root / "evidence/tickets/ODD-005"
    _write(evidence / "codex_result.json", json.dumps(_result()))
    _write(evidence / "commands.log", "")
    _write(evidence / "acceptance_matrix.json", "{}\n")
    for name in (
        "PUBLIC_CONTRACTS.md",
        "MIGRATION_SCHEMA_REVIEW.md",
        "FPL004_REMEDIATION.md",
        "PROVIDER_CLIENT_QUOTA.md",
        "MARKET_MAPPING_SEMANTICS.md",
        "RIGHTS_RETENTION.md",
        "ASOF_IDEMPOTENCY_CONCURRENCY.md",
        "TESTS_AND_COVERAGE.md",
        "SECURITY_AND_SECRET_REVIEW.md",
        "WHEEL_AND_CLI.md",
        "KNOWN_LIMITATIONS.md",
    ):
        _write(evidence / name, f"# {name}\n\nSynthetic review fixture.\n")
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')


def _write_zip(path: Path, names: Sequence[str], payload: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload[name])


def _built_payload(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    summary = build_review_pack(
        root,
        ticket="ODD-005",
        baseline=ODD_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-08-02T00:00:00Z",
        process_runner=OddGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    return summary.path, payload


def _refresh_odd_ledgers(payload: dict[str, bytes]) -> None:
    manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
    for item in manifest["files"]:
        name = item["name"]
        item["bytes"] = len(payload[name])
        item["sha256"] = hashlib.sha256(payload[name]).hexdigest()
    payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    payload["20_SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in ODD_PREFERRED_NAMES
        if name != "20_SHA256SUMS.txt"
    ).encode()


def _refresh_checksum_only(payload: dict[str, bytes]) -> None:
    payload["20_SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in ODD_PREFERRED_NAMES
        if name != "20_SHA256SUMS.txt"
    ).encode()


@pytest.mark.unit
def test_odd005_review_pack_has_exact_root_layout_and_pack_provenance(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    summary = build_review_pack(
        root,
        ticket="ODD-005",
        baseline=ODD_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-08-02T00:00:00Z",
        process_runner=OddGitRunner(),
    )
    assert summary.file_count == 20
    assert summary.path.name == ODD_REVIEW_ZIP_NAME
    assert validate_review_zip(summary.path).payload_sha256 == summary.payload_sha256
    with zipfile.ZipFile(summary.path) as archive:
        assert tuple(archive.namelist()) == ODD_PREFERRED_NAMES
        file_map = archive.read("04_FILE_CHANGE_MAP.md").decode()
        assert ODD_PACK_MANIFEST_SHA256 in file_map
        assert "62 detached checksums" in file_map


@pytest.mark.unit
def test_odd005_review_validator_rejects_reverse_order_even_with_valid_hashes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    summary = build_review_pack(
        root,
        ticket="ODD-005",
        baseline=ODD_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-08-02T00:00:00Z",
        process_runner=OddGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as source:
        payload = {name: source.read(name) for name in source.namelist()}
    reversed_path = tmp_path / "reversed.zip"
    _write_zip(reversed_path, tuple(reversed(ODD_PREFERRED_NAMES)), payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(reversed_path)
    assert caught.value.code == "REVIEW_PACK_LAYOUT"


@pytest.mark.unit
def test_odd005_review_validator_rejects_symbolic_link_entry(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    summary = build_review_pack(
        root,
        ticket="ODD-005",
        baseline=ODD_REQUIRED_BASELINE,
        output=tmp_path / "out",
        generated_at="2026-08-02T00:00:00Z",
        process_runner=OddGitRunner(),
    )
    with zipfile.ZipFile(summary.path) as source:
        payload = {name: source.read(name) for name in source.namelist()}
    symlink_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink_path, "w") as archive:
        for name in ODD_PREFERRED_NAMES:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (
                (stat.S_IFLNK | 0o777) << 16 if name == "01_REVIEW_INDEX.md" else 0o100644 << 16
            )
            archive.writestr(info, payload[name])
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(symlink_path)
    assert caught.value.code == "REVIEW_PACK_NONREGULAR_ENTRY"


@pytest.mark.unit
def test_odd005_review_assembly_rejects_canary_in_complete_patch(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="ODD-005",
            baseline=ODD_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-02T00:00:00Z",
            process_runner=OddCanaryRunner(),
        )
    assert caught.value.code == "REVIEW_PACK_RAW_PAYLOAD"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "code"),
    (
        ("branch", "REVIEW_BRANCH_INVALID"),
        ("head", "REVIEW_HEAD_INVALID"),
        ("ancestry", "REVIEW_BASELINE_ANCESTRY"),
        ("merge", "REVIEW_HISTORY_INVALID"),
        ("dirty", "REVIEW_TREE_DIRTY"),
    ),
)
def test_odd005_review_assembly_rejects_invalid_git_provenance(
    tmp_path: Path,
    mode: str,
    code: str,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="ODD-005",
            baseline=ODD_REQUIRED_BASELINE,
            output=tmp_path / "out",
            generated_at="2026-08-02T00:00:00Z",
            process_runner=OddStateRunner(mode),
        )
    assert caught.value.code == code


@pytest.mark.unit
def test_odd005_review_assembly_rejects_wrong_baseline(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture(root)
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="ODD-005",
            baseline="0" * 40,
            output=tmp_path / "out",
            generated_at="2026-08-02T00:00:00Z",
            process_runner=OddGitRunner(),
        )
    assert caught.value.code == "BASELINE_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("file_limit", "duplicate", "nested", "archive"))
def test_odd005_review_validator_rejects_unsafe_physical_layout(
    tmp_path: Path,
    mutation: str,
) -> None:
    _source, payload = _built_payload(tmp_path)
    names = list(ODD_PREFERRED_NAMES)
    if mutation == "file_limit":
        names.append("21_EXTRA.txt")
        payload["21_EXTRA.txt"] = b"extra\n"
        expected = "REVIEW_PACK_FILE_LIMIT"
    elif mutation == "duplicate":
        names[1] = names[0]
        expected = "REVIEW_PACK_LAYOUT"
    elif mutation == "nested":
        replaced = names[0]
        names[0] = "nested/01_REVIEW_INDEX.md"
        payload[names[0]] = payload[replaced]
        expected = "REVIEW_PACK_NESTED_PATH"
    else:
        replaced = names[0]
        names[0] = "nested.zip"
        payload[names[0]] = payload[replaced]
        expected = "REVIEW_PACK_NESTED_ARCHIVE"
    target = tmp_path / f"{mutation}.zip"
    if mutation == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            _write_zip(target, names, payload)
    else:
        _write_zip(target, names, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == expected


@pytest.mark.unit
def test_odd005_review_validator_rejects_malformed_zip(tmp_path: Path) -> None:
    target = tmp_path / "malformed.zip"
    target.write_bytes(b"not a ZIP")
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == "REVIEW_ZIP_INVALID"


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("raw", "utf8", "secret", "missing", "metadata"))
def test_odd005_review_validator_rejects_unsafe_or_missing_metadata(
    tmp_path: Path,
    mutation: str,
) -> None:
    _source, payload = _built_payload(tmp_path)
    names = list(ODD_PREFERRED_NAMES)
    if mutation == "raw":
        payload[names[0]] += ("ODD005_RAW_BODY_" + "CANARY_7c4f91").encode()
        expected = "REVIEW_PACK_RAW_PAYLOAD"
    elif mutation == "utf8":
        payload[names[0]] += b"\xff"
        expected = "REVIEW_METADATA_INVALID"
    elif mutation == "secret":
        payload[names[0]] += ("pass" + 'word = "unsafe-review-value-123456"').encode()
        expected = "REVIEW_PACK_SECRET"
    elif mutation == "missing":
        index = names.index("18_CODEX_RESULT.json")
        names[index] = "18_MISSING.txt"
        payload["18_MISSING.txt"] = b"missing result\n"
        expected = "REVIEW_PACK_LAYOUT"
    else:
        payload["18_CODEX_RESULT.json"] = b"{"
        expected = "REVIEW_METADATA_INVALID"
    target = tmp_path / f"{mutation}.zip"
    _write_zip(target, names, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_order",
        "manifest_hash",
        "checksum_order",
        "checksum_hash",
        "status",
        "provenance",
        "payload_digest",
    ),
)
def test_odd005_review_validator_rejects_rehashed_logical_false_success(
    tmp_path: Path,
    mutation: str,
) -> None:
    _source, payload = _built_payload(tmp_path)
    _refresh_odd_ledgers(payload)
    manifest = json.loads(payload["19_ARCHIVE_MANIFEST.json"])
    if mutation == "manifest_order":
        manifest["files"] = list(reversed(manifest["files"]))
        payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        _refresh_checksum_only(payload)
        expected = "REVIEW_MANIFEST_COVERAGE"
    elif mutation == "manifest_hash":
        manifest["files"][0]["sha256"] = "0" * 64
        payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        _refresh_checksum_only(payload)
        expected = "REVIEW_MANIFEST_HASH"
    elif mutation == "checksum_order":
        lines = payload["20_SHA256SUMS.txt"].decode().splitlines()
        payload["20_SHA256SUMS.txt"] = ("\n".join(reversed(lines)) + "\n").encode()
        expected = "REVIEW_CHECKSUM_COVERAGE"
    elif mutation == "checksum_hash":
        lines = payload["20_SHA256SUMS.txt"].decode().splitlines()
        lines[0] = "0" * 64 + lines[0][64:]
        payload["20_SHA256SUMS.txt"] = ("\n".join(lines) + "\n").encode()
        expected = "REVIEW_CHECKSUM_HASH"
    elif mutation == "status":
        manifest["acceptance_status"] = "COMPLETE"
        payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        _refresh_checksum_only(payload)
        expected = "REVIEW_STATUS_MISMATCH"
    elif mutation == "provenance":
        manifest["repository_head"] = "b" * 40
        payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        _refresh_checksum_only(payload)
        expected = "REVIEW_PROVENANCE_MISMATCH"
    else:
        manifest["payload_sha256"] = "0" * 64
        payload["19_ARCHIVE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        _refresh_checksum_only(payload)
        expected = "REVIEW_PAYLOAD_DIGEST"
    target = tmp_path / f"logical-{mutation}.zip"
    _write_zip(target, ODD_PREFERRED_NAMES, payload)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(target)
    assert caught.value.code == expected
