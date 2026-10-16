"""D1 failure localisation: synthetic/fake I/O only; never actual P01 execution."""

import hashlib
import importlib.util
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion import p01_fallback_acquisition as acquisition
from dmf_pulse.ingestion import p01_fallback_transport as transport_module
from dmf_pulse.ingestion.p01_fallback_consumption import load_consumption
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    ContentTypeClass,
    DiagnosticProgress,
    P01FallbackExecutionFailure,
    ReasonFailure,
    SafeDiagnostics,
    StoppedExecutionDiagnostic,
    persist_stopped,
    stopped_record,
)
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    ExecutionStage as S,
)
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    FailureReason as R,
)
from tests.unit.evaluation.p01_d1_test_support import captured_synthetic_forecast
from tests.unit.evaluation.test_p01_fallback_a02 import (
    AT,
    GLOBAL,
    LEAGUE,
    labels,
    provider_rows,
    review_fixture,
    synthetic_context,
    ten_forecast,
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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*a, **kw):
        raise AssertionError("D1 must remain offline")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)


def harness(tmp_path, monkeypatch, *, bodies=None, error=None, error_index=0, at=None):
    root, review_path, review = review_fixture(tmp_path)
    monkeypatch.setattr(acquisition, "load_context", synthetic_context)
    monkeypatch.setattr(acquisition, "authenticate_p01", lambda path: ten_forecast())
    payloads = [GLOBAL, LEAGUE, json.dumps(provider_rows()).encode()] if bodies is None else bodies
    calls = []

    class Fake:
        def get(self, url):
            index = len(calls)
            calls.append(url)
            if error is not None and index == error_index:
                raise error
            return payloads[index]

    progress = DiagnosticProgress()
    return (
        dict(
            forecast_path=tmp_path / "synthetic",
            review_path=review_path,
            expected_review_sha256=review.semantic_sha256,
            implementation_root=root,
            artifact_root=tmp_path / "retained",
            transport=Fake(),
            clock=lambda: at or datetime(2026, 10, 17, tzinfo=UTC),
            progress=progress,
        ),
        calls,
        progress,
    )


def change(case):
    bodies = [GLOBAL, LEAGUE, json.dumps(provider_rows()).encode()]
    rows = provider_rows()
    if case == "duplicate_json":
        bodies[0] = b'[{"id":1,"id":2}]'
    elif case == "malformed_json":
        bodies[2] = b"[{"
    elif case == "global_ambiguous":
        bodies[0] = b"[]"
    elif case == "league_ambiguous":
        bodies[1] = b"[]"
    elif case == "global_duplicate":
        bodies[0] = json.dumps([json.loads(GLOBAL)[0]] * 2).encode()
    elif case == "league_duplicate":
        bodies[1] = json.dumps(json.loads(LEAGUE) * 2).encode()
    elif case == "metadata_disagreement":
        bodies[1] = b'[{"id":7,"globalResultInfo":{"id":99,"kind":"After90Minutes"}}]'
    elif case == "not_array":
        bodies[2] = b"{}"
    elif case == "nine":
        rows.pop()
    elif case == "eleven":
        rows.append(rows[0])
    elif case == "unfinished":
        rows[0]["matchIsFinished"] = False
    elif case == "missing_regulation":
        rows[0]["matchResults"] = []
    elif case == "duplicate_regulation":
        rows[0]["matchResults"].append(rows[0]["matchResults"][0])
    elif case == "result_type":
        rows[0]["matchResults"][0]["resultTypeID"] = 99
    elif case in {"penalty", "extra_time", "abandoned"}:
        rows[0]["matchResults"][0]["resultName"] = {
            "penalty": "penalties",
            "extra_time": "extra time",
            "abandoned": "abandoned",
        }[case]
    elif case == "missing_timestamp":
        rows[0].pop("matchDateTimeUTC")
    elif case == "invalid_timestamp":
        rows[0]["matchDateTimeUTC"] = "CANARY_PRIVATE_TIMESTAMP"
    elif case == "naive_timestamp":
        rows[0]["matchDateTimeUTC"] = "2026-10-04T14:00:00"
    elif case == "score_type":
        rows[0]["matchResults"][0]["pointsTeam1"] = "CANARY_PRIVATE_SCORE"
    elif case == "identity_type":
        rows[0]["matchID"] = "CANARY_PRIVATE_ID"
    elif case == "mapping_missing":
        rows[0]["team1"]["teamName"] = "CANARY_PRIVATE_TEAM"
    elif case == "mapping_ambiguous":
        rows[1]["team1"] = rows[0]["team1"]
        rows[1]["team2"] = rows[0]["team2"]
    elif case == "club_ambiguous":
        rows[1]["team1"]["teamId"] = rows[0]["team1"]["teamId"]
        rows[1]["team2"]["teamId"] = rows[0]["team2"]["teamId"]
    if case not in {
        "duplicate_json",
        "malformed_json",
        "global_ambiguous",
        "league_ambiguous",
        "global_duplicate",
        "league_duplicate",
        "metadata_disagreement",
        "not_array",
    }:
        bodies[2] = json.dumps(rows).encode()
    return bodies


