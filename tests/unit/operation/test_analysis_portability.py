"""Portable first launch does not invoke Windows-only process discovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.operation import analysis_paths, desk_instance, local_control, start
from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime
from tests.unit.operation.standing_support import owned_policy


def test_posix_analytical_path_uses_absolute_xdg_or_home(monkeypatch):
    monkeypatch.setattr(analysis_paths, "os", SimpleNamespace(name="posix", environ={}))
    assert analysis_paths.warehouse_path() == (
        Path.home() / ".local/share/dmf-pulse/analysis/dmf_pulse.sqlite"
    )
    configured = str(Path.home() / "owned-data")
    analysis_paths.os.environ["XDG_DATA_HOME"] = configured
    assert (
        analysis_paths.warehouse_path() == Path(configured) / "dmf-pulse/analysis/dmf_pulse.sqlite"
    )
    analysis_paths.os.environ["XDG_DATA_HOME"] = "relative-data"
    with pytest.raises(ValueError, match="ANALYSIS_ABSOLUTE_DATA_PATH_REQUIRED"):
        analysis_paths.warehouse_path()


def test_posix_first_launch_loads_history_without_native_registration(tmp_path, monkeypatch):
    import uvicorn

    policy = owned_policy(tmp_path)
    events = []
    runtime = DeskRuntime(demo=True)
    journal = SimpleNamespace(recover=lambda: events.append("recover-journal"))

    class Listener:
        def setsockopt(self, *_):
            return None

        def bind(self, address):
            assert address == ("127.0.0.1", start.PORT)

        def listen(self, _):
            return None

        def close(self):
            events.append("close-listener")

    monkeypatch.setattr(start, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(start, "require_history_policy", lambda: policy)
    monkeypatch.setattr(start.socket, "socket", lambda *_: Listener())
    monkeypatch.setattr(
        analysis_paths, "warehouse_path", lambda: tmp_path / "analysis" / "history.sqlite"
    )
    monkeypatch.setattr(
        desk_instance, "register_instance", lambda *_: pytest.fail("Windows process API")
    )
    monkeypatch.setattr(
        local_control, "recover_local_control", lambda _: events.append("recover-control")
    )
    monkeypatch.setattr(start.OperationJournal, "production", lambda _: journal)
    monkeypatch.setattr(PersistentDeskRuntime, "production", lambda *_: runtime)
    monkeypatch.setattr(start.threading, "Thread", lambda **_: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(
        uvicorn,
        "Server",
        lambda _: SimpleNamespace(run=lambda **_: events.append("serve-history")),
    )
    start.run_start(progress=lambda _: None)
    assert events == ["recover-control", "recover-journal", "serve-history", "close-listener"]
