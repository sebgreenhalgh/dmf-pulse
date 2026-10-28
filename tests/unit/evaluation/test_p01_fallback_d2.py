"""D2 synthetic metadata boundary and historical v1 authentication; no live acquisition."""

import hashlib
import json
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.p01_fallback_context import load_context
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate
from dmf_pulse.ingestion.p01_fallback import project_final_facts, regulation_type
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    METADATA_REASONS,
    DiagnosticProgress,
    ExecutionStage,
    FailureReason,
    MetadataCategory,
    MetadataField,
    P01FallbackExecutionFailure,
    SafeDiagnostics,
    SafeMetadataFailure,
    StoppedExecutionDiagnostic,
    stopped_record,
)
from dmf_pulse.ingestion.p01_match_metadata import require_match_metadata
from tests.unit.evaluation.p01_d1_test_support import captured_synthetic_forecast
from tests.unit.evaluation.test_p01_fallback_a02 import (
    AT,
    GLOBAL,
    LEAGUE,
    labels,
    provider_rows,
    synthetic_context,
)


@pytest.fixture(scope="module", autouse=True)
def stable_synthetic_input():
    from tests.unit.evaluation import test_p01_fallback_a02 as support

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(support, "frozen", captured_synthetic_forecast)
        support.ten_forecast.cache_clear()
        support.synthetic_context.cache_clear()
        yield
    support.ten_forecast.cache_clear()
    support.synthetic_context.cache_clear()
    support.scored.cache_clear()


def project(rows, progress):
    return progress.run(
        ExecutionStage.PROJECT_FINAL_FACTS,
        FailureReason.MATCHDAY_RESPONSE_INVALID,
        lambda: project_final_facts(
            json.dumps(rows).encode(),
            context=synthetic_context(),
            result_type=regulation_type(GLOBAL, LEAGUE),
            diagnostics=progress,
        ),
    )


FIELDS = [
    ("leagueId", MetadataField.LEAGUE_ID, 5997),
    ("leagueShortcut", MetadataField.LEAGUE_SHORTCUT, "other"),
    ("leagueSeason", MetadataField.LEAGUE_SEASON, 2025),
    ("leagueName", MetadataField.DISPLAY_NAME, "Alternate descriptive name"),
    ("groupOrderID", MetadataField.MATCHDAY, 7),
]


@pytest.mark.parametrize("key,field,wrong", FIELDS)
@pytest.mark.parametrize("category", list(MetadataCategory))
def test_individual_metadata_failures_are_localised_without_values(key, field, wrong, category):
    rows = provider_rows()
    obj = rows[0]["group"] if key == "groupOrderID" else rows[0]
    if category == MetadataCategory.MISSING:
        obj.pop(key)
    elif category == MetadataCategory.WRONG_TYPE:
        obj[key] = None
    else:
        obj[key] = wrong
    # Finality is deliberately false too: metadata must win before it is examined.
    rows[0]["matchIsFinished"] = False
    progress = DiagnosticProgress()
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        project(rows, progress)
    failure = caught.value
    assert failure.stage == ExecutionStage.PROJECT_FINAL_FACTS
    assert failure.reason == METADATA_REASONS[field]
    issue = failure.diagnostics.metadata_failure
    assert issue == SafeMetadataFailure(field=field, category=category)
    assert progress.safe.provider_match_rows == 10
    assert progress.safe.finished_match_rows == progress.safe.regulation_result_rows == 0
    assert progress.safe.projected_fact_count == 0
    record = stopped_record(
        failure,
        started_at=AT,
        stopped_at=AT,
        context_sha256=synthetic_context().semantic_sha256,
        one_attempt_consumed=True,
    )
    output = record.model_dump_json()
    assert StoppedExecutionDiagnostic.model_validate_json(output) == record
    assert set(issue.model_dump()) == {"classification", "field", "category"}
    assert not any(
        token in output
        for token in (
            "Alternate descriptive",
            "home_goals",
            "away_goals",
            "teamName",
            "matchID",
            "MUST_NOT_BE_RETAINED",
            "expected",
            "actual",
            "row_index",
        )
    )
    assert all(
        name not in output for row in synthetic_context().fixtures for name in row.home_aliases
    )


@pytest.mark.parametrize("key,field,wrong", [FIELDS[i] for i in (0, 2, 4)])
@pytest.mark.parametrize("kind", ["bool", "float", "string"])
def test_integer_identifiers_refuse_coercion(key, field, wrong, kind):
    row = {
        "leagueId": 5996,
        "leagueShortcut": "pl",
        "leagueSeason": 2026,
        "leagueName": "Premier League",
        "group": {"groupOrderID": 6},
    }
    obj = row["group"] if key == "groupOrderID" else row
    obj[key] = {"bool": True, "float": float(obj[key]), "string": str(obj[key])}[kind]
    progress = DiagnosticProgress()
    with pytest.raises(ValueError, match=METADATA_REASONS[field].value):
        require_match_metadata(row, context=load_context(), diagnostics=progress)
    assert progress.safe.metadata_failure.category == MetadataCategory.WRONG_TYPE


@pytest.mark.parametrize("key,field", [(key, field) for key, field, _ in FIELDS[1:4:2]])
@pytest.mark.parametrize("value", [b"Premier League", 1, [], None])
def test_string_fields_refuse_non_strings(key, field, value):
    row = {
        "leagueId": 5996,
        "leagueShortcut": "pl",
        "leagueSeason": 2026,
        "leagueName": "Premier League",
        "group": {"groupOrderID": 6},
    }
    row[key] = value
    progress = DiagnosticProgress()
    with pytest.raises(ValueError, match=METADATA_REASONS[field].value):
        require_match_metadata(row, context=load_context(), diagnostics=progress)
    assert progress.safe.metadata_failure.category == MetadataCategory.WRONG_TYPE


