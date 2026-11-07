"""Owned orchestration checks; no ledger connection or actual source qualification."""

import json
import sys
from datetime import timedelta

import pytest

from dmf_pulse.operation.models import OperationError
from dmf_pulse.player_lab import real_rights as rights
from dmf_pulse.player_lab import real_store
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.real import RealDeadlineRegistration, RealPointFreeze
from dmf_pulse.player_lab.real_rights import AcceptedProtocolIntent
from dmf_pulse.player_lab.store import PostgresResearchLedger
from tests.unit.player_lab.real_support import AT, owned_case, owned_full, reseal
from tests.unit.scripts.script_support import load_script

mq = load_script("model_quality_custody")


class OwnedLedgerBoundary:
    """Mock only the existing ledger I/O boundary, never production custody."""

    def __init__(self, fail_at=None, wrong_response=False):
        self.calls = []
        self.fail_at = fail_at
        self.wrong_response = wrong_response

    def freeze_real_forecast(self, protocol, population, forecast):
        self.calls.append((protocol, population, forecast))
        if len(self.calls) == self.fail_at:
            raise OperationError("OWNED_FORCED_LEDGER_FAILURE")
        return seal(
            RealPointFreeze.model_construct(
                forecast=forecast,
                population_registration_sha256="f" * 64 if self.wrong_response else population,
                recorded_at=AT + timedelta(seconds=2),
                original_frozen_at=AT + timedelta(seconds=2),
                custody="DATABASE_PREDEADLINE",
                semantic_sha256="0" * 64,
            )
        )

    def append_real_label(self, label):
        self.calls.append(label)
        if len(self.calls) == self.fail_at:
            raise OperationError("OWNED_FORCED_LEDGER_FAILURE")
        return "f" * 64 if self.wrong_response else label.semantic_sha256


def prospective_case(monkeypatch, *, qualified=True, intent=True):
    protocol, populations, forecasts, _, registry = owned_case(prospective=True)
    accepted = AcceptedProtocolIntent(
        intent_sha256=real_store.protocol_intent_sha256(protocol),
        owner_decision_ref="OWNED_TEST_ONLY",
        independent_review_sha256="8" * 64,
        accepted_at=AT - timedelta(days=1),
        expires_at=AT + timedelta(days=1),
    )
    if intent:
        registry = registry.model_copy(update={"accepted_protocol_intents": (accepted,)})
    if qualified:
        monkeypatch.setattr(rights, "real_source_registry", lambda: registry)
        monkeypatch.setattr(real_store, "real_source_registry", lambda: registry)
    monkeypatch.setattr(mq, "_now", lambda: AT + timedelta(seconds=2))
    registration = seal(
        RealDeadlineRegistration.model_construct(
            protocol_sha256=protocol.semantic_sha256,
            population=populations[0],
            registered_at=AT,
            original_population_frozen_at=AT,
            semantic_sha256="0" * 64,
        )
    )
    originals = tuple(owned_full(x) for x in forecasts if x.key.gameweek == populations[0].gameweek)
    return protocol, registration, originals


def test_complete_original_population_uses_existing_adapter_without_prediction_changes(monkeypatch):
    protocol, registration, originals = prospective_case(monkeypatch)
    before = tuple(x.model_dump_json() for x in originals)
    ledger = OwnedLedgerBoundary()
    result = mq.freeze_full_population(ledger, protocol, registration, originals)
    assert result.kind == "COMPLETE_ORIGINAL_FORECAST_POPULATION"
    assert len(result.ledger_artifact_sha256s) == len(originals) == 2
    assert set(result.original_artifact_sha256s) == {x.semantic_sha256 for x in originals}
    assert tuple(x.model_dump_json() for x in originals) == before
    for _, population, adapted in ledger.calls:
        assert population == registration.semantic_sha256
        assert adapted.original_full_forecast in originals
        assert adapted.stage12.point_forecast == adapted.original_full_forecast.mean
        assert adapted.stage12.pmf == {
            str(k): v for k, v in adapted.original_full_forecast.pmf.items()
        }


def test_actual_empty_registry_refuses_before_any_database_connection(monkeypatch):
    protocol, registration, originals = prospective_case(monkeypatch, qualified=False)
    ledger = PostgresResearchLedger(lambda: pytest.fail("no database access authorized"))
    with pytest.raises(OperationError, match="SOURCE_NOT_QUALIFIED"):
        mq.freeze_full_population(ledger, protocol, registration, originals)


def test_missing_owner_intent_refuses_before_io(monkeypatch):
    protocol, registration, originals = prospective_case(monkeypatch, intent=False)
    ledger = OwnedLedgerBoundary()
    with pytest.raises(OperationError, match="OWNER_ACCEPTANCE_REQUIRED"):
        mq.freeze_full_population(ledger, protocol, registration, originals)
    assert ledger.calls == []


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "future", "version", "synthetic", "registration"]
)
def test_invalid_batch_is_rejected_before_first_ledger_write(monkeypatch, change):
    protocol, registration, originals = prospective_case(monkeypatch)
    if change == "missing":
        originals = originals[:1]
    elif change == "duplicate":
        originals = (originals[0], originals[0])
    elif change == "future":
        originals = (reseal(originals[0], generated_at=AT + timedelta(seconds=3)), originals[1])
    elif change == "version":
        originals = (reseal(originals[0], model_version_ids=("different",)), originals[1])
    elif change == "synthetic":
        originals = (reseal(originals[0], dataset_mode="SYNTHETIC"), originals[1])
    else:
        registration = reseal(registration, protocol_sha256="f" * 64)
    ledger = OwnedLedgerBoundary()
    with pytest.raises(ValueError):
        mq.freeze_full_population(ledger, protocol, registration, originals)
    assert ledger.calls == []


