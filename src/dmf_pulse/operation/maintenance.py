"""Fixed installed review trust and strictly bounded compatibility releases."""

from __future__ import annotations

import base64
import csv
import ctypes
import hashlib
import io
import json
import os
import stat
import sys
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Sha
from dmf_pulse.operation.release_signatures import (
    ReleaseManifest,
    ReviewPublicKey,
    SignedReleaseManifest,
    verify_signed_manifest,
)
from dmf_pulse.operation.runtime_integrity import DirectoryWatch, RuntimeIntegrityError, _new_watch


@dataclass(frozen=True, slots=True, repr=False)
class _ReleaseCache:
    root: Path
    package_root: Path
    policy: Metadata
    policy_sha256: str
    controls: tuple[str, str]
    manifest: ReleaseManifest
    watch: DirectoryWatch


_RELEASE_CACHE: dict[str, _ReleaseCache] = {}
_TECHNICAL_PROCESS_ONLY = False
_HOST_CONFIGURATION_SHA256 = "fd505d93d8c7e1e7589de8e6dbab3d86664f282b9ebbfe107a8e854c8daacd0f"
_PLATFORM_DLLS = {
    "python313.dll": "e1ff5878af41e21bf64b9916ed6735ca30ce48623e3d941fdd1460a541611596",
    "python3.dll": "40039942e112e8d252a676940d802a93bc98d681880d6326147f4a4da772bfb7",
}

# Only these existing reviewed glue/UI/credential files are maintenance-variable.
# Every ingestion, rules, solver, model and other package file remains protected.
COMPATIBILITY_FILES = frozenset(
    {
        "cli/app.py",
        "cli/credentials.py",
        "cli/start.py",
        "credentials/service.py",
        "credentials/jwt.py",
        "dashboard/app.py",
        "dashboard/current.py",
        "dashboard/current_sources.py",
        "dashboard/postgres_authorization.py",
        "dashboard/runtime.py",
        "dashboard/views.py",
        "current_failures.py",
        "dashboard/resources/desk.js",
        "dashboard/resources/production_refresh_enrollments.json",
    }
)
MATERIAL_EXCLUSIONS = frozenset(
    {
        "implementation_sha",
        "independent_review_sha256",
        "owner_acceptance_sha256",
        "accepted_at",
    }
)


class RootTrust(Metadata):
    schema_version: Literal["operator-root-trust-v1"] = "operator-root-trust-v1"
    review_public_key: ReviewPublicKey
    review_public_key_sha256: Sha
    owner_acceptance_sha256: Sha
    material_policy_sha256: Sha
    original_ledger_id: Sha
    accepted_at: datetime

    @model_validator(mode="after")
    def exact_key_pin(self) -> Self:
        if self.review_public_key_sha256 != self.review_public_key.fingerprint_sha256:
            raise ValueError("installed root review key differs from its pin")
        return self


def material_policy_sha256(policy: Metadata | Mapping[str, object]) -> str:
    value = policy.model_dump(mode="json") if isinstance(policy, Metadata) else dict(policy)
    return canonical_sha256(
        {key: item for key, item in value.items() if key not in MATERIAL_EXCLUSIONS}
    )


def _safe_path(path: Path) -> Path:
    for node in (path.absolute(), *path.absolute().parents):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OperationError("MAINTENANCE_REPARSE_PATH_DENIED")
    return path


def _read(path: Path, maximum: int = 262144) -> object:
    path = _safe_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise OperationError("MAINTENANCE_METADATA_INVALID")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate metadata field")
            value[key] = item
        return value

    body = path.read_bytes()
    if len(body) != info.st_size:
        raise OperationError("MAINTENANCE_METADATA_CHANGED_DURING_READ")
    return json.loads(body, object_pairs_hook=unique)


