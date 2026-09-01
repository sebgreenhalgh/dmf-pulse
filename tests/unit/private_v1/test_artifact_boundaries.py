from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.private_v1 import artifacts
from dmf_pulse.private_v1.artifacts import (
    load_execution_input,
    verify_replay_bundle,
    write_synthetic_replay_bundle,
)
from dmf_pulse.private_v1.errors import PrivateV1Error


def test_duplicate_json_key_fails_before_private_model_validation(tmp_path: Path) -> None:
    path = tmp_path / "private.json"
    path.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")

    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(path)

    assert caught.value.code == "DUPLICATE_JSON_KEY"
    assert str(path) not in str(caught.value)


def test_nonfinite_json_and_oversized_input_fail_closed(tmp_path: Path) -> None:
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(nonfinite)
    assert caught.value.code == "MALFORMED_JSON"

    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(oversized)
    assert caught.value.code == "PAYLOAD_TOO_LARGE"


def test_replay_directory_rejects_missing_and_extra_files_before_payload_use(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "bundle"
    directory.mkdir()
    for name in ("decision.json", "input.json", "manifest.json", "report.txt", "extra.txt"):
        (directory / name).write_text("{}", encoding="utf-8")

    with pytest.raises(PrivateV1Error) as caught:
        verify_replay_bundle(directory)
    assert caught.value.code == "REPLAY_BUNDLE_INVALID"

    (directory / "extra.txt").unlink()
    (directory / "report.txt").unlink()
    with pytest.raises(PrivateV1Error) as caught:
        verify_replay_bundle(directory)
    assert caught.value.code == "REPLAY_BUNDLE_INVALID"


def _fake_execution_and_decision(
    *, retention_class: str = "SYNTHETIC_REPLAY_ALLOWED", lineage_matches: bool = True
) -> tuple[SimpleNamespace, SimpleNamespace]:
    execution = SimpleNamespace(
        retention_class=retention_class,
        semantic_sha256="1" * 64,
        run_id="SYNTHETIC-BOUNDARY",
        code_sha="a" * 40,
    )
    decision = SimpleNamespace(
        lineage=SimpleNamespace(execution_input_sha256="1" * 64 if lineage_matches else "f" * 64),
        semantic_sha256="2" * 64,
    )
    return execution, decision


def test_replay_write_rejects_rights_lineage_report_and_destination_before_writing(
    tmp_path: Path,
) -> None:
    execution, decision = _fake_execution_and_decision(retention_class="REAL_TRANSIENT_ONLY")
    with pytest.raises(PrivateV1Error) as caught:
        write_synthetic_replay_bundle(execution, decision, "report", tmp_path / "real")  # type: ignore[arg-type]
    assert caught.value.code == "REPLAY_RETENTION_FORBIDDEN"

    execution, decision = _fake_execution_and_decision(lineage_matches=False)
    with pytest.raises(PrivateV1Error) as caught:
        write_synthetic_replay_bundle(execution, decision, "report", tmp_path / "lineage")  # type: ignore[arg-type]
    assert caught.value.code == "REPLAY_LINEAGE_MISMATCH"

    execution, decision = _fake_execution_and_decision()
    with pytest.raises(PrivateV1Error) as caught:
        write_synthetic_replay_bundle(execution, decision, "\ud800", tmp_path / "unicode")  # type: ignore[arg-type]
    assert caught.value.code == "REPORT_INVALID"
    with pytest.raises(PrivateV1Error) as caught:
        write_synthetic_replay_bundle(  # type: ignore[arg-type]
            execution,
            decision,
            "x" * (artifacts.MAX_REPORT_BYTES + 1),
            tmp_path / "large",
        )
    assert caught.value.code == "PAYLOAD_TOO_LARGE"

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(PrivateV1Error) as caught:
        write_synthetic_replay_bundle(execution, decision, "report", existing)  # type: ignore[arg-type]
    assert caught.value.code == "REPLAY_DESTINATION_INVALID"


def test_replay_write_failure_is_atomic_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, decision = _fake_execution_and_decision()
    monkeypatch.setattr(artifacts, "canonical_json_bytes", lambda value: b"{}")

    def _fail_write(path: Path, body: bytes) -> None:
        del path, body
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(artifacts, "_write_new_file", _fail_write)
    destination = tmp_path / "bundle"

    with pytest.raises(PrivateV1Error) as caught:
        write_synthetic_replay_bundle(execution, decision, "report", destination)  # type: ignore[arg-type]

    assert caught.value.code == "REPLAY_WRITE_FAILED"
    assert "sensitive filesystem detail" not in str(caught.value)
    assert not destination.exists()


def test_reader_and_manifest_shape_fail_closed_without_path_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "private-manager.json"
    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(missing)
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert str(missing) not in str(caught.value)

    not_directory = tmp_path / "bundle.txt"
    not_directory.write_text("x", encoding="utf-8")
    with pytest.raises(PrivateV1Error) as caught:
        verify_replay_bundle(not_directory)
    assert caught.value.code == "REPLAY_BUNDLE_INVALID"

    directory = tmp_path / "bundle"
    directory.mkdir()
    for name in ("decision.json", "input.json", "manifest.json", "report.txt"):
        (directory / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        artifacts,
        "load_replay_manifest",
        lambda path: SimpleNamespace(files=(SimpleNamespace(relative_path="unexpected.json"),)),
    )
    with pytest.raises(PrivateV1Error) as caught:
        verify_replay_bundle(directory)
    assert caught.value.code == "REPLAY_BUNDLE_INVALID"
