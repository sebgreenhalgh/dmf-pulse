"""A cold inspection recovers authenticated control before custody access.

All authority, recovery and journal objects below are owned fakes. These cases
do not read credentials, connect to a database, append real custody or send HTTP.
"""

from datetime import UTC
from types import SimpleNamespace

import pytest

from dmf_pulse.operation import campaign_start, local_control
from dmf_pulse.operation.models import OperationError

KEY = "a" * 64
TERMINAL = "b" * 64


@pytest.fixture
def cold_inspection(monkeypatch):
    def prepare(*, fail_at=None, terminal=TERMINAL):
        calls = []
        state = {"recovered": False, "inspection_appended": False, "exported": False}
        normal_policy = object()

        def authenticate():
            calls.append("AUTHENTICATE")
            if fail_at == "authenticate":
                raise OperationError("DIAGNOSTIC_OWNER_AND_SIGNED_AUTHORITY_REQUIRED")
            return SimpleNamespace(normal_policy=normal_policy)

        def recover(policy):
            calls.append("RECOVER_ORIGINAL_CONTROL")
            assert policy is normal_policy
            if fail_at == "recover":
                raise OperationError("DATABASE_CONFIGURATION_INVALID")
            state["recovered"] = True

        class OwnedJournal:
            def session_receipt(self, key):
                calls.append("READ_TERMINAL")
                assert key == KEY and state["recovered"] is True
                return {"terminal_sha256": terminal}

            def inspect_previous(self, key, terminal_sha256, *, now):
                calls.append("INSPECT_CLOSED_TERMINAL")
                assert key == KEY and terminal_sha256 == terminal
                assert now.tzinfo is UTC
                if fail_at == "inspect":
                    raise OperationError("DIAGNOSTIC_CLOSED_TERMINAL_INSPECTION_REQUIRED")
                state["inspection_appended"] = True

        journal = OwnedJournal()

        def production():
            calls.append("OPEN_CANONICAL_JOURNAL")
            assert state["recovered"] is True, "cold context must be recovered first"
            if fail_at == "production":
                raise OperationError("STANDING_CONTROL_UNAVAILABLE_OR_INVALID")
            return journal

        def export(current, key):
            calls.append("EXPORT_RECEIPT")
            assert current is journal and key == KEY and state["inspection_appended"] is True
            state["exported"] = True

        def forbid_credentials():
            raise AssertionError("inspection must not instantiate a credential service")

        monkeypatch.setattr(campaign_start, "load_verified_campaign", authenticate)
        monkeypatch.setattr(local_control, "recover_local_control", recover)
        if hasattr(campaign_start, "recover_local_control"):
            monkeypatch.setattr(campaign_start, "recover_local_control", recover)
        monkeypatch.setattr(
            campaign_start, "DiagnosticJournal", SimpleNamespace(production=production)
        )
        monkeypatch.setattr(campaign_start, "_export_receipt", export)
        monkeypatch.setattr(campaign_start, "CredentialService", forbid_credentials)
        return calls, state

    return prepare


def test_cold_inspection_authenticates_then_recovers_before_canonical_access(cold_inspection):
    calls, state = cold_inspection()

    result = campaign_start.inspect_session(KEY)

    assert calls == [
        "AUTHENTICATE",
        "RECOVER_ORIGINAL_CONTROL",
        "OPEN_CANONICAL_JOURNAL",
        "READ_TERMINAL",
        "INSPECT_CLOSED_TERMINAL",
        "EXPORT_RECEIPT",
    ]
    assert state == {"recovered": True, "inspection_appended": True, "exported": True}
    assert result == {
        "session_key": KEY,
        "inspected_terminal_sha256": TERMINAL,
        "provider_requests": 0,
    }


@pytest.mark.parametrize(
    ("fail_at", "code", "expected_calls"),
    [
        (
            "authenticate",
            "DIAGNOSTIC_OWNER_AND_SIGNED_AUTHORITY_REQUIRED",
            ["AUTHENTICATE"],
        ),
        (
            "recover",
            "DATABASE_CONFIGURATION_INVALID",
            ["AUTHENTICATE", "RECOVER_ORIGINAL_CONTROL"],
        ),
        (
            "production",
            "STANDING_CONTROL_UNAVAILABLE_OR_INVALID",
            ["AUTHENTICATE", "RECOVER_ORIGINAL_CONTROL", "OPEN_CANONICAL_JOURNAL"],
        ),
    ],
)
def test_authentication_or_control_failure_cannot_inspect_or_export(
    cold_inspection, fail_at, code, expected_calls
):
    calls, state = cold_inspection(fail_at=fail_at)

    with pytest.raises(OperationError) as error:
        campaign_start.inspect_session(KEY)

    assert error.value.code == code
    assert calls == expected_calls
    assert state["inspection_appended"] is False and state["exported"] is False


@pytest.mark.parametrize("terminal", [None, 0, {"outcome": "FAILED"}])
def test_missing_or_non_string_terminal_cannot_append_inspection(cold_inspection, terminal):
    calls, state = cold_inspection(terminal=terminal)

    with pytest.raises(OperationError) as error:
        campaign_start.inspect_session(KEY)

    assert error.value.code == "DIAGNOSTIC_TERMINAL_RESULT_REQUIRED"
    assert calls == [
        "AUTHENTICATE",
        "RECOVER_ORIGINAL_CONTROL",
        "OPEN_CANONICAL_JOURNAL",
        "READ_TERMINAL",
    ]
    assert state["inspection_appended"] is False and state["exported"] is False


def test_unclosed_or_mismatched_terminal_refusal_cannot_export(cold_inspection):
    calls, state = cold_inspection(fail_at="inspect")

    with pytest.raises(OperationError) as error:
        campaign_start.inspect_session(KEY)

    assert error.value.code == "DIAGNOSTIC_CLOSED_TERMINAL_INSPECTION_REQUIRED"
    assert calls[-1] == "INSPECT_CLOSED_TERMINAL"
    assert state["inspection_appended"] is False and state["exported"] is False
