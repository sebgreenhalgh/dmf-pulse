"""Public, deterministic RSA fixture and owned filesystem; never operator keys."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field, ValidationError

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.operation import maintenance
from dmf_pulse.operation.maintenance import (
    COMPATIBILITY_FILES,
    MATERIAL_EXCLUSIONS,
    RootTrust,
    _verify_active_release_at,
    material_policy_sha256,
    protected_package_sha256,
    release_package_path,
    verify_installed_wheel,
)
from dmf_pulse.operation.models import Metadata, OperationError, Sha
from dmf_pulse.operation.release_signatures import (
    ReleaseManifest,
    ReviewPublicKey,
    SignedReleaseManifest,
    release_signing_bytes,
    verify_rsa_signature,
    verify_signed_manifest,
)

# Deliberately public TEST-ONLY private exponent. No operational key uses this pair.
TEST_N = 4284783942888859315775505794588712410774113302654159732446730807355744605392119002486176528204950331004951777824847946354278728910452563530053976034076970497178399479355258330072913514396699714432323918300605220695576406796464266331026468488291289110665496283135982240918866714410367455840380252547839328150196203175411285897171568441945159600395799893892141703474321536721567931902847912421366915277365843637112264119156577211042181319256094915484455628868470495974858283417323522156766018993614632847577489495565328274753099650893442858648623160544658500101798205985020208403553096405397936869023638703077190886884744502686712974821867119843353199724994072951525187773636680177680904786305817136300958565044033871484037054042351518726862732446977527972952095914714508464734560522518970057737928951287938044953778072907224159443324753674619905307736285562515147748218771680378565330838062393992259627742410285303633684014809
TEST_D = 1383236551561707074535947267896201969494299634469903374572767805838312535152372884562919218261930423319220665630717121641476952981650745176089109525198993924177234200294783107089928303463554570063394374772813901372603415453755809432313456426244393300186915862219936467508742589327862799078610937381244742140679327259138754836603123022509937007577001363429452706416317816690086710335666162367805359209656059231127213207333196576804239287295744390602325827242172058456125354247401108330926145571465058487947091578778653431939086055314619329177973627367215788351128415042492840868665998755679491643877416734091365627546181319927315811915715823901866945999425295100022449466609277785385748089142541227486582053559185804913165007879407286444038736661639605408237924319504289259360845129353100392251415046390228579678670097266294583705842484701971340623859913451842237185322572226656015634371617890717126580628416103199890973731717
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
KEY = ReviewPublicKey(modulus_b64=base64.b64encode(TEST_N.to_bytes(384, "big")).decode())


class OwnedPolicy(Metadata):
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] = "a" * 40
    independent_review_sha256: Sha = "b" * 64
    owner_acceptance_sha256: Sha = "c" * 64
    accepted_at: datetime = NOW - timedelta(hours=1)
    valid_until: datetime = NOW + timedelta(days=365)
    ledger_id: Sha = "d" * 64
    protected_numerical_sha256: Sha
    purpose: str = "OWNED_TEST_ONLY"
    limits: dict[str, int] = Field(default_factory=lambda: {"requests": 1, "credits": 2})
    dependency_project_sha256: Sha = hashlib.sha256(b"owned-project").hexdigest()
    dependency_lock_sha256: Sha = hashlib.sha256(b"owned-lock").hexdigest()
    dependency_tree_sha256: Sha = "0" * 64
    python_platform_sha256: Sha = hashlib.sha256(b"owned-base-python").hexdigest()


def encoded_signature(encoded: bytes) -> str:
    return base64.b64encode(
        pow(int.from_bytes(encoded, "big"), TEST_D, TEST_N).to_bytes(384, "big")
    ).decode()


def sign(message: bytes) -> str:
    digest = (
        bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    )
    return encoded_signature(b"\x00\x01" + b"\xff" * (381 - len(digest)) + b"\x00" + digest)


def seal(manifest: ReleaseManifest) -> SignedReleaseManifest:
    return SignedReleaseManifest(
        manifest=manifest,
        review_public_key_sha256=KEY.fingerprint_sha256,
        signature_b64=sign(release_signing_bytes(manifest)),
    )


def write_json(path: Path, value: Metadata) -> None:
    path.write_bytes(canonical_json_bytes(value.model_dump(mode="json")))


def wheel_bytes(
    files: dict[str, bytes], *, record_override: list[list[str]] | None = None
) -> bytes:
    record = "dmf_pulse-0.2.0.dist-info/RECORD"
    rows = [
        [
            name,
            "sha256="
            + base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip("="),
            str(len(body)),
        ]
        for name, body in files.items()
    ]
    rows.append([record, "", ""])
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(
        rows if record_override is None else record_override
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, body in {**files, record: stream.getvalue().encode()}.items():
            archive.writestr(name, body)
    return output.getvalue()


def uv_generated_metadata(package: Path, wheel: Path) -> None:
    site = package.parent
    metadata = "dmf_pulse-0.2.0.dist-info/"
    record = site / metadata / "RECORD"
    rows = list(csv.reader(io.StringIO(record.read_text())))
    script = "../../Scripts/dmf.exe" if os.name == "nt" else "../../../bin/dmf"
    generated = {
        script: b"owned-generated-entrypoint",
        metadata + "INSTALLER": b"uv",
        metadata + "REQUESTED": b"",
        metadata + "direct_url.json": json.dumps(
            {"url": wheel.absolute().as_uri(), "archive_info": {}}
        ).encode(),
        metadata
        + "uv_cache.json": b'{"timestamp":{"secs_since_epoch":1,"nanos_since_epoch":0},"commit":null,"tags":null,"env":{},"directories":{}}',
    }
    for name, value in generated.items():
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
        digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
        rows.append([name, "sha256=" + digest, str(len(value))])
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    record.write_bytes(stream.getvalue().encode())


def installed(tmp_path: Path) -> tuple[Path, Path, OwnedPolicy, ReleaseManifest]:
    root = tmp_path / "operator"
    root.mkdir()
    files = {
        "dmf_pulse/__init__.py": b'"""Owned package."""\n',
        "dmf_pulse/operation/owned.py": b"VALUE = 1\n",
        "dmf_pulse/ingestion/owned.py": b"VALUE = 2\n",
        "dmf_pulse/dashboard/resources/desk.js": b"const value = 1;\n",
        "dmf_pulse-0.2.0.dist-info/METADATA": b"Name: dmf-pulse\nVersion: 0.2.0\n",
    }
    wheel = wheel_bytes(files)
    wheel_sha = hashlib.sha256(wheel).hexdigest()
    package = release_package_path(root, wheel_sha)
    package.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        for name in archive.namelist():
            target = package.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    wheel_path = root / "releases" / wheel_sha / "dmf_pulse-0.2.0-py3-none-any.whl"
    wheel_path.write_bytes(wheel)
    uv_generated_metadata(package, wheel_path)
    policy = OwnedPolicy(protected_numerical_sha256=protected_package_sha256(package))
    from dmf_pulse.operation.runtime_integrity import collect_dependency_tree

    dep = package.parent / "owned_dep.py"
    dep.write_bytes(b"OWNED_DEPENDENCY = 1\n")
    metadata = package.parent / "owned_dep-1.0.dist-info"
    metadata.mkdir()
    checksum = (
        base64.urlsafe_b64encode(hashlib.sha256(dep.read_bytes()).digest()).decode().rstrip("=")
    )
    (metadata / "RECORD").write_text(
        f"owned_dep.py,sha256={checksum},{dep.stat().st_size}\nowned_dep-1.0.dist-info/RECORD,,\n"
    )
    tree = collect_dependency_tree(package.parent, policy.dependency_lock_sha256)
    tree_bytes = canonical_json_bytes(tree)
    (wheel_path.parent / "dependency-tree.json").write_bytes(tree_bytes)
    policy = policy.model_copy(
        update={"dependency_tree_sha256": hashlib.sha256(tree_bytes).hexdigest()}
    )
    from dmf_pulse.operation.installation import InstallationInventory

    release = root / "releases" / wheel_sha
    retained = {
        "pyproject.toml": b"owned-project",
        "uv.lock": b"owned-lock",
        "launch_start.py": b"owned-bootstrap-python",
        "Launch-DMFPulse.ps1": b"owned-bootstrap-powershell",
        "dmf.cmd": b"owned-command-launcher",
    }
    for name, body in retained.items():
        (release / name).write_bytes(body)
        if name in {"launch_start.py", "Launch-DMFPulse.ps1", "dmf.cmd"}:
            (root / name).write_bytes(body)
    (root / "owned-uv.exe").write_bytes(b"owned-uv")
    (root / "owned-python.exe").write_bytes(b"owned-python")
    (root / "owned-execution-python.exe").write_bytes(b"owned-base-python")
    (root.parent / "pyvenv.cfg").write_bytes(b"owned-python-config")
    python = release / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"owned-python")
    (python.parent.parent / "pyvenv.cfg").write_bytes(b"owned-python-config")
    inventory = InstallationInventory(
        uv_sha256=hashlib.sha256(b"owned-uv").hexdigest(),
        uv_bytes=8,
        host_python_sha256=hashlib.sha256(b"owned-python").hexdigest(),
        pyproject_sha256=policy.dependency_project_sha256,
        lock_sha256=policy.dependency_lock_sha256,
        bootstrap_python_sha256=hashlib.sha256(retained["launch_start.py"]).hexdigest(),
        bootstrap_powershell_sha256=hashlib.sha256(retained["Launch-DMFPulse.ps1"]).hexdigest(),
        command_launcher_sha256=hashlib.sha256(retained["dmf.cmd"]).hexdigest(),
        dependency_tree_sha256=policy.dependency_tree_sha256,
        host_pyvenv_cfg_sha256=hashlib.sha256(b"owned-python-config").hexdigest(),
        release_pyvenv_cfg_sha256=hashlib.sha256(b"owned-python-config").hexdigest(),
        execution_python_sha256=policy.python_platform_sha256,
    )
    write_json(release / "installation-inventory.json", inventory)
    manifest = ReleaseManifest(
        wheel_sha256=wheel_sha,
        implementation_sha=policy.implementation_sha,
        protected_numerical_sha256=policy.protected_numerical_sha256,
        material_policy_sha256=material_policy_sha256(policy),
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        original_ledger_id=policy.ledger_id,
        independent_review_sha256=policy.independent_review_sha256,
        installation_inventory_sha256=inventory.semantic_sha256,
        reviewer_ref="owned-test-reviewer",
        reviewed_at=NOW,
        release_class="INITIAL_STANDING_INSTALL",
        test_evidence_sha256=("f" * 64,),
    )
    trust = RootTrust(
        review_public_key=KEY,
        review_public_key_sha256=KEY.fingerprint_sha256,
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        material_policy_sha256=material_policy_sha256(policy),
        original_ledger_id=policy.ledger_id,
        accepted_at=policy.accepted_at,
    )
    write_json(root / "root-trust.json", trust)
    write_json(root / "active-release.json", seal(manifest))
    return root, package, policy, manifest


def verify(context: tuple[Path, Path, OwnedPolicy, ReleaseManifest]) -> ReleaseManifest:
    root, package, policy, _ = context
    return _verify_active_release_at(
        policy,
        root=root,
        package_root=package,
        now=NOW,
        installation_tools=(root / "owned-uv.exe", root / "owned-python.exe"),
        execution_python=root / "owned-execution-python.exe",
    )


def test_exact_rsa_signature_and_signed_release(tmp_path: Path) -> None:
    context = installed(tmp_path)
    assert verify(context) == context[3]
    assert verify_signed_manifest(seal(context[3]), KEY) == context[3]
    assert verify_rsa_signature(KEY, b"owned", sign(b"owned"))
    assert not verify_rsa_signature(KEY, b"changed", sign(b"owned"))


@pytest.mark.parametrize(
    "signature",
    [
        "",
        "!" * 512,
        "A" * 512,
        base64.b64encode(TEST_N.to_bytes(384, "big")).decode(),
        " " + "A" * 511,
    ],
)
def test_bad_signature_encodings_and_range(signature: str) -> None:
    assert not verify_rsa_signature(KEY, b"owned", signature)


@pytest.mark.parametrize("index", [0, 1, 2, 100, 330, 350, 383])
def test_complete_padding_and_digest_are_compared(index: int) -> None:
    message = b"owned"
    digest = (
        bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    )
    encoded = bytearray(b"\x00\x01" + b"\xff" * (381 - len(digest)) + b"\x00" + digest)
    encoded[index] ^= 1
    assert not verify_rsa_signature(KEY, message, encoded_signature(encoded))


@pytest.mark.parametrize(
    "field,value",
    [("exponent", True), ("exponent", 3), ("algorithm", "RSA2048"), ("modulus_b64", "A" * 512)],
)
def test_only_exact_public_review_key(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        ReviewPublicKey.model_validate({**KEY.model_dump(), field: value})


def test_signed_manifest_cannot_select_another_public_key(tmp_path: Path) -> None:
    manifest = installed(tmp_path)[3]
    signed = seal(manifest).model_copy(update={"review_public_key_sha256": "0" * 64})
    with pytest.raises(OperationError, match="SIGNATURE_INVALID"):
        verify_signed_manifest(signed, KEY)


@pytest.mark.parametrize("field", sorted(MATERIAL_EXCLUSIONS))
def test_only_four_top_level_fields_are_nonmaterial(field: str) -> None:
    base = {
        "purpose": "PRIVATE",
        "nested": {"implementation_sha": "a"},
        **dict.fromkeys(MATERIAL_EXCLUSIONS, "old"),
    }
    assert material_policy_sha256(base) == material_policy_sha256({**base, field: "new"})
    assert material_policy_sha256(base) != material_policy_sha256(
        {**base, "nested": {field: "new"}}
    )


@pytest.mark.parametrize(
    "field",
    [
        "purpose",
        "limits",
        "ledger_id",
        "entry_id",
        "valid_until",
        "qualifications",
        "protected_numerical_sha256",
        "dependency_lock_sha256",
    ],
)
def test_material_scope_is_exact(field: str) -> None:
    assert material_policy_sha256({field: "old"}) != material_policy_sha256({field: "new"})


@pytest.mark.parametrize("path", [*sorted(COMPATIBILITY_FILES), "operation/new.py"])
def test_only_finite_compatibility_paths_are_excluded(tmp_path: Path, path: str) -> None:
    (tmp_path / "__init__.py").write_bytes(b"owned")
    before = protected_package_sha256(tmp_path)
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"changed")
    assert protected_package_sha256(tmp_path) == before


@pytest.mark.parametrize(
    "path",
    [
        "ingestion/odds/client.py",
        "rules/scorer.py",
        "models/owned.py",
        "solver/owned.py",
        "dashboard/authorization.py",
        "operation_extra.py",
        "data_model/tables.py",
        "numerics.py",
    ],
)
def test_model_source_and_other_boundaries_cannot_change(tmp_path: Path, path: str) -> None:
    (tmp_path / "__init__.py").write_bytes(b"owned")
    before = protected_package_sha256(tmp_path)
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"changed")
    assert protected_package_sha256(tmp_path) != before


@pytest.mark.parametrize(
    "path",
    ["operation/__pycache__/owned.pyc", "operation/owned.pyo", "dashboard/resources/owned.pyc"],
)
def test_bytecode_is_denied_including_compatibility_paths(tmp_path: Path, path: str) -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"cache")
    with pytest.raises(OperationError, match="BYTECODE"):
        protected_package_sha256(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        "owner_acceptance_sha256",
        "ledger_id",
        "implementation_sha",
        "independent_review_sha256",
        "purpose",
        "protected_numerical_sha256",
    ],
)
def test_signed_root_scope_and_policy_must_agree(tmp_path: Path, change: str) -> None:
    root, package, policy, manifest = installed(tmp_path)
    value = "0" * 40 if change == "implementation_sha" else "0" * 64
    policy = policy.model_copy(update={change: value})
    with pytest.raises(OperationError, match="SCOPE_OR_RELEASE"):
        verify((root, package, policy, manifest))


@pytest.mark.parametrize("body", [b"", b"malformed", b'{"withdrawn":false}'])
def test_any_withdrawal_marker_denies_even_false_or_malformed(tmp_path: Path, body: bytes) -> None:
    context = installed(tmp_path)
    (context[0] / "withdrawn.json").write_bytes(body)
    with pytest.raises(OperationError, match="PERMISSION_WITHDRAWN"):
        verify(context)


def test_review_and_owner_cannot_be_in_future(tmp_path: Path) -> None:
    context = installed(tmp_path)
    with pytest.raises(OperationError, match="SCOPE_OR_RELEASE"):
        _verify_active_release_at(
            context[2], root=context[0], package_root=context[1], now=NOW - timedelta(seconds=1)
        )
    with pytest.raises(ValidationError):
        _verify_active_release_at(
            context[2], root=context[0], package_root=context[1], now=NOW.replace(tzinfo=None)
        )


def test_checkout_or_another_release_origin_is_denied(tmp_path: Path) -> None:
    context = installed(tmp_path)
    with pytest.raises(OperationError, match="ORIGIN_INVALID"):
        _verify_active_release_at(context[2], root=context[0], package_root=tmp_path, now=NOW)


@pytest.mark.parametrize(
    "path",
    ["operation/owned.py", "dashboard/resources/desk.js", "../dmf_pulse-0.2.0.dist-info/METADATA"],
)
def test_even_compatible_executables_must_match_signed_wheel(tmp_path: Path, path: str) -> None:
    context = installed(tmp_path)
    (context[1] / path).write_bytes(b"modified")
    with pytest.raises(OperationError, match="INSTALLED_WHEEL_BYTES_CHANGED"):
        verify(context)


def test_protected_file_mutation_is_denied(tmp_path: Path) -> None:
    context = installed(tmp_path)
    (context[1] / "ingestion/owned.py").write_bytes(b"modified")
    with pytest.raises(OperationError, match="PROTECTED_PACKAGE_CHANGED"):
        verify(context)


def test_added_compatibility_file_still_denied_by_wheel_inventory(tmp_path: Path) -> None:
    context = installed(tmp_path)
    (context[1] / "operation/unreviewed.py").write_bytes(b"added")
    with pytest.raises(OperationError, match="PACKAGE_INVENTORY_CHANGED"):
        verify(context)


def test_retained_wheel_bytes_must_match_signed_hash(tmp_path: Path) -> None:
    context = installed(tmp_path)
    wheel = context[0] / "releases" / context[3].wheel_sha256 / "dmf_pulse-0.2.0-py3-none-any.whl"
    wheel.write_bytes(b"not the signed wheel")
    with pytest.raises(OperationError, match="RETAINED_WHEEL_CHANGED"):
        verify(context)


def test_wheel_record_and_file_inventory_are_not_caller_truth(tmp_path: Path) -> None:
    package = tmp_path / "dmf_pulse"
    package.mkdir()
    body = wheel_bytes(
        {"dmf_pulse/__init__.py": b"owned"},
        record_override=[
            ["dmf_pulse/__init__.py", "sha256=bad", "5"],
            ["dmf_pulse-0.2.0.dist-info/RECORD", "", ""],
        ],
    )
    wheel = tmp_path / "owned.whl"
    wheel.write_bytes(body)
    with pytest.raises(OperationError, match="RECORD_INVALID"):
        verify_installed_wheel(package, wheel, hashlib.sha256(body).hexdigest())


def test_direct_nonisolated_entrypoint_has_no_active_authority() -> None:
    with pytest.raises(OperationError, match="STANDING_REVIEWED_ENTRYPOINT_REQUIRED"):
        maintenance._require_entrypoint()


def test_installed_release_python_must_match_reviewed_host(tmp_path: Path) -> None:
    context = installed(tmp_path)
    python = (
        context[0]
        / "releases"
        / context[3].wheel_sha256
        / "venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    python.write_bytes(b"changed")
    with pytest.raises(OperationError, match="RELEASE_PYTHON_CHANGED"):
        verify(context)


def test_dependency_body_and_signed_tree_are_both_checked(tmp_path: Path) -> None:
    context = installed(tmp_path)
    (context[1].parent / "owned_dep.py").write_bytes(b"changed")
    with pytest.raises(OperationError, match="DEPENDENCY_TREE_CHANGED"):
        verify(context)
    path = context[0] / "releases" / context[3].wheel_sha256 / "dependency-tree.json"
    path.write_bytes(b"{}")
    with pytest.raises(OperationError, match="DEPENDENCY_INVENTORY_CHANGED"):
        verify(context)


def test_duplicate_metadata_keys_denied(tmp_path: Path) -> None:
    context = installed(tmp_path)
    path = context[0] / "root-trust.json"
    body = path.read_bytes()
    path.write_bytes(b'{"schema_version":"operator-root-trust-v1",' + body[1:])
    with pytest.raises(ValueError, match="duplicate"):
        verify(context)


def test_normal_api_has_no_caller_key_root_or_paths() -> None:
    import inspect

    assert list(inspect.signature(maintenance.verify_active_release).parameters) == ["policy"]


def test_public_failure_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maintenance, "_require_entrypoint", lambda: None)
    monkeypatch.setattr(maintenance, "operator_root_path", lambda: tmp_path / "absent")
    with pytest.raises(OperationError, match=r"^STANDING_RELEASE_AUTHENTICATION_FAILED$"):
        maintenance.verify_active_release(OwnedPolicy(protected_numerical_sha256="f" * 64))


def test_manifest_requires_inventory_evidence_and_schema(tmp_path: Path) -> None:
    value = installed(tmp_path)[3].model_dump(mode="json")
    for key in ("installation_inventory_sha256", "independent_review_sha256"):
        with pytest.raises(ValidationError):
            ReleaseManifest.model_validate_json(
                json.dumps({k: v for k, v in value.items() if k != key})
            )
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate_json(
            json.dumps({**value, "database_schema_revision": "old"})
        )
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate_json(
            json.dumps({**value, "reviewed_at": "2026-11-01T12:00:00"})
        )


def test_signer_is_explicit_engineering_and_public_export_only() -> None:
    source = (Path(__file__).parents[3] / "scripts/operator_review_key.ps1").read_text()
    assert "[switch]$EngineeringOnly" in source
    assert "UseNonExportableKey" in source and "UseExistingKey" in source
    assert "ExportParameters($false)" in source and "ExportParameters($true)" not in source
    assert "MachineKeyStore" in source and "FileMode]::CreateNew" in source


@pytest.mark.parametrize(
    "name", ["pyproject.toml", "uv.lock", "launch_start.py", "Launch-DMFPulse.ps1", "dmf.cmd"]
)
def test_retained_carrier_bytes_are_signed(tmp_path: Path, name: str) -> None:
    context = installed(tmp_path)
    (context[0] / "releases" / context[3].wheel_sha256 / name).write_bytes(b"changed")
    with pytest.raises(OperationError, match="CARRIER_CHANGED"):
        verify(context)


@pytest.mark.parametrize("name", ["launch_start.py", "Launch-DMFPulse.ps1", "dmf.cmd"])
def test_active_bootstrap_cannot_change_after_activation(tmp_path: Path, name: str) -> None:
    context = installed(tmp_path)
    (context[0] / name).write_bytes(b"changed")
    with pytest.raises(OperationError, match="ACTIVE_BOOTSTRAP_CHANGED"):
        verify(context)


@pytest.mark.parametrize("name", ["owned-uv.exe", "owned-python.exe"])
def test_native_tool_bytes_are_fixed(tmp_path: Path, name: str) -> None:
    context = installed(tmp_path)
    (context[0] / name).write_bytes(b"changed")
    with pytest.raises(OperationError, match="TOOL_CHANGED"):
        verify(context)


def test_resealed_inventory_cannot_override_signed_inventory(tmp_path: Path) -> None:
    context = installed(tmp_path)
    path = context[0] / "releases" / context[3].wheel_sha256 / "installation-inventory.json"
    value = json.loads(path.read_bytes())
    path.write_text(json.dumps({**value, "uv_sha256": "0" * 64}))
    with pytest.raises(OperationError, match="INVENTORY_CHANGED"):
        verify(context)


def test_release_class_is_closed(tmp_path: Path) -> None:
    manifest = installed(tmp_path)[3]
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(
            {**manifest.model_dump(), "release_class": "MATERIAL_SCOPE_WIDENING"}
        )


def test_reviewed_compatibility_release_and_rollback_keep_material_scope(tmp_path: Path) -> None:
    context = installed(tmp_path)
    root, _old_package, policy, manifest = context
    old_signed = (root / "active-release.json").read_bytes()
    old_wheel = root / "releases" / manifest.wheel_sha256 / "dmf_pulse-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(old_wheel) as archive:
        files = {
            name: archive.read(name) for name in archive.namelist() if not name.endswith("/RECORD")
        }
    files["dmf_pulse/operation/owned.py"] = b"VALUE = 3\n"
    body = wheel_bytes(files)
    new_sha = hashlib.sha256(body).hexdigest()
    new_package = release_package_path(root, new_sha)
    new_package.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for name in archive.namelist():
            target = new_package.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    old_release = root / "releases" / manifest.wheel_sha256
    new_release = root / "releases" / new_sha
    for name in (
        "installation-inventory.json",
        "pyproject.toml",
        "uv.lock",
        "launch_start.py",
        "Launch-DMFPulse.ps1",
        "dmf.cmd",
        "dependency-tree.json",
    ):
        (new_release / name).write_bytes((old_release / name).read_bytes())
    (new_release / old_wheel.name).write_bytes(body)
    uv_generated_metadata(new_package, new_release / old_wheel.name)
    for name in ("owned_dep.py", "owned_dep-1.0.dist-info/RECORD"):
        target = new_package.parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((_old_package.parent / name).read_bytes())
    python = new_release / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"owned-python")
    (python.parent.parent / "pyvenv.cfg").write_bytes(b"owned-python-config")
    changed_policy = policy.model_copy(
        update={"implementation_sha": "0" * 40, "independent_review_sha256": "1" * 64}
    )
    changed_manifest = ReleaseManifest.model_validate(
        {
            **manifest.model_dump(),
            "wheel_sha256": new_sha,
            "implementation_sha": changed_policy.implementation_sha,
            "independent_review_sha256": changed_policy.independent_review_sha256,
            "release_class": "WITHIN_POLICY_COMPATIBILITY",
        }
    )
    write_json(root / "active-release.json", seal(changed_manifest))
    assert material_policy_sha256(changed_policy) == material_policy_sha256(policy)
    assert verify((root, new_package, changed_policy, changed_manifest)) == changed_manifest
    with pytest.raises(OperationError, match="SCOPE_OR_RELEASE"):
        verify(context)
    (root / "active-release.json").write_bytes(old_signed)
    assert verify(context) == manifest


def test_empty_and_oversized_metadata_fail_closed(tmp_path: Path) -> None:
    context = installed(tmp_path)
    path = context[0] / "root-trust.json"
    path.write_bytes(b"x" * 262145)
    with pytest.raises(OperationError, match="METADATA_INVALID"):
        verify(context)


def test_no_nonfinite_manifest_values(tmp_path: Path) -> None:
    value = installed(tmp_path)[3].model_dump(mode="json")
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate_json(json.dumps({**value, "reviewed_at": float("nan")}))


@pytest.mark.parametrize("name", ["INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json"])
def test_installed_record_detects_generated_metadata_change(tmp_path: Path, name: str) -> None:
    context = installed(tmp_path)
    (context[1].parent / "dmf_pulse-0.2.0.dist-info" / name).write_bytes(b"changed")
    with pytest.raises(OperationError, match="INSTALLED_RECORD_BYTES_CHANGED"):
        verify(context)


@pytest.mark.parametrize("change", ["duplicate", "outside", "missing", "bad-size", "selfhash"])
def test_installed_record_rejects_unknown_and_malformed_entries(
    tmp_path: Path, change: str
) -> None:
    context = installed(tmp_path)
    record = context[1].parent / "dmf_pulse-0.2.0.dist-info/RECORD"
    rows = list(csv.reader(io.StringIO(record.read_text())))
    if change == "duplicate":
        rows.append(rows[0])
    elif change == "outside":
        rows.append(["../../../outside", "", ""])
    elif change == "missing":
        rows.pop(0)
    elif change == "bad-size":
        rows[0][2] = "0"
    else:
        next(row for row in rows if row[0].endswith("/RECORD"))[1] = "sha256=bad"
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    record.write_bytes(stream.getvalue().encode())
    with pytest.raises(OperationError, match="INSTALLED_RECORD"):
        verify(context)


def test_root_and_tool_paths_are_fixed_not_environment_selected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    class KnownFolder:
        def __call__(self, *arguments: object) -> int:
            arguments[-1].value = str(tmp_path)  # type: ignore[attr-defined]
            return 0

    if os.name == "nt":
        monkeypatch.setattr(
            maintenance.ctypes,
            "WinDLL",
            lambda name: SimpleNamespace(SHGetFolderPathW=KnownFolder()),
        )
    else:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("DMF_OPERATOR_ROOT", "/untrusted")
    root = maintenance.operator_root()
    assert root.parts[-2:] == ("DMFPulse", "operator")
    if os.name == "nt":
        uv, host = maintenance._installation_tools()
        assert uv.name == "uv.exe" and host.name == "python.exe"
        assert "gw10" in host.parts
    else:
        with pytest.raises(OperationError, match="WINDOWS_SSPI_SESSION"):
            maintenance._installation_tools()


def test_root_key_must_match_its_owner_installed_pin(tmp_path: Path) -> None:
    context = installed(tmp_path)
    value = json.loads((context[0] / "root-trust.json").read_bytes())
    with pytest.raises(ValidationError, match="differs from its pin"):
        RootTrust.model_validate_json(json.dumps({**value, "review_public_key_sha256": "0" * 64}))


def test_duplicate_review_evidence_is_rejected(tmp_path: Path) -> None:
    manifest = installed(tmp_path)[3]
    with pytest.raises(ValidationError, match="duplicates"):
        ReleaseManifest.model_validate(
            {**manifest.model_dump(), "test_evidence_sha256": ("f" * 64, "f" * 64)}
        )


@pytest.mark.parametrize("root_kind", ["missing", "empty", "regular-file"])
def test_package_root_and_empty_inventory_are_not_success(tmp_path: Path, root_kind: str) -> None:
    path = tmp_path / "owned"
    if root_kind == "empty":
        path.mkdir()
    elif root_kind == "regular-file":
        path.write_bytes(b"owned")
    with pytest.raises(OperationError, match="PROTECTED_PACKAGE"):
        protected_package_sha256(path)


def test_metadata_changed_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.json"
    target.write_bytes(b"{}")
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: original(path) + b" " if path == target else original(path)
    )
    with pytest.raises(OperationError, match="METADATA_CHANGED_DURING_READ"):
        maintenance._read(target)


def test_protected_source_changed_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "owned.py"
    target.write_bytes(b"owned")
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: original(path) + b" " if path == target else original(path)
    )
    with pytest.raises(OperationError, match="CHANGED_DURING_READ"):
        protected_package_sha256(tmp_path)


def test_reparse_point_is_refused_before_reading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import stat
    from types import SimpleNamespace

    target = tmp_path / "owned"
    original = Path.lstat
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: (
            SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            if path == target
            else original(path)
        ),
    )
    with pytest.raises(OperationError, match="REPARSE_PATH_DENIED"):
        maintenance._safe_path(target)


@pytest.mark.parametrize(
    "name,value",
    [
        ("INSTALLER", b"pip"),
        ("REQUESTED", b"unexpected"),
        ("direct_url.json", b'{"url":"file:///unreviewed.whl","archive_info":{}}'),
        ("uv_cache.json", b'{"unexpected":true}'),
        (
            "uv_cache.json",
            b'{"timestamp":{"secs_since_epoch":true,"nanos_since_epoch":0},"commit":null,"tags":null,"env":{},"directories":{}}',
        ),
        (
            "uv_cache.json",
            b'{"timestamp":{"secs_since_epoch":1,"nanos_since_epoch":1000000000},"commit":null,"tags":null,"env":{},"directories":{}}',
        ),
    ],
)
def test_rewritten_installed_record_cannot_bless_semantic_metadata(
    tmp_path: Path, name: str, value: bytes
) -> None:
    context = installed(tmp_path)
    site = context[1].parent
    target = site / "dmf_pulse-0.2.0.dist-info" / name
    target.write_bytes(value)
    record = site / "dmf_pulse-0.2.0.dist-info/RECORD"
    rows = list(csv.reader(io.StringIO(record.read_text())))
    row = next(row for row in rows if row[0] == target.relative_to(site).as_posix())
    row[1] = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip(
        "="
    )
    row[2] = str(len(value))
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    record.write_bytes(stream.getvalue().encode())
    with pytest.raises(OperationError, match=r"INSTALLER_METADATA_CHANGED|INSTALL_SOURCE_CHANGED"):
        verify(context)


def test_public_api_preserves_closed_withdrawal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(maintenance, "_require_entrypoint", lambda: None)
    (tmp_path / "withdrawn.json").write_bytes(b"withdrawn")
    monkeypatch.setattr(maintenance, "operator_root_path", lambda: tmp_path)
    with pytest.raises(OperationError, match="PERMISSION_WITHDRAWN"):
        maintenance.verify_active_release(OwnedPolicy(protected_numerical_sha256="f" * 64))


@pytest.mark.parametrize(
    "records",
    [
        [["dmf_pulse/__init__.py", "", ""], ["dmf_pulse/__init__.py", "", ""]],
        [["dmf_pulse/__init__.py", "", ""]],
        [["dmf_pulse/__init__.py", "sha256=bad"]],
        [
            ["dmf_pulse/__init__.py", "sha256=bad", "5"],
            ["dmf_pulse-0.2.0.dist-info/RECORD", "bad", ""],
        ],
    ],
)
def test_malformed_wheel_record_is_not_trusted(tmp_path: Path, records: list[list[str]]) -> None:
    package = tmp_path / "dmf_pulse"
    package.mkdir()
    body = wheel_bytes({"dmf_pulse/__init__.py": b"owned"}, record_override=records)
    wheel = tmp_path / "owned.whl"
    wheel.write_bytes(body)
    with pytest.raises(OperationError, match="RECORD_INVALID"):
        verify_installed_wheel(package, wheel, hashlib.sha256(body).hexdigest())


class CacheKernel:
    status = 258

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

        from dmf_pulse.operation import runtime_integrity

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
        return self.status

    def FindCloseChangeNotification(self, handle: int) -> bool:
        return True


def cached_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[tuple[Path, Path, OwnedPolicy, ReleaseManifest], CacheKernel]:
    from dmf_pulse.operation import runtime_integrity

    context = installed(tmp_path)
    root, package, _, _manifest = context
    kernel = CacheKernel()
    monkeypatch.setattr(maintenance, "operator_root_path", lambda: root)
    monkeypatch.setattr(maintenance, "__file__", str(package / "operation/maintenance.py"))
    monkeypatch.setattr(maintenance, "_require_entrypoint", lambda: None)
    monkeypatch.setattr(
        maintenance,
        "_installation_tools",
        lambda: (root / "owned-uv.exe", root / "owned-python.exe"),
    )
    monkeypatch.setattr(
        maintenance, "_new_watch", lambda root: runtime_integrity.DirectoryWatch(kernel, 123)
    )
    monkeypatch.setattr(
        runtime_integrity, "_new_watch", lambda root: runtime_integrity.DirectoryWatch(kernel, 123)
    )
    monkeypatch.setattr(runtime_integrity, "_EXECUTION_CACHE", {})
    monkeypatch.setattr(maintenance, "_RELEASE_CACHE", {})
    monkeypatch.setattr(
        maintenance, "_execution_python_path", lambda host: root / "owned-execution-python.exe"
    )
    monkeypatch.setattr(maintenance, "_PLATFORM_DLLS", {})
    python = root / "owned-execution-python.exe"
    monkeypatch.setattr(maintenance.sys, "executable", str(python))
    return context, kernel


def test_whole_release_cache_requires_full_success_and_live_kernel_watch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, kernel = cached_context(tmp_path, monkeypatch)
    assert maintenance.cached_implementation_fingerprint(context[1]) is None
    assert maintenance.verify_active_release(context[2]) == context[3]
    assert (
        maintenance.cached_implementation_fingerprint(context[1]) == context[3].implementation_sha
    )

    # No byte verifier is invoked a second time while the kernel guarantees that
    # no file, directory, ACL, size or write changed in the installed operator tree.
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("full byte verifier repeated under unchanged kernel watch")

    monkeypatch.setattr(maintenance, "verify_installed_wheel", unexpected)
    assert maintenance.verify_active_release(context[2]) == context[3]
    kernel.status = 0
    with pytest.raises(OperationError, match="RESTART_REQUIRED"):
        maintenance.cached_implementation_fingerprint(context[1])
    kernel.status = 258
    with pytest.raises(OperationError, match="RESTART_REQUIRED"):
        maintenance.verify_active_release(context[2])


@pytest.mark.parametrize("change", ["withdrawal", "roottrust", "active", "policy", "nested-memory"])
def test_cached_release_fresh_controls_and_policy_cannot_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    context, _ = cached_context(tmp_path, monkeypatch)
    root, _, policy, _ = context
    maintenance.verify_active_release(policy)
    if change == "withdrawal":
        (root / "withdrawn.json").write_bytes(b"false")
    elif change in {"roottrust", "active"}:
        path = root / ("root-trust.json" if change == "roottrust" else "active-release.json")
        value = json.loads(path.read_bytes())
        value["unexpected"] = True
        path.write_text(json.dumps(value))
    elif change == "policy":
        policy = policy.model_copy(update={"purpose": "CHANGED"})
    else:
        policy.limits["requests"] = 2
    with pytest.raises(OperationError, match=r"PERMISSION_WITHDRAWN|RESTART_REQUIRED"):
        maintenance.verify_active_release(policy)


@pytest.mark.parametrize("name", ["pyvenv.cfg", "python._pth", "python313._pth", "python.exe._pth"])
def test_release_python_override_files_are_denied(tmp_path: Path, name: str) -> None:
    context = installed(tmp_path)
    scripts = (
        context[0]
        / "releases"
        / context[3].wheel_sha256
        / "venv"
        / ("Scripts" if os.name == "nt" else "bin")
    )
    (scripts / name).write_bytes(b"unexpected override")
    with pytest.raises(OperationError, match="PYTHON_CONFIGURATION_CHANGED"):
        verify(context)


def test_technical_transition_closes_leases_and_cannot_regrant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dmf_pulse.operation import runtime_integrity

    context, _ = cached_context(tmp_path, monkeypatch)
    monkeypatch.setattr(maintenance, "_TECHNICAL_PROCESS_ONLY", False)
    monkeypatch.setattr(runtime_integrity, "_TECHNICAL_PROCESS_ONLY", False)
    monkeypatch.setattr(runtime_integrity, "_WATCHES", [])
    maintenance.verify_active_release(context[2])
    maintenance.close_execution_leases_for_maintenance()
    assert not maintenance._RELEASE_CACHE and not runtime_integrity._EXECUTION_CACHE
    assert maintenance.cached_implementation_fingerprint(context[1]) is None
    with pytest.raises(OperationError, match="TECHNICAL_PROCESS_CANNOT_ACQUIRE"):
        maintenance.verify_active_release(context[2])
    with pytest.raises(runtime_integrity.RuntimeIntegrityError):
        runtime_integrity.verify_dependency_tree_for_execution(context[1].parent, {})


@pytest.mark.parametrize("home_kind", ["valid", "missing", "duplicate", "relative", "wrong-hash"])
def test_execution_python_comes_only_from_authenticated_original_cfg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home_kind: str
) -> None:
    host = tmp_path / "host/venv/Scripts/python.exe"
    host.parent.mkdir(parents=True)
    base = tmp_path / "owned-base"
    base.mkdir()
    value = f"home = {base}\n".encode()
    if home_kind == "missing":
        value = b"implementation = CPython\n"
    elif home_kind == "duplicate":
        value = value + value
    elif home_kind == "relative":
        value = b"home = relative\n"
    cfg = host.parent.parent / "pyvenv.cfg"
    cfg.write_bytes(value)
    monkeypatch.setattr(
        maintenance,
        "_HOST_CONFIGURATION_SHA256",
        hashlib.sha256(value).hexdigest() if home_kind != "wrong-hash" else "0" * 64,
    )
    if home_kind == "valid":
        assert maintenance._execution_python_path(host) == base / "python.exe"
    else:
        with pytest.raises(OperationError, match="PYTHON_CONFIGURATION_CHANGED"):
            maintenance._execution_python_path(host)
