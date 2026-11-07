"""Review modes preserve separate immutable evidence and refuse overwrite."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def owned_builder(tmp_path, monkeypatch):
    location = Path(__file__).resolve().parents[3] / "tickets/DMF-MODEL-QUALITY-001/build_review.py"
    spec = importlib.util.spec_from_file_location("owned_review_builder", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "tickets/TICKET/build_review.py"))
    head = "1" * 40
    capture_root = tmp_path / "review_pack/dev-checks"
    supplied = capture_root / "full-supplied/receipt.json"
    supplied.parent.mkdir(parents=True)
    receipt = dict(
        tier="FULL",
        status="PASS",
        head=head,
        mandatory_jobs=20,
        event="push",
        workflow_path=".github/workflows/ci.yml",
        ci_run=123,
    )
    supplied.write_text(json.dumps(receipt))

    def run(args, **kwargs):
        if args[0] != "git":
            assert args[-3:] == ["full", "--ci-run", "123"]
            capture = capture_root / "full-reauthenticated"
            capture.mkdir()
            (capture / "receipt.json").write_text(json.dumps(receipt))
            (capture / "ci.json").write_text(json.dumps({"owned": True, "headSha": head}))
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"status": "PASS", "head": head}).encode(), b""
            )
        if args[1:3] == ["rev-parse", "HEAD"]:
            data = head.encode()
        elif args[1] == "status":
            data = b""
        elif args[1:3] == ["diff", "--name-only"]:
            data = b"scripts/owned.py\n"
        elif args[1] == "diff":
            data = b"owned isolated patch\n"
        elif args[1] == "show":
            data = b"{}" if args[-1].endswith(".json") else b"wholly owned source\n"
        else:
            raise AssertionError("unexpected command")
        return subprocess.CompletedProcess(args, 0, data, b"")

    monkeypatch.setattr(module.subprocess, "run", run)
    return module, supplied


def test_pending_full_and_historical_modes_cannot_overwrite_each_other(tmp_path, monkeypatch):
    builder, supplied = owned_builder(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["builder", "--continuation"])
    builder.main()
    monkeypatch.setattr(sys, "argv", ["builder", "--continuation", "--full-receipt", str(supplied)])
    builder.main()
    full = next(tmp_path.glob("review_pack/DMF-MODEL-QUALITY-001/*/continuation-full-*/*.zip"))
    before = hashlib.sha256(full.read_bytes()).hexdigest()
    monkeypatch.setattr(sys, "argv", ["builder", "--continuation"])
    builder.main()
    monkeypatch.setattr(sys, "argv", ["builder"])
    builder.main()
    assert hashlib.sha256(full.read_bytes()).hexdigest() == before
    assert len(list(tmp_path.rglob("*.zip"))) == 3
    with zipfile.ZipFile(full) as packet:
        assert len(packet.namelist()) == 20 and packet.testzip() is None


def test_existing_different_review_archive_is_preserved(tmp_path, monkeypatch):
    builder, _ = owned_builder(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["builder", "--continuation"])
    builder.main()
    archive = next(tmp_path.rglob("*.zip"))
    with zipfile.ZipFile(archive, "w") as packet:
        packet.writestr("unique-review.txt", "preserve this existing evidence")
    original = archive.read_bytes()
    with pytest.raises(ValueError, match="PRESERVE_DIFFERENT_EXISTING_ARCHIVE"):
        builder.main()
    assert archive.read_bytes() == original


@pytest.mark.parametrize("mutation", ["duplicate", "comment", "trailing"])
def test_opaque_or_extra_zip_payload_is_rejected_and_preserved(tmp_path, monkeypatch, mutation):
    builder, _ = owned_builder(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["builder", "--continuation"])
    builder.main()
    archive = next(tmp_path.rglob("*.zip"))
    if mutation == "duplicate":
        with (
            zipfile.ZipFile(archive, "a") as packet,
            pytest.warns(UserWarning, match="Duplicate name"),
        ):
            packet.writestr("01_INDEX.md", packet.read("01_INDEX.md"))
    elif mutation == "comment":
        with zipfile.ZipFile(archive, "a") as packet:
            packet.comment = b"opaque unreviewed payload"
    else:
        with archive.open("ab") as destination:
            destination.write(b"opaque trailing payload")
    original = archive.read_bytes()
    with pytest.raises(ValueError, match="PRESERVE_DIFFERENT_EXISTING_ARCHIVE"):
        builder.main()
    assert archive.read_bytes() == original
