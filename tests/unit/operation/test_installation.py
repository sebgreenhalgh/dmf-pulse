"""Owned private carrier, path/scope attacks and maintenance exclusion lifetime."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.operation import installation
from dmf_pulse.operation.installation import InstallationInventory, _same_policy, authenticate_wheel
from dmf_pulse.operation.maintenance import RootTrust, material_policy_sha256
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.release_signatures import ReleaseManifest
from dmf_pulse.operation.wheel import RESOURCE
from tests.unit.operation.standing_support import NOW, owned_policy
from tests.unit.operation.test_maintenance import KEY, seal, wheel_bytes


@pytest.fixture
def carrier(tmp_path):
    policy = owned_policy(tmp_path)
    body = b'"""Owned miniature wheel, never executed."""\n'
    code = hashlib.sha256(b"__init__.py\0" + body + b"\0").hexdigest()[:40]
    policy = policy.model_copy(update={"implementation_sha": code})
    registry = {
        "schema_version": "trusted-refresh-enrollments-v3",
        "approvals": [],
        "qualifications": [],
        "release_permits": [],
        "default_authorization_id": None,
        "standing_policy": policy.model_dump(mode="json"),
    }
    files = {
        "dmf_pulse/__init__.py": body,
        RESOURCE: canonical_json_bytes(registry),
        "dmf_pulse-0.2.0.dist-info/METADATA": b"Name: dmf-pulse\nVersion: 0.2.0\n",
    }
    path = tmp_path / "OWNED-private.whl"
    path.write_bytes(wheel_bytes(files))
    inventory = InstallationInventory(
        uv_sha256="1" * 64,
        uv_bytes=8,
        host_python_sha256="2" * 64,
        execution_python_sha256=policy.python_platform_sha256,
        host_pyvenv_cfg_sha256="4" * 64,
        release_pyvenv_cfg_sha256="5" * 64,
        pyproject_sha256=policy.dependency_project_sha256,
        lock_sha256=policy.dependency_lock_sha256,
        dependency_tree_sha256=policy.dependency_tree_sha256,
        bootstrap_python_sha256=hashlib.sha256(b"owned-python").hexdigest(),
        bootstrap_powershell_sha256=hashlib.sha256(b"owned-powershell").hexdigest(),
        command_launcher_sha256=hashlib.sha256(b"owned-cmd").hexdigest(),
    )
    manifest = ReleaseManifest(
        wheel_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        implementation_sha=code,
        protected_numerical_sha256=policy.protected_numerical_sha256,
        material_policy_sha256=material_policy_sha256(policy),
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        original_ledger_id=policy.ledger_id,
        independent_review_sha256=policy.independent_review_sha256,
        installation_inventory_sha256=inventory.semantic_sha256,
        reviewer_ref="OWNED-INDEPENDENT-REVIEW",
        reviewed_at=NOW,
        release_class="WITHIN_POLICY_COMPATIBILITY",
        test_evidence_sha256=("3" * 64,),
    )
    trust = RootTrust(
        review_public_key=KEY,
        review_public_key_sha256=KEY.fingerprint_sha256,
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        material_policy_sha256=material_policy_sha256(policy),
        original_ledger_id=policy.ledger_id,
        accepted_at=policy.accepted_at,
    )
    return path, files, policy, inventory, seal(manifest), trust


def test_private_wheel_is_authenticated_before_installation(carrier):
    path, files, policy, _, _, _ = carrier
    actual, digest, qualified = authenticate_wheel(path)
    assert all(actual[name] == body for name, body in files.items())
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert qualified == policy


@pytest.mark.parametrize(
    "name",
    [
        "arbitrary.pth",
        "other_project/__init__.py",
        "dmf_pulse-0.3.0.dist-info/METADATA",
        "dmf_pulse/__pycache__/owned.pyc",
    ],
)
def test_reviewed_wheel_cannot_install_unexpected_code(carrier, name):
    path, files, *_ = carrier
    path.write_bytes(wheel_bytes({**files, name: b"OWNED_UNREVIEWED_BYTES"}))
    with pytest.raises(OperationError, match=r"UNEXPECTED_INSTALL_TARGET|BYTECODE_FORBIDDEN"):
        authenticate_wheel(path)


def test_duplicate_private_registry_key_is_rejected_even_with_valid_record(carrier):
    path, files, *_ = carrier
    original = files[RESOURCE]
    files[RESOURCE] = b'{"schema_version":"unreviewed",' + original[1:]
    path.write_bytes(wheel_bytes(files))
    with pytest.raises(OperationError, match="DUPLICATE_REGISTRY_FIELD"):
        authenticate_wheel(path)


def test_legacy_authority_cannot_be_smuggled_into_standing_carrier(carrier):
    path, files, *_ = carrier
    registry = json.loads(files[RESOURCE])
    registry["release_permits"] = [{"unreviewed": True}]
    files[RESOURCE] = canonical_json_bytes(registry)
    path.write_bytes(wheel_bytes(files))
    with pytest.raises(OperationError, match="STANDING_PRIVATE_WHEEL_REQUIRED"):
        authenticate_wheel(path)


def test_material_scope_signed_by_correct_key_still_cannot_replace_owner_decision(carrier):
    _, _, policy, inventory, signed, trust = carrier
    _same_policy(trust, signed, policy, inventory)
    changed = policy.model_copy(update={"entry_id": 18})
    with pytest.raises(OperationError, match="MATERIAL_SCOPE_CHANGE"):
        _same_policy(trust, signed, changed, inventory)


@pytest.mark.parametrize(
    "field",
    [
        "owner_acceptance_sha256",
        "original_ledger_id",
        "material_policy_sha256",
        "installation_inventory_sha256",
    ],
)
def test_reviewer_signature_does_not_expand_owner_material_scope(carrier, field):
    _, _, policy, inventory, signed, trust = carrier
    candidate = seal(signed.manifest.model_copy(update={field: "0" * 64}))
    with pytest.raises(OperationError, match="MATERIAL_SCOPE_CHANGE"):
        _same_policy(trust, candidate, policy, inventory)


def test_future_release_review_cannot_activate(carrier):
    _, _, policy, inventory, signed, trust = carrier
    candidate = seal(signed.manifest.model_copy(update={"reviewed_at": NOW.replace(year=2099)}))
    with pytest.raises(OperationError, match="TIME_OR_PERMISSION_INVALID"):
        _same_policy(trust, candidate, policy, inventory)


def test_all_retained_bootstrap_buffers_verified_before_any_replacement(
    carrier, tmp_path, monkeypatch
):
    _, _, _, inventory, signed, _ = carrier
    root, release = tmp_path / "owned-operator", tmp_path / "owned-release"
    root.mkdir()
    release.mkdir()
    for name, body in (
        ("launch_start.py", b"owned-python"),
        ("Launch-DMFPulse.ps1", b"owned-powershell"),
        ("dmf.cmd", b"owned-cmd"),
    ):
        (release / name).write_bytes(body)
        (root / name).write_bytes(b"OLD_REVIEWED_BYTES")
    (root / "active-release.json").write_bytes(b"OLD_SIGNED_RELEASE")

    def changed_after_validation(*_):
        (release / "dmf.cmd").write_bytes(b"OWNED_ATTACK_BETWEEN_VALIDATION_AND_COPY")
        return inventory, signed

    monkeypatch.setattr(installation, "_authenticate_retained_release", changed_after_validation)
    with pytest.raises(OperationError, match="CHANGED_DURING_ACTIVATION"):
        installation._activate(root, release)
    assert (root / "active-release.json").read_bytes() == b"OLD_SIGNED_RELEASE"
    assert all(
        (root / name).read_bytes() == b"OLD_REVIEWED_BYTES"
        for name in ("launch_start.py", "Launch-DMFPulse.ps1", "dmf.cmd")
    )


def test_exclusive_maintenance_socket_remains_held_through_activation_work(carrier, monkeypatch):
    _, _, policy, *_ = carrier
    events = []
    state = {"held": False}

    class Socket:
        def setsockopt(self, *_):
            events.append("exclusive")

        def bind(self, address):
            assert address == ("127.0.0.1", 8765)
            if state["held"]:
                raise OSError("OWNED_CONCURRENT_START_REFUSED")
            state["held"] = True

        def close(self):
            state["held"] = False
            events.append("closed")

    from dmf_pulse.operation import journal, local_control, maintenance

    monkeypatch.setattr(installation.socket, "socket", lambda *_: Socket())
    monkeypatch.setattr(
        maintenance,
        "close_execution_leases_for_maintenance",
        lambda: events.append("execution-leases-closed"),
    )
    monkeypatch.setattr(
        local_control, "recover_local_control", lambda _: events.append("recovered")
    )
    monkeypatch.setattr(
        journal.OperationJournal,
        "production",
        lambda _: SimpleNamespace(
            require_no_live_execution=lambda **_: events.append("all-release-grants-checked")
        ),
    )
    with installation._maintenance_lease(policy):
        assert state["held"]
        events.append("install-and-activate")
        with pytest.raises(OSError):
            Socket().bind(("127.0.0.1", 8765))
    assert not state["held"]
    assert events[-2:] == ["install-and-activate", "closed"]
    assert events.index("all-release-grants-checked") < events.index("execution-leases-closed")
    assert events.index("execution-leases-closed") < events.index("install-and-activate")
