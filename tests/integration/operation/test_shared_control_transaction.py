"""Actual owned PostgreSQL proves original/diagnostic custody commits together."""

from datetime import timedelta

import pytest

from dmf_pulse.dashboard.authorization import AuthorizationError, RefreshAuthorizer, RefreshRequest
from dmf_pulse.operation import enrollment
from tests.integration.operation import test_standing_journal as support
from tests.unit.operation.standing_support import NOW, owned_event

case = support.case
clean_postgres_test = support.clean_postgres_test
journal_engine = support.journal_engine
rows = support.rows

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def prepare(case, monkeypatch):
    _, registry = support.admit(case)
    monkeypatch.setattr(enrollment, "installed_enrollment", lambda: registry)
    approval = registry.approvals[0]
    request = RefreshRequest(
        **{
            name: getattr(approval, name)
            for name in (
                "authorization_id",
                "implementation_sha",
                "review_sha256",
                "operator_ref",
                "purpose",
                "season_code",
                "mode",
                "source_scopes",
            )
        },
        horizon=1,
        information_cutoff=NOW + timedelta(seconds=300),
        deadline_at=owned_event().deadline_at,
    )
    return RefreshAuthorizer(case.journal.ledger, clock=lambda: NOW + timedelta(seconds=2)), request


@pytest.mark.parametrize("fail_after_journal", [False, True])
def test_cross_journal_failure_rolls_back_reservation_and_all_related_rows(
    case, monkeypatch, fail_after_journal
):
    authorizer, request = prepare(case, monkeypatch)
    before_legacy, before_journal = case.original.audit(), rows(case)
    with pytest.raises(RuntimeError, match="owned rollback"):  # noqa: SIM117
        with case.journal._transaction() as (connection, history):
            with case.journal.ledger.participate_in_transaction(connection):
                grant = authorizer.authorize(request)
                # The same connection must see its own uncommitted reservation.
                case.journal.ledger.claim(grant, "a" * 64, now=NOW + timedelta(seconds=3))
                assert case.journal.ledger.audit().event_count == before_legacy.event_count + 2
                if fail_after_journal:
                    case.journal._append(
                        connection,
                        history,
                        "LAUNCH",
                        {"owned_diagnostic_grant": grant.semantic_sha256},
                        now=NOW + timedelta(seconds=3),
                    )
                raise RuntimeError("owned rollback")
    assert case.original.audit() == before_legacy
    assert rows(case) == before_journal
    assert case.journal.ledger._active.get() is None


def test_cross_journal_commit_retains_one_reservation_claim_and_tag(case, monkeypatch):
    authorizer, request = prepare(case, monkeypatch)
    before_legacy, before_journal = case.original.audit(), rows(case)
    with case.journal._transaction() as (connection, history):  # noqa: SIM117
        with case.journal.ledger.participate_in_transaction(connection):
            grant = authorizer.authorize(request)
            case.journal.ledger.claim(grant, "b" * 64, now=NOW + timedelta(seconds=3))
            case.journal._append(
                connection,
                history,
                "LAUNCH",
                {"owned_diagnostic_grant": grant.semantic_sha256},
                now=NOW + timedelta(seconds=3),
            )
    actual = case.original.audit()
    assert actual.event_count == before_legacy.event_count + 2
    assert actual.reservation_count == before_legacy.reservation_count + 1
    assert actual.claim_count == before_legacy.claim_count + 1
    assert len(rows(case)) == len(before_journal) + 1
    assert case.journal.ledger._active.get() is None


def test_shared_transaction_rejects_missing_outer_transaction_and_nested_binding(case):
    with case.engine.connect() as connection:
        with pytest.raises(AuthorizationError, match="USAGE_LEDGER_TRANSACTION_REQUIRED"):  # noqa: SIM117
            with case.journal.ledger.participate_in_transaction(connection):
                pytest.fail("missing transaction admitted")
        with connection.begin(), case.journal.ledger.participate_in_transaction(connection):  # noqa: SIM117
            with pytest.raises(AuthorizationError, match="USAGE_LEDGER_TRANSACTION_REQUIRED"):
                with case.journal.ledger.participate_in_transaction(connection):
                    pytest.fail("nested connection binding admitted")
