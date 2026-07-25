"""Strict, offline tests for the frozen FPL payload adapter."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import (
    CONTRACT_VERSION,
    MAX_COLLECTION_ITEMS,
    MAX_JSON_DEPTH,
    MAX_PAYLOAD_BYTES,
    BootstrapPayload,
    FixturePayload,
    FplResource,
    parse_fpl_payload,
    parsed_artifact,
)
from dmf_pulse.ingestion.models import DriftClassification

pytestmark = pytest.mark.unit


def _fixture(root: Path, case: str, resource: FplResource) -> bytes:
    return (root / "fixtures" / "fpl" / "FPL-004" / case / f"{resource.value}.json").read_bytes()


def _json_fixture(root: Path, case: str, resource: FplResource) -> object:
    return json.loads(_fixture(root, case, resource))


def _encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _assert_error(
    resource: FplResource,
    body: bytes,
    code: str,
    *,
    classification: str | None = None,
) -> IngestionError:
    with pytest.raises(IngestionError) as raised:
        parse_fpl_payload(resource, body)
    error = raised.value
    assert error.code == code
    if classification is not None:
        assert error.details["classification"] == classification
    return error


def test_happy_fixtures_have_frozen_hashes_and_typed_values(repository_root: Path) -> None:
    bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP, _fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    )
    fixtures = parse_fpl_payload(
        FplResource.FIXTURES, _fixture(repository_root, "happy_path", FplResource.FIXTURES)
    )

    assert (
        bootstrap.payload_sha256
        == "b878e03f0eddb88889794f86df486c0d28f33e2498b58b9e66f947dd7c6e611e"
    )
    assert (
        fixtures.payload_sha256
        == "c4c5108488ed02c61c933ea4184a23ac0e808f3097f4f36ef25e7fe7a48fd2e0"
    )
    assert (
        bootstrap.semantic_sha256
        == "e05f0104d63b08a040a81ce40fef9e5665013dc6460ea1b64ee12bbe25e2eb82"
    )
    assert (
        fixtures.semantic_sha256
        == "450e98768e045fe4682c8c40c8adac9f98e42bf52892260ee642c30f4dc345a7"
    )
    assert bootstrap.drift.classification is DriftClassification.MISSING_OPTIONAL
    assert fixtures.drift.classification is DriftClassification.NO_DRIFT
    assert isinstance(bootstrap.payload, BootstrapPayload)
    assert isinstance(fixtures.payload, FixturePayload)
    assert bootstrap.payload.events[0].deadline_time.utcoffset().total_seconds() == 0
    assert isinstance(bootstrap.payload.elements[0].selected_by_percent, Decimal)


def test_unknown_additive_paths_are_exact_and_do_not_change_semantic_projection(
    repository_root: Path,
) -> None:
    happy_bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP, _fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    )
    unknown_bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        _fixture(repository_root, "unknown_additive", FplResource.BOOTSTRAP),
    )
    happy_fixtures = parse_fpl_payload(
        FplResource.FIXTURES, _fixture(repository_root, "happy_path", FplResource.FIXTURES)
    )
    unknown_fixtures = parse_fpl_payload(
        FplResource.FIXTURES,
        _fixture(repository_root, "unknown_additive", FplResource.FIXTURES),
    )

    assert unknown_bootstrap.drift.classification is DriftClassification.ADDITIVE_UNKNOWN
    assert unknown_bootstrap.drift.unknown_paths == (
        "$.elements[0].future_player_metric",
        "$.future_top_level",
        "$.teams[0].future_team_metric",
    )
    assert unknown_fixtures.drift.unknown_paths == ("$[0].future_fixture_field",)
    assert unknown_bootstrap.semantic_sha256 == happy_bootstrap.semantic_sha256
    assert unknown_fixtures.semantic_sha256 == happy_fixtures.semantic_sha256
    assert unknown_bootstrap.payload_sha256 != happy_bootstrap.payload_sha256
    assert unknown_fixtures.payload_sha256 != happy_fixtures.payload_sha256


def test_absent_optional_field_and_explicit_null_have_distinct_semantics(
    repository_root: Path,
) -> None:
    body = _json_fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    assert isinstance(body, dict)
    explicit_null = deepcopy(body)
    teams = explicit_null["teams"]
    assert isinstance(teams, list)
    assert isinstance(teams[0], dict)
    teams[0]["played"] = None

    absent = parse_fpl_payload(FplResource.BOOTSTRAP, _encode(body))
    present_null = parse_fpl_payload(FplResource.BOOTSTRAP, _encode(explicit_null))

    assert "$.teams[0].played" in absent.drift.missing_optional_paths
    assert "$.teams[0].played" not in present_null.drift.missing_optional_paths
    assert absent.semantic_sha256 != present_null.semantic_sha256


def test_parsed_artifact_excludes_additive_unknown_values_but_retains_drift(
    repository_root: Path,
) -> None:
    parsed = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        _fixture(repository_root, "unknown_additive", FplResource.BOOTSTRAP),
    )

    artifact = parsed_artifact(parsed)
    payload = artifact["payload"]
    assert isinstance(payload, dict)
    assert "future_top_level" not in payload
    teams = payload["teams"]
    assert isinstance(teams, list)
    assert isinstance(teams[0], dict)
    assert "future_team_metric" not in teams[0]
    drift = artifact["drift"]
    assert isinstance(drift, dict)
    assert "$.future_top_level" in drift["unknown_paths"]


@pytest.mark.parametrize(
    ("case", "code", "classification", "detail_key", "expected_path"),
    [
        (
            "missing_required",
            "VALIDATION_FAILED",
            "BLOCKING_MISSING_REQUIRED",
            "missing_required_paths",
            "$.elements[0].code",
        ),
        (
            "wrong_type",
            "VALIDATION_FAILED",
            "BLOCKING_TYPE_CHANGE",
            "type_error_paths",
            "$.teams[0].id",
        ),
        ("malformed", "MALFORMED_JSON", "MALFORMED", None, None),
    ],
)
def test_blocking_pack_cases_have_stable_failures(
    repository_root: Path,
    case: str,
    code: str,
    classification: str,
    detail_key: str | None,
    expected_path: str | None,
) -> None:
    error = _assert_error(
        FplResource.BOOTSTRAP,
        _fixture(repository_root, case, FplResource.BOOTSTRAP),
        code,
        classification=classification,
    )
    if detail_key is not None:
        assert error.details[detail_key] == [expected_path]


@pytest.mark.parametrize(
    ("resource", "body", "code", "classification"),
    [
        (FplResource.BOOTSTRAP, b"[]", "VALIDATION_FAILED", None),
        (FplResource.FIXTURES, b"{}", "VALIDATION_FAILED", None),
        (FplResource.BOOTSTRAP, b"\xff", "MALFORMED_JSON", "MALFORMED"),
        (
            FplResource.BOOTSTRAP,
            b'{"events":[],"events":[]}',
            "DUPLICATE_JSON_KEY",
            "MALFORMED",
        ),
        (FplResource.FIXTURES, b"[NaN]", "MALFORMED_JSON", "MALFORMED"),
    ],
)
def test_parser_rejects_malformed_or_wrong_root_payloads(
    resource: FplResource,
    body: bytes,
    code: str,
    classification: str | None,
) -> None:
    _assert_error(resource, body, code, classification=classification)


def test_parser_enforces_byte_depth_and_collection_limits() -> None:
    _assert_error(
        FplResource.BOOTSTRAP,
        b" " * (MAX_PAYLOAD_BYTES + 1),
        "PAYLOAD_TOO_LARGE",
        classification="LIMIT_EXCEEDED",
    )
    too_deep = ("[" * (MAX_JSON_DEPTH + 1) + "]" * (MAX_JSON_DEPTH + 1)).encode()
    _assert_error(
        FplResource.FIXTURES,
        too_deep,
        "PAYLOAD_TOO_DEEP",
        classification="LIMIT_EXCEEDED",
    )
    too_many = _encode([None] * (MAX_COLLECTION_ITEMS + 1))
    _assert_error(FplResource.FIXTURES, too_many, "PAYLOAD_TOO_LARGE")


def test_parser_rejects_unknown_contract_version(repository_root: Path) -> None:
    body = _fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    with pytest.raises(IngestionError) as raised:
        parse_fpl_payload(FplResource.BOOTSTRAP, body, contract_version="future-v2")
    assert raised.value.code == "CONFIGURATION_INVALID"
    assert CONTRACT_VERSION == "fpl-reference-v1"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["teams"].append(deepcopy(value["teams"][0])), "provider identifiers"),
        (
            lambda value: value["teams"][1].update(code=value["teams"][0]["code"]),
            "provider identifiers",
        ),
        (
            lambda value: value["events"].append(deepcopy(value["events"][0])),
            "Gameweek identifiers",
        ),
        (
            lambda value: value["elements"].append(deepcopy(value["elements"][0])),
            "player identifiers",
        ),
        (lambda value: value["elements"][0].update(team=999), "unknown team"),
        (lambda value: value["elements"][0].update(element_type=999), "unknown position"),
    ],
)
def test_bootstrap_semantic_invariants(
    repository_root: Path,
    mutation: object,
    message: str,
) -> None:
    value = _json_fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    assert isinstance(value, dict)
    mutation(value)  # type: ignore[operator]
    with pytest.raises(IngestionError, match=message) as raised:
        parse_fpl_payload(FplResource.BOOTSTRAP, _encode(value))
    assert raised.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.append(deepcopy(value[0])), "fixture identifiers"),
        (lambda value: value[0].update(team_a=value[0]["team_h"]), "teams must differ"),
        (
            lambda value: value[0].update(
                started=False, finished=False, team_h_score=1, team_a_score=None
            ),
            "score lacks",
        ),
    ],
)
def test_fixture_semantic_invariants(
    repository_root: Path,
    mutation: object,
    message: str,
) -> None:
    value = _json_fixture(repository_root, "happy_path", FplResource.FIXTURES)
    assert isinstance(value, list)
    mutation(value)  # type: ignore[operator]
    with pytest.raises(IngestionError, match=message) as raised:
        parse_fpl_payload(FplResource.FIXTURES, _encode(value))
    assert raised.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize("invalid_event", [0, -1])
def test_fixture_gameweek_identifier_must_be_positive(
    repository_root: Path, invalid_event: int
) -> None:
    value = _json_fixture(repository_root, "happy_path", FplResource.FIXTURES)
    assert isinstance(value, list) and isinstance(value[0], dict)
    value[0]["event"] = invalid_event
    error = _assert_error(
        FplResource.FIXTURES,
        _encode(value),
        "VALIDATION_FAILED",
        classification="BLOCKING_TYPE_CHANGE",
    )
    assert error.details["type_error_paths"] == ["$.fixtures[0].event"]


@pytest.mark.parametrize(
    ("resource", "mutate", "path"),
    [
        (
            FplResource.BOOTSTRAP,
            lambda value: value["events"][0].update(deadline_time="2026-08-14T18:30:00"),
            "$.events[0].deadline_time",
        ),
        (
            FplResource.FIXTURES,
            lambda value: value[0].update(kickoff_time="2026-08-15T14:00:00"),
            "$.fixtures[0].kickoff_time",
        ),
    ],
)
def test_naive_timestamps_are_blocking_type_changes(
    repository_root: Path,
    resource: FplResource,
    mutate: object,
    path: str,
) -> None:
    value = _json_fixture(repository_root, "happy_path", resource)
    mutate(value)  # type: ignore[operator]
    error = _assert_error(
        resource, _encode(value), "VALIDATION_FAILED", classification="BLOCKING_TYPE_CHANGE"
    )
    assert error.details["type_error_paths"] == [path]


@pytest.mark.parametrize(
    "invalid",
    (
        "2026-08-14 18:30:00+00:00",
        "2026-W33-5T18:30:00+00:00",
        "2026-08-14T18:30:00+00:00:30",
        "2026-08-14t18:30:00z",
    ),
)
def test_non_rfc3339_timestamp_forms_are_blocking_type_changes(
    repository_root: Path, invalid: str
) -> None:
    value = _json_fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    assert isinstance(value, dict)
    value["events"][0]["deadline_time"] = invalid
    error = _assert_error(
        FplResource.BOOTSTRAP,
        _encode(value),
        "VALIDATION_FAILED",
        classification="BLOCKING_TYPE_CHANGE",
    )
    assert error.details["type_error_paths"] == ["$.events[0].deadline_time"]


@pytest.mark.parametrize("invalid", [-1, 101, True, [], "not-a-decimal"])
def test_selected_percentage_is_exact_and_bounded(repository_root: Path, invalid: object) -> None:
    value = _json_fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    assert isinstance(value, dict)
    value["elements"][0]["selected_by_percent"] = invalid
    error = _assert_error(
        FplResource.BOOTSTRAP,
        _encode(value),
        "VALIDATION_FAILED",
        classification="BLOCKING_TYPE_CHANGE",
    )
    assert error.details["type_error_paths"] == ["$.elements[0].selected_by_percent"]


def test_repeated_parse_is_deterministic(repository_root: Path) -> None:
    body = _fixture(repository_root, "happy_path", FplResource.BOOTSTRAP)
    first = parse_fpl_payload(FplResource.BOOTSTRAP, body)
    second = parse_fpl_payload(FplResource.BOOTSTRAP, body)
    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
