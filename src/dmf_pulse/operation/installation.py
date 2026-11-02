"""Offline reviewed release installation, activation and rollback.

Maintenance accepts only signatures under the already installed owner trust.
Initial trust is provisioned separately by the one-time accepted private carrier;
there is deliberately no public command for importing replacement trust JSON.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import Field

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.operation.maintenance import (
    RootTrust,
    _read,
    _safe_path,
    material_policy_sha256,
    operator_root,
    protected_package_sha256,
    verify_installed_wheel,
)
from dmf_pulse.operation.models import Metadata, OperationError, Sha
from dmf_pulse.operation.release_signatures import SignedReleaseManifest, verify_signed_manifest
from dmf_pulse.operation.standing import StandingPolicy, validate_policy
from dmf_pulse.operation.wheel import RESOURCE, _record_hash, _wheel_members


class InstallationInventory(Metadata):
    schema_version: Literal["operator-installation-inventory-v1"] = (
        "operator-installation-inventory-v1"
    )
    uv_sha256: Sha
    uv_bytes: Annotated[int, Field(ge=1, le=100_663_296)]
    host_python_sha256: Sha
    execution_python_sha256: Sha
    host_pyvenv_cfg_sha256: Sha
    release_pyvenv_cfg_sha256: Sha
    pyproject_sha256: Sha
    lock_sha256: Sha
    bootstrap_python_sha256: Sha
    bootstrap_powershell_sha256: Sha
    command_launcher_sha256: Sha
    dependency_tree_sha256: Sha
    locked_runtime_dependencies: Literal[31] = 31
    offline_only: Literal[True] = True
    application_bytecode: Literal["FORBIDDEN"] = "FORBIDDEN"


def _file_sha(path: Path, *, maximum: int = 67_108_864) -> str:
    _safe_path(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise OperationError("INSTALLATION_ARTIFACT_INVALID")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _dependency_tree(path: Path) -> dict[str, Any]:
    value = _read(path, maximum=4_194_304)
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise OperationError("REVIEWED_DEPENDENCY_INVENTORY_INVALID")
    return value


def authenticate_wheel(path: Path) -> tuple[dict[str, bytes], str, StandingPolicy]:
    members, digest = _wheel_members(path)
    records = [name for name in members if name.endswith(".dist-info/RECORD")]
    if len(records) != 1 or RESOURCE not in members:
        raise OperationError("REVIEWED_WHEEL_RECORD_INVALID")
    rows = list(csv.reader(io.StringIO(members[records[0]].decode("utf-8"))))
    if len(rows) != len(members) or {row[0] for row in rows} != set(members):
        raise OperationError("REVIEWED_WHEEL_RECORD_INVALID")
    for row in rows:
        if len(row) != 3:
            raise OperationError("REVIEWED_WHEEL_RECORD_INVALID")
        name, checksum, size = row
        if not name.startswith(("dmf_pulse/", "dmf_pulse-0.2.0.dist-info/")):
            raise OperationError("REVIEWED_WHEEL_UNEXPECTED_INSTALL_TARGET")
        if name == records[0]:
            if checksum or size:
                raise OperationError("REVIEWED_WHEEL_RECORD_INVALID")
        elif checksum != _record_hash(members[name]) or size != str(len(members[name])):
            raise OperationError("REVIEWED_WHEEL_RECORD_INVALID")
        if name.endswith((".pyc", ".pyo")) or "__pycache__" in name.split("/"):
            raise OperationError("APPLICATION_BYTECODE_FORBIDDEN")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise OperationError("REVIEWED_WHEEL_DUPLICATE_REGISTRY_FIELD")
            value[key] = item
        return value

    registry = json.loads(members[RESOURCE], object_pairs_hook=unique)
    if (
        registry.get("schema_version") != "trusted-refresh-enrollments-v3"
        or set(registry)
        != {
            "schema_version",
            "approvals",
            "qualifications",
            "release_permits",
            "default_authorization_id",
            "standing_policy",
        }
        or any(registry[name] != [] for name in ("approvals", "qualifications", "release_permits"))
        or registry["default_authorization_id"] is not None
    ):
        raise OperationError("STANDING_PRIVATE_WHEEL_REQUIRED")
    policy = validate_policy(registry["standing_policy"])
    code = hashlib.sha256()
    for name in sorted(
        (name for name in members if name.startswith("dmf_pulse/") and name != RESOURCE),
        key=lambda name: Path(name),
    ):
        code.update(name.removeprefix("dmf_pulse/").encode() + b"\0" + members[name] + b"\0")
    if code.hexdigest()[:40] != policy.implementation_sha:
        raise OperationError("REVIEWED_WHEEL_IMPLEMENTATION_INVALID")
    return members, digest, policy


def validate_installed_members(site: Path, members: dict[str, bytes]) -> None:
    expected = {name: body for name, body in members.items() if name.startswith("dmf_pulse/")}
    observed = set()
    for path in (site / "dmf_pulse").rglob("*"):
        _safe_path(path)
        if path.is_dir():
            if path.name == "__pycache__":
                raise OperationError("APPLICATION_BYTECODE_FORBIDDEN")
            continue
        name = path.relative_to(site).as_posix()
        if name not in expected or _file_sha(path) != hashlib.sha256(expected[name]).hexdigest():
            raise OperationError("INSTALLED_REVIEWED_PACKAGE_CHANGED")
        observed.add(name)
    if observed != set(expected):
        raise OperationError("INSTALLED_REVIEWED_PACKAGE_INCOMPLETE")


def _closed_environment(venv: Path | None = None) -> dict[str, str]:
    from dmf_pulse.operation.local_control import original_installation_root

    local = original_installation_root().parents[1]
    temporary = local / "Temp"
    if not temporary.is_dir():
        raise OperationError("OWNER_TEMP_DIRECTORY_REQUIRED")
    system = Path(os.environ["SYSTEMROOT"])
    result = {
        "SYSTEMROOT": str(system),
        "WINDIR": str(system),
        "COMSPEC": str(system / "System32/cmd.exe"),
        "PATH": str(system / "System32"),
        "LOCALAPPDATA": str(local),
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "UV_OFFLINE": "1",
        "UV_NO_BUILD": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_NO_PROGRESS": "1",
    }
    if venv is not None:
        result["VIRTUAL_ENV"] = str(venv)
    return result


def _run(arguments: list[str], *, cwd: Path, environment: dict[str, str], log: Path) -> None:
    with log.open("xb") as stream:
        try:
            result = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=environment,
                cwd=cwd,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise OperationError("OFFLINE_INSTALLATION_COMMAND_FAILED") from None
    if result.returncode != 0:
        raise OperationError("OFFLINE_INSTALLATION_COMMAND_FAILED")


def _same_policy(
    trust: RootTrust,
    signed: SignedReleaseManifest,
    policy: StandingPolicy,
    inventory: InstallationInventory,
) -> None:
    manifest = signed.manifest
    verify_signed_manifest(signed, trust.review_public_key)
    if signed.review_public_key_sha256 != trust.review_public_key_sha256:
        raise OperationError("INSTALLATION_REVIEW_AUTHORITY_CHANGED")
    now = datetime.now(UTC)
    if (
        not trust.accepted_at
        == policy.accepted_at
        <= manifest.reviewed_at
        <= now
        < policy.valid_until
    ):
        raise OperationError("REVIEWED_INSTALLATION_TIME_OR_PERMISSION_INVALID")
    if (
        manifest.owner_acceptance_sha256 != trust.owner_acceptance_sha256
        or policy.owner_acceptance_sha256 != trust.owner_acceptance_sha256
        or manifest.material_policy_sha256 != trust.material_policy_sha256
        or material_policy_sha256(policy) != trust.material_policy_sha256
        or manifest.original_ledger_id != trust.original_ledger_id
        or policy.ledger_id != trust.original_ledger_id
        or manifest.implementation_sha != policy.implementation_sha
        or manifest.protected_numerical_sha256 != policy.protected_numerical_sha256
        or manifest.independent_review_sha256 != policy.independent_review_sha256
        or manifest.installation_inventory_sha256 != inventory.semantic_sha256
        or inventory.lock_sha256 != policy.dependency_lock_sha256
        or inventory.pyproject_sha256 != policy.dependency_project_sha256
        or inventory.dependency_tree_sha256 != policy.dependency_tree_sha256
        or inventory.execution_python_sha256 != policy.python_platform_sha256
    ):
        raise OperationError("MATERIAL_SCOPE_CHANGE_REQUIRES_OWNER_REVIEW")


def _install_reviewed_carrier(carrier: Path, *, root: Path, trust: RootTrust) -> Path:
    """Internal shared installer; initial trust must already be accepted externally."""
    _safe_path(carrier)
    _safe_path(root)
    if (root / "withdrawn.json").exists():
        raise OperationError("STANDING_AUTHORITY_WITHDRAWN")
    signed = SignedReleaseManifest.model_validate_json(
        json.dumps(_read(carrier / "active-release.json"))
    )
    inventory = InstallationInventory.model_validate_json(
        json.dumps(_read(carrier / "installation-inventory.json"))
    )
    wheel = carrier / "dmf_pulse-0.2.0-py3-none-any.whl"
    members, wheel_sha, policy = authenticate_wheel(wheel)
    _same_policy(trust, signed, policy, inventory)
    if wheel_sha != signed.manifest.wheel_sha256:
        raise OperationError("REVIEWED_WHEEL_IDENTITY_CHANGED")
    dependency_tree = _dependency_tree(carrier / "dependency-tree.json")
    if canonical_sha256(dependency_tree) != inventory.dependency_tree_sha256:
        raise OperationError("REVIEWED_DEPENDENCY_INVENTORY_CHANGED")
    from dmf_pulse.operation.local_control import original_installation_root

    local = original_installation_root().parents[1]
    uv = (
        local
        / "Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe"
    )
    host = original_installation_root() / "venv/Scripts/python.exe"
    if (
        uv.stat().st_size != inventory.uv_bytes
        or _file_sha(uv, maximum=inventory.uv_bytes) != inventory.uv_sha256
        or _file_sha(host) != inventory.host_python_sha256
        or _file_sha(host.parent.parent / "pyvenv.cfg") != inventory.host_pyvenv_cfg_sha256
    ):
        raise OperationError("REVIEWED_INSTALLATION_TOOL_CHANGED")
    for name, expected in (
        ("pyproject.toml", inventory.pyproject_sha256),
        ("uv.lock", inventory.lock_sha256),
        ("launch_start.py", inventory.bootstrap_python_sha256),
        ("Launch-DMFPulse.ps1", inventory.bootstrap_powershell_sha256),
        ("dmf.cmd", inventory.command_launcher_sha256),
    ):
        if _file_sha(carrier / name) != expected:
            raise OperationError("REVIEWED_INSTALLATION_CARRIER_CHANGED")
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / wheel_sha
    _safe_path(release)
    if release.exists():
        try:
            retained = _read(release / "active-release.json")
            if retained != signed.model_dump(mode="json"):
                raise OperationError("EXISTING_RELEASE_IDENTITY_DIFFERS")
            _authenticate_retained_release(root, release)
            return release
        except (OSError, ValueError, OperationError):
            active_path = root / "active-release.json"
            if active_path.exists() and _read(active_path) == signed.model_dump(mode="json"):
                raise OperationError("ACTIVE_RELEASE_REPAIR_REQUIRES_TECHNICAL_REVIEW") from None
            failed = releases / f"{wheel_sha}.failed.{uuid4().hex}"
            if (
                release.resolve().parent != releases.resolve()
                or failed.absolute().parent != releases.resolve()
            ):
                raise OperationError("INSTALLATION_PATH_ESCAPE") from None
            release.rename(failed)
    release.mkdir()
    # Use the final content address while constructing Windows console launchers;
    # relocating a completed venv would invalidate their embedded Python path.
    for name, expected in (
        ("pyproject.toml", inventory.pyproject_sha256),
        ("uv.lock", inventory.lock_sha256),
        ("launch_start.py", inventory.bootstrap_python_sha256),
        ("Launch-DMFPulse.ps1", inventory.bootstrap_powershell_sha256),
        ("dmf.cmd", inventory.command_launcher_sha256),
        (wheel.name, wheel_sha),
    ):
        with (carrier / name).open("rb") as stream:
            body = stream.read(67_108_865)
        if len(body) > 67_108_864 or hashlib.sha256(body).hexdigest() != expected:
            raise OperationError("REVIEWED_CARRIER_CHANGED_DURING_INSTALLATION")
        (release / name).write_bytes(body)
    (release / "active-release.json").write_bytes(
        canonical_json_bytes(signed.model_dump(mode="json")) + b"\n"
    )
    (release / "installation-inventory.json").write_bytes(
        canonical_json_bytes(inventory.model_dump(mode="json")) + b"\n"
    )
    (release / "dependency-tree.json").write_bytes(canonical_json_bytes(dependency_tree) + b"\n")
    inspected = release / "inspection"
    for name, body in members.items():
        if name.startswith("dmf_pulse/"):
            target = inspected / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
    if protected_package_sha256(inspected / "dmf_pulse") != policy.protected_numerical_sha256:
        raise OperationError("PROTECTED_NUMERICAL_PACKAGE_CHANGED")
    environment = _closed_environment()
    venv = release / "venv"
    _run(
        [
            str(uv),
            "--no-config",
            "venv",
            "--offline",
            "--no-python-downloads",
            "--python",
            str(host),
            str(venv),
        ],
        cwd=release,
        environment=environment,
        log=release / "create-venv.log",
    )
    _run(
        [
            str(uv),
            "--no-config",
            "sync",
            "--frozen",
            "--offline",
            "--no-dev",
            "--no-install-project",
            "--no-editable",
            "--no-build",
            "--no-compile-bytecode",
            "--active",
        ],
        cwd=release,
        environment=_closed_environment(venv),
        log=release / "install-dependencies.log",
    )
    _run(
        [
            str(uv),
            "--no-config",
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--no-build",
            "--no-compile-bytecode",
            "--python",
            str(venv / "Scripts/python.exe"),
            str(release / wheel.name),
        ],
        cwd=release,
        environment=environment,
        log=release / "install-application.log",
    )
    site = venv / "Lib/site-packages"
    validate_installed_members(site, members)
    if (
        _file_sha(venv / "pyvenv.cfg") != inventory.release_pyvenv_cfg_sha256
        or (venv / "Scripts/pyvenv.cfg").exists()
        or tuple(venv.glob("*._pth"))
        or tuple((venv / "Scripts").glob("*._pth"))
    ):
        raise OperationError("REVIEWED_INTERPRETER_SELECTION_CHANGED")
    from dmf_pulse.operation.runtime_integrity import verify_dependency_tree

    verify_dependency_tree(site, dependency_tree)
    if protected_package_sha256(site / "dmf_pulse") != policy.protected_numerical_sha256:
        raise OperationError("INSTALLED_NUMERICAL_PACKAGE_CHANGED")
    (release / "installation-receipt.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "operator-installed-release-v1",
                "wheel_sha256": wheel_sha,
                "manifest_sha256": signed.semantic_sha256,
                "inventory_sha256": inventory.semantic_sha256,
                "installed_at": datetime.now(UTC).isoformat(),
                "canonical_ledger_id": trust.original_ledger_id,
                "provider_requests": 0,
            }
        )
        + b"\n"
    )
    return release


def activate_reviewed_release(carrier: Path) -> Path:
    """Maintenance only: neither caller paths nor JSON can replace owner trust."""
    root = operator_root()
    trust = RootTrust.model_validate_json(json.dumps(_read(root / "root-trust.json")))
    signed = SignedReleaseManifest.model_validate_json(
        json.dumps(_read(carrier / "active-release.json"))
    )
    inventory = InstallationInventory.model_validate_json(
        json.dumps(_read(carrier / "installation-inventory.json"))
    )
    _, _, incoming = authenticate_wheel(carrier / "dmf_pulse-0.2.0-py3-none-any.whl")
    _same_policy(trust, signed, incoming, inventory)
    if signed.manifest.release_class != "WITHIN_POLICY_COMPATIBILITY":
        raise OperationError("REVIEWED_COMPATIBILITY_RELEASE_REQUIRED")
    with _maintenance_lease(incoming):
        release = _install_reviewed_carrier(carrier, root=root, trust=trust)
        _activate(root, release)
        return release


def _activate(root: Path, release: Path) -> None:
    _safe_path(root)
    _safe_path(release)
    inventory, signed = _authenticate_retained_release(root, release)
    payloads = {}
    for name, expected in (
        ("launch_start.py", inventory.bootstrap_python_sha256),
        ("Launch-DMFPulse.ps1", inventory.bootstrap_powershell_sha256),
        ("dmf.cmd", inventory.command_launcher_sha256),
    ):
        with (release / name).open("rb") as stream:
            body = stream.read(262145)
        if len(body) > 262144 or hashlib.sha256(body).hexdigest() != expected:
            raise OperationError("RETAINED_BOOTSTRAP_CHANGED_DURING_ACTIVATION")
        payloads[name] = body
    current = root / "active-release.json"
    if current.exists():
        history = root / "activation-history"
        history.mkdir(exist_ok=True)
        shutil.copyfile(current, history / f"{uuid4().hex}.json")
    for name, body in payloads.items():
        temporary = root / f".{name}-{uuid4().hex}"
        temporary.write_bytes(body)
        os.replace(temporary, root / name)
    pending = root / f".activate-{uuid4().hex}.json"
    pending.write_bytes(canonical_json_bytes(signed.model_dump(mode="json")) + b"\n")
    os.replace(pending, current)


def _authenticate_retained_release(
    root: Path, release: Path
) -> tuple[InstallationInventory, SignedReleaseManifest]:
    trust = RootTrust.model_validate_json(json.dumps(_read(root / "root-trust.json")))
    signed = SignedReleaseManifest.model_validate_json(
        json.dumps(_read(release / "active-release.json"))
    )
    inventory = InstallationInventory.model_validate_json(
        json.dumps(_read(release / "installation-inventory.json"))
    )
    members, digest, policy = authenticate_wheel(release / "dmf_pulse-0.2.0-py3-none-any.whl")
    _same_policy(trust, signed, policy, inventory)
    if digest != release.name or digest != signed.manifest.wheel_sha256:
        raise OperationError("RETAINED_RELEASE_IDENTITY_CHANGED")
    for name, expected in (
        ("pyproject.toml", inventory.pyproject_sha256),
        ("uv.lock", inventory.lock_sha256),
        ("launch_start.py", inventory.bootstrap_python_sha256),
        ("Launch-DMFPulse.ps1", inventory.bootstrap_powershell_sha256),
        ("dmf.cmd", inventory.command_launcher_sha256),
    ):
        if _file_sha(release / name) != expected:
            raise OperationError("RETAINED_INSTALLATION_CARRIER_CHANGED")
    dependency_tree = _dependency_tree(release / "dependency-tree.json")
    if canonical_sha256(dependency_tree) != inventory.dependency_tree_sha256:
        raise OperationError("RETAINED_DEPENDENCY_INVENTORY_CHANGED")
    site = release / "venv/Lib/site-packages"
    if (
        _file_sha(release / "venv/pyvenv.cfg") != inventory.release_pyvenv_cfg_sha256
        or (release / "venv/Scripts/pyvenv.cfg").exists()
        or tuple((release / "venv").glob("*._pth"))
        or tuple((release / "venv/Scripts").glob("*._pth"))
    ):
        raise OperationError("RETAINED_INTERPRETER_SELECTION_CHANGED")
    validate_installed_members(site, members)
    verify_installed_wheel(site / "dmf_pulse", release / "dmf_pulse-0.2.0-py3-none-any.whl", digest)
    from dmf_pulse.operation.runtime_integrity import verify_dependency_tree

    verify_dependency_tree(site, dependency_tree)
    if protected_package_sha256(site / "dmf_pulse") != policy.protected_numerical_sha256:
        raise OperationError("RETAINED_NUMERICAL_PACKAGE_CHANGED")
    return inventory, signed


@contextmanager
def _maintenance_lease(policy: StandingPolicy) -> Iterator[None]:
    from dmf_pulse.operation.journal import OperationJournal
    from dmf_pulse.operation.local_control import recover_local_control

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 8765))
    except OSError:
        listener.close()
        raise OperationError("CLOSE_DASHBOARD_BEFORE_REVIEWED_MAINTENANCE") from None
    try:
        recover_local_control(policy)
        journal = OperationJournal.production(policy)
        journal.require_no_live_execution(now=datetime.now(UTC))
        from dmf_pulse.operation.maintenance import close_execution_leases_for_maintenance

        close_execution_leases_for_maintenance()
        yield
    finally:
        listener.close()


def rollback_reviewed_release(wheel_sha256: str) -> Path:
    root = operator_root()
    if len(wheel_sha256) != 64 or any(c not in "0123456789abcdef" for c in wheel_sha256):
        raise OperationError("ROLLBACK_RELEASE_ID_INVALID")
    trust = RootTrust.model_validate_json(json.dumps(_read(root / "root-trust.json")))
    release = root / "releases" / wheel_sha256
    signed = SignedReleaseManifest.model_validate_json(
        json.dumps(_read(release / "active-release.json"))
    )
    inventory = InstallationInventory.model_validate_json(
        json.dumps(_read(release / "installation-inventory.json"))
    )
    members, digest, policy = authenticate_wheel(release / "dmf_pulse-0.2.0-py3-none-any.whl")
    _same_policy(trust, signed, policy, inventory)
    if digest != wheel_sha256:
        raise OperationError("ROLLBACK_RELEASE_IDENTITY_CHANGED")
    for name, expected in (
        ("launch_start.py", inventory.bootstrap_python_sha256),
        ("Launch-DMFPulse.ps1", inventory.bootstrap_powershell_sha256),
        ("dmf.cmd", inventory.command_launcher_sha256),
    ):
        if _file_sha(release / name) != expected:
            raise OperationError("ROLLBACK_BOOTSTRAP_CHANGED")
    validate_installed_members(release / "venv/Lib/site-packages", members)
    with _maintenance_lease(policy):
        _activate(root, release)
        return release
