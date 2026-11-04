"""Portable checks of owner/process instance matching; native proof is tested installed."""

import os
from pathlib import Path

import pytest

from dmf_pulse.operation import desk_instance
from tests.unit.operation.standing_support import owned_policy


def fixture(tmp_path, monkeypatch):
    policy = owned_policy(tmp_path)
    image = str((tmp_path / "trusted-python.exe").resolve())
    monkeypatch.setattr(desk_instance, "_listener_pid", lambda _: os.getpid())
    monkeypatch.setattr(desk_instance, "_process_identity", lambda _: (123, image))
    path = tmp_path / "instance" / "desk-instance.json"
    instance = desk_instance.register_instance(path, policy, 8765)
    return path, policy, instance


def test_matching_owned_instance_is_reusable_without_model_or_account_access(tmp_path, monkeypatch):
    path, policy, instance = fixture(tmp_path, monkeypatch)
    assert desk_instance.verified_existing_instance(path, policy, 8765)
    assert set(__import__("json").loads(path.read_bytes())) == set(type(instance).model_fields)
    desk_instance.remove_instance(path, instance)
    assert not path.exists()


@pytest.mark.parametrize("change", ["birth", "image", "listener", "policy", "missing"])
def test_unrecognized_reused_pid_foreign_listener_or_policy_is_refused(
    tmp_path, monkeypatch, change
):
    path, policy, instance = fixture(tmp_path, monkeypatch)
    if change == "birth":
        monkeypatch.setattr(
            desk_instance, "_process_identity", lambda _: (124, instance.executable)
        )
    if change == "image":
        path.write_text(
            instance.model_copy(
                update={"executable": str(Path("foreign.exe").resolve())}
            ).model_dump_json(),
            encoding="utf-8",
        )
    if change == "listener":
        monkeypatch.setattr(desk_instance, "_listener_pid", lambda _: os.getpid() + 1)
    if change == "policy":
        policy = policy.model_copy(update={"implementation_sha": "1" * 40})
    if change == "missing":
        path.unlink()
    assert not desk_instance.verified_existing_instance(path, policy, 8765)
