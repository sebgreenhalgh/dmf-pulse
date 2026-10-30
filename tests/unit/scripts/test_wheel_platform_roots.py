"""Installation expectations retain all exact applicable roots on both platforms."""

import importlib.util

import pytest
from packaging.markers import Marker as RealMarker


def load(root):
    spec = importlib.util.spec_from_file_location(
        "owned_wheel_platform_verifier", root / "scripts/verify_wheel.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def distributions(module, monkeypatch, platform):
    class Marker:
        def __init__(self, text):
            self.marker = RealMarker(text)

        def evaluate(self):
            return self.marker.evaluate({"sys_platform": platform})

    monkeypatch.setattr(module, "Marker", Marker)
    return module._expected_runtime_distributions()


def test_linux_and_windows_install_exact_applicable_frozen_graph(repository_root, monkeypatch):
    module = load(repository_root)
    windows = distributions(module, monkeypatch, "win32")
    linux = distributions(module, monkeypatch, "linux")
    assert windows["pywin32-ctypes"] == "0.2.3"
    assert "pywin32-ctypes" not in linux
    assert windows.keys() - linux.keys() == {"pywin32-ctypes", "colorama", "tzdata"}
    assert not linux.keys() - windows.keys()
    assert all(windows[name] == version for name, version in linux.items())
    assert {
        "alembic",
        "pydantic",
        "psycopg",
        "psycopg-binary",
        "sqlalchemy",
        "typer",
        "pyyaml",
        "fastapi",
        "uvicorn",
    } <= linux.keys()


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_platform_selection_never_bypasses_lock_manifest_authentication(
    repository_root, monkeypatch, platform
):
    module = load(repository_root)
    original = module._runtime_manifest_from_lock
    monkeypatch.setattr(
        module, "_runtime_manifest_from_lock", lambda: {**original(), "lock_sha256": "0" * 64}
    )
    with pytest.raises(module.VerificationError, match=r"exactly match uv\.lock"):
        distributions(module, monkeypatch, platform)
