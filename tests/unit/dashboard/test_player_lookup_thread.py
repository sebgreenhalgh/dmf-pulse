"""Absent player lookups return 404 without crossing Futures or cancelling jobs."""

from threading import get_ident
from types import SimpleNamespace

import pytest

from dmf_pulse.dashboard.app import create_app
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime
from tests.unit.dashboard.test_dashboard import CODE, pair, request


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize(
    "path", ["/api/players/99999999", "/api/compare/1/99999999", "/api/compare/99999999/1"]
)
def test_missing_player_is_translated_inside_worker_without_cancellation(
    monkeypatch, persistent, path
):
    if persistent:
        runtime = PersistentDeskRuntime(
            SimpleNamespace(snapshot=lambda: None),
            local_check=lambda: pytest.fail("lookup admitted refresh"),
            register=lambda _: pytest.fail("lookup registered credential"),
            prepare=lambda *_: pytest.fail("lookup started work"),
            provenance="OWNED_SYNTHETIC",
        )
    else:
        runtime = DeskRuntime(demo=True)
    caller = get_ident()
    calls = []

    def lookup(official_id):
        assert get_ident() != caller
        calls.append(official_id)
        if official_id == 99999999:
            raise StopIteration
        return object()

    before = runtime.tick()
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "player", lookup)
        if persistent:
            patch.setattr(
                runtime, "player_pair", lambda first, second: (lookup(first), lookup(second))
            )
        patch.setattr(runtime, "cancel", lambda: pytest.fail("missing player cancelled job"))
        application = create_app(runtime=runtime, pairing_code=CODE, port=8765)
        cookie = pair(application)
        status, _, body = request(application, path, browser_header=cookie)
        assert status == 404 and body == b'{"error_code":"PLAYER_UNAVAILABLE"}'
        assert 99999999 in calls
        assert runtime.tick() == before
    runtime.close()