def protected_package_sha256(package_root: Path) -> str:
    package_root = _safe_path(package_root)
    if not package_root.is_dir():
        raise OperationError("PROTECTED_PACKAGE_ROOT_INVALID")
    digest = hashlib.sha256()
    paths = sorted(package_root.rglob("*"))
    if not paths or len(paths) > 10000:
        raise OperationError("PROTECTED_PACKAGE_INVENTORY_INVALID")
    total = 0
    for path in paths:
        _safe_path(path)
        relative = path.relative_to(package_root).as_posix()
        if "__pycache__" in path.parts or path.suffix.casefold() in {".pyc", ".pyo"}:
            raise OperationError("APPLICATION_BYTECODE_FORBIDDEN")
        if path.is_dir():
            continue
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise OperationError("PROTECTED_PACKAGE_FILE_INVALID")
        total += info.st_size
        if total > 256 * 1024 * 1024:
            raise OperationError("PROTECTED_PACKAGE_INVENTORY_INVALID")
        if relative.startswith("operation/") or relative in COMPATIBILITY_FILES:
            continue
        body = path.read_bytes()
        if len(body) != info.st_size:
            raise OperationError("PROTECTED_PACKAGE_CHANGED_DURING_READ")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
    return digest.hexdigest()


def operator_root_path() -> Path:
    """No caller policy, environment override or JSON path selects the trust root."""
    if os.name == "nt":
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise OperationError("OWNER_LOCAL_APPLICATION_FOLDER_UNAVAILABLE")
        function = loader("shell32").SHGetFolderPathW
        function.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_wchar_p,
        ]
        function.restype = ctypes.c_long
        buffer = ctypes.create_unicode_buffer(32768)
        if function(None, 0x001C, None, 0, buffer) != 0:
            raise OperationError("OPERATOR_ROOT_UNAVAILABLE")
        return _safe_path(Path(buffer.value) / "DMFPulse/operator")
    return _safe_path(Path.home() / ".local/share/DMFPulse/operator")


def operator_root() -> Path:
    return operator_root_path()


def _installation_tools() -> tuple[Path, Path]:
    from dmf_pulse.operation.local_control import original_installation_root

    original = original_installation_root()
    uv = (
        original.parents[1]
        / "Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe"
    )
    return uv, original / "venv/Scripts/python.exe"


def _file_sha(path: Path, maximum: int = 67_108_864) -> str:
    path = _safe_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= maximum:
        raise OperationError("STANDING_INSTALLATION_ARTIFACT_INVALID")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _execution_python_path(host: Path) -> Path:
    cfg = host.parent.parent / "pyvenv.cfg"
    _safe_path(cfg)
    with cfg.open("rb") as stream:
        body = stream.read(16385)
    if len(body) > 16384 or hashlib.sha256(body).hexdigest() != _HOST_CONFIGURATION_SHA256:
        raise OperationError("STANDING_PYTHON_CONFIGURATION_CHANGED")
    homes = [
        line.partition("=")[2].strip()
        for line in body.decode("utf-8").splitlines()
        if line.partition("=")[0].strip() == "home"
    ]
    if len(homes) != 1 or not Path(homes[0]).is_absolute():
        raise OperationError("STANDING_PYTHON_CONFIGURATION_CHANGED")
    return _safe_path(Path(homes[0]) / "python.exe")