def test_partial_commit_is_explicit_and_attempted_outcome_requires_reconciliation(monkeypatch):
    protocol, registration, originals = prospective_case(monkeypatch)
    ledger = OwnedLedgerBoundary(fail_at=2)
    with pytest.raises(mq.IncompleteCaptureError) as error:
        mq.freeze_full_population(ledger, protocol, registration, originals)
    assert len(error.value.completed_sha256s) == 1
    assert error.value.attempted_outcome == "UNKNOWN_RECONCILE_EXISTING_LEDGER"
    assert len(ledger.calls) == 2


def test_bad_ledger_response_cannot_return_complete_receipt(monkeypatch):
    protocol, registration, originals = prospective_case(monkeypatch)
    ledger = OwnedLedgerBoundary(wrong_response=True)
    with pytest.raises(mq.IncompleteCaptureError):
        mq.freeze_full_population(ledger, protocol, registration, originals)


def label_case(monkeypatch):
    protocol, populations, _, labels, registry = owned_case()
    monkeypatch.setattr(rights, "real_source_registry", lambda: registry)
    monkeypatch.setattr(mq, "_now", lambda: AT)
    population = populations[0]
    before = population.catalogue_source.usable_at
    registration = seal(
        RealDeadlineRegistration.model_construct(
            protocol_sha256=protocol.semantic_sha256,
            population=population,
            registered_at=before,
            original_population_frozen_at=before,
            semantic_sha256="0" * 64,
        )
    )
    return registration, tuple(x for x in labels if x.key.gameweek == population.gameweek)


def test_complete_finalized_labels_preserve_exact_revision_hashes(monkeypatch):
    registration, labels = label_case(monkeypatch)
    ledger = OwnedLedgerBoundary()
    result = mq.append_finalized_population(ledger, registration, labels)
    assert set(result.ledger_artifact_sha256s) == {x.semantic_sha256 for x in labels}
    assert ledger.calls == sorted(labels, key=lambda x: x.key.target_id())


def test_missing_label_remains_missing_and_denies_complete_capture(monkeypatch):
    registration, labels = label_case(monkeypatch)
    ledger = OwnedLedgerBoundary()
    with pytest.raises(ValueError, match="COMPLETE_UNIQUE_FINAL_LABEL"):
        mq.append_finalized_population(ledger, registration, labels[:1])
    assert ledger.calls == []


def test_label_partial_failure_preserves_completed_hashes(monkeypatch):
    registration, labels = label_case(monkeypatch)
    with pytest.raises(mq.IncompleteCaptureError) as error:
        mq.append_finalized_population(OwnedLedgerBoundary(fail_at=2), registration, labels)
    assert len(error.value.completed_sha256s) == 1


@pytest.mark.parametrize("failure", [RuntimeError, AttributeError, KeyboardInterrupt])
@pytest.mark.parametrize("kind", ["forecast", "label"])
def test_unexpected_error_or_interruption_preserves_progress_without_false_pass(
    monkeypatch, failure, kind
):
    class InterruptedLedger(OwnedLedgerBoundary):
        def freeze_real_forecast(self, protocol, population, forecast):
            if len(self.calls) == 1:
                self.calls.append((protocol, population, forecast))
                raise failure("owned failure details must not escape")
            return super().freeze_real_forecast(protocol, population, forecast)

        def append_real_label(self, label):
            if len(self.calls) == 1:
                self.calls.append(label)
                raise failure("owned failure details must not escape")
            return super().append_real_label(label)

    ledger = InterruptedLedger()
    with pytest.raises(mq.IncompleteCaptureError) as captured:
        if kind == "forecast":
            protocol, registration, originals = prospective_case(monkeypatch)
            mq.freeze_full_population(ledger, protocol, registration, originals)
        else:
            registration, labels = label_case(monkeypatch)
            mq.append_finalized_population(ledger, registration, labels)
    assert len(captured.value.completed_sha256s) == 1
    assert len(ledger.calls) == 2
    assert captured.value.exception_family == failure.__name__
    assert captured.value.interrupted is (failure is KeyboardInterrupt)
    assert captured.value.attempted_outcome == "UNKNOWN_RECONCILE_EXISTING_LEDGER"
    assert "owned failure details" not in str(captured.value)
    if kind == "forecast":
        assert captured.value.attempted_model_id == "owned-point"


def test_readiness_reports_actual_unqualified_state_and_cannot_pass(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["model_quality_custody.py", "--readiness"])
    with pytest.raises(SystemExit) as error:
        mq.main()
    assert error.value.code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED_REAL_AUTHORITY_NOT_INSTALLED"
    assert result["package_qualified_source_count"] == 0
    assert result["package_accepted_intent_count"] == 0
    assert result["database_or_provider_access"] is False