CASES = [
    ("global_duplicate", S.RESOLVE_REGULATION_RESULT_TYPE, R.REGULATION_METADATA_AMBIGUOUS),
    ("league_duplicate", S.RESOLVE_REGULATION_RESULT_TYPE, R.REGULATION_METADATA_AMBIGUOUS),
    ("duplicate_json", S.RESOLVE_REGULATION_RESULT_TYPE, R.PROVIDER_JSON_INVALID),
    ("malformed_json", S.PROJECT_FINAL_FACTS, R.PROVIDER_JSON_INVALID),
    ("global_ambiguous", S.RESOLVE_REGULATION_RESULT_TYPE, R.REGULATION_METADATA_AMBIGUOUS),
    ("league_ambiguous", S.RESOLVE_REGULATION_RESULT_TYPE, R.REGULATION_METADATA_AMBIGUOUS),
    ("metadata_disagreement", S.RESOLVE_REGULATION_RESULT_TYPE, R.REGULATION_METADATA_DISAGREEMENT),
    ("not_array", S.PROJECT_FINAL_FACTS, R.MATCHDAY_RESPONSE_INVALID),
    ("nine", S.PROJECT_FINAL_FACTS, R.MATCHDAY_FIXTURE_COUNT_INVALID),
    ("eleven", S.PROJECT_FINAL_FACTS, R.MATCHDAY_FIXTURE_COUNT_INVALID),
    ("unfinished", S.PROJECT_FINAL_FACTS, R.MATCH_NOT_FINISHED),
    ("missing_regulation", S.PROJECT_FINAL_FACTS, R.REGULATION_RESULT_MISSING_OR_AMBIGUOUS),
    ("duplicate_regulation", S.PROJECT_FINAL_FACTS, R.REGULATION_RESULT_MISSING_OR_AMBIGUOUS),
    ("result_type", S.PROJECT_FINAL_FACTS, R.REGULATION_RESULT_TYPE_MISMATCH),
    ("penalty", S.PROJECT_FINAL_FACTS, R.EXCEPTIONAL_RESULT_REFUSED),
    ("extra_time", S.PROJECT_FINAL_FACTS, R.EXCEPTIONAL_RESULT_REFUSED),
    ("abandoned", S.PROJECT_FINAL_FACTS, R.EXCEPTIONAL_RESULT_REFUSED),
    ("missing_timestamp", S.PROJECT_FINAL_FACTS, R.PLAYED_TIMESTAMP_MISSING_OR_INVALID),
    ("invalid_timestamp", S.PROJECT_FINAL_FACTS, R.PLAYED_TIMESTAMP_MISSING_OR_INVALID),
    ("naive_timestamp", S.PROJECT_FINAL_FACTS, R.PLAYED_TIMESTAMP_MISSING_OR_INVALID),
    ("score_type", S.PROJECT_FINAL_FACTS, R.PROVIDER_FIELD_TYPE_INVALID),
    ("identity_type", S.PROJECT_FINAL_FACTS, R.PROVIDER_FIELD_TYPE_INVALID),
    ("mapping_missing", S.ADMIT_EXACT_TEN, R.EXACT_TEN_INCOMPLETE),
    ("mapping_ambiguous", S.ADMIT_EXACT_TEN, R.ORIENTED_MAPPING_AMBIGUOUS),
    ("club_ambiguous", S.ADMIT_EXACT_TEN, R.PROVIDER_CLUB_IDENTITY_AMBIGUOUS),
]


