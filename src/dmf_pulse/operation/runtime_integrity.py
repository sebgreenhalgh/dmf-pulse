"""Stdlib-only dependency inventory, usable before any site-package import.

The owner application and its dist-info are authenticated separately against the
signed retained wheel. Every other site-package file is either byte-pinned or
one of the finite, validated UV installation metadata files described below.
"""

from __future__ import annotations

import atexit
import base64
import csv
import ctypes
import hashlib
import io
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urlsplit

_OWN = frozenset({"dmf_pulse", "dmf_pulse-0.2.0.dist-info"})
_GENERATED = frozenset({"INSTALLER", "REQUESTED", "uv_cache.json", "direct_url.json"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAXIMUM_FILE = 64 * 1024 * 1024
_MAXIMUM_TOTAL = 512 * 1024 * 1024
_EXECUTION_CACHE: dict[tuple[str, str], DirectoryWatch] = {}
_WATCHES: list[DirectoryWatch] = []
_CLOSE_REGISTERED = False
_TECHNICAL_PROCESS_ONLY = False

IntegrityReason = Literal[
    "CONTENT_OR_METADATA_MISMATCH",
    "WATCH_ALREADY_INVALID",
    "ROOT_IDENTITY_CHANGED",
    "DIRECTORY_MEMBERSHIP_CHANGED",
    "DIRECTORY_OBSERVATION_FAILED",
    "NATIVE_NOTIFICATION",
    "NATIVE_WAIT_FAILED",
    "LEASE_OPEN_FAILED",
    "LEASE_IDENTITY_CHANGED",
    "DIRECTORY_SCAN_LIMIT",
    "ROOT_CHANGED_DURING_PREPARATION",
]
INTEGRITY_REASONS = frozenset(
    {
        "CONTENT_OR_METADATA_MISMATCH",
        "WATCH_ALREADY_INVALID",
        "ROOT_IDENTITY_CHANGED",
        "DIRECTORY_MEMBERSHIP_CHANGED",
        "DIRECTORY_OBSERVATION_FAILED",
        "NATIVE_NOTIFICATION",
        "NATIVE_WAIT_FAILED",
        "LEASE_OPEN_FAILED",
        "LEASE_IDENTITY_CHANGED",
        "DIRECTORY_SCAN_LIMIT",
        "ROOT_CHANGED_DURING_PREPARATION",
    }
)


class _FileId(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_ulonglong), ("identity", ctypes.c_ubyte * 16)]


class _FileAttributes(ctypes.Structure):
    _fields_ = [("attributes", ctypes.c_uint32), ("tag", ctypes.c_uint32)]


class RuntimeIntegrityError(ValueError):
    """A closed diagnostic without file contents, paths or native exceptions."""

    def __init__(self, reason: object = "CONTENT_OR_METADATA_MISMATCH") -> None:
        self.reason: IntegrityReason = (
            cast(IntegrityReason, reason)
            if type(reason) is str and reason in INTEGRITY_REASONS
            else "CONTENT_OR_METADATA_MISMATCH"
        )
        super().__init__("DEPENDENCY_TREE_INTEGRITY_FAILED")


class DirectoryWatch:
    """Latched kernel invalidation. No rearm, reset or accept-changed operation."""

    def __init__(
        self,
        kernel: Any,
        handle: int,
        *,
        root: Path | None = None,
        identity: tuple[int, int] | None = None,
    ) -> None:
        self._kernel, self._handle = kernel, handle
        self._failed = False
        self._closed = False
        self._root, self._identity = root, identity
        self._leases: dict[Path, int] = {}
        self._directory_states: dict[Path, tuple[tuple[int, int], tuple[tuple[str, str], ...]]] = {}

    def require_unchanged(self) -> None:
        if self._closed or self._failed:
            raise RuntimeIntegrityError("WATCH_ALREADY_INVALID")
        try:
            root_changed = (
                self._root is not None and _directory_identity(self._root) != self._identity
            )
        except (OSError, ValueError, TypeError):
            self._failed = True
            raise RuntimeIntegrityError("DIRECTORY_OBSERVATION_FAILED") from None
        if root_changed:
            self._failed = True
            raise RuntimeIntegrityError("ROOT_IDENTITY_CHANGED")
        try:
            membership_changed = any(
                _directory_snapshot(path) != state for path, state in self._directory_states.items()
            )
        except (OSError, ValueError, TypeError):
            self._failed = True
            raise RuntimeIntegrityError("DIRECTORY_OBSERVATION_FAILED") from None
        if membership_changed:
            self._failed = True
            raise RuntimeIntegrityError("DIRECTORY_MEMBERSHIP_CHANGED")
        try:
            status = self._kernel.WaitForSingleObject(self._handle, 0)
        except (OSError, ValueError, TypeError):
            self._failed = True
            raise RuntimeIntegrityError("NATIVE_WAIT_FAILED") from None
        if status != 258:
            self._failed = True
            raise RuntimeIntegrityError(
                "NATIVE_NOTIFICATION" if status == 0 else "NATIVE_WAIT_FAILED"
            )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                for handle in self._leases.values():
                    self._kernel.CloseHandle(handle)
                self._leases.clear()
            finally:
                self._kernel.FindCloseChangeNotification(self._handle)

    def _lock(self, path: Path, *, directory: bool = False) -> None:
        path = _safe(path.absolute())
        if path in self._leases:
            return
        flags = 0x00200000 | (0x02000000 if directory else 0x80)
        handle = self._kernel.CreateFileW(str(path), 0x80000080, 1, None, 3, flags, None)
        if handle is None or handle == ctypes.c_void_p(-1).value:
            self._failed = True
            raise RuntimeIntegrityError("LEASE_OPEN_FAILED")
        self._leases[path] = handle
        identity = _FileId()
        attributes = _FileAttributes()
        if not self._kernel.GetFileInformationByHandleEx(
            handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)
        ) or not self._kernel.GetFileInformationByHandleEx(
            handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)
        ):
            self._failed = True
            raise RuntimeIntegrityError("LEASE_IDENTITY_CHANGED")
        info = path.lstat()
        actual = (identity.volume, int.from_bytes(bytes(identity.identity), "little"))
        if (
            attributes.attributes & 0x400
            or bool(attributes.attributes & 0x10) != directory
            or (info.st_dev, info.st_ino) != actual
            or actual[0] <= 0
            or actual[1] <= 0
        ):
            self._failed = True
            raise RuntimeIntegrityError("LEASE_IDENTITY_CHANGED")

    def _protect_directory(self, path: Path) -> None:
        path = path.absolute()
        if path not in self._directory_states:
            self._lock(path, directory=True)
            self._directory_states[path] = _directory_snapshot(path)

    def lock_paths(self, paths: list[Path]) -> None:
        """Deny WRITE and DELETE before the verifier reads protected bytes."""
        for path in paths:
            self._protect_directory(path.parent)
            self._lock(path)

    def protect_tree(self, root: Path) -> None:
        root = _safe(root.absolute())
        pending = [root]
        count = 0
        while pending:
            directory = pending.pop()
            self._protect_directory(directory)
            for name, kind in self._directory_states[directory][1]:
                path = directory / name
                count += 1
                _require(count <= 100000)
                if kind == "D":
                    pending.append(path)
                else:
                    self._lock(path)