def _verify_installation_inventory(
    policy: Metadata,
    manifest: ReleaseManifest,
    root: Path,
    tools: tuple[Path, Path],
    *,
    for_execution: bool = False,
    execution_python: Path | None = None,
) -> None:
    # Late import: installation also consumes RootTrust and the public verifier.
    from dmf_pulse.operation.installation import InstallationInventory

    release = root / "releases" / manifest.wheel_sha256
    inventory = InstallationInventory.model_validate_json(
        json.dumps(_read(release / "installation-inventory.json"))
    )
    values = policy.model_dump(mode="json")
    if (
        inventory.semantic_sha256 != manifest.installation_inventory_sha256
        or inventory.lock_sha256 != values.get("dependency_lock_sha256")
        or inventory.pyproject_sha256 != values.get("dependency_project_sha256")
    ):
        raise OperationError("STANDING_INSTALLATION_INVENTORY_CHANGED")
    tree = _read(release / "dependency-tree.json", maximum=4194304)
    if (
        not isinstance(tree, dict)
        or canonical_sha256(tree) != inventory.dependency_tree_sha256
        or inventory.dependency_tree_sha256 != values.get("dependency_tree_sha256")
    ):
        raise OperationError("STANDING_DEPENDENCY_INVENTORY_CHANGED")
    from dmf_pulse.operation.runtime_integrity import (
        verify_dependency_tree,
        verify_dependency_tree_for_execution,
    )

    try:
        verifier = verify_dependency_tree_for_execution if for_execution else verify_dependency_tree
        verifier(release_package_path(root, manifest.wheel_sha256).parent, tree)
    except RuntimeIntegrityError as error:
        raise OperationError(
            "STANDING_DEPENDENCY_TREE_CHANGED", integrity_reason=error.reason
        ) from None
    python = release / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if _file_sha(python) != inventory.host_python_sha256:
        raise OperationError("STANDING_RELEASE_PYTHON_CHANGED")
    if _file_sha(python.parent.parent / "pyvenv.cfg") != inventory.release_pyvenv_cfg_sha256:
        raise OperationError("STANDING_PYTHON_CONFIGURATION_CHANGED")
    _require_no_python_overrides(python.parent)
    uv, host = tools
    if (
        uv.stat().st_size != inventory.uv_bytes
        or _file_sha(uv, inventory.uv_bytes) != inventory.uv_sha256
        or _file_sha(host) != inventory.host_python_sha256
        or _file_sha(host.parent.parent / "pyvenv.cfg") != inventory.host_pyvenv_cfg_sha256
    ):
        raise OperationError("STANDING_INSTALLATION_TOOL_CHANGED")
    executor = _execution_python_path(host) if execution_python is None else execution_python
    if (
        inventory.execution_python_sha256 != values.get("python_platform_sha256")
        or _file_sha(executor) != inventory.execution_python_sha256
    ):
        raise OperationError("STANDING_EXECUTION_PYTHON_CHANGED")
    if execution_python is None:
        _require_no_python_overrides(executor.parent)
        for name, digest in _PLATFORM_DLLS.items():
            if _file_sha(executor.parent / name) != digest:
                raise OperationError("STANDING_EXECUTION_PYTHON_CHANGED")
    files = (
        ("pyproject.toml", inventory.pyproject_sha256),
        ("uv.lock", inventory.lock_sha256),
        ("launch_start.py", inventory.bootstrap_python_sha256),
        ("Launch-DMFPulse.ps1", inventory.bootstrap_powershell_sha256),
        ("dmf.cmd", inventory.command_launcher_sha256),
    )
    for name, digest in files:
        if _file_sha(release / name) != digest:
            raise OperationError("STANDING_INSTALLATION_CARRIER_CHANGED")
        if (
            name in {"launch_start.py", "Launch-DMFPulse.ps1", "dmf.cmd"}
            and _file_sha(root / name) != digest
        ):
            raise OperationError("STANDING_ACTIVE_BOOTSTRAP_CHANGED")


