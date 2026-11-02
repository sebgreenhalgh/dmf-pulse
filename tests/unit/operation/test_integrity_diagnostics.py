"""Integrity refusals disclose only fixed reasons and the actual process phase."""

import pytest

from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.runtime_integrity import INTEGRITY_REASONS, RuntimeIntegrityError
from tests.unit.operation.test_operator_bootstrap import bootstrap

CANARY = "owned-sensitive-exception-path-canary"


@pytest.mark.parametrize("reason", [None, [], {}, CANARY, 7])
def test_invalid_reasons_fail_closed_without_formatting(reason):
    native = RuntimeIntegrityError(reason)
    translated = OperationError("STANDING_DEPENDENCY_TREE_CHANGED", integrity_reason=reason)
    assert native.reason == "CONTENT_OR_METADATA_MISMATCH"
    assert translated.integrity_reason is None
    assert CANARY not in str(native)


@pytest.mark.parametrize("phase", ["BOOTSTRAP", "WORKER_BOOTSTRAP", "APPLICATION"])
@pytest.mark.parametrize("translated", [False, True])
def test_native_reporting_preserves_phase_and_closed_reason(capsys, phase, translated):
    module = bootstrap()
    assert module.INTEGRITY_REASON_CODES == INTEGRITY_REASONS
    module._APPLICATION_ENTERED = phase == "APPLICATION"
    error = (
        OperationError(CANARY, integrity_reason="NATIVE_NOTIFICATION")
        if translated
        else RuntimeIntegrityError("NATIVE_NOTIFICATION")
    )
    module.report_verification_failure(error, worker=phase == "WORKER_BOOTSTRAP")
    output = capsys.readouterr().err
    assert phase in output and "[NATIVE_NOTIFICATION]" in output
    assert CANARY not in output and "0 provider" not in output
    assert "No automatic retry" in output


def test_unknown_native_exception_text_is_not_reported(capsys):
    bootstrap().report_verification_failure(ValueError(CANARY))
    output = capsys.readouterr().err
    assert "[UNSPECIFIED]" in output and CANARY not in output