def _close_watches() -> None:
    for watch in _WATCHES:
        try:
            watch.close()
        except (OSError, ValueError, TypeError):
            continue


def _new_watch(root: Path) -> DirectoryWatch | None:
    """Create only at explicit execution, never at import or during collection."""
    global _CLOSE_REGISTERED
    if os.name != "nt":
        return None
    _safe(root)
    identity = _directory_identity(root)
    if identity is None:
        return None
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        return None
    try:
        kernel = loader("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None
    kernel.FindFirstChangeNotificationW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32]
    kernel.FindFirstChangeNotificationW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.FindCloseChangeNotification.argtypes = [ctypes.c_void_p]
    kernel.FindCloseChangeNotification.restype = ctypes.c_int
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    kernel.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel.GetFileInformationByHandleEx.restype = ctypes.c_int
    # A first Windows directory enumeration can itself produce a LAST_WRITE
    # notification without changing bytes/membership. Discover directories before
    # the FIRST watch only. No content is read/accepted here. All existing leases,
    # fresh snapshots, full signed hashes and latched checks still follow.
    _prepare_directory_observations(root)
    if _directory_identity(root) != identity:
        raise RuntimeIntegrityError("ROOT_CHANGED_DURING_PREPARATION")
    # Names, directories, attributes, sizes, writes and security changes all
    # latch invalidation across the complete operator tree, including controls.
    handle = kernel.FindFirstChangeNotificationW(str(root), 1, 0x11F)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise RuntimeIntegrityError()
    watch = DirectoryWatch(kernel, handle, root=root.absolute(), identity=identity)
    _WATCHES.append(watch)
    if not _CLOSE_REGISTERED:
        atexit.register(_close_watches)
        _CLOSE_REGISTERED = True
    try:
        watch.require_unchanged()
    except BaseException:
        watch.close()
        raise
    return watch


