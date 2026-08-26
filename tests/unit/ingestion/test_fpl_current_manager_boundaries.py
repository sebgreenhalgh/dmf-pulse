"""Temporal, rights, source-binding, and local-file boundary tests for 001C."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl import manager_current
from dmf_pulse.ingestion.fpl.manager_current import (
    MAX_MANAGER_DECLARATION_BYTES,
    CurrentManagerStateRequest,
    CurrentManagerStateService,
    bind_current_manager_state_request,
)
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset, RulesetStatus
from tests.unit.ingestion.current_manager_test_support import (
    CUTOFF,
    MANAGER_RECEIVED,
    MANAGER_USABLE,
    CurrentManagerTestContext,
    build_context,
    write_declaration,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def context(repository_root: Path, tmp_path: Path) -> CurrentManagerTestContext:
    return build_context(repository_root, tmp_path)


def _compile_path(
    context: CurrentManagerTestContext,
    path: Path,
    *,
    request: CurrentManagerStateRequest | None = None,
    fpl_input: object | None = None,
    ruleset: CompiledRuleset | None = None,
    capability: CapabilityArtifact | None = None,
    times: tuple[datetime, datetime] = (MANAGER_RECEIVED, MANAGER_USABLE),
) -> object:
    fpl = context.fpl_input if fpl_input is None else fpl_input
    rules = context.ruleset if ruleset is None else ruleset
    cap = context.capability if capability is None else capability
    bound = request or bind_current_manager_state_request(
        path, context.fpl_input, context.ruleset, context.capability
    )
    clock = iter(times)
    return CurrentManagerStateService(clock=lambda: next(clock)).compile(
        bound,
        fpl_input=fpl,  # type: ignore[arg-type]
        ruleset=rules,
        capability=cap,
    )


def _assert_failure(call: Callable[[], object], code: str | set[str]) -> None:
    with pytest.raises(IngestionError) as caught:
        call()
    expected = {code} if isinstance(code, str) else code
    assert caught.value.code in expected
    assert "synthetic-operator" not in caught.value.message


@pytest.mark.parametrize(
    "mutation",
    [
        "naive-declared",
        "declared-after-cutoff",
        "attested-after-cutoff",
        "attested-before-declared",
        "declared-before-fpl-usable",
        "wrong-cutoff",
    ],
)
def test_declaration_temporal_mutations_are_rejected(
    context: CurrentManagerTestContext,
    mutation: str,
) -> None:
    value = deepcopy(context.declaration)
    if mutation == "naive-declared":
        value["attestation"]["declared_at"] = "2026-08-24T11:00:00"
    elif mutation == "declared-after-cutoff":
        value["attestation"]["declared_at"] = "2026-08-26T12:00:01Z"
        value["attestation"]["attested_at"] = "2026-08-26T12:00:02Z"
    elif mutation == "attested-after-cutoff":
        value["attestation"]["attested_at"] = "2026-08-26T12:00:01Z"
    elif mutation == "attested-before-declared":
        value["attestation"]["attested_at"] = "2026-08-24T10:59:59Z"
    elif mutation == "declared-before-fpl-usable":
        value["attestation"]["declared_at"] = "2026-08-24T10:05:59Z"
        value["attestation"]["attested_at"] = "2026-08-24T10:06:00Z"
    else:
        value["information_cutoff"] = "2026-08-26T11:59:59Z"
    path = write_declaration(context, value)
    _assert_failure(
        lambda: _compile_path(context, path),
        {"VALIDATION_FAILED", "POST_CUTOFF", "MAPPING_CONFLICT"},
    )


@pytest.mark.parametrize(
    ("times", "code"),
    [
        ((CUTOFF.replace(microsecond=1), CUTOFF.replace(microsecond=2)), "POST_CUTOFF"),
        ((MANAGER_RECEIVED, CUTOFF.replace(microsecond=1)), "POST_CUTOFF"),
        ((MANAGER_USABLE, MANAGER_RECEIVED), "INTERNAL_INVARIANT"),
        (
            (
                datetime(2026, 8, 24, 11, 2),
                datetime(2026, 8, 24, 11, 3, tzinfo=UTC),
            ),
            "INTERNAL_INVARIANT",
        ),
    ],
    ids=("receipt-post-cutoff", "usable-post-cutoff", "clock-backward", "naive-clock"),
)
def test_service_time_boundary_is_fail_closed(
    context: CurrentManagerTestContext,
    times: tuple[datetime, datetime],
    code: str,
) -> None:
    path = write_declaration(context, context.declaration)
    _assert_failure(lambda: _compile_path(context, path, times=times), code)


@pytest.mark.parametrize(
    ("owner", "field", "value"),
    [
        ("rights", "automated_access", "ALLOW"),
        ("rights", "derived_storage", "ALLOW"),
        ("rights", "raw_storage_performed", True),
        ("rights", "database_accessed", True),
        ("provenance", "transport_called", True),
        ("provenance", "derived_storage_performed", True),
    ],
)
def test_inherited_fpl_rights_cannot_be_weakened(
    context: CurrentManagerTestContext,
    owner: str,
    field: str,
    value: object,
) -> None:
    path = write_declaration(context, context.declaration)
    nested = getattr(context.fpl_input, owner).model_copy(update={field: value})
    mutated = context.fpl_input.model_copy(update={owner: nested})
    request = bind_current_manager_state_request(path, mutated, context.ruleset, context.capability)
    _assert_failure(
        lambda: _compile_path(context, path, request=request, fpl_input=mutated),
        {"MAPPING_CONFLICT", "RIGHTS_BLOCKED"},
    )


def test_fpl_catalogue_substitution_after_binding_is_rejected(
    context: CurrentManagerTestContext,
) -> None:
    path = write_declaration(context, context.declaration)
    request = bind_current_manager_state_request(
        path, context.fpl_input, context.ruleset, context.capability
    )
    first = context.fpl_input.players[0]
    changed = first.model_copy(update={"current_price_tenths": first.current_price_tenths + 1})
    mutated = context.fpl_input.model_copy(
        update={"players": (changed, *context.fpl_input.players[1:])}
    )
    _assert_failure(
        lambda: _compile_path(context, path, request=request, fpl_input=mutated),
        "MAPPING_CONFLICT",
    )


@pytest.mark.parametrize(
    "binding",
    [
        "target_gameweek",
        "information_cutoff",
        "fpl_input_semantic_sha256",
        "fpl_catalogue_view_sha256",
        "ruleset_sha256",
        "full_season_capability_sha256",
    ],
)
def test_each_prebound_source_identity_is_enforced(
    context: CurrentManagerTestContext,
    binding: str,
) -> None:
    path = write_declaration(context, context.declaration)
    request = bind_current_manager_state_request(
        path, context.fpl_input, context.ruleset, context.capability
    )
    replacement: object
    if binding == "target_gameweek":
        replacement = request.target_gameweek + 1
    elif binding == "information_cutoff":
        replacement = request.information_cutoff.replace(microsecond=1)
    else:
        replacement = "0" * 64
    mutated = request.model_copy(update={binding: replacement})
    _assert_failure(lambda: _compile_path(context, path, request=mutated), "MAPPING_CONFLICT")


def test_inactive_rules_and_substituted_rule_lineage_are_blocked(
    context: CurrentManagerTestContext,
) -> None:
    path = write_declaration(context, context.declaration)
    inactive = context.ruleset.model_copy(update={"status": RulesetStatus.VERIFIED})
    inactive_request = bind_current_manager_state_request(
        path, context.fpl_input, inactive, context.capability
    )
    _assert_failure(
        lambda: _compile_path(context, path, request=inactive_request, ruleset=inactive),
        "CONFIGURATION_INVALID",
    )

    request = bind_current_manager_state_request(
        path, context.fpl_input, context.ruleset, context.capability
    )
    changed_rules = context.ruleset.model_copy(update={"ruleset_hash": "0" * 64})
    _assert_failure(
        lambda: _compile_path(context, path, request=request, ruleset=changed_rules),
        "MAPPING_CONFLICT",
    )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"[]", "VALIDATION_FAILED"),
        (b'{"schema_version":"1.0.0","schema_version":"1.0.0"}', "DUPLICATE_JSON_KEY"),
        (b"\xff", "MALFORMED_JSON"),
        (b'{"bank_tenths":NaN}', "MALFORMED_JSON"),
        (b'{"bank_tenths":Infinity}', "MALFORMED_JSON"),
        (b"{", "MALFORMED_JSON"),
    ],
)
def test_strict_json_rejects_malformed_sources(
    context: CurrentManagerTestContext,
    body: bytes,
    code: str,
) -> None:
    path = context.working / "strict-source.json"
    path.write_bytes(body)
    _assert_failure(lambda: _compile_path(context, path), code)


def test_extra_fields_and_wrong_scalar_types_are_rejected(
    context: CurrentManagerTestContext,
) -> None:
    extra = deepcopy(context.declaration)
    extra["entry_id"] = 123456
    _assert_failure(
        lambda: _compile_path(context, write_declaration(context, extra)), "VALIDATION_FAILED"
    )
    wrong = deepcopy(context.declaration)
    wrong["bank_tenths"] = "15"
    _assert_failure(
        lambda: _compile_path(context, write_declaration(context, wrong)), "VALIDATION_FAILED"
    )


def test_missing_nonregular_and_oversize_sources_are_rejected(
    context: CurrentManagerTestContext,
) -> None:
    missing = context.working / "missing.json"
    _assert_failure(lambda: _compile_path(context, missing), "SOURCE_UNAVAILABLE")
    _assert_failure(lambda: _compile_path(context, context.working), "SOURCE_UNAVAILABLE")

    oversize = context.working / "oversize.json"
    oversize.write_bytes(b" " * (MAX_MANAGER_DECLARATION_BYTES + 1))
    _assert_failure(lambda: _compile_path(context, oversize), "PAYLOAD_TOO_LARGE")


def test_symlink_source_is_rejected(
    context: CurrentManagerTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_declaration(context, context.declaration, name="symlink-target.json")
    observed = os.lstat(path)
    values = list(observed)
    values[0] = stat.S_IFLNK | 0o777
    monkeypatch.setattr(manager_current.os, "lstat", lambda _path: os.stat_result(values))
    _assert_failure(lambda: _compile_path(context, path), "SOURCE_UNAVAILABLE")


def test_open_and_path_substitution_checks_are_descriptor_bound(
    context: CurrentManagerTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_declaration(context, context.declaration)
    real_lstat = os.lstat
    before = real_lstat(path)
    altered_values = list(before)
    altered_values[1] = int(before.st_ino) + 1
    altered = os.stat_result(altered_values)
    calls = iter((before, altered))
    monkeypatch.setattr(manager_current.os, "lstat", lambda _path: next(calls))
    _assert_failure(lambda: _compile_path(context, path), "SOURCE_UNAVAILABLE")


def test_descriptor_size_change_still_obeys_bounded_read(
    context: CurrentManagerTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = context.working / "growing.json"
    path.write_bytes(b" " * (MAX_MANAGER_DECLARATION_BYTES + 1))
    real_fstat = os.fstat

    def understated(descriptor: int) -> os.stat_result:
        observed = real_fstat(descriptor)
        values = list(observed)
        values[6] = 1
        return os.stat_result(values)

    monkeypatch.setattr(manager_current.os, "fstat", understated)
    _assert_failure(lambda: _compile_path(context, path), "PAYLOAD_TOO_LARGE")
