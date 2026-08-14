from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/verify_gcs008_wheel.py")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gcs008_wheel", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(value: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode(
        "ascii"
    )


def _wheel(path: Path, *, recorded: bytes, actual: bytes) -> None:
    member = "dmf_pulse/example.txt"
    record = "dmf_pulse-0.2.0.dist-info/RECORD"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow((member, _digest(recorded), str(len(recorded))))
    writer.writerow((record, "", ""))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, actual)
        archive.writestr(record, buffer.getvalue())


def test_wheel_record_verifies_every_member_hash_and_size(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "valid.whl"
    _wheel(path, recorded=b"content", actual=b"content")
    with zipfile.ZipFile(path) as archive:
        assert module._validate_wheel_record(archive) == 2


def test_wheel_record_rejects_tampered_member(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "tampered.whl"
    _wheel(path, recorded=b"expected", actual=b"tampered")
    with (
        zipfile.ZipFile(path) as archive,
        pytest.raises(module.VerificationError, match="integrity mismatch"),
    ):
        module._validate_wheel_record(archive)
