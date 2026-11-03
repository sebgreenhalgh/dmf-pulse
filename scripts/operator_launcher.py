"""Installed stdlib bootstrap: verify reviewed bytes before importing the app."""

from __future__ import annotations

import sys

# Spawn restores the parent import path before running __mp_main__. Remove its
# site entry before loading even stdlib helpers, then authenticate it below.
if __name__ == "__mp_main__":
    sys.path[:] = [
        entry
        for entry in sys.path
        if not {"site-packages", "dist-packages"}.intersection(
            entry.replace("\\", "/").casefold().split("/")
        )
    ]

import base64
import csv
import ctypes
import hashlib
import hmac
import io
import json
import os
import re
import stat
import types
import zipfile
from pathlib import Path, PurePosixPath

RESOURCE = "dmf_pulse/dashboard/resources/production_refresh_enrollments.json"
DOMAIN = b"DMF-PULSE-OPERATOR-RELEASE-V1\0"
_APPLICATION_ENTERED = False
INTEGRITY_REASON_CODES = frozenset(
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


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def require(value: object) -> None:
    if not value:
        raise ValueError("OPERATOR_RELEASE_VERIFICATION_FAILED")


def safe(path: Path) -> Path:
    for node in (path.absolute(), *path.absolute().parents):
        information = node.lstat()
        require(
            not stat.S_ISLNK(information.st_mode)
            and not getattr(information, "st_file_attributes", 0) & 0x400
        )
    return path


def read(path: Path, maximum: int = 262144) -> bytes:
    safe(path)
    with path.open("rb") as stream:
        body = stream.read(maximum + 1)
    require(len(body) <= maximum)
    return body


def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def metadata(path: Path) -> dict:
    result = json.loads(read(path), object_pairs_hook=unique)
    require(isinstance(result, dict))
    return result


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def signature_valid(key: dict, manifest: dict, signature: str) -> bool:
    require(set(key) == {"algorithm", "modulus_b64", "exponent"})
    require(
        key["algorithm"] == "RSA3072_SHA256_PKCS1_V1_5"
        and type(key["exponent"]) is int
        and key["exponent"] == 65537
    )
    modulus = base64.b64decode(key["modulus_b64"], validate=True)
    signed = base64.b64decode(signature, validate=True)
    require(len(modulus) == len(signed) == 384)
    require(
        base64.b64encode(modulus).decode() == key["modulus_b64"]
        and base64.b64encode(signed).decode() == signature
    )
    number = int.from_bytes(modulus, "big")
    integer = int.from_bytes(signed, "big")
    require(number.bit_length() == 3072 and number % 2 == 1 and integer < number)
    encoded = pow(integer, 65537, number).to_bytes(384, "big")
    info = (
        bytes.fromhex("3031300d060960864801650304020105000420")
        + hashlib.sha256(DOMAIN + canonical(manifest)).digest()
    )
    expected = b"\x00\x01" + b"\xff" * (384 - len(info) - 3) + b"\x00" + info
    return hmac.compare_digest(encoded, expected)


def installation_root() -> Path:
    require(os.name == "nt")
    function = ctypes.WinDLL("shell32").SHGetFolderPathW
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    ]
    function.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    require(function(None, 0x001C, None, 0, buffer) == 0)
    return Path(buffer.value) / "DMFPulse/operator"


