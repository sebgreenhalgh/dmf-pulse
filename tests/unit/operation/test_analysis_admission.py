"""Read-only admission mirrors existing account reservation caps before token input."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation.journal import OperationJournal
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.standing import execution_key
from tests.unit.operation.standing_support import NOW, owned_event, owned_policy


def journal(tmp_path, *, daily=0, monthly=0, unresolved=0, used=0, consumed=False):
    policy = owned_policy(tmp_path)
    event = owned_event(gameweek=11)
    rows = [{"kind": "DISCOVERY", "payload": {"value": event.model_dump(mode="json")}, "at": NOW}]
    if consumed:
        rows.append({"kind": "ENROLL", "execution_key": execution_key(policy, 11), "at": NOW})
    account = canonical_sha256(policy.odds_account_ref)
    period = NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    records = [
        {
            "kind": "RESERVATION",
            "account_sha256": account,
            "day": (NOW if i < daily else NOW - timedelta(days=1)).date().isoformat(),
            "period": period,
        }
        for i in range(monthly)
    ]

    @contextmanager
    def transaction():
        yield None, rows

    value = OperationJournal(policy, lambda: pytest.fail("unit scope never connects"))
    value._transaction = transaction
    value._paid_state = lambda *_: (used, unresolved)
    value.ledger = SimpleNamespace(account_sha256=account, _read_records=lambda _: records)
    return value, rows, records


@pytest.mark.parametrize(
    "changes,code",
    [
        ({}, None),
        ({"daily": 1, "monthly": 1}, "DAILY_BUDGET_EXHAUSTED"),
        ({"monthly": 8}, "MONTHLY_BUDGET_EXHAUSTED"),
        ({"unresolved": 1}, "QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION"),
        ({"used": 490}, "QUOTA_BELOW_SAFETY_RESERVE"),
        ({"consumed": True, "daily": 1, "monthly": 1}, "GAMEWEEK_ACQUISITION_ALREADY_RECORDED"),
    ],
)
def test_local_check_never_enrolls_reserves_or_rewrites_custody(tmp_path, changes, code):
    value, rows, records = journal(tmp_path, **changes)
    before = deepcopy((rows, records))
    if code:
        with pytest.raises(OperationError, match=code):
            value.local_refresh_check(now=NOW)
    else:
        value.local_refresh_check(now=NOW)
    assert (rows, records) == before


def test_old_deadline_does_not_infer_next_event_or_reopen_consumed_one(tmp_path):
    value, rows, records = journal(tmp_path, consumed=True)
    rows[0]["payload"]["value"]["deadline_at"] = (NOW - timedelta(seconds=1)).isoformat()
    rows[1]["at"] = NOW - timedelta(days=1)
    value.local_refresh_check(now=NOW)
    assert len(rows) == 2 and not records
    assert rows[1]["execution_key"] == execution_key(value.policy, 11)