@pytest.mark.parametrize("case,stage,reason", CASES, ids=[row[0] for row in CASES])
def test_failure_matrix(tmp_path, monkeypatch, case, stage, reason):
    args, calls, progress = harness(tmp_path, monkeypatch, bodies=change(case))
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    failure = caught.value
    assert (failure.stage, failure.reason) == (stage, reason)
    assert failure.diagnostics == progress.safe
    if case == "global_duplicate":
        assert progress.safe.regulation_global_candidate_count == 2
    if case == "league_duplicate":
        assert progress.safe.regulation_league_candidate_count == 2
    assert len(calls) == (2 if stage == S.RESOLVE_REGULATION_RESULT_TYPE else 3)
    assert failure.diagnostics.provider_requests_completed == len(calls)
    record = stopped_record(
        failure,
        started_at=AT,
        stopped_at=args["clock"](),
        context_sha256=synthetic_context().semantic_sha256,
        one_attempt_consumed=True,
    )
    path = persist_stopped(record, root=tmp_path / "diagnostics")
    assert StoppedExecutionDiagnostic.model_validate_json(path.read_bytes()) == record
    output = path.read_text()
    assert "CANARY" not in output and "MUST_NOT_BE_RETAINED" not in output
    assert all(
        name not in output for row in synthetic_context().fixtures for name in row.home_aliases
    )
    assert all(
        key not in output
        for key in (
            "home_goals",
            "away_goals",
            "provider_match_id",
            "home_name",
            "away_name",
            "traceback",
        )
    )
    with pytest.raises(FileExistsError):
        persist_stopped(record, root=tmp_path / "diagnostics")


@pytest.mark.parametrize(
    "index,stage",
    [
        (0, S.FETCH_GLOBAL_RESULT_TYPES),
        (1, S.FETCH_LEAGUE_RESULT_INFO),
        (2, S.FETCH_MATCHDAY_RESPONSE),
    ],
)
@pytest.mark.parametrize(
    "error,reason",
    [
        (TimeoutError("CANARY"), R.TRANSPORT_TIMEOUT),
        (OSError("CANARY"), R.TRANSPORT_UNAVAILABLE),
        (RuntimeError("CANARY"), R.UNKNOWN_P01_OUTCOME_FAILURE),
    ],
)
def test_each_fetch_stage(tmp_path, monkeypatch, index, stage, error, reason):
    args, calls, state = harness(tmp_path, monkeypatch, error=error, error_index=index)
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    assert (caught.value.stage, caught.value.reason) == (stage, reason)
    assert state.safe.provider_requests_attempted == index + 1
    assert len(calls) == index + 1
    assert state.safe.provider_requests_completed == index
    assert "CANARY" not in str(caught.value)


@pytest.mark.parametrize(
    "target,stage,reason",
    [
        ("load_context", S.LOAD_CONTEXT, R.CONTEXT_INVALID),
        ("require_openligadb_rights", S.AUTHENTICATE_RIGHTS, R.RIGHTS_IDENTITY_MISMATCH),
        ("authenticate_review", S.AUTHENTICATE_REVIEW, R.REVIEW_INVALID),
        ("authenticate_p01", S.AUTHENTICATE_FORECAST, R.FORECAST_IDENTITY_MISMATCH),
        ("admit_final_facts", S.ADMIT_EXACT_TEN, R.FALLBACK_ADMISSION_INVALID),
        ("persist_fallback", S.PERSIST_OUTCOME_ARTIFACT, R.PERSISTENCE_FAILED),
        ("require_d_plus_2", S.VALIDATE_D_PLUS_2, R.D_PLUS_2_NOT_COMPLETE),
    ],
)
def test_narrow_boundary_translation(tmp_path, monkeypatch, target, stage, reason):
    args, calls, state = harness(tmp_path, monkeypatch)

    def invalid(*a, **kw):
        raise ValueError("CANARY_PRIVATE_EXCEPTION")

    monkeypatch.setattr(acquisition, target, invalid)
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    assert (caught.value.stage, caught.value.reason) == (stage, reason)
    assert "CANARY" not in str(caught.value)
    assert len(calls) == state.safe.provider_requests_attempted
    assert state.safe.provider_requests_attempted == (
        3 if stage in {S.ADMIT_EXACT_TEN, S.PERSIST_OUTCOME_ARTIFACT, S.VALIDATE_D_PLUS_2} else 0
    )


