"""Recovery custody, temporal classification and bounded hash-only file attacks."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.player_lab import recovery
from dmf_pulse.player_lab.recovery import (
    RecoveryError,
    recovery_catalogue,
    verify_recovered_artifact,
)
from dmf_pulse.player_lab.recovery_models import (
    LastKnownP01Labels,
    RecoveredFamily,
    RecoveryCatalogue,
)

pytestmark = pytest.mark.unit


def test_reviewed_catalogue_separates_real_match_synthetic_and_unresolved():
    catalogue = recovery_catalogue()
    families = {family.family_id: family for family in catalogue.families}
    original = families["P01_PUBLIC_MATCH_FORECAST"]
    assert original.classification == "REAL_PRE_OUTCOME_FROZEN"
    assert original.forecast_origin.isoformat() == "2026-10-03T13:38:40.513349+00:00"
    assert original.frozen_at.isoformat() == "2026-10-03T13:40:19.466686+00:00"
    assert (original.sample_count, original.products_per_sample, original.forecast_rows) == (
        10,
        3,
        30,
    )
    assert original.real_accuracy_metrics is None
    assert original.retention == "QUALIFIED_PUBLIC_PRIVATE_USE_ONLY"
    assert catalogue.p01_labels.final_fixture_count == 0
    assert catalogue.p01_labels.missing_fixture_count == 10
    assert catalogue.p01_labels.current_provider_availability == "NOT_QUERIED"
    assert catalogue.canonical_resumption == "BLOCKED_EXACT_CODE_NO_REGENERATION"
    assert families["ACCEL001_CONTROLLED_PRIVATE_PIPELINE_DECISIONS"].classification == "SYNTHETIC"
    assert families["EXPLICIT_RECONSTRUCTED_SOURCE_REPLAY_RECORDS"].classification == (
        "HISTORICAL_RECONSTRUCTED"
    )
    assert families["HISTORICAL_PRIVATE_LIVE_OPERATION_FAMILIES"].retention == (
        "NOT_QUALIFIED_FOR_RETENTION"
    )
    assert catalogue.additional_owner_report == "UNRESOLVED_NOT_DISPROVED"
    assert all(family.real_accuracy_metrics is None for family in catalogue.families)
    assert catalogue.promotion == "FORBIDDEN" and not catalogue.scoring_performed
    assert catalogue.coverage.access_or_absence_gaps == 83
    assert not catalogue.coverage.mtime_is_freeze_proof


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_byte_sha256": None},
        {"forecast_origin": None},
        {"frozen_at": datetime(2026, 10, 3)},
        {"sample_count": 30},
        {"sample_count": True},
        {"sample_unit": "NOT_ESTABLISHED"},
        {"training_cutoff": None},
        {"products": ("INVENTED_PRODUCT",)},
        {"real_accuracy_metrics": {"mae": 0}},
    ],
)
def test_missing_custody_naive_time_wrong_denominator_and_invented_metrics_rejected(change):
    payload = recovery_catalogue().families[0].model_dump()
    payload.update(change)
    with pytest.raises(ValidationError):
        RecoveredFamily.model_validate(payload)


def test_label_accounting_and_catalogue_semantic_seal_fail_closed():
    catalogue = recovery_catalogue()
    payload = catalogue.p01_labels.model_dump()
    payload["missing_fixture_count"] = 9
    with pytest.raises(ValidationError):
        LastKnownP01Labels.model_validate(payload)
    data = catalogue.model_dump(mode="json")
    data["additional_owner_report"] = "NO_OTHER_FORECASTS_EXIST"
    with pytest.raises(ValidationError):
        RecoveryCatalogue.model_validate_json(json.dumps(data))
    data = catalogue.model_dump(mode="json")
    data["families"][0]["sample_count"] = 30
    with pytest.raises(ValidationError):
        RecoveryCatalogue.model_validate_json(json.dumps(data))


class Resource:
    def __init__(self, body):
        self.body = body

    def joinpath(self, *parts):
        assert parts == ("resources", "recovered_forecasts_v1.json")
        return self

    def read_bytes(self):
        return self.body


@pytest.mark.parametrize(
    "attack", ["corrupt", "oversized", "semantic", "p01_rebinding", "duplicates"]
)
def test_packaged_resource_cannot_be_replaced_or_rebaseline_p01(attack, monkeypatch):
    data = recovery_catalogue().model_dump(mode="json")
    if attack == "corrupt":
        body = b"not reviewed metadata"
    elif attack == "oversized":
        body = b" " * 48_001
    else:
        if attack == "semantic":
            data["families"][0]["explanation"] = "invented"
        elif attack == "p01_rebinding":
            data["families"][0]["artifact_byte_sha256"] = "f" * 64
        else:
            data["families"].append(data["families"][0])
        if attack != "semantic":
            data["semantic_sha256"] = canonical_sha256(
                {k: v for k, v in data.items() if k != "semantic_sha256"}
            )
        body = json.dumps(data).encode()
        monkeypatch.setattr(recovery, "_RESOURCE_SHA256", hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(recovery, "files", lambda _: Resource(body))
    with pytest.raises(RecoveryError, match="RECOVERY_CATALOGUE_UNAVAILABLE"):
        recovery_catalogue()


@pytest.mark.parametrize(
    "body",
    [
        b'{"classification":"REAL_PRE_OUTCOME_FROZEN","retention":"APPROVED"}',
        b"[" * 1100 + b"]" * 1100,
        b"cos\nsystem\n(S'owned-canary-never-execute'\ntR.",
    ],
    ids=["self_asserted_real", "deep_json", "pickle_code"],
)
def test_unknown_bytes_are_hashed_never_deserialized_or_admitted(body, tmp_path, monkeypatch):
    path = tmp_path / "forecast.pkl"
    path.write_bytes(body)
    monkeypatch.setattr(os, "system", lambda _: pytest.fail("unknown pickle must not execute"))
    result = verify_recovered_artifact(path)
    assert result.byte_sha256 == hashlib.sha256(body).hexdigest()
    assert result.bytes == len(body)
    assert result.classification == "UNVERIFIED_CUSTODY" and result.family_id is None
    assert result.retention == "NOT_ESTABLISHED" and not result.scoring_authorized
    assert str(tmp_path) not in result.model_dump_json()
    assert "owned-canary" not in result.model_dump_json()


def test_matching_reviewed_digest_keeps_rights_and_scoring_separate(monkeypatch):
    original = recovery_catalogue().families[0]
    monkeypatch.setattr(
        recovery, "_artifact_digest", lambda _: (original.artifact_byte_sha256, 38_208_223)
    )
    result = verify_recovered_artifact(Path("synthetic-digest-seam-only"))
    assert result.family_id == original.family_id
    assert result.status == "MATCHED_REVIEWED_ORIGINAL_BYTES"
    assert result.classification == "REAL_PRE_OUTCOME_FROZEN"
    assert not result.scoring_authorized


@pytest.mark.parametrize(
    "kind", ["missing", "directory", "oversize", "secret_name", "unc", "stream"]
)
def test_unsafe_input_never_opened_or_echoed(kind, tmp_path, monkeypatch):
    path = tmp_path / "forecast.json"
    if kind == "directory":
        path.mkdir()
    elif kind == "oversize":
        path.write_bytes(b"too large")
        monkeypatch.setattr(recovery, "_MAX_ARTIFACT_BYTES", 1)
    elif kind == "secret_name":
        path = tmp_path / "credentials.json"
        path.write_bytes(b"never read this owned body")
    elif kind == "unc":
        path = Path("//owned-invalid-host/forecast.json")
    elif kind == "stream":
        path = tmp_path / "forecast.json:stream"
    monkeypatch.setattr(
        os, "open", lambda *a, **k: pytest.fail("unsafe input must be rejected first")
    )
    with pytest.raises(RecoveryError) as error:
        verify_recovered_artifact(path)
    assert str(error.value) == "RECOVERY_ARTIFACT_UNSAFE_OR_UNREADABLE"


@pytest.mark.parametrize("kind", ["symlink", "reparse", "fifo"])
def test_link_reparse_and_fifo_metadata_rejected_before_open(kind, tmp_path, monkeypatch):
    path = tmp_path / "forecast.json"
    path.write_bytes(b"owned")
    metadata = path.stat()
    mode = (
        stat.S_IFLNK if kind == "symlink" else stat.S_IFIFO if kind == "fifo" else metadata.st_mode
    )
    original = Path.lstat

    def fake_stat(candidate):
        if candidate == path:
            return SimpleNamespace(
                st_mode=mode, st_size=5, st_file_attributes=0x400 if kind == "reparse" else 0
            )
        return original(candidate)

    monkeypatch.setattr(Path, "lstat", fake_stat)
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("unsafe input must not open"))
    with pytest.raises(RecoveryError):
        verify_recovered_artifact(path)


def test_regular_file_identity_swap_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "forecast.json"
    path.write_bytes(b"owned")
    actual = os.fstat

    def swapped(descriptor):
        value = actual(descriptor)
        return SimpleNamespace(
            st_mode=value.st_mode,
            st_size=value.st_size,
            st_ino=value.st_ino + 1,
            st_dev=value.st_dev,
        )

    monkeypatch.setattr(os, "fstat", swapped)
    with pytest.raises(RecoveryError):
        verify_recovered_artifact(path)


def test_file_mutation_during_hashing_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "forecast.json"
    path.write_bytes(b"owned")
    actual = os.fstat
    calls = 0

    def changed(descriptor):
        nonlocal calls
        value = actual(descriptor)
        calls += 1
        return SimpleNamespace(
            st_mode=value.st_mode,
            st_size=value.st_size,
            st_ino=value.st_ino,
            st_dev=value.st_dev,
            st_mtime_ns=value.st_mtime_ns + (1 if calls > 1 else 0),
        )

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(RecoveryError):
        verify_recovered_artifact(path)


@pytest.mark.parametrize("target", ["digest", "catalogue"])
def test_failure_exception_retains_no_raw_input_or_suppressed_context(
    target, tmp_path, monkeypatch
):
    canary = b"owned-private-body-canary-do-not-retain"
    path = tmp_path / "forecast.json"
    path.write_bytes(canary)

    def raw_failure(_):
        raw_body = canary
        raise ValueError(raw_body)

    if target == "digest":
        monkeypatch.setattr(recovery, "_artifact_digest", raw_failure)

        def operation():
            return verify_recovered_artifact(path)

    else:
        monkeypatch.setattr(recovery, "files", raw_failure)
        operation = recovery_catalogue
    with pytest.raises(RecoveryError) as captured:
        operation()
    error = captured.value
    assert error.__cause__ is None and error.__context__ is None
    trace = error.__traceback__
    while trace is not None:
        if trace.tb_frame.f_globals.get("__name__", "").startswith("dmf_pulse."):
            assert "raw_body" not in trace.tb_frame.f_locals
            assert canary.decode() not in repr(trace.tb_frame.f_locals)
        trace = trace.tb_next


def test_file_growing_after_descriptor_check_is_bounded_without_context_leak(tmp_path, monkeypatch):
    path = tmp_path / "forecast.json"
    path.write_bytes(b"x")
    original = os.fdopen
    monkeypatch.setattr(recovery, "_MAX_ARTIFACT_BYTES", 2)

    class GrowingFile:
        def __init__(self, handle):
            self.handle = handle
            self.grown = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, count):
            if not self.grown:
                self.grown = True
                with path.open("ab") as writer:
                    writer.write(b"owned-private-growing-body-canary")
            return self.handle.read(count)

    monkeypatch.setattr(
        os, "fdopen", lambda *args, **kwargs: GrowingFile(original(*args, **kwargs))
    )
    with pytest.raises(RecoveryError) as captured:
        verify_recovered_artifact(path)
    assert captured.value.__context__ is None
