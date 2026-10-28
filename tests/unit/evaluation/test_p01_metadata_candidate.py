"""D3 is an inactive synthetic candidate, never new acquisition policy."""

import hashlib
import json

import pytest

from dmf_pulse.evaluation.p01_fallback_context import FORECAST_SHA, load_context
from dmf_pulse.evaluation.p01_fallback_store import persist_fallback
from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from dmf_pulse.ingestion.p01_fallback import project_final_facts, regulation_type
from dmf_pulse.ingestion.p01_fallback_diagnostics import FailureReason, ReasonFailure
from dmf_pulse.ingestion.p01_metadata_candidate import project_synthetic_candidate
from tests.unit.evaluation.test_p01_fallback_a02 import (
    GLOBAL,
    LEAGUE,
    labels,
    provider_rows,
    synthetic_context,
)


def candidate(rows=None, context=None):
    return project_synthetic_candidate(
        json.dumps(provider_rows() if rows is None else rows).encode(),
        context=synthetic_context() if context is None else context,
        result_type=regulation_type(GLOBAL, LEAGUE),
    )


@pytest.mark.parametrize("name", ["Premier League", "SYNTHETIC Alternative", None, "ABSENT"])
def test_descriptive_variation_does_not_change_canonical_identity(name):
    rows = provider_rows()
    if name == "ABSENT":
        rows[0].pop("leagueName")
    else:
        rows[0]["leagueName"] = name
    result = candidate(rows)
    observed = result.facts[0].provider_display_name
    assert observed.state == (
        "ABSENT" if name == "ABSENT" else "NULL" if name is None else "STRING"
    )
    assert observed.value == (None if name == "ABSENT" else name)
    assert result.facts[0].canonical_fact.league_name == "Premier League"
    assert tuple(r.canonical_fact for r in result.facts) == project_final_facts(
        json.dumps(provider_rows()).encode(),
        context=synthetic_context(),
        result_type=regulation_type(GLOBAL, LEAGUE),
    )
    assert result.activation == "INACTIVE" and result.policy_state == "PROPOSED_UNAPPROVED"
    if name != "Premier League":
        with pytest.raises(ReasonFailure):
            project_final_facts(
                json.dumps(rows).encode(),
                context=synthetic_context(),
                result_type=regulation_type(GLOBAL, LEAGUE),
            )


@pytest.mark.parametrize(
    "name", ["", " ", "a\n", "a\x00", "\ud800", "a\u200b", 1, True, [], {}, "x" * 257]
)
def test_malformed_description_refused(name):
    rows = provider_rows()
    rows[0]["leagueName"] = name
    with pytest.raises(ValueError, match="CANDIDATE_DISPLAY_NAME_INVALID"):
        candidate(rows)


@pytest.mark.parametrize("field", ["leagueId", "leagueShortcut", "leagueSeason", "groupOrderID"])
@pytest.mark.parametrize("value", [None, True, 1.0, "1", -1, "MISSING"])
def test_stable_keys_never_relax(field, value):
    rows = provider_rows()
    rows[0]["leagueName"] = "SYNTHETIC Alternate"
    obj = rows[0]["group"] if field == "groupOrderID" else rows[0]
    if value == "MISSING":
        obj.pop(field)
    else:
        obj[field] = value
    with pytest.raises(ReasonFailure):
        candidate(rows)


@pytest.mark.parametrize("group", [None, [], 6, "6"])
def test_malformed_group(group):
    rows = provider_rows()
    rows[0]["group"] = group
    with pytest.raises(ReasonFailure):
        candidate(rows)


@pytest.mark.parametrize("value", [None, True, False, 1.0, "1", "MISSING"])
def test_linked_regulation_id_is_exact_integer(value):
    league = json.loads(LEAGUE)
    if value == "MISSING":
        league[0]["globalResultInfo"].pop("id")
    else:
        league[0]["globalResultInfo"]["id"] = value
    with pytest.raises(ReasonFailure) as failure:
        regulation_type(GLOBAL, json.dumps(league).encode())
    assert failure.value.reason == FailureReason.PROVIDER_FIELD_TYPE_INVALID


