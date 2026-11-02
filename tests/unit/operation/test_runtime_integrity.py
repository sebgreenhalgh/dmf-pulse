"""Complete owned dependency snapshots and bounded generated metadata."""

from __future__ import annotations

import base64
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from dmf_pulse.operation import runtime_integrity
from dmf_pulse.operation.runtime_integrity import (
    RuntimeIntegrityError,
    collect_dependency_tree,
    verify_dependency_tree,
)


def record(site: Path) -> None:
    rows = []
    for path in sorted(site.rglob("*")):
        if (
            not path.is_file()
            or path.name == "RECORD"
            or path.parts[-2] in {"dmf_pulse", "dmf_pulse-0.2.0.dist-info"}
        ):
            continue
        value = path.read_bytes()
        rows.append(
            [
                path.relative_to(site).as_posix(),
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("="),
                str(len(value)),
            ]
        )
    rows.append(["owned-1.0.dist-info/RECORD", "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    (site / "owned-1.0.dist-info/RECORD").write_text(output.getvalue(), encoding="utf-8")


def installed(tmp_path: Path) -> tuple[Path, dict]:
    site = (
        tmp_path
        / "venv"
        / ("Lib/site-packages" if os.name == "nt" else "lib/python3.13/site-packages")
    )
    files = {
        "owned/__init__.py": b"VALUE = 1\n",
        "owned/data.txt": b"owned data",
        "_virtualenv.py": b"owned hook",
        "_virtualenv.pth": b"import _virtualenv\n",
        "owned-1.0.dist-info/METADATA": b"Name: owned\nVersion: 1.0\n",
        "owned-1.0.dist-info/INSTALLER": b"uv",
        "owned-1.0.dist-info/REQUESTED": b"",
        "owned-1.0.dist-info/uv_cache.json": b'{"timestamp":{"secs_since_epoch":1,"nanos_since_epoch":0},"commit":null,"tags":null,"env":{},"directories":{}}',
        "owned-1.0.dist-info/direct_url.json": b'{"url":"https://example.test/owned.whl","archive_info":{}}',
    }
    for name, value in files.items():
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    record(site)
    return site, collect_dependency_tree(site, "a" * 64)


def test_exact_tree_and_prefix_portability(tmp_path: Path) -> None:
    site, inventory = installed(tmp_path / "first")
    second, other = installed(tmp_path / "different-prefix")
    assert inventory == other
    verify_dependency_tree(site, inventory)
    verify_dependency_tree(second, inventory)


@pytest.mark.parametrize(
    "name",
    [
        "unexpected.py",
        "new_package/__init__.py",
        "owned/extra.pyd",
        "owned/new.data",
        "surprise.pth",
        "empty_namespace/",
    ],
)
def test_extra_top_level_nested_native_data_pth_and_empty_namespace_denied(
    tmp_path: Path, name: str
) -> None:
    site, inventory = installed(tmp_path)
    target = site / name
    if name.endswith("/"):
        target.mkdir()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"owned marker")
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


@pytest.mark.parametrize(
    "name", ["owned/__init__.py", "owned/data.txt", "_virtualenv.py", "_virtualenv.pth"]
)
def test_modified_static_bytes_cannot_be_blessed_by_rewritten_record(
    tmp_path: Path, name: str
) -> None:
    site, inventory = installed(tmp_path)
    (site / name).write_bytes(b"changed marker")
    record(site)
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


@pytest.mark.parametrize(
    "name", ["owned/__pycache__/file.pyc", "owned/extra.pyo", "__pycache__/top.pyc"]
)
def test_any_dependency_bytecode_denied(tmp_path: Path, name: str) -> None:
    site, inventory = installed(tmp_path)
    target = site / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"cache marker")
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


@pytest.mark.parametrize("name", ["INSTALLER", "REQUESTED", "uv_cache.json", "direct_url.json"])
def test_generated_metadata_is_validated_even_if_record_updated(tmp_path: Path, name: str) -> None:
    site, inventory = installed(tmp_path)
    (site / "owned-1.0.dist-info" / name).write_bytes(b"invalid")
    record(site)
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


def test_only_uv_timestamp_is_normalized(tmp_path: Path) -> None:
    site, inventory = installed(tmp_path)
    path = site / "owned-1.0.dist-info/uv_cache.json"
    value = json.loads(path.read_bytes())
    value["timestamp"] = {"secs_since_epoch": 999, "nanos_since_epoch": 123}
    path.write_text(json.dumps(value))
    record(site)
    verify_dependency_tree(site, inventory)
    value["env"] = {"injected": "value"}
    path.write_text(json.dumps(value))
    record(site)
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


def test_exact_signed_direct_url_source(tmp_path: Path) -> None:
    site, inventory = installed(tmp_path)
    (site / "owned-1.0.dist-info/direct_url.json").write_text(
        '{"url":"https://changed.test/owned.whl","archive_info":{}}'
    )
    record(site)
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