def release_package_path(root: Path, wheel_sha256: str) -> Path:
    # Sha validation is independent of any path supplied in JSON.
    class Identity(Metadata):
        sha256: Sha

    identity = Identity(sha256=wheel_sha256).sha256
    site = (
        Path("Lib/site-packages")
        if os.name == "nt"
        else Path(f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
    )
    return root / "releases" / identity / "venv" / site / "dmf_pulse"


def verify_installed_wheel(package_root: Path, wheel_path: Path, wheel_sha256: str) -> None:
    """Check executable bytes against the signed retained wheel, including its RECORD."""
    package_root, wheel_path = _safe_path(package_root), _safe_path(wheel_path)
    info = wheel_path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 64 * 1024 * 1024:
        raise OperationError("STANDING_RETAINED_WHEEL_INVALID")
    body = wheel_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != wheel_sha256:
        raise OperationError("STANDING_RETAINED_WHEEL_CHANGED")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not 1 <= len(names) <= 10000:
            raise OperationError("STANDING_WHEEL_INVENTORY_INVALID")
        record_name = "dmf_pulse-0.2.0.dist-info/RECORD"
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
        if any(len(row) != 3 for row in rows):
            raise OperationError("STANDING_WHEEL_RECORD_INVALID")
        records = {row[0]: row[1:] for row in rows}
        if len(records) != len(rows) or set(records) != set(names):
            raise OperationError("STANDING_WHEEL_RECORD_INVALID")
        package_names: set[str] = set()
        total = 0
        for item in archive.infolist():
            name = item.filename
            if (
                item.is_dir()
                or "\\" in name
                or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or not name.startswith(("dmf_pulse/", "dmf_pulse-0.2.0.dist-info/"))
                or item.file_size > 16 * 1024 * 1024
            ):
                raise OperationError("STANDING_WHEEL_INVENTORY_INVALID")
            total += item.file_size
            if total > 256 * 1024 * 1024:
                raise OperationError("STANDING_WHEEL_INVENTORY_INVALID")
            value = archive.read(item)
            if name == record_name:
                if records[name] != ["", ""]:
                    raise OperationError("STANDING_WHEEL_RECORD_INVALID")
            else:
                encoded = (
                    base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
                )
                if records[name] != ["sha256=" + encoded, str(len(value))]:
                    raise OperationError("STANDING_WHEEL_RECORD_INVALID")
                installed = _safe_path(package_root.parent / name)
                file_info = installed.stat()
                if (
                    not stat.S_ISREG(file_info.st_mode)
                    or file_info.st_size != len(value)
                    or installed.read_bytes() != value
                ):
                    raise OperationError("STANDING_INSTALLED_WHEEL_BYTES_CHANGED")
            if name.startswith("dmf_pulse/"):
                package_names.add(name.removeprefix("dmf_pulse/"))
        actual = {
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if not path.is_dir()
        }
        if actual != package_names:
            raise OperationError("STANDING_INSTALLED_PACKAGE_INVENTORY_CHANGED")
        _verify_installed_record(package_root, wheel_path, set(names))


def _verify_installed_record(package_root: Path, wheel_path: Path, wheel_names: set[str]) -> None:
    site = package_root.parent
    metadata = "dmf_pulse-0.2.0.dist-info/"
    record = metadata + "RECORD"
    record_path = _safe_path(site / record)
    if record_path.stat().st_size > 262144:
        raise OperationError("STANDING_INSTALLED_RECORD_INVALID")
    rows = list(csv.reader(io.StringIO(record_path.read_text(encoding="utf-8"))))
    if any(len(row) != 3 for row in rows) or len({row[0] for row in rows}) != len(rows):
        raise OperationError("STANDING_INSTALLED_RECORD_INVALID")
    generated = {
        metadata + name for name in ("INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json")
    }
    script = "../../Scripts/dmf.exe" if os.name == "nt" else "../../../bin/dmf"
    if {row[0] for row in rows} != wheel_names | generated | {script}:
        raise OperationError("STANDING_INSTALLED_RECORD_INVENTORY_CHANGED")
    for name, checksum, size in rows:
        if name == record:
            if checksum or size:
                raise OperationError("STANDING_INSTALLED_RECORD_INVALID")
            continue
        target = _safe_path(site / name)
        info = target.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise OperationError("STANDING_INSTALLED_RECORD_INVALID")
        value = target.read_bytes()
        digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
        if checksum != "sha256=" + digest or size != str(len(value)):
            raise OperationError("STANDING_INSTALLED_RECORD_BYTES_CHANGED")
    if (site / metadata / "INSTALLER").read_bytes() != b"uv" or (
        site / metadata / "REQUESTED"
    ).read_bytes():
        raise OperationError("STANDING_INSTALLER_METADATA_CHANGED")
    if _read(site / metadata / "direct_url.json") != {
        "url": wheel_path.absolute().as_uri(),
        "archive_info": {},
    }:
        raise OperationError("STANDING_INSTALL_SOURCE_CHANGED")
    cache = _read(site / metadata / "uv_cache.json")
    if (
        not isinstance(cache, dict)
        or set(cache) != {"timestamp", "commit", "tags", "env", "directories"}
        or cache["commit"] is not None
        or cache["tags"] is not None
        or cache["env"] != {}
        or cache["directories"] != {}
    ):
        raise OperationError("STANDING_INSTALLER_METADATA_CHANGED")
    timestamp = cache["timestamp"]
    if (
        not isinstance(timestamp, dict)
        or set(timestamp) != {"secs_since_epoch", "nanos_since_epoch"}
        or any(type(value) is not int or value < 0 for value in timestamp.values())
        or timestamp["nanos_since_epoch"] >= 1_000_000_000
    ):
        raise OperationError("STANDING_INSTALLER_METADATA_CHANGED")


def _verify_active_release_at(
    policy: Metadata,
    *,
    root: Path,
    package_root: Path,
    now: datetime,
    installation_tools: tuple[Path, Path] | None = None,
    for_execution: bool = False,
    execution_python: Path | None = None,
) -> ReleaseManifest:
    """Explicit owned-context seam for tests; normal startup uses fixed roots."""
    root = _safe_path(root)
    now = MetadataTime(checked_at=now).checked_at
    try:
        (root / "withdrawn.json").lstat()
    except FileNotFoundError:
        withdrawn = False
    else:
        withdrawn = True
    if withdrawn:
        raise OperationError("STANDING_PERMISSION_WITHDRAWN")
    trust = RootTrust.model_validate_json(
        json.dumps(_read(root / "root-trust.json"), allow_nan=False)
    )
    signed = SignedReleaseManifest.model_validate_json(
        json.dumps(_read(root / "active-release.json"), allow_nan=False)
    )
    manifest = verify_signed_manifest(signed, trust.review_public_key)
    values = policy.model_dump(mode="json")
    if not (
        trust.accepted_at <= now
        and manifest.reviewed_at <= now
        and manifest.owner_acceptance_sha256
        == trust.owner_acceptance_sha256
        == values.get("owner_acceptance_sha256")
        and manifest.original_ledger_id == trust.original_ledger_id == values.get("ledger_id")
        and manifest.material_policy_sha256
        == trust.material_policy_sha256
        == material_policy_sha256(policy)
        and manifest.implementation_sha == values.get("implementation_sha")
        and manifest.independent_review_sha256 == values.get("independent_review_sha256")
        and manifest.protected_numerical_sha256 == values.get("protected_numerical_sha256")
    ):
        raise OperationError("STANDING_MATERIAL_SCOPE_OR_RELEASE_CHANGED")
    expected = _safe_path(release_package_path(root, manifest.wheel_sha256))
    actual = _safe_path(package_root)
    if actual.resolve(strict=True) != expected.resolve(strict=True):
        raise OperationError("STANDING_INSTALLED_RELEASE_ORIGIN_INVALID")
    if protected_package_sha256(actual) != manifest.protected_numerical_sha256:
        raise OperationError("STANDING_PROTECTED_PACKAGE_CHANGED")
    verify_installed_wheel(
        actual,
        root / "releases" / manifest.wheel_sha256 / "dmf_pulse-0.2.0-py3-none-any.whl",
        manifest.wheel_sha256,
    )
    _verify_installation_inventory(
        policy,
        manifest,
        root,
        _installation_tools() if installation_tools is None else installation_tools,
        for_execution=for_execution,
        execution_python=execution_python,
    )
    return manifest


def verify_active_release(policy: Metadata) -> ReleaseManifest:
    """Only an owner-installed root key can authenticate active compatibility code."""
    try:
        if _TECHNICAL_PROCESS_ONLY:
            raise OperationError("STANDING_TECHNICAL_PROCESS_CANNOT_ACQUIRE")
        _require_entrypoint()
        root = operator_root_path()
        _deny_withdrawal(root)
        package_root = Path(__file__).resolve().parents[1]
        key = str(package_root)
        if key in _RELEASE_CACHE:
            cached = _RELEASE_CACHE[key]
            _check_cached_release(cached, policy)
            return cached.manifest
        watch = _new_watch(root)
        try:
            if watch is not None:
                release = package_root.parents[3 if os.name == "nt" else 4]
                if release.parent.resolve() != (root / "releases").resolve():
                    raise OperationError("STANDING_INSTALLED_RELEASE_ORIGIN_INVALID")
                watch.protect_tree(release)
                uv, host = _installation_tools()
                watch.lock_paths([uv, host, host.parent.parent / "pyvenv.cfg"])
                executor = _execution_python_path(host)
                watch.lock_paths(
                    [
                        root / name
                        for name in (
                            "root-trust.json",
                            "active-release.json",
                            "launch_start.py",
                            "Launch-DMFPulse.ps1",
                            "dmf.cmd",
                        )
                    ]
                    + [
                        uv,
                        host,
                        host.parent.parent / "pyvenv.cfg",
                        executor,
                        *[executor.parent / name for name in _PLATFORM_DLLS],
                    ]
                )
                watch.require_unchanged()
            controls = _control_hashes(root)
            manifest = _verify_active_release_at(
                policy,
                root=root,
                package_root=package_root,
                now=datetime.now(UTC),
                for_execution=True,
            )
            expected = _execution_python_path(_installation_tools()[1])
            if Path(sys.executable).resolve() != expected.resolve():
                raise OperationError("STANDING_REVIEWED_ENTRYPOINT_REQUIRED")
            if watch is not None:
                cached = _ReleaseCache(
                    root, package_root, policy, policy.semantic_sha256, controls, manifest, watch
                )
                _check_cached_release(cached, policy)
                _RELEASE_CACHE[key] = cached
            return manifest
        except BaseException:
            if watch is not None:
                watch.close()
            raise
    except OperationError:
        raise
    except RuntimeIntegrityError as error:
        raise OperationError(
            "STANDING_RELEASE_RESTART_REQUIRED", integrity_reason=error.reason
        ) from None
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        zipfile.BadZipFile,
        RuntimeError,
        csv.Error,
    ):
        raise OperationError("STANDING_RELEASE_AUTHENTICATION_FAILED") from None