def _prepare_directory_observations(root: Path) -> None:
    pending = [root]
    count = 0
    while pending:
        directory = _safe(pending.pop())
        _, entries = _directory_snapshot(directory)
        for name, kind in entries:
            count += 1
            if count > 100000:
                raise RuntimeIntegrityError("DIRECTORY_SCAN_LIMIT")
            if kind == "D":
                pending.append(directory / name)


def _directory_identity(root: Path) -> tuple[int, int] | None:
    _safe(root)
    value = root.lstat()
    _require(stat.S_ISDIR(value.st_mode))
    if (
        type(value.st_dev) is not int
        or type(value.st_ino) is not int
        or value.st_dev <= 0
        or value.st_ino <= 0
    ):
        return None
    return value.st_dev, value.st_ino


def _directory_snapshot(root: Path) -> tuple[tuple[int, int], tuple[tuple[str, str], ...]]:
    info = root.lstat()
    _require(
        stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and not getattr(info, "st_file_attributes", 0) & 0x400
        and info.st_dev > 0
        and info.st_ino > 0
    )
    entries = []
    with os.scandir(root) as scan:
        for entry in scan:
            _require(
                not entry.is_symlink()
                and not (entry.is_junction() if hasattr(entry, "is_junction") else False)
            )
            kind = "D" if entry.is_dir(follow_symlinks=False) else "F"
            _require(kind == "D" or entry.is_file(follow_symlinks=False))
            entries.append((entry.name, kind))
    return (info.st_dev, info.st_ino), tuple(sorted(entries))


def _require(value: object) -> None:
    if not value:
        raise RuntimeIntegrityError()


def _safe(path: Path, checked_directories: set[Path] | None = None) -> Path:
    for node in (path.absolute(), *path.absolute().parents):
        if checked_directories is not None and node in checked_directories:
            continue
        info = node.lstat()
        _require(
            not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400
        )
        if checked_directories is not None and stat.S_ISDIR(info.st_mode):
            checked_directories.add(node)
    return path


def _body(
    path: Path, maximum: int = _MAXIMUM_FILE, checked_directories: set[Path] | None = None
) -> bytes:
    _safe(path, checked_directories)
    before = path.stat()
    _require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum)
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    after = path.stat()
    _require(
        len(value) == before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
    )
    return value