@pytest.mark.parametrize(
    "relative",
    [
        "../../../../outside",
        "/absolute",
        "owned/../../outside",
        "dmf_pulse/owned.py",
        "../../Scripts/subdir/escape.exe",
    ],
)
def test_record_paths_fail_closed_before_reading_outside_boundary(
    tmp_path: Path, relative: str
) -> None:
    site, inventory = installed(tmp_path)
    path = site / "owned-1.0.dist-info/RECORD"
    path.write_text(path.read_text() + relative + ",sha256=bad,1\n")
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


def test_own_application_is_separately_authenticated(tmp_path: Path) -> None:
    site, inventory = installed(tmp_path)
    for name in ("dmf_pulse/__init__.py", "dmf_pulse-0.2.0.dist-info/RECORD"):
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"separate wheel authority")
    verify_dependency_tree(site, inventory)


@pytest.mark.parametrize("change", ["extra", "missing", "lock", "schema", "static"])
def test_malformed_inventory_is_not_a_new_authority(tmp_path: Path, change: str) -> None:
    site, inventory = installed(tmp_path)
    value = copy.deepcopy(inventory)
    if change == "extra":
        value["extra"] = True
    elif change == "missing":
        value.pop("records")
    elif change == "lock":
        value["lock_sha256"] = True
    elif change == "schema":
        value["schema_version"] = "other"
    else:
        value["static_files"]["owned/__init__.py"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeIntegrityError, match=r"^DEPENDENCY_TREE_INTEGRITY_FAILED$"):
        verify_dependency_tree(site, value)


def test_runtime_verifier_imports_only_stdlib() -> None:
    import ast

    source = Path(__file__).parents[3] / "src/dmf_pulse/operation/runtime_integrity.py"
    tree = ast.parse(source.read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and name.startswith(("dmf_pulse", "pydantic")) for name in imports)


def add_external(site: Path, relative: str, value: bytes) -> Path:
    target = site / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)
    record_path = site / "owned-1.0.dist-info/RECORD"
    digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
    with record_path.open("a", encoding="utf-8") as stream:
        stream.write(f"{relative},sha256={digest},{len(value)}\n")
    return target


def test_external_header_bytes_are_pinned_and_scripts_record_checked_never_executed(
    tmp_path: Path,
) -> None:
    site, _ = installed(tmp_path)
    prefix = "../../" if os.name == "nt" else "../../../"
    script = prefix + ("Scripts/owned.exe" if os.name == "nt" else "bin/owned")
    header = prefix + "include/site/python3.13/owned.h"
    script_path = add_external(site, script, b"owned nonexecuted script marker")
    add_external(site, header, b"owned static header")
    inventory = collect_dependency_tree(site, "a" * 64)
    verify_dependency_tree(site, inventory)
    assert inventory["external_scripts"]
    assert inventory["external_files"]
    script_path.write_bytes(b"different marker")
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)
    # Generated script bytes vary by venv prefix; the standing policy only admits
    # the separately authenticated stdlib bootstrap and release Python.
    record(site)
    script_path = add_external(site, script, b"rebased script marker")
    add_external(site, header, b"owned static header")
    verify_dependency_tree(site, inventory)
    record(site)
    add_external(site, script, script_path.read_bytes())
    add_external(site, header, b"changed static header")
    with pytest.raises(RuntimeIntegrityError):
        verify_dependency_tree(site, inventory)


class OwnedKernel:
    status = 258
    closed = 0

    def __init__(self) -> None:
        self.handles: dict[int, Path] = {}
        self.next_handle = 200

    def CreateFileW(
        self,
        path: str,
        desired: int,
        share: int,
        security: object,
        disposition: int,
        flags: int,
        template: object,
    ) -> int:
        assert desired == 0x80000080 and share == 1 and disposition == 3
        self.next_handle += 1
        self.handles[self.next_handle] = Path(path)
        return self.next_handle

    def GetFileInformationByHandleEx(
        self, handle: int, kind: int, pointer: object, size: int
    ) -> bool:
        import ctypes
        import stat

        info = self.handles[handle].lstat()
        if kind == 18:
            value = ctypes.cast(pointer, ctypes.POINTER(runtime_integrity._FileId)).contents
            value.volume = info.st_dev
            value.identity[:] = info.st_ino.to_bytes(16, "little")
        else:
            value = ctypes.cast(pointer, ctypes.POINTER(runtime_integrity._FileAttributes)).contents
            value.attributes = 0x10 if stat.S_ISDIR(info.st_mode) else 0x80
        return True

    def CloseHandle(self, handle: int) -> bool:
        del self.handles[handle]
        return True

    def WaitForSingleObject(self, handle: int, timeout: int) -> int:
        assert handle == 123 and timeout == 0
        return self.status

    def FindCloseChangeNotification(self, handle: int) -> bool:
        assert handle == 123
        self.closed += 1
        return True