def test_consumed_a02_cannot_change_root_or_reset_marker(tmp_path):
    consumed = load_consumption()
    assert consumed.historical_stage == "UNKNOWN_HISTORICAL"
    assert consumed.historical_exact_cause == "NOT_RETAINED"

    class Fake:
        def get(self, url):
            raise AssertionError("consumed authority must precede transport")

    for root in (tmp_path / "original", tmp_path / "alternate"):
        with pytest.raises(P01FallbackExecutionFailure) as caught:
            acquisition.acquire_p01_once(
                forecast_path=tmp_path / "missing",
                review_path=tmp_path / "missing",
                expected_review_sha256="0" * 64,
                implementation_root=tmp_path,
                artifact_root=root,
                transport=Fake(),
            )
        assert (caught.value.stage, caught.value.reason) == (
            S.SEAL_ONE_ATTEMPT_MARKER,
            R.ONE_ATTEMPT_ALREADY_CONSUMED,
        )
        assert caught.value.diagnostics.provider_requests_attempted == 0 and not root.exists()
    with pytest.raises(ReasonFailure) as caught:
        acquisition.HttpOpenLigaTransport().get(acquisition.load_context().allowed_routes[0])
    assert caught.value.reason == R.ONE_ATTEMPT_ALREADY_CONSUMED


def test_synthetic_success_semantics_and_progress_identical(tmp_path, monkeypatch):
    args, calls, state = harness(tmp_path, monkeypatch, at=AT)
    # Review chronology is a separate admission prerequisite; preserve parent semantics.
    review = acquisition.authenticate_review(
        args["review_path"],
        expected_sha256=args["expected_review_sha256"],
        implementation_root=args["implementation_root"],
    )
    from dmf_pulse.ingestion.openfootball.team_strength_data import seal

    values = {
        name: getattr(review, name)
        for name in type(review).model_fields
        if name != "semantic_sha256"
    }
    values["reviewed_at"] = synthetic_context().amended_at
    monkeypatch.setattr(
        acquisition,
        "authenticate_review",
        lambda *a, **kw: seal(type(review), **values),
    )
    admitted = acquisition.acquire_p01_once(**args)
    expected = labels()
    expected = seal(
        type(expected),
        **{
            name: getattr(expected, name)
            for name in type(expected).model_fields
            if name not in {"semantic_sha256", "attribution", "independent_review_sha256"}
        },
        attribution=admitted.attribution,
        independent_review_sha256=admitted.independent_review_sha256,
    )
    assert admitted == expected and admitted.semantic_sha256 == expected.semantic_sha256
    actual = admitted.model_dump(
        mode="json", exclude={"semantic_sha256", "independent_review_sha256"}
    )
    oracle = expected.model_dump(
        mode="json", exclude={"semantic_sha256", "independent_review_sha256"}
    )
    assert actual == oracle
    assert state.stage == S.COMPLETE
    assert len(calls) == 3
    assert state.safe.provider_requests_completed == 3
    assert state.safe.admitted_outcome_count == state.safe.uniquely_mapped_fixture_count == 10
    assert all(row.strict_json_valid for row in state.safe.request_receipts)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("arbitrary_exception", "CANARY"),
        ("home_goals", 3),
        ("provider_match_id", 99),
        ("raw_body", "CANARY"),
    ],
)
def test_diagnostic_schema_refuses_unreviewed_fields(field, bad):
    with pytest.raises(ValueError):
        SafeDiagnostics.model_validate({field: bad})


def test_runner_safe_output_persistence_and_no_scoring(tmp_path, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[3] / "scripts/run_p01_fallback_a02.py"
    spec = importlib.util.spec_from_file_location("d1_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert "score_p01_fallback" not in runner.__dict__
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--forecast",
            "unused",
            "--review",
            "unused",
            "--review-sha256",
            "0" * 64,
            "--artifact-root",
            str(tmp_path),
        ],
    )
    assert runner.main() == 2
    output = capsys.readouterr().out
    value = json.loads(output)
    assert value["stopped_diagnostic"]["reason"] == R.ONE_ATTEMPT_ALREADY_CONSUMED.value
    assert value["diagnostic_persisted"]
    assert "Traceback" not in output and "unused" not in output


HTTP_CASES = [
    ("status", R.TRANSPORT_STATUS_OR_CONTENT_TYPE_REFUSED),
    ("content_type", R.TRANSPORT_STATUS_OR_CONTENT_TYPE_REFUSED),
    ("length", R.TRANSPORT_RESPONSE_TOO_LARGE),
    ("stream", R.TRANSPORT_RESPONSE_TOO_LARGE),
    ("timeout", R.TRANSPORT_TIMEOUT),
    ("socket_timeout", R.TRANSPORT_TIMEOUT),
    ("connection", R.TRANSPORT_UNAVAILABLE),
    ("truncated", R.TRANSPORT_TRUNCATED),
]