def _identity(value: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _json(value: bytes) -> Any:
    return json.loads(
        value,
        object_pairs_hook=_unique,
        parse_constant=lambda _: (_ for _ in ()).throw(RuntimeIntegrityError()),
    )


def _name(name: str) -> None:
    _require(
        bool(name)
        and len(name) <= 2048
        and "\\" not in name
        and ":" not in name
        and not name.startswith("/")
        and all(ord(char) >= 32 for char in name)
        and all(part not in {"", ".", ".."} for part in name.split("/"))
    )


def _metadata(name: str, body: bytes) -> dict[str, object]:
    if name == "INSTALLER":
        _require(body == b"uv")
        return {"kind": name, "value": "uv"}
    if name == "REQUESTED":
        _require(body == b"")
        return {"kind": name, "value": ""}
    value = _json(body)
    _require(isinstance(value, dict))
    if name == "uv_cache.json":
        _require(
            set(value) == {"timestamp", "commit", "tags", "env", "directories"}
            and value["commit"] is None
            and value["tags"] is None
            and value["env"] == {}
            and value["directories"] == {}
        )
        timestamp = value["timestamp"]
        _require(
            isinstance(timestamp, dict)
            and set(timestamp) == {"secs_since_epoch", "nanos_since_epoch"}
        )
        _require(
            all(type(item) is int and item >= 0 for item in timestamp.values())
            and timestamp["nanos_since_epoch"] < 1_000_000_000
        )
        return {"kind": name, "timestamp": "VALIDATED_NONNEGATIVE_UV_TIMESTAMP"}
    _require(
        name == "direct_url.json"
        and set(value) == {"url", "archive_info"}
        and isinstance(value["url"], str)
        and isinstance(value["archive_info"], dict)
    )
    parsed = urlsplit(value["url"])
    _require(
        parsed.scheme in {"https", "file"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and bool(parsed.path)
    )
    archive = value["archive_info"]
    _require(set(archive) <= {"hash", "hashes"})
    if "hash" in archive:
        _require(
            isinstance(archive["hash"], str)
            and re.fullmatch(r"sha256=[0-9a-f]{64}", archive["hash"]) is not None
        )
    if "hashes" in archive:
        _require(
            isinstance(archive["hashes"], dict)
            and set(archive["hashes"]) == {"sha256"}
            and isinstance(archive["hashes"]["sha256"], str)
            and _SHA.fullmatch(archive["hashes"]["sha256"]) is not None
        )
    return {"kind": name, "value": value}


def _venv(site: Path) -> Path:
    _require(site.name == "site-packages")
    if os.name == "nt":
        _require(site.parent.name.casefold() == "lib")
        return site.parents[1]
    _require(site.parent.name.startswith("python3.") and site.parents[1].name == "lib")
    return site.parents[2]


def _record_target(
    site: Path, venv: Path, name: str, checked_directories: set[Path]
) -> tuple[Path, bool]:
    if name.startswith("../"):
        parts = PurePosixPath(name).parts
        count = 2 if os.name == "nt" else 3
        _require(parts[:count] == ("..",) * count and len(parts) > count + 1)
        tail = parts[count:]
        _name("/".join(tail))
        script = tail[0] == ("Scripts" if os.name == "nt" else "bin")
        _require(
            (
                script
                and len(tail) == 2
                and (tail[1].endswith(".exe") if os.name == "nt" else "." not in tail[1])
            )
            or (tail[0] == "include" and len(tail) >= 3 and tail[-1].endswith(".h"))
        )
        target = _safe(venv.joinpath(*tail), checked_directories)
        _require(target.resolve().is_relative_to(venv.resolve()))
        return target, script
    _name(name)
    _require(name.split("/")[0] not in _OWN)
    return _safe(site / name, checked_directories), False


def _collect(site: Path, lock_sha256: str) -> dict[str, Any]:
    _require(isinstance(lock_sha256, str) and _SHA.fullmatch(lock_sha256) is not None)
    site = _safe(site)
    site = _safe(site.resolve())
    _require(site.is_dir())
    venv = _safe(_venv(site))
    static_files: dict[str, object] = {}
    generated: dict[str, object] = {}
    records: dict[str, list[str]] = {}
    external_scripts: dict[str, object] = {}
    external_files: dict[str, object] = {}
    checked_directories: set[Path] = set()
    bodies: dict[Path, bytes] = {}

    def read_once(path: Path) -> bytes:
        if path not in bodies:
            bodies[path] = _body(path, checked_directories=checked_directories)
        return bodies[path]

    seen: set[str] = set()
    total = 0
    paths: list[Path] = []
    directories: list[str] = []
    pending = [site]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            _safe(path, checked_directories)
            name = path.relative_to(site).as_posix()
            _name(name)
            _require(path.name != "__pycache__" and path.suffix.casefold() not in {".pyc", ".pyo"})
            first = name.split("/")[0]
            if first.casefold() in {item.casefold() for item in _OWN}:
                _require(first in _OWN)
                continue
            _require(name.casefold() not in seen)
            seen.add(name.casefold())
            _require(len(seen) <= 100000)
            if path.is_dir():
                directories.append(name)
                pending.append(path)
            else:
                paths.append(path)
    for path in sorted(paths):
        name = path.relative_to(site).as_posix()
        body = read_once(path)
        total += len(body)
        _require(total <= _MAXIMUM_TOTAL)
        parts = name.split("/")
        distinfo = len(parts) == 2 and parts[0].endswith(".dist-info")
        if distinfo and parts[1] == "RECORD":
            _require(len(body) <= 1_048_576)
            rows = list(csv.reader(io.StringIO(body.decode("utf-8"))))
            _require(
                all(len(row) == 3 for row in rows)
                and len(rows) == len({row[0].casefold() for row in rows})
            )
            _require(name in {row[0] for row in rows})
            records[name] = sorted(row[0] for row in rows)
            for relative, checksum, size in rows:
                target, script = _record_target(site, venv, relative, checked_directories)
                if relative == name:
                    _require(checksum == size == "")
                    continue
                value = read_once(target)
                digest = (
                    base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
                )
                _require(checksum == "sha256=" + digest and size == str(len(value)))
                if relative.startswith("../"):
                    key = target.relative_to(venv).as_posix()
                    identity = (
                        {"verification": "RECORD_HASH_ONLY_NEVER_EXECUTED"}
                        if script
                        else _identity(value)
                    )
                    output = external_scripts if script else external_files
                    _require(key not in output or output[key] == identity)
                    output[key] = identity
        elif distinfo and parts[1] in _GENERATED:
            _require(len(body) <= 262144)
            generated[name] = _metadata(parts[1], body)
        else:
            static_files[name] = _identity(body)
    _require(0 < len(records) <= 128)
    return {
        "schema_version": "dependency-tree-v1",
        "lock_sha256": lock_sha256,
        "static_files": static_files,
        "generated_metadata": generated,
        "records": records,
        "external_scripts": external_scripts,
        "external_files": external_files,
        "directories": sorted(directories),
    }


def collect_dependency_tree(site: Path, lock_sha256: str) -> dict[str, Any]:
    """Collect owned offline installation facts; this never grants authority."""
    try:
        return _collect(site, lock_sha256)
    except RuntimeIntegrityError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error):
        raise RuntimeIntegrityError() from None


def verify_dependency_tree(site: Path, inventory: dict[str, Any]) -> None:
    """The caller must authenticate this inventory SHA before calling."""
    try:
        _require(
            type(inventory) is dict
            and set(inventory)
            == {
                "schema_version",
                "lock_sha256",
                "static_files",
                "generated_metadata",
                "records",
                "external_scripts",
                "external_files",
                "directories",
            }
            and inventory["schema_version"] == "dependency-tree-v1"
        )

        def canonical(value: object) -> str:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )

        _require(canonical(_collect(site, inventory["lock_sha256"])) == canonical(inventory))
    except RuntimeIntegrityError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error):
        raise RuntimeIntegrityError() from None