@pytest.mark.parametrize("signal", [0, 1, 0xFFFFFFFF])
def test_kernel_signal_or_error_latches_permanently(signal: int) -> None:
    kernel = OwnedKernel()
    watch = runtime_integrity.DirectoryWatch(kernel, 123)
    watch.require_unchanged()
    kernel.status = signal
    with pytest.raises(RuntimeIntegrityError):
        watch.require_unchanged()
    kernel.status = 258
    with pytest.raises(RuntimeIntegrityError):
        watch.require_unchanged()
    watch.close()
    watch.close()
    assert kernel.closed == 1


def test_execution_cache_only_populates_after_full_check_under_watch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, inventory = installed(tmp_path / "operator/releases" / ("f" * 64))
    kernel = OwnedKernel()
    watch = runtime_integrity.DirectoryWatch(kernel, 123)
    monkeypatch.setattr(runtime_integrity, "_new_watch", lambda root: watch)
    monkeypatch.setattr(runtime_integrity, "_EXECUTION_CACHE", {})
    original = runtime_integrity.verify_dependency_tree
    calls = []

    def verify(site: Path, inventory: dict) -> None:
        calls.append(True)
        original(site, inventory)

    monkeypatch.setattr(runtime_integrity, "verify_dependency_tree", verify)
    runtime_integrity.verify_dependency_tree_for_execution(site, inventory)
    runtime_integrity.verify_dependency_tree_for_execution(site, inventory)
    assert len(calls) == 1
    kernel.status = 0
    with pytest.raises(RuntimeIntegrityError):
        runtime_integrity.verify_dependency_tree_for_execution(site, inventory)
    assert len(calls) == 1


def test_change_during_full_check_never_seeds_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, inventory = installed(tmp_path / "operator/releases" / ("f" * 64))
    kernel = OwnedKernel()
    watch = runtime_integrity.DirectoryWatch(kernel, 123)
    monkeypatch.setattr(runtime_integrity, "_new_watch", lambda root: watch)
    monkeypatch.setattr(runtime_integrity, "_EXECUTION_CACHE", {})

    def verify(site: Path, inventory: dict) -> None:
        kernel.status = 0

    monkeypatch.setattr(runtime_integrity, "verify_dependency_tree", verify)
    with pytest.raises(RuntimeIntegrityError):
        runtime_integrity.verify_dependency_tree_for_execution(site, inventory)
    assert not runtime_integrity._EXECUTION_CACHE
    assert kernel.closed == 1


def test_no_native_watch_always_runs_full_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, inventory = installed(tmp_path / "operator/releases" / ("f" * 64))
    monkeypatch.setattr(runtime_integrity, "_new_watch", lambda root: None)
    monkeypatch.setattr(runtime_integrity, "_EXECUTION_CACHE", {})
    calls = []
    monkeypatch.setattr(
        runtime_integrity, "verify_dependency_tree", lambda site, inventory: calls.append(True)
    )
    runtime_integrity.verify_dependency_tree_for_execution(site, inventory)
    runtime_integrity.verify_dependency_tree_for_execution(site, inventory)
    assert len(calls) == 2 and not runtime_integrity._EXECUTION_CACHE


def test_actual_native_immutable_lease_contract(tmp_path: Path) -> None:
    if os.name != "nt":
        assert runtime_integrity._new_watch(tmp_path) is None
        return
    root = tmp_path / "owned-native-watch"
    nested = root / "nested"
    nested.mkdir(parents=True)
    path = nested / "owned-marker.bin"
    path.write_bytes(b"owned harmless marker")
    writer = path.open("r+b", buffering=0)
    watch = runtime_integrity._new_watch(root)
    assert watch is not None
    try:
        with pytest.raises(RuntimeIntegrityError):
            watch.protect_tree(root)
    finally:
        watch.close()
        writer.close()
    watch = runtime_integrity._new_watch(root)
    assert watch is not None
    try:
        watch.protect_tree(root)
        watch.require_unchanged()
        with pytest.raises(PermissionError):
            path.open("r+b", buffering=0)
        replacement = tmp_path / "owned-retained-native-watch"
        assert root.resolve().is_relative_to(tmp_path.resolve())
        assert replacement.absolute().is_relative_to(tmp_path.resolve())
        with pytest.raises(PermissionError):
            root.rename(replacement)
        # A withdrawal marker must remain possible. Directory membership catches
        # the new name even when the notification check is deliberately delayed.
        (root / "withdrawn.json").write_bytes(b'{"owned_test":true}')
        watch._kernel.WaitForSingleObject = lambda handle, timeout: 258
        with pytest.raises(RuntimeIntegrityError):
            watch.require_unchanged()
    finally:
        watch.close()


def test_unknown_native_root_identity_never_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "nt":
        assert runtime_integrity._new_watch(tmp_path) is None
        return
    monkeypatch.setattr(runtime_integrity, "_directory_identity", lambda path: None)
    assert runtime_integrity._new_watch(tmp_path) is None