@pytest.mark.parametrize("case,reason", HTTP_CASES, ids=[row[0] for row in HTTP_CASES])
def test_http_safe_diagnostics(tmp_path, monkeypatch, case, reason):
    args, calls, state = harness(tmp_path, monkeypatch)
    body = b"x" * 524289 if case == "stream" else b"CANARY_PRIVATE_BODY"

    class Response:
        status = 503 if case == "status" else 200
        offset = 0

        def getheader(self, name, default=None):
            if name == "Content-Type":
                return "text/html; CANARY_HEADER" if case == "content_type" else "application/json"
            if name == "Content-Length":
                return (
                    "524289"
                    if case == "length"
                    else "999"
                    if case == "truncated"
                    else None
                    if case == "stream"
                    else str(len(body))
                )
            return default

        def read1(self, size):
            part = body[self.offset : self.offset + size]
            self.offset += len(part)
            return part

    class Connection:
        sock = None
        closed = False

        def request(self, *a, **kw):
            assert a[0] == "GET" and "Authorization" not in kw["headers"]
            if case == "socket_timeout":
                raise TimeoutError("CANARY")
            if case == "connection":
                raise OSError("CANARY")

        def getresponse(self):
            return Response()

        def close(self):
            self.closed = True

    connection = Connection()
    http = acquisition.HttpOpenLigaTransport(connection_factory=lambda *a, **kw: connection)
    if case == "timeout":
        times = iter((0, 21))
        monkeypatch.setattr(transport_module.time, "monotonic", lambda: next(times))

    class Fake:
        def get(self, url):
            calls.append(url)
            return http.get(url, progress=state, clock=args["clock"])

    args["transport"] = Fake()
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    assert (caught.value.stage, caught.value.reason) == (S.FETCH_GLOBAL_RESULT_TYPES, reason)
    assert len(calls) == 1 and connection.closed
    safe = caught.value.diagnostics
    assert safe.provider_requests_attempted == 1 and safe.provider_requests_completed == 0
    receipt = safe.request_receipts[0]
    assert not receipt.response_complete and receipt.strict_json_valid is None
    assert receipt.digest_scope == "OBSERVED_BYTES"
    assert "CANARY" not in safe.model_dump_json()
    if case == "stream":
        assert (
            receipt.response_bytes == 524289
            and receipt.response_sha256 == hashlib.sha256(body).hexdigest()
        )
    if case == "content_type":
        assert receipt.content_type_class == ContentTypeClass.OTHER


def test_root_and_marker_failures(tmp_path, monkeypatch):
    args, calls, state = harness(tmp_path, monkeypatch)
    args["artifact_root"].write_text("synthetic blocked root")
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    assert (caught.value.stage, caught.value.reason) == (
        S.VALIDATE_ACQUISITION_ROOT,
        R.ACQUISITION_ROOT_INVALID,
    )
    assert calls == []
    assert state.safe.provider_requests_attempted == 0
    args["artifact_root"] = tmp_path / "new-root"
    original = Path.open

    def denied(path, *a, **kw):
        if path.name == "OPENLIGADB-P01-ONE-ATTEMPT.json":
            raise OSError("CANARY")
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    assert (caught.value.stage, caught.value.reason) == (
        S.SEAL_ONE_ATTEMPT_MARKER,
        R.MARKER_PERSISTENCE_FAILED,
    )
    assert calls == []


def test_real_d_plus_2_boundary_still_after_persistence(tmp_path, monkeypatch):
    args, calls, state = harness(tmp_path, monkeypatch, at=datetime(2026, 10, 5, tzinfo=UTC))
    original = acquisition.authenticate_review
    from dmf_pulse.ingestion.openfootball.team_strength_data import seal

    review = original(
        args["review_path"],
        expected_sha256=args["expected_review_sha256"],
        implementation_root=args["implementation_root"],
    )
    values = {
        name: getattr(review, name)
        for name in type(review).model_fields
        if name != "semantic_sha256"
    }
    values["reviewed_at"] = synthetic_context().amended_at
    monkeypatch.setattr(
        acquisition, "authenticate_review", lambda *a, **kw: seal(type(review), **values)
    )
    with pytest.raises(P01FallbackExecutionFailure) as caught:
        acquisition.acquire_p01_once(**args)
    assert (caught.value.stage, caught.value.reason) == (
        S.VALIDATE_D_PLUS_2,
        R.D_PLUS_2_NOT_COMPLETE,
    )
    assert len(calls) == 3 and state.safe.admitted_outcome_count == 10
    assert (
        len(
            list(
                args["artifact_root"].rglob("public-team-strength-p01-fallback-outcomes-v1/*.json")
            )
        )
        == 1
    )


