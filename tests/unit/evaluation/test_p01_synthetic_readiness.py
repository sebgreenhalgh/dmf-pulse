"""Full injected-byte synthetic exercise, isolated from actual P01 labels."""

import hashlib
import json
from datetime import timedelta
from functools import lru_cache

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.p01_fallback_context import CONTEXT_SHA, FORECAST_SHA, load_context
from dmf_pulse.evaluation.p01_fallback_store import load_fallback, persist_fallback
from dmf_pulse.evaluation.p01_frozen_view import _read_pinned_representation
from dmf_pulse.evaluation.p01_synthetic_readiness import (
    SyntheticPipelineReceiptV1,
    exercise_synthetic_pipeline,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from tests.unit.evaluation.test_p01_fallback_a02 import (
    AT,
    GLOBAL,
    LEAGUE,
    provider_rows,
    synthetic_context,
    ten_forecast,
)


@lru_cache(maxsize=1)
def view():
    raw = ten_forecast().model_dump_json().encode()
    return _read_pinned_representation(
        raw,
        expected_byte_sha256=hashlib.sha256(raw).hexdigest(),
        expected_semantic_sha256=ten_forecast().semantic_sha256,
    )


def exercise(*, rows=None, candidate=False, context=None, at=AT):
    return exercise_synthetic_pipeline(
        view(),
        context=synthetic_context() if context is None else context,
        global_types=GLOBAL,
        league_types=LEAGUE,
        matchday=json.dumps(provider_rows() if rows is None else rows).encode(),
        as_of=at,
        candidate=candidate,
    )


@pytest.mark.parametrize("candidate", [False, True])
def test_complete_synthetic_pipeline_is_deterministic_and_not_operational(candidate, tmp_path):
    receipt = exercise(candidate=candidate)
    assert exercise(candidate=candidate) == receipt
    assert receipt.fixture_count == 10 and receipt.product_rows == 30
    assert receipt.actual_p01_scored is False and receipt.acquisition_permitted is False
    raw = receipt.model_dump_json()
    assert "home_goals" not in raw and "exact_score_log_loss" not in raw
    assert "DESCRIPTIVE_P01_PILOT" not in raw
    assert SyntheticPipelineReceiptV1.model_validate_json(raw) == receipt
    path = tmp_path / "synthetic-receipt.json"
    with path.open("xb") as stream:
        stream.write(raw.encode())
    assert SyntheticPipelineReceiptV1.model_validate_json(path.read_bytes()) == receipt
    with pytest.raises(ValueError):
        persist_fallback(receipt, artifact_root=tmp_path / "not-created")
    with pytest.raises(ValueError):
        load_fallback(path, expected_sha256=receipt.semantic_sha256)
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("name", [None, "SYNTHETIC Alternative", "ABSENT"])
def test_candidate_score_values_equal_strict_baseline_without_claiming_real_scores(
    monkeypatch, name
):
    import dmf_pulse.evaluation.p01_synthetic_readiness as module

    original = module._score_admitted
    metrics = []

    def capture(*args, **kwargs):
        score = original(*args, **kwargs)
        metrics.append(score.metrics.scores)
        return score

    monkeypatch.setattr(module, "_score_admitted", capture)
    rows = provider_rows()
    for row in rows:
        if name == "ABSENT":
            row.pop("leagueName")
        else:
            row["leagueName"] = name
    baseline = exercise()
    alternate = exercise(rows=rows, candidate=True)
    # Original source bytes/provenance differ, so report identity must differ.
    assert baseline.synthetic_scorecard_sha256 != alternate.synthetic_scorecard_sha256
    assert baseline.synthetic_source_sha256[:2] == alternate.synthetic_source_sha256[:2]
    assert baseline.product_rows == alternate.product_rows == 30
    assert metrics[0] == metrics[1]


@pytest.mark.parametrize(
    "change",
    [
        "switched",
        "duplicate",
        "future_played",
        "prefreeze",
        "unfinished",
        "wrong_season",
        "duplicate_match_id",
        "duplicate_result_id",
        "ambiguous_club",
    ],
)
def test_downstream_independent_gate_failures(change):
    rows = provider_rows()
    if change == "switched":
        rows[0]["team1"], rows[0]["team2"] = rows[0]["team2"], rows[0]["team1"]
    if change == "duplicate":
        rows[1] = dict(rows[0])
    if change == "future_played":
        rows[0]["matchDateTimeUTC"] = "2026-10-07T14:00:00Z"
    if change == "prefreeze":
        rows[0]["matchDateTimeUTC"] = "2020-01-01T14:00:00Z"
    if change == "unfinished":
        rows[0]["matchIsFinished"] = False
    if change == "wrong_season":
        rows[0]["leagueSeason"] = 2025
    if change == "duplicate_match_id":
        rows[1]["matchID"] = rows[0]["matchID"]
    if change == "duplicate_result_id":
        rows[1]["matchResults"][0]["resultID"] = rows[0]["matchResults"][0]["resultID"]
    if change == "ambiguous_club":
        assert rows[1]["team2"]["teamName"] != rows[0]["team2"]["teamName"]
        rows[1]["team2"]["teamId"] = rows[0]["team2"]["teamId"]
    with pytest.raises(ValueError):
        exercise(rows=rows, candidate=True)


def test_d_plus_2_boundary():
    with pytest.raises(ValueError):
        exercise(at=AT - timedelta(microseconds=1))
    assert exercise(at=AT).fixture_count == 10


def test_real_forecast_context_and_tampered_binding_fail_before_scoring(monkeypatch):
    import dmf_pulse.evaluation.p01_synthetic_readiness as module

    def forbidden(*args, **kwargs):
        raise AssertionError("scorer must not run")

    monkeypatch.setattr(module, "_score_admitted", forbidden)
    with pytest.raises(ValueError):
        exercise(context=load_context())
    values = synthetic_context().model_dump(exclude={"semantic_sha256"})
    values["fixtures"] = synthetic_context().fixtures
    for sha in (FORECAST_SHA, "a" * 64):
        values["forecast_sha256"] = sha
        with pytest.raises(ValueError):
            exercise(context=seal(type(synthetic_context()), **values))


def test_scorecard_failure_never_returns_success(monkeypatch):
    import dmf_pulse.evaluation.p01_synthetic_readiness as module

    def refused(*args, **kwargs):
        raise ValueError("synthetic scorecard failure")

    monkeypatch.setattr(module, "fallback_scorecard", refused)
    with pytest.raises(ValueError, match="scorecard failure"):
        exercise()


def command_inputs(root):
    raw = ten_forecast().model_dump_json().encode()
    values = {
        "forecast": raw,
        "context": synthetic_context().model_dump_json().encode(),
        "global-types": GLOBAL,
        "league-types": LEAGUE,
        "matchday": json.dumps(provider_rows()).encode(),
    }
    args = ["events", "team-strength", "p01-fallback", "synthetic-readiness"]
    for key, payload in values.items():
        path = root / (key + ".json")
        path.write_bytes(payload)
        args += ["--" + key, str(path)]
    return [*args, "--as-of", AT.isoformat()]


def test_public_cli_receipt_and_safe_failure(tmp_path):
    args = command_inputs(tmp_path)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert SyntheticPipelineReceiptV1.model_validate_json(result.stdout) == exercise()
    (tmp_path / "context.json").write_text(load_context().model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2 and result.stdout == ""
    assert "SYNTHETIC_READINESS_REFUSED" in result.output


def test_receipt_tamper_or_actual_identity_is_rejected():
    values = exercise().model_dump(exclude={"semantic_sha256"})
    values["forecast_sha256"] = FORECAST_SHA
    with pytest.raises(ValueError):
        seal(SyntheticPipelineReceiptV1, **values)

    values = exercise().model_dump(exclude={"semantic_sha256"})
    values["context_sha256"] = CONTEXT_SHA
    with pytest.raises(ValueError):
        seal(SyntheticPipelineReceiptV1, **values)


def test_rights_refusal_precedes_projection_and_scoring(monkeypatch):
    import dmf_pulse.evaluation.p01_synthetic_readiness as module

    def rights_refused():
        raise ValueError("synthetic rights denied")

    def forbidden(*args, **kwargs):
        raise AssertionError("downstream gate must not run")

    monkeypatch.setattr(module, "require_openligadb_rights", rights_refused)
    monkeypatch.setattr(module, "project_final_facts", forbidden)
    monkeypatch.setattr(module, "_score_admitted", forbidden)
    with pytest.raises(ValueError, match="rights denied"):
        exercise()


def test_full_generative_forecast_type_refused():
    with pytest.raises(ValueError, match="RECONSTRUCTED_FORECAST_REQUIRED"):
        exercise_synthetic_pipeline(
            ten_forecast(),
            context=synthetic_context(),
            global_types=GLOBAL,
            league_types=LEAGUE,
            matchday=b"[]",
            as_of=AT,
        )


@pytest.mark.parametrize(
    "failure", ["malformed", "oversized", "missing", "bad_time", "candidate_success"]
)
def test_cli_new_boundary_cases(tmp_path, failure):
    args = command_inputs(tmp_path)
    path = tmp_path / "matchday.json"
    if failure == "malformed":
        path.write_bytes(b"{BAD_SYNTHETIC_INPUT}")
    if failure == "oversized":
        path.write_bytes(b" " * 524289)
    if failure == "missing":
        args[args.index("--matchday") + 1] = str(tmp_path / "absent.json")
    if failure == "bad_time":
        args[-1] = "2026-10-06T00:00:00"
    if failure == "candidate_success":
        rows = provider_rows()
        rows[0].pop("leagueName")
        path.write_text(json.dumps(rows), encoding="utf-8")
        args.append("--candidate")
    result = CliRunner().invoke(app, args)
    if failure == "candidate_success":
        assert result.exit_code == 0, result.output
        assert (
            SyntheticPipelineReceiptV1.model_validate_json(result.stdout).metadata_policy
            == "INACTIVE_CANDIDATE_V1"
        )
    else:
        assert result.exit_code == 2 and result.stdout == ""
        assert "BAD_SYNTHETIC_INPUT" not in result.output
