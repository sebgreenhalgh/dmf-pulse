"""Cold directory discovery precedes the FIRST watch; later changes still latch."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dmf_pulse.operation import runtime_integrity as integrity
from dmf_pulse.operation.runtime_integrity import DirectoryWatch, RuntimeIntegrityError
from tests.unit.operation.test_runtime_integrity import installed, record


class Kernel:
    def __init__(self, status):
        self.status = status

    def WaitForSingleObject(self, handle, timeout):
        assert handle == 17 and timeout == 0
        return self.status


@pytest.mark.parametrize(
    "status,reason",
    [(0, "NATIVE_NOTIFICATION"), (4294967295, "NATIVE_WAIT_FAILED"), (128, "NATIVE_WAIT_FAILED")],
)
def test_native_failures_keep_closed_reasons_and_remain_latched(status, reason):
    kernel = Kernel(status)
    watch = DirectoryWatch(kernel, 17)
    with pytest.raises(RuntimeIntegrityError) as first:
        watch.require_unchanged()
    assert first.value.reason == reason
    kernel.status = 258
    with pytest.raises(RuntimeIntegrityError) as second:
        watch.require_unchanged()
    assert second.value.reason == "WATCH_ALREADY_INVALID"


def test_prescan_reads_metadata_only_and_propagates_observation_failure(tmp_path, monkeypatch):
    root = tmp_path / "owned"
    (root / "nested").mkdir(parents=True)
    (root / "nested/marker").write_bytes(b"owned bytes must not be read")

    def forbidden(*args, **kwargs):
        raise AssertionError("prescan read file contents")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    integrity._prepare_directory_observations(root)
    original = integrity._directory_snapshot

    def unavailable(path):
        if path.name == "nested":
            raise RuntimeIntegrityError()
        return original(path)

    monkeypatch.setattr(integrity, "_directory_snapshot", unavailable)
    with pytest.raises(RuntimeIntegrityError):
        integrity._prepare_directory_observations(root)


def test_32_cold_trees_verify_without_sleep_reset_or_rearming(tmp_path):
    if os.name != "nt":
        assert integrity._new_watch(tmp_path) is None
        return
    for number in range(32):
        root = tmp_path / f"owned-{number}"
        (root / "nested").mkdir(parents=True)
        marker = root / "nested/marker"
        marker.write_bytes(b"owned unchanged marker")
        watch = integrity._new_watch(root)
        assert watch is not None
        try:
            watch.protect_tree(root)
            for _ in range(4):
                assert marker.read_bytes() == b"owned unchanged marker"
                watch.require_unchanged()
            with pytest.raises(PermissionError):
                marker.write_bytes(b"unsafe overwrite")
            watch.require_unchanged()
        finally:
            watch.close()


def test_membership_reversion_does_not_restore_a_cached_watch(tmp_path):
    if os.name != "nt":
        assert integrity._new_watch(tmp_path) is None
        return
    root = tmp_path / "owned"
    root.mkdir()
    (root / "marker").write_bytes(b"owned unchanged marker")
    watch = integrity._new_watch(root)
    assert watch is not None
    try:
        watch.protect_tree(root)
        extra = root / "unexpected"
        extra.write_bytes(b"owned mutation")
        with pytest.raises(RuntimeIntegrityError):
            watch.require_unchanged()
        extra.unlink()
        with pytest.raises(RuntimeIntegrityError) as error:
            watch.require_unchanged()
        assert error.value.reason == "WATCH_ALREADY_INVALID"
    finally:
        watch.close()


def test_mutation_during_prescan_cannot_be_blessed_by_matching_record(tmp_path, monkeypatch):
    if os.name != "nt":
        assert integrity._new_watch(tmp_path) is None
        return
    root = tmp_path / "owned"
    site, inventory = installed(root / "releases" / ("a" * 64))
    original = integrity._prepare_directory_observations

    def mutate(path):
        original(path)
        (site / "owned/data.txt").write_bytes(b"changed after discovery")
        record(site)

    monkeypatch.setattr(integrity, "_prepare_directory_observations", mutate)
    with pytest.raises(RuntimeIntegrityError):
        integrity.verify_dependency_tree_for_execution(site, inventory)
    with pytest.raises(RuntimeIntegrityError):
        integrity.verify_dependency_tree(site, inventory)
