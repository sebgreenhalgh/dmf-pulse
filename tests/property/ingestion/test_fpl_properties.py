"""Deterministic properties for strict payload and rights boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import FplResource, parse_fpl_payload
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    QualityIssue,
    QualityReport,
    RightsCapability,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.rights import decide_rights, load_rights_profiles

pytestmark = pytest.mark.property


def _bootstrap(root: Path) -> dict[str, object]:
    path = root / "fixtures" / "fpl" / "FPL-004" / "happy_path" / "bootstrap.json"
    value = json.loads(path.read_text("utf-8"))
    assert isinstance(value, dict)
    return value


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@given(
    st.text(
        alphabet=st.characters(whitelist_categories=("Ll",), min_codepoint=97, max_codepoint=122),
        min_size=1,
        max_size=20,
    ).filter(
        lambda name: (
            name
            not in {
                "events",
                "game_settings",
                "teams",
                "elements",
                "element_types",
                "phases",
                "total_players",
                "element_stats",
            }
        )
    ),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
)
def test_additive_top_level_fields_never_change_promoted_semantics(
    repository_root: Path, name: str, value: int
) -> None:
    baseline = _bootstrap(repository_root)
    changed = dict(baseline)
    changed[name] = value
    baseline_parsed = parse_fpl_payload(FplResource.BOOTSTRAP, _encode(baseline))
    changed_parsed = parse_fpl_payload(FplResource.BOOTSTRAP, _encode(changed))
    assert changed_parsed.drift.classification.value == "ADDITIVE_UNKNOWN"
    assert f"$.{name}" in changed_parsed.drift.unknown_paths
    assert changed_parsed.semantic_sha256 == baseline_parsed.semantic_sha256


@given(st.decimals(min_value="0", max_value="100", allow_nan=False, allow_infinity=False, places=6))
def test_decimal_percentages_are_exact_and_deterministic(
    repository_root: Path, percentage: object
) -> None:
    value = _bootstrap(repository_root)
    elements = value["elements"]
    assert isinstance(elements, list) and isinstance(elements[0], dict)
    elements[0]["selected_by_percent"] = str(percentage)
    body = _encode(value)
    first = parse_fpl_payload(FplResource.BOOTSTRAP, body)
    second = parse_fpl_payload(FplResource.BOOTSTRAP, body)
    assert first.semantic_sha256 == second.semantic_sha256
    assert str(first.payload.elements[0].selected_by_percent) == str(percentage)  # type: ignore[union-attr]


@given(
    invalid=st.one_of(
        st.booleans(), st.text(min_size=0), st.floats(allow_nan=False, allow_infinity=False)
    )
)
def test_required_integer_identity_never_coerces(invalid: object, repository_root: Path) -> None:
    if isinstance(invalid, int) and not isinstance(invalid, bool):
        return
    value = _bootstrap(repository_root)
    teams = value["teams"]
    assert isinstance(teams, list) and isinstance(teams[0], dict)
    teams[0]["id"] = invalid
    with pytest.raises(IngestionError) as raised:
        parse_fpl_payload(FplResource.BOOTSTRAP, _encode(value))
    assert raised.value.code == "VALIDATION_FAILED"
    assert raised.value.details["classification"] == "BLOCKING_TYPE_CHANGE"
    assert "$.teams[0].id" in raised.value.details["type_error_paths"]


@given(st.lists(st.sampled_from(["P0", "P1", "P2", "P3"]), max_size=25))
def test_quality_status_and_counts_follow_severity_partition(severities: list[str]) -> None:
    issues = tuple(
        QualityIssue(severity=severity, code=f"ISSUE_{index}", subject_scope="synthetic")
        for index, severity in enumerate(severities)
    )
    blockers = sum(severity in {"P0", "P1"} for severity in severities)
    warnings = sum(severity in {"P2", "P3"} for severity in severities)
    status = "BLOCKED" if blockers else "PASS_WITH_WARNINGS" if warnings else "PASS"
    report = QualityReport(
        status=status,  # type: ignore[arg-type]
        warning_count=warnings,
        blocker_count=blockers,
        issues=issues,
    )
    assert report.blocker_count + report.warning_count == len(severities)
    assert report.status == status


@given(
    st.sampled_from(
        [
            status
            for status in RightsProfileStatus
            if status is not RightsProfileStatus.HUMAN_APPROVED
        ]
    )
)
def test_nonapproved_statuses_fail_closed_for_allow_capabilities(
    repository_root: Path, status: RightsProfileStatus
) -> None:
    profile = load_rights_profiles(repository_root / "config" / "rights" / "fpl_profiles.json")[
        "synthetic_test_v1"
    ]
    assert profile.capabilities[RightsCapability.RAW_STORAGE] is CapabilityValue.ALLOW
    decision = decide_rights(
        profile.model_copy(update={"status": status}), RightsCapability.RAW_STORAGE
    )
    assert decision.decision == "DENY"
    assert decision.reason == "PROFILE_NOT_APPROVED"
