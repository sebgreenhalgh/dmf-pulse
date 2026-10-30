"""Clock/deadline guards do not alter football utility or legal optimisation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from dmf_pulse.private_v1.actionability import (
    ActionabilityReceipt,
    DeadlineGuard,
    checked_report,
    require_publication,
)
from dmf_pulse.private_v1.errors import PrivateV1Error

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
DEADLINE = NOW + timedelta(hours=1)


def test_receipt_and_publication_bind_exact_report_and_decision():
    receipt = DeadlineGuard(lambda: NOW).bind(
        deadline_at=DEADLINE, decision_sha256="a" * 64, report="SYNTHETIC REPORT"
    )
    assert ActionabilityReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    require_publication(
        receipt,
        decision_sha256="a" * 64,
        report="SYNTHETIC REPORT",
        now=DEADLINE - timedelta(microseconds=1),
    )
    for decision, report in (("b" * 64, "SYNTHETIC REPORT"), ("a" * 64, "ALTERED REPORT")):
        with pytest.raises(PrivateV1Error) as failure:
            require_publication(receipt, decision_sha256=decision, report=report, now=NOW)
        assert failure.value.code == "DECISION_PUBLICATION_INVALID"
    changed = receipt.model_copy(update={"deadline_at": DEADLINE + timedelta(days=1)})
    with pytest.raises(PrivateV1Error) as failure:
        require_publication(changed, decision_sha256="a" * 64, report="SYNTHETIC REPORT", now=NOW)
    assert failure.value.code == "DECISION_PUBLICATION_INVALID"


@pytest.mark.parametrize("time", [DEADLINE, DEADLINE + timedelta(microseconds=1)])
def test_exact_deadline_is_expired(time):
    with pytest.raises(PrivateV1Error) as failure:
        DeadlineGuard(lambda: time).check(DEADLINE)
    assert failure.value.code == "DECISION_DEADLINE_PASSED"


@pytest.mark.parametrize(
    "time", [None, "not a time", NOW.replace(tzinfo=None), NOW - timedelta(seconds=1)]
)
def test_invalid_or_reversed_clock_fails_closed(time):
    with pytest.raises(PrivateV1Error) as failure:
        DeadlineGuard(lambda: time, not_before=NOW).check(DEADLINE)
    assert failure.value.code == "DECISION_CLOCK_INVALID"


def test_clock_exception_is_sanitized():
    def broken():
        raise OSError("PRIVATE_VALUE_NOT_FOR_OUTPUT")

    with pytest.raises(PrivateV1Error) as failure:
        DeadlineGuard(broken).check(DEADLINE)
    assert failure.value.code == "DECISION_CLOCK_INVALID"
    assert "PRIVATE_VALUE" not in failure.value.message


def test_offset_clock_normalizes_and_cpu_after_cutoff_is_allowed():
    offset = NOW.astimezone(timezone(timedelta(hours=2)))
    guard = DeadlineGuard(lambda: offset, not_before=NOW - timedelta(minutes=5))
    assert guard.check(DEADLINE) == NOW
    # No information cutoff is accepted as an execution deadline by this API.
    assert guard.check(DEADLINE) == NOW


def test_cli_shared_publication_never_prints_a_report_rejected_by_runtime(monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from dmf_pulse.authorization_errors import AuthorizationError
    from dmf_pulse.cli import pulse
    from dmf_pulse.cli.app import app
    from dmf_pulse.operation.console import publish_runtime

    report = "SYNTHETIC_ACTION_MUST_NOT_PRINT"
    receipt = DeadlineGuard(lambda: NOW).bind(
        deadline_at=DEADLINE, decision_sha256="a" * 64, report=report
    )

    class Runtime:
        def refresh(self, horizon):
            return SimpleNamespace(status="COMPLETE", job_id="owned-expired")

        def view(self):
            result = SimpleNamespace(
                report=report,
                decision=SimpleNamespace(semantic_sha256="a" * 64),
                actionability=receipt,
                publication_not_before=NOW,
            )
            try:
                checked_report(result, clock=lambda: DEADLINE)
            except PrivateV1Error:
                raise AuthorizationError("REFRESH_GRANT_EXPIRED", "EXPIRED") from None
            pytest.fail("expired report admitted")

        def close(self):
            self.closed = True

    runtime = Runtime()

    def enrolled(**kwargs):
        return publish_runtime(runtime, horizon=kwargs["horizon"], publish=kwargs["publish"])

    monkeypatch.setattr(pulse, "run_enrolled_current", enrolled)
    result = CliRunner().invoke(
        app, ["pulse", "--entry-id", "42", "--no-progress", "--refresh-approval", "OWNED-TEST"]
    )
    assert result.exit_code == 2 and result.stdout == ""
    assert report not in result.output
    assert "REFRESH_GRANT_EXPIRED" in result.stderr and runtime.closed


def test_publication_checks_clock_after_hash_validation(monkeypatch):
    from types import SimpleNamespace

    from dmf_pulse.private_v1 import actionability

    report = "SYNTHETIC REPORT"
    receipt = DeadlineGuard(lambda: NOW).bind(
        deadline_at=DEADLINE, decision_sha256="a" * 64, report=report
    )
    state = {"now": NOW}
    original = actionability.hashlib.sha256

    def delayed_hash(*args, **kwargs):
        state["now"] = DEADLINE
        return original(*args, **kwargs)

    monkeypatch.setattr(actionability.hashlib, "sha256", delayed_hash)
    with pytest.raises(PrivateV1Error) as failure:
        checked_report(
            SimpleNamespace(
                actionability=receipt,
                publication_not_before=NOW,
                decision=SimpleNamespace(semantic_sha256="a" * 64),
                report=report,
            ),
            clock=lambda: state["now"],
        )
    assert failure.value.code == "DECISION_DEADLINE_PASSED"


def test_service_sealing_cannot_cross_deadline(monkeypatch):
    from dmf_pulse.private_v1 import actionability

    state = {"now": NOW}
    original = actionability.hashlib.sha256

    def delayed_hash(*args, **kwargs):
        state["now"] = DEADLINE
        return original(*args, **kwargs)

    monkeypatch.setattr(actionability.hashlib, "sha256", delayed_hash)
    with pytest.raises(PrivateV1Error) as failure:
        DeadlineGuard(lambda: state["now"]).bind(
            deadline_at=DEADLINE, decision_sha256="a" * 64, report="SYNTHETIC REPORT"
        )
    assert failure.value.code == "DECISION_DEADLINE_PASSED"


@pytest.mark.parametrize("result", [None, object(), {"report": "SYNTHETIC"}])
def test_missing_publication_evidence_is_sanitized(result):
    with pytest.raises(PrivateV1Error) as failure:
        checked_report(result, clock=lambda: NOW)
    assert failure.value.code == "DECISION_PUBLICATION_INVALID"


def test_final_clock_failure_is_sanitized():
    from types import SimpleNamespace

    report = "SYNTHETIC REPORT"
    receipt = DeadlineGuard(lambda: NOW).bind(
        deadline_at=DEADLINE, decision_sha256="a" * 64, report=report
    )

    def broken():
        raise OSError("PRIVATE_VALUE_NOT_FOR_OUTPUT")

    with pytest.raises(PrivateV1Error) as failure:
        checked_report(
            SimpleNamespace(
                actionability=receipt,
                publication_not_before=NOW,
                decision=SimpleNamespace(semantic_sha256="a" * 64),
                report=report,
            ),
            clock=broken,
        )
    assert failure.value.code == "DECISION_CLOCK_INVALID"
    assert "PRIVATE_VALUE" not in str(failure.value)


@pytest.mark.parametrize("reversed_clock", [False, True])
def test_publication_preserves_post_sealing_clock_high_water_mark(reversed_clock):
    from types import SimpleNamespace

    samples = iter((NOW + timedelta(seconds=10), NOW + timedelta(seconds=11)))
    guard = DeadlineGuard(lambda: next(samples))
    report = "SYNTHETIC REPORT"
    receipt = guard.bind(deadline_at=DEADLINE, decision_sha256="a" * 64, report=report)
    assert receipt.checked_at == NOW + timedelta(seconds=10)
    assert guard.latest_observed_at == NOW + timedelta(seconds=11)
    result = SimpleNamespace(
        report=report,
        actionability=receipt,
        publication_not_before=guard.latest_observed_at,
        decision=SimpleNamespace(semantic_sha256="a" * 64),
    )
    clock = lambda: NOW + timedelta(seconds=10.5 if reversed_clock else 11)  # noqa: E731
    if reversed_clock:
        with pytest.raises(PrivateV1Error) as failure:
            checked_report(result, clock=clock)
        assert failure.value.code == "DECISION_CLOCK_INVALID"
    else:
        assert checked_report(result, clock=clock) == report


@pytest.mark.parametrize(
    "floor", [None, NOW.replace(tzinfo=None), NOW - timedelta(seconds=1), DEADLINE]
)
def test_publication_rejects_missing_or_invalid_service_clock_mark(floor):
    from types import SimpleNamespace

    report = "SYNTHETIC REPORT"
    receipt = DeadlineGuard(lambda: NOW).bind(
        deadline_at=DEADLINE, decision_sha256="a" * 64, report=report
    )
    with pytest.raises(PrivateV1Error):
        checked_report(
            SimpleNamespace(
                report=report,
                actionability=receipt,
                publication_not_before=floor,
                decision=SimpleNamespace(semantic_sha256="a" * 64),
            ),
            clock=lambda: NOW,
        )


def test_unsampled_guard_has_no_clock_mark():
    with pytest.raises(PrivateV1Error) as failure:
        _ = DeadlineGuard(lambda: NOW).latest_observed_at
    assert failure.value.code == "DECISION_CLOCK_INVALID"
