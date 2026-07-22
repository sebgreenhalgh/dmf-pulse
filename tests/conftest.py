"""Global deterministic, offline, user-home-isolated test controls."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    database=None,
    deadline=None,
    derandomize=True,
    max_examples=75,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
settings.load_profile("ci")


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_home_and_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    fake_home = tmp_path / "isolated-home"
    fake_home.mkdir()
    for name in ("HOME", "USERPROFILE", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(fake_home))

    def blocked_network(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("tests must not access the network")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket, "getaddrinfo", blocked_network)
    monkeypatch.setattr(socket, "gethostbyaddr", blocked_network)
    monkeypatch.setattr(socket, "gethostbyname", blocked_network)
    monkeypatch.setattr(socket, "gethostbyname_ex", blocked_network)
    monkeypatch.setattr(socket, "getnameinfo", blocked_network)
    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_network)
    monkeypatch.setattr(socket.socket, "sendto", blocked_network)
    yield
