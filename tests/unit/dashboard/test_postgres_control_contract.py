"""Read-free construction and strict control metadata boundary without PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.postgres_authorization import (
    PostgresUsageLedger,
    _aware,
    _validated_record,
)

pytestmark = pytest.mark.unit


def _record():
    record = {
        "kind": "RESERVATION",
        "at": "2026-10-29T12:00:00+00:00",
        "reservation_id": "1" * 64,
        "ledger_id": "2" * 64,
        "sequence": 0,
        "previous_sha256": "0" * 64,
        "grant_sha256": "3" * 64,
        "approval_sha256": "4" * 64,
        "account_sha256": "5" * 64,
        "authorization_sha256": "6" * 64,
        "day": "2026-10-29",
        "period": "2026-10-01T00:00:00+00:00",
    }
    return {**record, "sha256": canonical_sha256(record)}


def test_constructor_is_read_free_and_database_ref_is_only_identifier():
    calls = []

    def forbidden():
        calls.append(True)
        raise AssertionError("constructor touched database")

    ledger = PostgresUsageLedger(
        forbidden, "a" * 64, account_ref="owned-account", database_ref="SYNTHETIC_TEST_DATABASE"
    )
    assert ledger.backend_discriminator == "POSTGRES"
    assert ledger.database_ref == "SYNTHETIC_TEST_DATABASE"
    assert ledger.account_sha256 == canonical_sha256("owned-account")
    assert calls == []
    with pytest.raises(AuthorizationError, match="TRANSACTION_REQUIRED"):
        ledger._sql_append([], {})
    with pytest.raises(AuthorizationError, match="CONFIGURATION_INVALID"):
        PostgresUsageLedger(
            forbidden,
            "a" * 64,
            account_ref="owned-account",
            database_ref="postgresql://not-a-reference",
        )
    assert calls == []


@pytest.mark.parametrize(
    "field,value", [("account_ref", "invalid/account"), ("ledger_id", "not-a-digest")]
)
def test_invalid_identity_fails_before_factory(field, value):
    def forbidden():
        raise AssertionError("invalid config reached connection factory")

    values = {"account_ref": "owned-account", "ledger_id": "a" * 64, field: value}
    with pytest.raises(AuthorizationError, match="CONFIGURATION_INVALID"):
        PostgresUsageLedger(forbidden, **values)


@pytest.mark.parametrize("value", [None, 12, "2026-10-29T12:00:00", "x" * 41])
def test_control_clocks_reject_missing_naive_and_oversized(value):
    with pytest.raises(AuthorizationError, match="USAGE_LEDGER_INVALID"):
        _aware(value)


def test_aware_clock_normalizes_utc():
    assert _aware("2026-10-29T14:00:00+02:00") == datetime(2026, 10, 29, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "attack",
    [
        "extra",
        "wrong_kind",
        "bool_sequence",
        "negative_sequence",
        "wrong_ledger",
        "bad_hash_field",
        "wrong_account",
        "wrong_day",
        "future_period",
        "digest",
        "too_large",
    ],
)
def test_event_shape_values_and_hashes_fail_closed(attack):
    record = _record()
    if attack == "extra":
        record["provider_body"] = "OWNED_SYNTHETIC_FORBIDDEN_FIELD"
    elif attack == "wrong_kind":
        record["kind"] = "RESULT"
    elif attack == "bool_sequence":
        record["sequence"] = False
    elif attack == "negative_sequence":
        record["sequence"] = -1
    elif attack == "wrong_ledger":
        record["ledger_id"] = "f" * 64
    elif attack == "bad_hash_field":
        record["grant_sha256"] = "unsupported"
    elif attack == "wrong_account":
        record["account_sha256"] = "f" * 64
    elif attack == "wrong_day":
        record["day"] = "2026-10-30"
    elif attack == "future_period":
        record["period"] = "2026-11-01T00:00:00+00:00"
    elif attack == "too_large":
        record["at"] = "x" * 5000
    else:
        record["sha256"] = "f" * 64
    with pytest.raises(AuthorizationError):
        _validated_record(record, ledger_id="2" * 64, account_sha256="5" * 64)


def test_valid_control_event_contains_hashes_and_clocks_only():
    value = _record()
    _validated_record(value, ledger_id="2" * 64, account_sha256="5" * 64)
    assert not any(
        name in value
        for name in ("token", "credential", "provider_body", "manager_state", "forecast", "score")
    )