@pytest.mark.parametrize("value", [None, [], 6, "CANARY_UNAPPROVED_GROUP"])
def test_group_wrong_type_has_safe_group_field(value):
    rows = provider_rows()
    rows[0]["group"] = value
    progress = DiagnosticProgress()
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        project(rows, progress)
    assert caught.value.reason == FailureReason.METADATA_MATCHDAY_INVALID
    assert progress.safe.metadata_failure == SafeMetadataFailure(
        field=MetadataField.GROUP, category=MetadataCategory.WRONG_TYPE
    )
    assert "CANARY" not in progress.safe.model_dump_json()


def test_missing_group_and_stable_mismatch_precedence():
    rows = provider_rows()
    rows[0].pop("group")
    progress = DiagnosticProgress()
    with pytest.raises(P01FallbackExecutionFailure):
        project(rows, progress)
    assert progress.safe.metadata_failure == SafeMetadataFailure(
        field=MetadataField.GROUP, category=MetadataCategory.MISSING
    )
    rows[0].update(leagueId=5997, leagueName="CANARY_ALTERNATE_NAME")
    progress = DiagnosticProgress()
    with pytest.raises(P01FallbackExecutionFailure):
        project(rows, progress)
    assert progress.safe.metadata_failure.field == MetadataField.LEAGUE_ID


@pytest.mark.parametrize(
    "case,finished,reason",
    [
        ("unfinished", 0, FailureReason.MATCH_NOT_FINISHED),
        ("missing_final", 1, FailureReason.REGULATION_RESULT_MISSING_OR_AMBIGUOUS),
    ],
)
def test_correct_metadata_reaches_finality(case, finished, reason):
    rows = provider_rows()
    if case == "unfinished":
        rows[0]["matchIsFinished"] = False
    else:
        rows[0]["matchResults"] = []
    progress = DiagnosticProgress()
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        project(rows, progress)
    assert caught.value.reason == reason
    assert progress.safe.finished_match_rows == finished
    assert progress.safe.metadata_failure is None


def test_valid_completed_reordered_exact_ten_and_ambiguous_mapping():
    rows = provider_rows()
    progress = DiagnosticProgress()
    facts = project(rows, progress)
    assert (
        len(facts)
        == progress.safe.finished_match_rows
        == progress.safe.regulation_result_rows
        == 10
    )
    assert progress.safe.projected_fact_count == 10
    assert progress.safe.metadata_failure is None
    original = labels(rows=rows)
    reordered = labels(rows=list(reversed(rows)))
    assert original.outcomes == reordered.outcomes
    rows[1]["team1"], rows[1]["team2"] = rows[0]["team1"], rows[0]["team2"]
    with pytest.raises(ValueError, match="ORIENTED_MAPPING_AMBIGUOUS"):
        labels(rows=rows)


def test_original_a03_diagnostic_authenticates_without_hash_change():
    path = (
        Path(__file__).resolve().parents[2] / "fixtures/evaluation/a03_stopped_metadata_gate.json"
    )
    raw = path.read_bytes()
    original = json.loads(raw)
    record = authenticate(StoppedExecutionDiagnostic.model_validate_json(raw))
    assert record.reason == FailureReason.MATCHDAY_RESPONSE_INVALID
    assert record.stage == ExecutionStage.PROJECT_FINAL_FACTS
    assert record.diagnostics.provider_match_rows == 10
    assert record.diagnostics.finished_match_rows == 0
    assert record.diagnostics.metadata_failure is None
    assert record.model_dump(mode="json") == original
    assert canonical_sha256(record.model_dump(mode="json", exclude={"semantic_sha256"})) == (
        "db81ef1576046e5c5788830576aa44ce72ace03851cc4eb62106648aeb6c0cb2"
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == "d683b15240cd2ff6216d4566442c21c868c822411771715068627bd33d42d30f"
    )


@pytest.mark.parametrize(
    "value",
    [
        {"field": "teamName", "category": "MISMATCH"},
        {"field": "leagueName", "category": "CANARY"},
        {"field": "leagueName", "category": "MISMATCH", "actual": "CANARY"},
        {"field": "leagueName", "category": "MISMATCH", "classification": "MATCH_NOT_FINISHED"},
    ],
)
def test_metadata_schema_is_closed(value):
    with pytest.raises(ValueError):
        SafeMetadataFailure.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "stage,reason",
    [
        (ExecutionStage.ADMIT_EXACT_TEN, FailureReason.METADATA_DISPLAY_NAME_INVALID),
        (ExecutionStage.PROJECT_FINAL_FACTS, FailureReason.MATCH_NOT_FINISHED),
        (ExecutionStage.PROJECT_FINAL_FACTS, FailureReason.METADATA_LEAGUE_ID_INVALID),
    ],
)
def test_metadata_reason_and_stage_must_agree(stage, reason):
    safe = SafeDiagnostics(
        metadata_failure=SafeMetadataFailure(
            field=MetadataField.DISPLAY_NAME, category=MetadataCategory.MISMATCH
        )
    )
    with pytest.raises(ValueError, match="stage/reason"):
        P01FallbackExecutionFailure(stage, reason, safe)


def test_metadata_reason_requires_typed_details_and_old_serialization_unchanged():
    safe = SafeDiagnostics()
    assert "metadata_failure" not in safe.model_dump()
    assert "metadata_failure" not in safe.model_dump_json()
    with pytest.raises(ValueError, match="requires field/category"):
        P01FallbackExecutionFailure(
            ExecutionStage.PROJECT_FINAL_FACTS, FailureReason.METADATA_LEAGUE_ID_INVALID, safe
        )