def verified_release(root: Path) -> Path:
    require(not (root / "withdrawn.json").exists())
    trust, signed = metadata(root / "root-trust.json"), metadata(root / "active-release.json")
    require(
        trust["schema_version"] == "operator-root-trust-v1"
        and signed["schema_version"] == "operator-signed-release-v1"
    )
    key, manifest = trust["review_public_key"], signed["manifest"]
    require(
        digest(canonical(key))
        == trust["review_public_key_sha256"]
        == signed["review_public_key_sha256"]
    )
    require(signature_valid(key, manifest, signed["signature_b64"]))
    require(
        all(
            manifest[field] == trust[field]
            for field in ("owner_acceptance_sha256", "material_policy_sha256", "original_ledger_id")
        )
    )
    wheel_sha = manifest["wheel_sha256"]
    require(re.fullmatch(r"[0-9a-f]{64}", wheel_sha) is not None)
    release = root / "releases" / wheel_sha
    inventory = metadata(release / "installation-inventory.json")
    require(digest(canonical(inventory)) == manifest["installation_inventory_sha256"])
    require(metadata(release / "active-release.json") == signed)
    wheel_path = release / "dmf_pulse-0.2.0-py3-none-any.whl"
    wheel = read(wheel_path, 64 * 1024 * 1024)
    require(digest(wheel) == wheel_sha)
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        items = archive.infolist()
        names = [item.filename for item in items]
        require(len(items) <= 2000 and sum(item.file_size for item in items) <= 64 * 1024 * 1024)
        require(len(names) == len({name.casefold() for name in names}))
        for item in items:
            name = item.filename
            require(
                name.startswith(("dmf_pulse/", "dmf_pulse-0.2.0.dist-info/"))
                and not name.endswith("/")
            )
            require(
                "\\" not in name
                and ":" not in name
                and ".." not in PurePosixPath(name).parts
                and not stat.S_ISLNK(item.external_attr >> 16)
            )
        members = {item.filename: archive.read(item) for item in items}
    record = "dmf_pulse-0.2.0.dist-info/RECORD"
    rows = list(csv.reader(io.StringIO(members[record].decode())))
    require(len(rows) == len(members) and {row[0] for row in rows} == set(members))
    for name, checksum, size in rows:
        if name == record:
            require(checksum == size == "")
        else:
            require(
                checksum
                == "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(members[name]).digest())
                .rstrip(b"=")
                .decode()
                and size == str(len(members[name]))
            )
    registry = json.loads(members[RESOURCE], object_pairs_hook=unique)
    require(
        set(registry)
        == {
            "schema_version",
            "approvals",
            "qualifications",
            "release_permits",
            "default_authorization_id",
            "standing_policy",
        }
    )
    require(
        registry["schema_version"] == "trusted-refresh-enrollments-v3"
        and all(registry[name] == [] for name in ("approvals", "qualifications", "release_permits"))
        and registry["default_authorization_id"] is None
    )
    policy = registry["standing_policy"]
    scope = {
        name: value
        for name, value in policy.items()
        if name
        not in {
            "implementation_sha",
            "independent_review_sha256",
            "owner_acceptance_sha256",
            "accepted_at",
        }
    }
    require(digest(canonical(scope)) == trust["material_policy_sha256"])
    require(
        policy["owner_acceptance_sha256"] == trust["owner_acceptance_sha256"]
        and policy["execution_entrypoint"] == "REVIEWED_STDLIB_BOOTSTRAP_ONLY"
    )
    dependency_tree = json.loads(
        read(release / "dependency-tree.json", 4 * 1024 * 1024), object_pairs_hook=unique
    )
    require(
        digest(canonical(dependency_tree))
        == inventory["dependency_tree_sha256"]
        == policy["dependency_tree_sha256"]
    )
    require(
        dependency_tree["lock_sha256"]
        == inventory["lock_sha256"]
        == policy["dependency_lock_sha256"]
    )
    site = release / "venv/Lib/site-packages"
    verifier_name = "dmf_pulse/operation/runtime_integrity.py"
    verifier = types.ModuleType("dmf_pulse.operation.runtime_integrity")
    verifier.__file__ = str(site / verifier_name)
    sys.modules[verifier.__name__] = verifier
    exec(compile(members[verifier_name], verifier.__file__, "exec"), verifier.__dict__)
    lease = verifier.prepare_execution_lease(site, dependency_tree)
    host_cfg = root.parent / "gw10/venv/pyvenv.cfg"
    host_body = read(host_cfg)
    require(digest(host_body) == inventory["host_pyvenv_cfg_sha256"])
    homes = [
        line.split(" = ", 1)[1]
        for line in host_body.decode().splitlines()
        if line.startswith("home = ")
    ]
    require(len(homes) == 1)
    base = Path(homes[0])
    execution_python = base / "python.exe"
    fixed = [
        root / name
        for name in (
            "root-trust.json",
            "active-release.json",
            "launch_start.py",
            "Launch-DMFPulse.ps1",
            "dmf.cmd",
        )
    ]
    if lease is not None:
        lease.protect_tree(release)
        lease.lock_paths(
            [*fixed, host_cfg, execution_python, base / "python313.dll", base / "python3.dll"]
        )
    require(
        metadata(root / "root-trust.json") == trust
        and metadata(root / "active-release.json") == signed
    )
    require(metadata(release / "installation-inventory.json") == inventory)
    require(
        digest(read(execution_python, 16 * 1024 * 1024))
        == inventory["execution_python_sha256"]
        == policy["python_platform_sha256"]
    )
    require(Path(sys.executable).resolve() == execution_python.resolve())
    for name, expected in (
        ("python313.dll", "e1ff5878af41e21bf64b9916ed6735ca30ce48623e3d941fdd1460a541611596"),
        ("python3.dll", "40039942e112e8d252a676940d802a93bc98d681880d6326147f4a4da772bfb7"),
    ):
        require(digest(read(base / name, 64 * 1024 * 1024)) == expected)
    require(
        not (base / "pyvenv.cfg").exists()
        and not (base.parent / "pyvenv.cfg").exists()
        and not tuple(base.glob("*._pth"))
    )
    for name, field in (
        ("launch_start.py", "bootstrap_python_sha256"),
        ("Launch-DMFPulse.ps1", "bootstrap_powershell_sha256"),
        ("dmf.cmd", "command_launcher_sha256"),
    ):
        require(digest(read(root / name)) == digest(read(release / name)) == inventory[field])
    for name, field in (("pyproject.toml", "pyproject_sha256"), ("uv.lock", "lock_sha256")):
        require(digest(read(release / name, 4 * 1024 * 1024)) == inventory[field])
    expected_package, observed = set(), set()
    implementation = hashlib.sha256()
    for name in sorted(members, key=lambda name: Path(name)):
        if name.startswith("dmf_pulse/"):
            expected_package.add(name)
            require(digest(read(site / name, 64 * 1024 * 1024)) == digest(members[name]))
            if name != RESOURCE:
                implementation.update(
                    name.removeprefix("dmf_pulse/").encode() + b"\0" + members[name] + b"\0"
                )
        elif name != record:
            require(read(site / name, 64 * 1024 * 1024) == members[name])
    for path in (site / "dmf_pulse").rglob("*"):
        safe(path)
        require(path.name != "__pycache__" and path.suffix.casefold() not in {".pyc", ".pyo"})
        if path.is_file():
            observed.add(path.relative_to(site).as_posix())
    require(
        observed == expected_package
        and implementation.hexdigest()[:40] == manifest["implementation_sha"]
    )
    require(digest(read(release / "venv/pyvenv.cfg")) == inventory["release_pyvenv_cfg_sha256"])
    require(
        not (release / "venv/Scripts/pyvenv.cfg").exists()
        and not tuple((release / "venv").glob("*._pth"))
        and not tuple((release / "venv/Scripts").glob("*._pth"))
    )
    verifier.verify_dependency_tree_for_execution(site, dependency_tree, lease=lease)
    if lease is not None:
        lease.require_unchanged()
    return release


