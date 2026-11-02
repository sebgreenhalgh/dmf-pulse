"""An expired free observation never admits a paid transport or key lookup."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.dashboard.current import CurrentAcquisitionGuard
from dmf_pulse.operation import standing
from tests.unit.operation.standing_support import NOW, owned_policy


@pytest.mark.parametrize("entry", ["preflight_send", "before_send", "before_transport"])
def test_paid_request_rechecks_quota_after_waiting_for_control_lock(tmp_path, monkeypatch, entry):
    policy = owned_policy(tmp_path)
    monkeypatch.setattr(standing, "require_policy", lambda: policy)
    clock = [NOW + timedelta(seconds=299)]
    transport = []
    guard = CurrentAcquisitionGuard.__new__(CurrentAcquisitionGuard)
    guard._launch = SimpleNamespace(
        grant=SimpleNamespace(request=SimpleNamespace(authorization_id="OPR001-OWNED")),
        quota=SimpleNamespace(observed_at=NOW),
        worker_id="OWNED",
    )
    guard._clock = lambda: clock[0]
    guard._closed = False
    guard._next_transport_provider = "ODDS"
    guard.failure = None

    def blocking_check(*_, **__):
        clock[0] = NOW + timedelta(seconds=301)

    guard._ledger = SimpleNamespace(
        preflight_attempt=blocking_check,
        check_transport_window=blocking_check,
        attempt=lambda *_, **__: transport.append("ATTEMPT"),
    )
    # Before-send is also an independent boundary: the observation may have
    # expired after preflight and before the attempt is written.
    if entry == "before_send":
        blocking_check()
    arguments = (
        ()
        if entry == "before_transport"
        else ("ODDS", "GET", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds")
    )
    with pytest.raises(AuthorizationError, match="QUALIFIED_QUOTA_EVIDENCE_STALE"):
        getattr(guard, entry)(*arguments)
    assert transport == []
    assert guard.failure.code == "QUALIFIED_QUOTA_EVIDENCE_STALE"
