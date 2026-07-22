"""Review-pack cap, diff, detached manifest, and tamper tests."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from dmf_pulse.assurance import review_pack as review_pack_module
from dmf_pulse.assurance.review_pack import (
    REVIEW_ZIP_NAME,
    ReviewEntry,
    ReviewPackError,
    build_empty_baseline_diff,
    build_review_pack,
    calculate_review_payload_digest,
    enforce_review_limit,
    validate_review_zip,
)
from dmf_pulse.system.process import ProcessResult


class GitRunner:
    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert timeout_seconds == 5
        if "rev-parse" in command:
            return ProcessResult(return_code=0, stdout="a" * 40 + "\n")
        return ProcessResult(return_code=0, stdout="## test/FND-001\n")


class OneResultRunner:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert "-C" in command
        assert timeout_seconds == 5
        return self.result


def _codex_result(*, status: str = "FAILED") -> dict[str, object]:
    return {
        "ticket_id": "FND-001",
        "status": status,
        "summary": "Fixture foundation complete.",
        "files_changed": [{"path": "src/example.py", "change": "created"}],
        "public_interfaces": ["dmf --version"],
        "commands": [{"command": "pytest", "exit_code": 0}],
        "tests": [{"name": "fixture", "status": "PASS"}],
        "acceptance": [{"name": "fixture", "status": "PASS"}],
        "dependency_impact": "approved only",
        "migration_impact": "none",
        "assumptions": [],
        "exclusions_verified": ["domain logic"],
        "risks": [],
        "review_pack": {
            "path": "review_pack/FND-001/" + REVIEW_ZIP_NAME,
            "file_count": 20,
            "sha256": "0" * 64,
        },
    }


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fixture_repository(root: Path) -> None:
    _write(
        root / "evidence/tickets/FND-001/baseline_manifest.json",
        json.dumps({"repository_empty": True}),
    )
    _write(root / "evidence/tickets/FND-001/codex_result.json", json.dumps(_codex_result()))
    for name, text in {
        "commands.log": "pytest | exit=0\n",
        "TEST_RESULTS.md": "# Tests\n\nPass.\n",
        "ACCEPTANCE.md": "# Acceptance\n\nComplete.\n",
        "DEPENDENCY_REPORT.md": "# Dependencies\n\nApproved.\n",
        "SECURITY_REVIEW.md": "# Security\n\nNo findings.\n",
        "PACKAGE_REVIEW.md": "# Package\n\nClean wheel.\n",
        "KNOWN_LIMITATIONS.md": "None.\n",
    }.items():
        _write(root / "evidence/tickets/FND-001" / name, text)
    _write(root / "docs/adr/ADR-FND-001-TOOLCHAIN.md", "# Toolchain\n\nPython 3.13.\n")
    _write(root / "AGENTS.md", "# Agents\n\nStay in scope.\n")
    _write(root / "pyproject.toml", '[project]\nname = "fixture"\n')
    _write(root / "Makefile", "test:\n\tuv run pytest\n")
    _write(root / ".github/workflows/ci.yml", "name: ci\n")
    _write(root / "src/example.py", "VALUE = 1\n")
    _write(root / "uv.lock", "generated lock noise\n")
    _write(root / ".secret-scan-allowlist.json", '{"entries": [], "version": "1.0"}\n')


@pytest.mark.unit
def test_review_pack_refuses_twenty_one_files() -> None:
    entries = [
        ReviewEntry(name=f"{index:02d}.txt", data=b"x", purpose="test") for index in range(21)
    ]
    with pytest.raises(ReviewPackError) as caught:
        enforce_review_limit(entries)
    assert caught.value.code == "REVIEW_PACK_FILE_LIMIT"


@pytest.mark.unit
def test_review_entries_reject_duplicate_and_nested_names() -> None:
    duplicate = [
        ReviewEntry(name="same.txt", data=b"one", purpose="one"),
        ReviewEntry(name="same.txt", data=b"two", purpose="two"),
    ]
    with pytest.raises(ReviewPackError) as duplicate_error:
        enforce_review_limit(duplicate)
    assert duplicate_error.value.code == "REVIEW_PACK_DUPLICATE_NAME"
    with pytest.raises(ReviewPackError) as nested_error:
        enforce_review_limit([ReviewEntry(name="nested/file.txt", data=b"x", purpose="x")])
    assert nested_error.value.code == "REVIEW_PACK_NESTED_PATH"


@pytest.mark.unit
def test_empty_baseline_diff_includes_authored_file_and_omits_lock(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    (tmp_path / ".coverage").write_bytes(b"sqlite\x00generated")
    (tmp_path / "coverage.xml").write_text("<generated/>\n", encoding="utf-8")
    diff, stat = build_empty_baseline_diff(tmp_path)
    assert "+++ b/src/example.py" in diff
    assert "+VALUE = 1" in diff
    assert "uv.lock" not in diff
    assert ".coverage" not in diff
    assert "coverage.xml" not in diff
    assert "uv.lock" in stat


@pytest.mark.unit
def test_diff_rejects_missing_nonempty_and_binary_baselines(tmp_path: Path) -> None:
    with pytest.raises(ReviewPackError) as missing:
        build_empty_baseline_diff(tmp_path)
    assert missing.value.code == "BASELINE_INVALID"

    _write(
        tmp_path / "evidence/tickets/FND-001/baseline_manifest.json",
        json.dumps({"repository_empty": False}),
    )
    with pytest.raises(ReviewPackError) as nonempty:
        build_empty_baseline_diff(tmp_path)
    assert nonempty.value.code == "BASELINE_DIFF_UNSUPPORTED"

    _write(
        tmp_path / "evidence/tickets/FND-001/baseline_manifest.json",
        json.dumps({"repository_empty": True}),
    )
    binary = tmp_path / "src/binary.py"
    binary.parent.mkdir()
    binary.write_bytes(b"text\x00binary")
    with pytest.raises(ReviewPackError) as prohibited:
        build_empty_baseline_diff(tmp_path)
    assert prohibited.value.code == "BINARY_DIFF_PROHIBITED"


@pytest.mark.unit
def test_full_review_pack_build_validates_and_detects_tamper(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture_repository(root)
    digest = calculate_review_payload_digest(
        root, generated_at="2026-07-22T00:00:00Z", process_runner=GitRunner()
    )
    result_path = root / "evidence/tickets/FND-001/codex_result.json"
    result = _codex_result(status="COMPLETE")
    review_reference = result["review_pack"]
    assert isinstance(review_reference, dict)
    review_reference["sha256"] = digest
    result_path.write_text(json.dumps(result), encoding="utf-8")
    output = tmp_path / "output"
    summary = build_review_pack(
        root,
        ticket="FND-001",
        output=output,
        generated_at="2026-07-22T00:00:00Z",
        process_runner=GitRunner(),
    )
    assert summary.file_count == 20
    assert summary.payload_sha256 == digest
    assert summary.path.name == REVIEW_ZIP_NAME
    assert validate_review_zip(summary.path).sha256 == summary.sha256
    with zipfile.ZipFile(summary.path) as archive:
        assert len(archive.namelist()) == 20
        assert all("/" not in name for name in archive.namelist())

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(summary.path) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            target.writestr(name, data + b"tamper" if name == "16_AGENTS.md" else data)
    with pytest.raises(ReviewPackError) as caught:
        validate_review_zip(tampered)
    assert caught.value.code in {"REVIEW_MANIFEST_HASH", "REVIEW_CHECKSUM_HASH"}


@pytest.mark.unit
def test_builder_rejects_ticket_and_repository_secret(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture_repository(root)
    with pytest.raises(ReviewPackError) as ticket_error:
        build_review_pack(
            root,
            ticket="OTHER",
            output=tmp_path / "out",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=GitRunner(),
        )
    assert ticket_error.value.code == "REVIEW_TICKET_UNSUPPORTED"

    _write(root / "leak.txt", "token=" + "ghp_" + "FakeCredentialValue987654321")
    with pytest.raises(ReviewPackError) as secret_error:
        build_review_pack(
            root,
            ticket="FND-001",
            output=tmp_path / "out",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=GitRunner(),
        )
    assert secret_error.value.code == "REPOSITORY_SECRET"


@pytest.mark.unit
def test_complete_pack_rejects_wrong_primary_payload_digest(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _fixture_repository(root)
    result_path = root / "evidence/tickets/FND-001/codex_result.json"
    result_path.write_text(json.dumps(_codex_result(status="COMPLETE")), encoding="utf-8")
    with pytest.raises(ReviewPackError) as caught:
        build_review_pack(
            root,
            ticket="FND-001",
            output=tmp_path / "out",
            generated_at="2026-07-22T00:00:00Z",
            process_runner=GitRunner(),
        )
    assert caught.value.code == "REVIEW_PAYLOAD_DIGEST"


@pytest.mark.unit
def test_bad_zip_checksum_parser_and_error_object(tmp_path: Path) -> None:
    with pytest.raises(ReviewPackError) as invalid_zip:
        validate_review_zip(tmp_path / "missing.zip")
    assert invalid_zip.value.code == "REVIEW_ZIP_INVALID"
    assert invalid_zip.value.as_error_object()["ok"] is False

    with pytest.raises(ReviewPackError) as malformed:
        review_pack_module._parse_checksums("bad-line")
    assert malformed.value.code == "REVIEW_CHECKSUM_FORMAT"
    digest = "0" * 64
    with pytest.raises(ReviewPackError) as duplicate:
        review_pack_module._parse_checksums(f"{digest}  same.txt\n{digest}  same.txt\n")
    assert duplicate.value.code == "REVIEW_CHECKSUM_DUPLICATE"


@pytest.mark.unit
def test_zip_over_limit_and_layout_fail_before_metadata(tmp_path: Path) -> None:
    over = tmp_path / "over.zip"
    with zipfile.ZipFile(over, "w") as archive:
        for index in range(21):
            archive.writestr(f"{index}.txt", "x")
    with pytest.raises(ReviewPackError) as over_error:
        validate_review_zip(over)
    assert over_error.value.code == "REVIEW_PACK_FILE_LIMIT"

    layout = tmp_path / "layout.zip"
    with zipfile.ZipFile(layout, "w") as archive:
        archive.writestr("wrong.txt", "x")
    with pytest.raises(ReviewPackError) as layout_error:
        validate_review_zip(layout)
    assert layout_error.value.code == "REVIEW_PACK_LAYOUT"


@pytest.mark.unit
def test_git_and_small_review_helper_failure_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_pack_module.shutil, "which", lambda _name: None)
    assert review_pack_module._run_git(tmp_path, ["status"], GitRunner()) == "git unavailable\n"

    monkeypatch.setattr(review_pack_module.shutil, "which", lambda _name: "git")
    timed_out = OneResultRunner(ProcessResult(return_code=None, timed_out=True))
    assert "timed out" in review_pack_module._run_git(tmp_path, ["status"], timed_out)
    failed = OneResultRunner(ProcessResult(return_code=1))
    assert "failed" in review_pack_module._run_git(tmp_path, ["status"], failed)
    invalid_head = OneResultRunner(ProcessResult(return_code=0, stdout="not-a-head\n"))
    assert review_pack_module._repository_head(tmp_path, invalid_head) == "UNAVAILABLE"

    with pytest.raises(ReviewPackError) as missing:
        review_pack_module._required_text(tmp_path, "missing.txt")
    assert missing.value.code == "REVIEW_SOURCE_MISSING"
    assert review_pack_module._entry("x", "no-newline", "test").data.endswith(b"\n")
    with pytest.raises(ReviewPackError) as incomplete:
        review_pack_module._primary_payload_digest({})
    assert incomplete.value.code == "REVIEW_PRIMARY_PAYLOAD"
