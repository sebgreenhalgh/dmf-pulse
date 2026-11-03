"""Owned supervisor faults preserve consumed sessions and require child quiescence."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.operation import campaign_start as subject
from dmf_pulse.operation.models import OperationError

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
KEY = "f" * 64


@pytest.fixture
def supervisor_case(monkeypatch, tmp_path):
    def prepare(mode):
        events = []
        terminal = [None]
        session = SimpleNamespace(
            session_index=1, session_key=KEY, lease_until=NOW + timedelta(minutes=30)
        )

        class Journal:
            def verify_original_custody(self):
                events.append("VERIFY_ORIGINAL")

            def begin_session(self, requested_mode, *, now):
                assert requested_mode == "PAID_ELIGIBLE" and now == NOW
                events.append("BEGIN_SESSION")
                return session

            def execution_ceiling(self, key):
                assert key == KEY
                events.append("AUTHENTICATED_CEILING")
                return (
                    NOW - timedelta(seconds=1)
                    if mode in {"phase", "periodic"}
                    else session.lease_until
                )

            def session_receipt(self, key):
                assert key == KEY
                return {"terminal": terminal[0]}

            def terminate(self, key, *, diagnostics, error_code, now):
                assert key == KEY and now == NOW
                assert diagnostics.failure is not None
                expected = "RUN_TIMEOUT" if mode in {"phase", "periodic"} else "WORKER_STOPPED"
                assert error_code == expected
                events.append("TERMINAL_FACT")
                terminal[0] = {"outcome": "FAILED", "error_code": error_code}

            def close(self, key, *, worker_and_transports_quiescent, now):
                assert key == KEY and worker_and_transports_quiescent is True and now == NOW
                events.append("CUSTODY_CLOSE")

        class Worker:
            def __init__(self, key, expiry):
                assert key == KEY and expiry == NOW + timedelta(hours=1)
                self.receives = 0
                events.append("WORKER_CREATED")

            def start(self):
                events.append("WORKER_START")
                if mode == "spawn_failure":
                    raise RuntimeError("owned spawn refused")

            def alive(self):
                return True

            def receive(self):
                self.receives += 1
                if mode == "keyboard_interrupt":
                    raise KeyboardInterrupt()
                if mode == "phase" and self.receives == 1:
                    events.append("PHASE_NOTIFICATION")
                    return "phase", "OFFICIAL_GW10_DEADLINE_VERIFIED"
                raise RuntimeError("owned worker loop stopped")

            def close(self):
                events.append("WORKER_CLOSE_ATTEMPT")
                if mode == "close_failure":
                    raise RuntimeError("owned child termination unconfirmed")
                events.append("WORKER_QUIESCENT")

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                assert tz == UTC
                return NOW

        progress_count = [0]

        def progress(value):
            assert isinstance(value, str)
            progress_count[0] += 1
            if mode == "initial_progress_failure" and progress_count[0] == 1:
                raise BrokenPipeError("owned output unavailable")

        def export(journal, key):
            assert isinstance(journal, Journal) and key == KEY
            events.append("EXPORT")
            return tmp_path / "owned-receipt-not-created.json"

        monkeypatch.setattr(subject, "datetime", Clock)
        monkeypatch.setattr(subject, "DiagnosticWorker", Worker)
        monkeypatch.setattr(subject, "_export_receipt", export)
        monkeypatch.setattr(subject.time, "sleep", lambda _: None)
        if mode in {"phase", "periodic"}:
            elapsed = [0.0]

            def monotonic():
                elapsed[0] += 1.1 if mode == "periodic" else 0.01
                return elapsed[0]

            monkeypatch.setattr(subject.time, "monotonic", monotonic)
        return SimpleNamespace(events=events, journal=Journal(), progress=progress)

    return prepare


@pytest.mark.parametrize(
    "mode", ["keyboard_interrupt", "initial_progress_failure", "spawn_failure"]
)
def test_failure_closes_and_exports_only_after_confirmed_worker_quiescence(supervisor_case, mode):
    owned = supervisor_case(mode)
    key, receipt = subject.run_bounded_session(
        owned.journal, "PAID_ELIGIBLE", NOW + timedelta(hours=1), progress=owned.progress
    )
    assert key == KEY and receipt["terminal"]["outcome"] == "FAILED"
    assert owned.events.count("BEGIN_SESSION") == 1
    assert owned.events.count("TERMINAL_FACT") == owned.events.count("CUSTODY_CLOSE") == 1
    assert owned.events.count("EXPORT") == 1
    if mode == "initial_progress_failure":
        assert "WORKER_CREATED" not in owned.events
    else:
        assert owned.events.index("WORKER_QUIESCENT") < owned.events.index("TERMINAL_FACT")
    assert owned.events.index("TERMINAL_FACT") < owned.events.index("CUSTODY_CLOSE")
    assert owned.events.index("CUSTODY_CLOSE") < owned.events.index("EXPORT")


def test_unconfirmed_child_shutdown_preserves_the_lease_and_writes_no_close(supervisor_case):
    owned = supervisor_case("close_failure")
    with pytest.raises(OperationError, match="WORKER_CLEANUP_FAILED"):
        subject.run_bounded_session(
            owned.journal, "PAID_ELIGIBLE", NOW + timedelta(hours=1), progress=owned.progress
        )
    assert owned.events.count("BEGIN_SESSION") == owned.events.count("WORKER_CREATED") == 1
    assert "WORKER_CLOSE_ATTEMPT" in owned.events
    assert not {"WORKER_QUIESCENT", "TERMINAL_FACT", "CUSTODY_CLOSE", "EXPORT"} & set(owned.events)


@pytest.mark.parametrize("mode", ["phase", "periodic"])
def test_shortened_canonical_ceiling_stops_child_before_terminal_and_close(supervisor_case, mode):
    owned = supervisor_case(mode)
    _, receipt = subject.run_bounded_session(
        owned.journal, "PAID_ELIGIBLE", NOW + timedelta(hours=1), progress=owned.progress
    )
    assert receipt["terminal"]["error_code"] == "RUN_TIMEOUT"
    assert owned.events.count("AUTHENTICATED_CEILING") == 1
    assert ("PHASE_NOTIFICATION" in owned.events) is (mode == "phase")
    assert owned.events.index("AUTHENTICATED_CEILING") < owned.events.index("WORKER_QUIESCENT")
    assert owned.events.index("WORKER_QUIESCENT") < owned.events.index("TERMINAL_FACT")
    assert owned.events.index("TERMINAL_FACT") < owned.events.index("CUSTODY_CLOSE")
    assert owned.events.count("BEGIN_SESSION") == owned.events.count("EXPORT") == 1
