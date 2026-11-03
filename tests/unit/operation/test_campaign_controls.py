"""Stable identifiers and closed diagnostics, with no acquisition authority."""

import ast
import re
from pathlib import Path

import pytest

from dmf_pulse.current_failures import CURRENT_FAILURE_CODES
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.operation.campaign_execution import diagnostic_run_id
from dmf_pulse.operation.diagnostics import safe_failure
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1.models import PrivateV1ExecutionInput

CANARY = "owned-unknown-code-credential-body-canary"


def test_canonical_session_hash_fits_the_unchanged_protected_run_id_contract():
    pattern = PrivateV1ExecutionInput.model_json_schema()["properties"]["run_id"]["pattern"]
    key = "abcdef0123456789" * 4
    assert re.fullmatch(pattern, diagnostic_run_id(key))
    assert diagnostic_run_id(key) == "OPR003_" + key.upper()


@pytest.mark.parametrize("key", ["a" * 63, "A" * 64, "../" + "a" * 61, CANARY])
def test_run_identifier_cannot_change_or_import_canonical_session_identity(key):
    with pytest.raises(OperationError, match="DIAGNOSTIC_SESSION_NOT_FOUND"):
        diagnostic_run_id(key)


def test_every_literal_campaign_refusal_has_a_finite_safe_diagnostic_mapping():
    root = Path(__file__).resolve().parents[3] / "src/dmf_pulse/operation"
    codes = set()
    for path in (*root.glob("campaign*.py"), *root.glob("diagnostic*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "OperationError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("DIAGNOSTIC_")
            ):
                codes.add(node.args[0].value)
    assert codes and codes <= CURRENT_FAILURE_CODES
    for code in codes:
        failure = safe_failure(OperationError(code), "RESULT_VALIDATION")
        assert failure.code == code and failure.typed_code_recognized


def test_unknown_or_provider_exception_text_never_enters_safe_receipt():
    for error in (
        OperationError(CANARY),
        OperationError("DIAGNOSTIC_" + CANARY),
        ValueError(CANARY),
    ):
        failure = safe_failure(error, "RESULT_VALIDATION")
        assert CANARY not in failure.model_dump_json()
        assert failure.code in {"CURRENT_TYPED_FAILURE_UNRECOGNIZED", "CURRENT_INTERNAL_EXCEPTION"}


def test_fixed_ingestion_rights_refusal_is_precise_without_supplier_or_body_text():
    failure = safe_failure(IngestionError("RIGHTS_BLOCKED", CANARY), "SCORE_SOURCE_ACQUISITION")
    assert failure.code == "SOURCE_SCOPE_INVALID"
    assert failure.typed_code_recognized and CANARY not in failure.model_dump_json()