def prepare_execution_lease(site: Path, inventory: dict[str, Any]) -> DirectoryWatch | None:
    """Acquire immutable native handles before ANY application byte validation."""
    _require(not _TECHNICAL_PROCESS_ONLY)
    site = _safe(site).resolve()
    venv = _venv(site)
    release = venv.parent
    _require(release.parent.name == "releases" and _SHA.fullmatch(release.name) is not None)
    root = release.parent.parent
    watch = _new_watch(root)
    if watch is None:
        return None
    try:
        watch.protect_tree(site)
        records = inventory.get("records")
        if not isinstance(records, dict):
            raise RuntimeIntegrityError()
        external = []
        for rows in records.values():
            _require(isinstance(rows, list) and all(isinstance(name, str) for name in rows))
            for name in rows:
                if name.startswith("../"):
                    target, _ = _record_target(site, venv, name, set())
                    external.append(target)
        watch.lock_paths(external)
        watch.require_unchanged()
        return watch
    except BaseException:
        watch.close()
        raise


def verify_dependency_tree_for_execution(
    site: Path, inventory: dict[str, Any], *, lease: DirectoryWatch | None = None
) -> None:
    """Full initial check, then a kernel-guarded cache for this process only."""
    try:
        _require(not _TECHNICAL_PROCESS_ONLY)
        site = _safe(site).resolve()
        venv = _venv(site)
        release = venv.parent
        _require(release.parent.name == "releases" and _SHA.fullmatch(release.name) is not None)
        root = release.parent.parent
        identity = hashlib.sha256(
            json.dumps(
                inventory,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        key = (str(site), identity)
        cached = False
        for old_key, old_watch in _EXECUTION_CACHE.items():
            if old_key[0] == str(site):
                old_watch.require_unchanged()
                cached = cached or old_key == key
        if cached:
            return
        watch = lease if lease is not None else prepare_execution_lease(site, inventory)
        if watch is not None:
            _require(watch._root is None or watch._root.resolve() == root.resolve())
            watch.protect_tree(site)
        try:
            verify_dependency_tree(site, inventory)
            if watch is not None:
                watch.require_unchanged()
                _EXECUTION_CACHE[key] = watch
        except BaseException:
            if watch is not None:
                watch.close()
            raise
    except RuntimeIntegrityError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        raise RuntimeIntegrityError() from None


def close_execution_leases_for_maintenance() -> None:
    """Trusted maintenance holds the port and proves quiescence before this call."""
    global _TECHNICAL_PROCESS_ONLY
    _TECHNICAL_PROCESS_ONLY = True
    for watch in _EXECUTION_CACHE.values():
        watch.close()
    _close_watches()
    _EXECUTION_CACHE.clear()