@pytest.mark.parametrize("stage", list(S)[:-1])
def test_unexpected_failure_at_every_boundary_is_sanitized(stage):
    state = DiagnosticProgress()

    def unexpected():
        raise RuntimeError("CANARY_PRIVATE_EXCEPTION")

    with pytest.raises(P01FallbackExecutionFailure) as caught:
        state.run(stage, R.FALLBACK_ADMISSION_INVALID, unexpected)
    assert (caught.value.stage, caught.value.reason) == (stage, R.UNKNOWN_P01_OUTCOME_FAILURE)
    assert "CANARY" not in str(caught.value) and caught.value.__cause__ is None


def test_parent_complete_outcome_score_scorecard_envelopes_and_every_metric():
    from dmf_pulse.assurance.canonical import canonical_sha256
    from dmf_pulse.evaluation.p01_fallback import _score_admitted, fallback_scorecard

    path = Path(__file__).resolve().parents[2] / "fixtures/evaluation/a02_d1_parent_semantics.json"
    oracle = json.loads(path.read_bytes())
    expected = oracle.pop("semantic_sha256")
    assert canonical_sha256(oracle) == expected
    assert oracle["parent"] == "5ca798db9f2d75c8b577e8b37e9ee21205a2d0f0"
    outcomes = labels()
    score = _score_admitted(ten_forecast(), outcomes=outcomes, as_of=AT)
    card = fallback_scorecard(score, outcomes=outcomes)
    assert outcomes.semantic_sha256 == oracle["outcomes_sha256"]
    assert score.semantic_sha256 == oracle["score_sha256"]
    assert card.semantic_sha256 == oracle["scorecard_sha256"]
    assert score.metrics.model_dump(mode="json") == oracle["metrics"]
    assert len(score.metrics.scores) == 30 and all(
        len(pairs) == 49 for _, _, pairs in score.metrics.scores
    )


def test_stopped_hash_tamper_and_rights_before_storage(tmp_path, monkeypatch):
    failure = P01FallbackExecutionFailure(
        S.AUTHENTICATE_REVIEW, R.REVIEW_INVALID, SafeDiagnostics()
    )
    record = stopped_record(
        failure, started_at=AT, stopped_at=AT, context_sha256=None, one_attempt_consumed=False
    )
    tampered = json.loads(record.model_dump_json())
    tampered["reason"] = R.UNKNOWN_P01_OUTCOME_FAILURE.value
    with pytest.raises(ValueError):
        StoppedExecutionDiagnostic.model_validate_json(json.dumps(tampered))
    from dmf_pulse.evaluation import p01_fallback_context as context_module

    def denied():
        raise ValueError("CANARY_RIGHTS")

    monkeypatch.setattr(context_module, "require_openligadb_rights", denied)
    with pytest.raises(ValueError):
        persist_stopped(record, root=tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_runner_reports_diagnostic_persistence_failure_without_trace(tmp_path, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[3] / "scripts/run_p01_fallback_a02.py"
    spec = importlib.util.spec_from_file_location("d1_runner_storage", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def denied(*a, **kw):
        raise OSError("CANARY_PRIVATE_PATH")

    monkeypatch.setattr(runner, "persist_stopped", denied)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--forecast",
            "unused",
            "--review",
            "unused",
            "--review-sha256",
            "0" * 64,
            "--artifact-root",
            str(tmp_path),
        ],
    )
    assert runner.main() == 2
    output = capsys.readouterr().out
    value = json.loads(output)
    assert value["diagnostic_persistence_reason"] == R.PERSISTENCE_FAILED.value
    assert not value["diagnostic_persisted"]
    assert value["stopped_diagnostic"]["reason"] == R.ONE_ATTEMPT_ALREADY_CONSUMED.value
    assert "CANARY" not in output and "Traceback" not in output