def approved_arguments(arguments: list[str]) -> list[str]:
    if not arguments or arguments == ["start"]:
        return ["start"]
    if arguments == ["operation", "withdraw-standing"]:
        return arguments
    if arguments in (
        ["operation", "gw10-diagnostic-paid"],
        ["operation", "gw10-diagnostic-read-only"],
    ):
        return arguments
    if len(arguments) == 3 and arguments[:2] == ["operation", "inspect-gw10-diagnostic"]:
        require(re.fullmatch(r"[0-9a-f]{64}", arguments[2]) is not None)
        return arguments
    if len(arguments) == 3 and arguments[:2] == ["operation", "install-reviewed-update"]:
        require(Path(arguments[2]).is_absolute())
        return arguments
    if len(arguments) == 3 and arguments[:2] == ["operation", "rollback-reviewed-update"]:
        require(re.fullmatch(r"[0-9a-f]{64}", arguments[2]) is not None)
        return arguments
    raise ValueError("OPERATOR_ARGUMENTS_NOT_ALLOWED")


def protect_worker_preparation() -> None:
    """Keep unverified site paths out of spawn's pre-bootstrap runpy imports."""
    from multiprocessing import spawn

    original = spawn.get_preparation_data

    def preparation(name: str) -> dict:
        data = original(name)
        data["sys_path"] = [
            entry
            for entry in data["sys_path"]
            if not {"site-packages", "dist-packages"}.intersection(
                entry.replace("\\", "/").casefold().split("/")
            )
        ]
        return data

    spawn.get_preparation_data = preparation


def main() -> int:
    global _APPLICATION_ENTERED
    require(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode)
    arguments = approved_arguments(sys.argv[1:])
    root = installation_root()
    require(Path(__file__).resolve() == (root / "launch_start.py").resolve())
    release = verified_release(root)
    # Retain only nonsecret Windows platform paths. Provider variables, alternate
    # credential selectors, Python overrides and database overrides are removed.
    environment = {
        name: os.environ[name]
        for name in (
            "SYSTEMROOT",
            "WINDIR",
            "SYSTEMDRIVE",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
        )
        if name in os.environ
    }
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PATH=str(Path(environment["SYSTEMROOT"]) / "System32"),
    )
    os.environ.clear()
    os.environ.update(environment)
    protect_worker_preparation()
    sys.path.insert(0, str(release / "venv/Lib/site-packages"))
    sys.argv = ["dmf", *arguments]
    from dmf_pulse.cli.app import main as application

    _APPLICATION_ENTERED = True
    application()
    return 0


def report_verification_failure(error: Exception, *, worker: bool = False) -> None:
    reason = getattr(error, "reason", None)
    if type(reason) is not str or reason not in INTEGRITY_REASON_CODES:
        reason = getattr(error, "integrity_reason", None)
    detail = reason if type(reason) is str and reason in INTEGRITY_REASON_CODES else "UNSPECIFIED"
    stage = "WORKER_BOOTSTRAP" if worker else "APPLICATION" if _APPLICATION_ENTERED else "BOOTSTRAP"
    prefix = (
        "OPERATOR_EXECUTION_BLOCKED"
        if _APPLICATION_ENTERED
        else "OPERATOR_RELEASE_VERIFICATION_FAILED"
    )
    print(
        f"{prefix}: {stage} [{detail}]; preserve the canonical request audit. No automatic retry is authorized.",
        file=sys.stderr,
    )


if __name__ == "__mp_main__":
    # Complete the independent child check before spawn unpickles application
    # dataclasses or imports its worker/Pydantic modules.
    try:
        child_release = verified_release(installation_root())
        sys.path.insert(0, str(child_release / "venv/Lib/site-packages"))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        report_verification_failure(error, worker=True)
        raise SystemExit(2) from None

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        report_verification_failure(error)
        raise SystemExit(2) from None