def _require_entrypoint() -> None:
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise OperationError("STANDING_REVIEWED_ENTRYPOINT_REQUIRED")


def _require_no_python_overrides(scripts: Path) -> None:
    for name in ("pyvenv.cfg", "python._pth", "python313._pth", "python.exe._pth"):
        try:
            (scripts / name).lstat()
        except FileNotFoundError:
            continue
        raise OperationError("STANDING_PYTHON_CONFIGURATION_CHANGED")


def _deny_withdrawal(root: Path) -> None:
    try:
        (root / "withdrawn.json").lstat()
    except FileNotFoundError:
        withdrawn = False
    else:
        withdrawn = True
    if withdrawn:
        raise OperationError("STANDING_PERMISSION_WITHDRAWN")


def _control_hashes(root: Path) -> tuple[str, str]:
    _deny_withdrawal(root)
    return canonical_sha256(_read(root / "root-trust.json")), canonical_sha256(
        _read(root / "active-release.json")
    )


def _check_cached_release(cached: _ReleaseCache, policy: Metadata) -> None:
    try:
        controls = _control_hashes(cached.root)
        cached.watch.require_unchanged()
        if (
            policy.semantic_sha256 != cached.policy_sha256
            or cached.policy.semantic_sha256 != cached.policy_sha256
            or controls != cached.controls
        ):
            raise OperationError("STANDING_RELEASE_RESTART_REQUIRED")
        values = policy.model_dump()
        accepted, expires = values.get("accepted_at"), values.get("valid_until")
        now = datetime.now(UTC)
        if (
            not isinstance(accepted, datetime)
            or not isinstance(expires, datetime)
            or not accepted <= now < expires
        ):
            raise OperationError("STANDING_PERMISSION_REVIEW_EXPIRED")
    except RuntimeIntegrityError as error:
        raise OperationError(
            "STANDING_RELEASE_RESTART_REQUIRED", integrity_reason=error.reason
        ) from None


def cached_implementation_fingerprint(package_root: Path) -> str | None:
    """Only a fully authenticated release under a live kernel watch can shortcut."""
    if _TECHNICAL_PROCESS_ONLY:
        return None
    key = str(package_root.resolve())
    if key not in _RELEASE_CACHE:
        return None
    cached = _RELEASE_CACHE[key]
    _check_cached_release(cached, cached.policy)
    return cached.manifest.implementation_sha


def close_execution_leases_for_maintenance() -> None:
    """No grant can follow this irreversible per-process technical transition."""
    global _TECHNICAL_PROCESS_ONLY
    from dmf_pulse.operation.runtime_integrity import (
        close_execution_leases_for_maintenance as close_dependencies,
    )

    _TECHNICAL_PROCESS_ONLY = True
    for cached in _RELEASE_CACHE.values():
        cached.watch.close()
    _RELEASE_CACHE.clear()
    close_dependencies()