def test_wrong_linked_integer_is_disagreement():
    league = json.loads(LEAGUE)
    league[0]["globalResultInfo"]["id"] = 3
    with pytest.raises(ReasonFailure) as failure:
        regulation_type(GLOBAL, json.dumps(league).encode())
    assert failure.value.reason == FailureReason.REGULATION_METADATA_DISAGREEMENT


@pytest.mark.parametrize(
    "change",
    ["unfinished", "true_like", "missing_result", "duplicate_result", "wrong_kind", "exceptional"],
)
def test_result_guards_unchanged(change):
    rows = provider_rows()
    row = rows[0]
    row["leagueName"] = None
    if change == "unfinished":
        row["matchIsFinished"] = False
    if change == "true_like":
        row["matchIsFinished"] = 1
    if change == "missing_result":
        row["matchResults"] = []
    if change == "duplicate_result":
        row["matchResults"].append(dict(row["matchResults"][0]))
    if change == "wrong_kind":
        row["matchResults"][0]["resultTypeKind"] = "AfterExtraTime"
    if change == "exceptional":
        row["matchResults"][0]["resultName"] = "Awarded"
    with pytest.raises(ReasonFailure):
        candidate(rows)


def test_reordering_retains_oriented_exact_ten():
    rows = provider_rows()
    rows.reverse()
    projected = candidate(rows)
    assert {r.canonical_fact.provider_match_id for r in projected.facts} == {
        r.source_fact.provider_match_id for r in labels().outcomes
    }


def test_real_context_and_resealed_real_forecast_refused():
    with pytest.raises(ValueError, match="ACTUAL_P01"):
        candidate(context=load_context())
    values = synthetic_context().model_dump(exclude={"semantic_sha256"})
    values["fixtures"] = synthetic_context().fixtures
    values["forecast_sha256"] = FORECAST_SHA
    with pytest.raises(ValueError, match="ACTUAL_P01"):
        candidate(context=seal(type(synthetic_context()), **values))


def test_candidate_cannot_persist_as_operational_outcome(tmp_path):
    with pytest.raises(ValueError, match="only explicit"):
        persist_fallback(candidate(), artifact_root=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("shape", [None, {}, [None] * 10, [], "NINE", "ELEVEN"])
def test_candidate_invalid_top_level(shape):
    rows = provider_rows()
    if shape == "NINE":
        shape = rows[:-1]
    elif shape == "ELEVEN":
        shape = rows + rows[:1]
    with pytest.raises(ValueError):
        project_synthetic_candidate(
            json.dumps(shape).encode(),
            context=synthetic_context(),
            result_type=regulation_type(GLOBAL, LEAGUE),
        )


@pytest.mark.parametrize(
    "body", [b'{"x":1,"x":2}', b" " * 524289], ids=["duplicate-json", "oversized-body"]
)
def test_candidate_duplicate_json_or_oversize(body):
    with pytest.raises(ValueError):
        project_synthetic_candidate(
            body, context=synthetic_context(), result_type=regulation_type(GLOBAL, LEAGUE)
        )


@pytest.mark.parametrize(
    "key,value", [("leagueId", 5997), ("leagueSeason", 2025), ("groupOrderID", 7)]
)
def test_true_other_identity_never_admitted(key, value):
    rows = provider_rows()
    target = rows[0]["group"] if key == "groupOrderID" else rows[0]
    target[key] = value
    with pytest.raises(ReasonFailure):
        candidate(rows)


def test_original_byte_identity_is_not_normalized_body_identity():
    rows = provider_rows()
    rows[0].pop("leagueName")
    raw = json.dumps(rows).encode()
    assert candidate(rows).original_synthetic_body_sha256 == hashlib.sha256(raw).hexdigest()
