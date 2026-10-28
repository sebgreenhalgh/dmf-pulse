"""A03 authorization, remote consumption and offline execution adversaries."""

import base64
import hashlib
import json
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json
from dmf_pulse.evaluation.p01_a03_authority import (
    AUTHORITY_SHA,
    CONSUMED_REF,
    D1_SHA,
    REVIEW_PATHS,
    A03IndependentReview,
    A03ReviewBinding,
    A03ReviewedFile,
    authenticate_a03_review,
    load_a03_authority,
)
from dmf_pulse.evaluation.p01_fallback import _score_admitted
from dmf_pulse.evaluation.p01_fallback_store import load_fallback
from dmf_pulse.evaluation.p01_frozen_view import _read_pinned_representation
from dmf_pulse.ingestion import p01_a03_execution as execution
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate, seal
from dmf_pulse.ingestion.p01_a03_control import (
    EXPECTED_JOBS,
    GitHubA03Control,
    consumption_receipt,
)
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    ContentTypeClass,
    ReasonFailure,
)
from dmf_pulse.ingestion.p01_fallback_diagnostics import ExecutionStage as S
from dmf_pulse.ingestion.p01_fallback_diagnostics import FailureReason as R
from tests.unit.evaluation.p01_d1_test_support import captured_synthetic_forecast
from tests.unit.evaluation.test_p01_fallback_a02 import (
    GLOBAL,
    LEAGUE,
    provider_rows,
    synthetic_context,
    ten_forecast,
)
from tests.unit.evaluation.test_p01_fallback_d1 import CASES, change

NOW = datetime(2026, 10, 28, tzinfo=UTC)
IMPLEMENTATION = "1" * 40
TICKET = "CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03"


@pytest.fixture(scope="module", autouse=True)
def fixed_input():
    from tests.unit.evaluation import test_p01_fallback_a02 as support

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(support, "frozen", captured_synthetic_forecast)
        support.ten_forecast.cache_clear()
        support.synthetic_context.cache_clear()
        yield
    support.ten_forecast.cache_clear()
    support.synthetic_context.cache_clear()
    support.scored.cache_clear()
    fixed_view.cache_clear()


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*a, **kw):
        raise AssertionError("A03 tests must remain offline")

    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


def reviewed(root):
    files = []
    for name in REVIEW_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        original = Path(__file__).resolve().parents[3] / name
        path.write_bytes(
            original.read_bytes()
            if name.startswith("src/dmf_pulse/")
            else b"reviewed offline input\n"
        )
        files.append(
            A03ReviewedFile(path=name, byte_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        )
    review = seal(
        A03IndependentReview,
        schema_version="public-team-strength-p01-a03-independent-review-v1",
        authority_sha256=AUTHORITY_SHA,
        reviewer_identity="offline synthetic reviewer",
        reviewed_at=NOW,
        verdict="CLEAR_FOR_P01_A03_ONE_SHOT_EXECUTION",
        answers=(True,) * 15,
        unresolved_p0_p1_material_p2=0,
        p01_scores_exist=False,
        provider_requests=0,
        files=tuple(files),
        assessment=("synthetic offline assessment",) * 8,
    )
    binding = seal(
        A03ReviewBinding,
        schema_version="public-team-strength-p01-a03-exact-sha-review-binding-v1",
        authority_sha256=AUTHORITY_SHA,
        file_review_sha256=review.semantic_sha256,
        implementation_sha=IMPLEMENTATION,
        immutable_parent=D1_SHA,
        reviewer_identity=review.reviewer_identity,
        bound_at=NOW,
        verdict=review.verdict,
        ci_run_id=123,
        ci_conclusion="success",
        successful_required_jobs=20,
    )
    return review, binding


class Remote:
    """An atomic remote Git create-ref simulator shared across independent clients."""

    def __init__(self):
        self.ref = None
        self.text = None
        self.lock = threading.Lock()
        self.calls = []
        self.fail = None

    def api(self, endpoint, *, payload=None, absent_ok=False):
        with self.lock:
            self.calls.append((endpoint, payload))
            if self.fail == endpoint:
                if endpoint == "git/refs":
                    self.ref = {"ref": CONSUMED_REF, "object": {"sha": "2" * 40}}
                raise ReasonFailure(R.MARKER_PERSISTENCE_FAILED)
            if endpoint.startswith("git/ref/"):
                return self.ref
            if endpoint == "git/trees":
                self.text = payload["tree"][0]["content"]
                return {"sha": "3" * 40}
            if endpoint == "git/commits":
                return {"sha": "2" * 40}
            if endpoint == "git/refs":
                if self.ref is not None:
                    raise ReasonFailure(R.MARKER_PERSISTENCE_FAILED)
                self.ref = {"ref": CONSUMED_REF, "object": {"sha": payload["sha"]}}
                return self.ref
            if endpoint.startswith("contents/"):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(self.text.encode()).decode(),
                }
            raise AssertionError(endpoint)


def control(root, remote, binding):
    value = GitHubA03Control(root)
    value._api = remote.api
    value._verified = binding
    return value


@lru_cache(maxsize=1)
def fixed_view():
    raw = ten_forecast().model_dump_json().encode()
    return _read_pinned_representation(
        raw,
        expected_byte_sha256=hashlib.sha256(raw).hexdigest(),
        expected_semantic_sha256=ten_forecast().semantic_sha256,
    )


def harness(tmp_path, monkeypatch, *, bodies=None, error=None, error_index=0, remote=None):
    root = tmp_path / "implementation"
    review, binding = reviewed(root)
    review_path, binding_path = tmp_path / "review.json", tmp_path / "binding.json"
    review_path.write_text(pretty_json(review))
    binding_path.write_text(pretty_json(binding))
    monkeypatch.setattr(execution, "authenticate_a03_review", lambda *a, **kw: (review, binding))
    monkeypatch.setattr(execution, "load_context", synthetic_context)
    view = fixed_view()
    authentications = []

    def authenticate_input(path):
        authentications.append(path)
        return view

    monkeypatch.setattr(execution, "authenticate_p01", authenticate_input)
    monkeypatch.setattr(execution, "score_p01_fallback", _score_admitted)
    shared = remote or Remote()
    governance = control(root, shared, binding)
    monkeypatch.setattr(governance, "verify", lambda *a, **kw: None)
    payloads = bodies or [GLOBAL, LEAGUE, json.dumps(provider_rows()).encode()]
    events = []

    class FakeHTTP:
        def __init__(self):
            assert shared.ref is not None
            events.append("client-enabled-after-seal")

        def get(self, url, *, progress, clock):
            index = len([x for x in events if x.startswith("https:")])
            events.append(url)
            if error is not None and index == error_index:
                raise ReasonFailure(error)
            body = payloads[index]
            progress.receipt(
                response_received_at=clock(),
                http_status_code=200,
                content_type_class=ContentTypeClass.JSON,
                response_bytes=len(body),
                response_sha256=hashlib.sha256(body).hexdigest(),
                response_complete=True,
            )
            return body

    args = dict(
        forecast_path=tmp_path / "fixed-synthetic",
        review_path=review_path,
        binding_path=binding_path,
        expected_binding_sha256=binding.semantic_sha256,
        implementation_root=root,
        artifact_root=tmp_path / TICKET,
        control=governance,
        transport_factory=FakeHTTP,
        clock=lambda: NOW,
    )
    return args, events, authentications, shared, binding


def test_pinned_authority_and_d1_unchanged():
    authority = load_a03_authority()
    assert authority.semantic_sha256 == AUTHORITY_SHA
    assert authority.maximum_attempts == authority.attempt_number == 1
    assert authority.evaluation_epoch == "EVALUATION_EPOCH_003"
    from dmf_pulse.ingestion.p01_fallback_consumption import load_consumption

    assert load_consumption().consumed and not load_consumption().new_provider_authority


def test_review_binding_hashes_and_source_tamper(tmp_path):
    review, binding = reviewed(tmp_path / "source")
    a, b = tmp_path / "review.json", tmp_path / "binding.json"
    a.write_text(pretty_json(review))
    b.write_text(pretty_json(binding))
    assert authenticate_a03_review(a, b, implementation_root=tmp_path / "source") == (
        review,
        binding,
    )
    (tmp_path / "source" / REVIEW_PATHS[0]).write_bytes(b"changed")
    with pytest.raises(ValueError):
        authenticate_a03_review(a, b, implementation_root=tmp_path / "source")
    value = json.loads(b.read_bytes())
    value["implementation_sha"] = "4" * 40
    b.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        authenticate_a03_review(a, b, implementation_root=tmp_path / "source")


@pytest.mark.parametrize("case,stage,reason", CASES, ids=[row[0] for row in CASES])
def test_a03_uses_every_d1_projection_failure(tmp_path, monkeypatch, case, stage, reason):
    args, events, authentications, remote, _ = harness(tmp_path, monkeypatch, bodies=change(case))
    handoff = execution.execute_a03(**args)
    assert (handoff.diagnostic.stage, handoff.diagnostic.reason) == (stage, reason)
    assert handoff.one_attempt_consumed and handoff.consumption_verified and remote.ref is not None
    assert not handoff.scoring_performed and handoff.score_sha256 is None
    assert len(authentications) == 3
    encoded = pretty_json(handoff)
    assert "CANARY" not in encoded and "MUST_NOT_BE_RETAINED" not in encoded
    assert all(
        key not in encoded for key in ("home_goals", "away_goals", "provider_match_id", "traceback")
    )
    assert all(
        alias not in encoded for row in synthetic_context().fixtures for alias in row.home_aliases
    )
    assert len([x for x in events if x.startswith("https:")]) == (
        2 if stage == S.RESOLVE_REGULATION_RESULT_TYPE else 3
    )


@pytest.mark.parametrize(
    "index,stage",
    [
        (0, S.FETCH_GLOBAL_RESULT_TYPES),
        (1, S.FETCH_LEAGUE_RESULT_INFO),
        (2, S.FETCH_MATCHDAY_RESPONSE),
    ],
)
@pytest.mark.parametrize(
    "reason",
    [
        R.TRANSPORT_TIMEOUT,
        R.TRANSPORT_UNAVAILABLE,
        R.TRANSPORT_TRUNCATED,
        R.TRANSPORT_RESPONSE_TOO_LARGE,
        R.TRANSPORT_STATUS_OR_CONTENT_TYPE_REFUSED,
    ],
)
def test_transport_stop_no_retry_or_score(tmp_path, monkeypatch, index, stage, reason):
    args, events, authentications, _, _ = harness(
        tmp_path, monkeypatch, error=reason, error_index=index
    )
    value = execution.execute_a03(**args)
    assert (value.diagnostic.stage, value.diagnostic.reason) == (stage, reason)
    assert value.diagnostic.diagnostics.provider_requests_attempted == index + 1
    assert value.diagnostic.diagnostics.provider_requests_completed == index
    assert len([x for x in events if x.startswith("https:")]) == index + 1
    assert len(authentications) == 3 and not value.scoring_performed


@pytest.mark.parametrize(
    "endpoint",
    [
        "git/ref/" + CONSUMED_REF.removeprefix("refs/"),
        "git/trees",
        "git/commits",
        "git/refs",
        "contents/A03-ATTEMPT-CONSUMED.json?ref=" + "2" * 40,
    ],
)
def test_remote_failure_or_ambiguous_create_never_enables_http(tmp_path, monkeypatch, endpoint):
    remote = Remote()
    remote.fail = endpoint
    args, events, auth, _, binding = harness(tmp_path, monkeypatch, remote=remote)
    value = execution.execute_a03(**args)
    assert value.diagnostic.stage == S.SEAL_ONE_ATTEMPT_MARKER
    assert value.diagnostic.reason == R.MARKER_PERSISTENCE_FAILED
    assert not events and len(auth) == 2 and value.one_attempt_consumed
    with pytest.raises(ReasonFailure) as caught:
        args["control"].consume(consumption_receipt(binding, at=NOW))
    assert caught.value.reason == R.ONE_ATTEMPT_ALREADY_CONSUMED


def test_different_root_cwd_removed_local_evidence_cannot_reopen(tmp_path, monkeypatch):
    args, events, _, remote, binding = harness(tmp_path, monkeypatch, error=R.TRANSPORT_TIMEOUT)
    first = execution.execute_a03(**args)
    for path in args["artifact_root"].rglob("*.json"):
        path.unlink()
    second_root = tmp_path / "alternate" / TICKET
    governance = control(args["implementation_root"], remote, binding)
    monkeypatch.setattr(governance, "verify", lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)
    args.update(control=governance, artifact_root=second_root)
    second = execution.execute_a03(**args)
    assert first.one_attempt_consumed and second.diagnostic.reason == R.ONE_ATTEMPT_ALREADY_CONSUMED
    assert len([x for x in events if x.startswith("https:")]) == 1


def test_two_contenders_only_one_create_wins_and_seal_not_reusable(tmp_path):
    _, binding = reviewed(tmp_path / "source")
    remote = Remote()
    controls = [control(tmp_path, remote, binding) for _ in range(2)]

    def attempt(value):
        try:
            return value.consume(consumption_receipt(binding, at=NOW))
        except ReasonFailure:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, controls))
    assert sum(value is not None for value in results) == 1
    for value in controls:
        with pytest.raises(ReasonFailure):
            value.consume(consumption_receipt(binding, at=NOW))
    assert all("match" not in str(payload).lower() for _, payload in remote.calls if payload)


@pytest.mark.parametrize(
    "bad",
    [
        "head",
        "parent",
        "dirty",
        "review",
        "remote",
        "run_head",
        "run_status",
        "run_conclusion",
        "jobs_count",
        "jobs_name",
        "job_failed",
    ],
)
def test_exact_commit_and_all_ci_jobs_required_before_consumption(tmp_path, monkeypatch, bad):
    review, binding = reviewed(tmp_path / "source")
    value = GitHubA03Control(tmp_path)
    review_bytes = pretty_json(review).encode()

    def git(*a):
        if a == ("rev-parse", "HEAD"):
            return (("9" * 40 if bad == "head" else IMPLEMENTATION) + "\n").encode()
        if a == ("rev-parse", "HEAD^"):
            return (("9" * 40 if bad == "parent" else D1_SHA) + "\n").encode()
        if a == ("status", "--porcelain"):
            return b"M source" if bad == "dirty" else b""
        return b"changed" if bad == "review" else review_bytes

    def api(endpoint, **kw):
        if endpoint.startswith("git/ref/"):
            return {"object": {"sha": "9" * 40 if bad == "remote" else IMPLEMENTATION}}
        if endpoint.endswith("/jobs?per_page=100"):
            rows = [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in EXPECTED_JOBS
            ]
            if bad == "jobs_count":
                rows.pop()
            if bad == "jobs_name":
                rows[0]["name"] = "unreviewed job"
            if bad == "job_failed":
                rows[0]["conclusion"] = "failure"
            return {"total_count": len(rows), "jobs": rows}
        return {
            "head_sha": "9" * 40 if bad == "run_head" else IMPLEMENTATION,
            "status": "in_progress" if bad == "run_status" else "completed",
            "conclusion": "failure" if bad == "run_conclusion" else "success",
        }

    monkeypatch.setattr(value, "_git", git)
    monkeypatch.setattr(value, "_api", api)
    with pytest.raises(ReasonFailure):
        value.verify(binding, expected_review_bytes=review_bytes)
    assert value._verified is None


@pytest.mark.parametrize(
    "raw,code,absent,expected",
    [
        (
            b'HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"ok":true}',
            0,
            False,
            {"ok": True},
        ),
        (b"HTTP/2.0 404 Not Found\n\n{}", 1, True, None),
        (b"HTTP/2.0 422 Refused\n\n{}", 1, False, "refused"),
        (b'HTTP/2.0 200 OK\n\n{"a":1,"a":2}', 0, False, "refused"),
        (b"partial", 0, False, "refused"),
        (b"", 1, False, "refused"),
    ],
)
def test_safe_governance_http_headers(tmp_path, monkeypatch, raw, code, absent, expected):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=raw, returncode=code)
    )
    value = GitHubA03Control(tmp_path)
    if expected == "refused":
        with pytest.raises(ReasonFailure):
            value._api("git/refs", absent_ok=absent)
    else:
        assert value._api("git/refs", absent_ok=absent) == expected


def test_success_all_three_products_parent_numerics_and_authority_link(tmp_path, monkeypatch):
    args, events, auth, _, _ = harness(tmp_path, monkeypatch)
    value = execution.execute_a03(**args)
    assert (
        value.status == "P01_A03_COMPLETE" and value.scoring_performed and value.diagnostic is None
    )
    assert len(auth) == 3 and len([x for x in events if x.startswith("https:")]) == 3
    report = load_fallback(
        next(args["artifact_root"].glob("public-team-strength-p01-fallback-scorecard-v1/*.json")),
        expected_sha256=value.scorecard_sha256,
    )
    oracle = json.loads(
        (
            Path(__file__).resolve().parents[2] / "fixtures/evaluation/a02_d1_parent_semantics.json"
        ).read_bytes()
    )
    assert report.score.metrics.model_dump(mode="json")["scores"] == oracle["metrics"]["scores"]
    assert len(report.product_means) == 3 and len(report.score.metrics.scores) == 30
    binding = next(
        args["artifact_root"].glob(
            "public-team-strength-p01-fallback-a03-outcome-binding-v1/*.json"
        )
    )
    identity = authenticate(execution.A03OutcomeBinding.model_validate_json(binding.read_bytes()))
    assert (
        identity.authority_sha256 == AUTHORITY_SHA
        and identity.outcome_artifact_sha256 == value.outcome_artifact_sha256
    )
    assert not report.score.promotion.production_active


def test_no_force_retry_reset_or_source_override_in_script():
    script = (Path(__file__).resolve().parents[3] / "scripts/run_p01_fallback_a03.py").read_text()
    assert all(
        flag not in script
        for flag in ("--force", "--retry", "--reset", "--ignore-consumed", "--source")
    )
    assert "fpl" not in script.lower() and "odds" not in script.lower()
    authority = load_a03_authority()
    payload = authority.model_dump(mode="json")
    payload.pop("semantic_sha256")
    assert canonical_sha256(payload) == AUTHORITY_SHA


@pytest.mark.parametrize(
    "target,stage,reason",
    [
        ("persist_fallback", S.PERSIST_OUTCOME_ARTIFACT, R.PERSISTENCE_FAILED),
        ("require_d_plus_2", S.VALIDATE_D_PLUS_2, R.D_PLUS_2_NOT_COMPLETE),
    ],
)
def test_post_admission_gates_precede_any_score(tmp_path, monkeypatch, target, stage, reason):
    args, events, _, _, _ = harness(tmp_path, monkeypatch)

    def refuse(*a, **kw):
        raise ValueError("CANARY_PRIVATE_EXCEPTION")

    def no_score(*a, **kw):
        raise AssertionError("scorer must not run")

    monkeypatch.setattr(execution, target, refuse)
    monkeypatch.setattr(execution, "score_p01_fallback", no_score)
    value = execution.execute_a03(**args)
    assert (value.diagnostic.stage, value.diagnostic.reason) == (stage, reason)
    assert not value.scoring_performed and value.score_sha256 is None
    assert len([x for x in events if x.startswith("https:")]) == 3
    assert "CANARY" not in pretty_json(value)


def test_post_attempt_forecast_failure_is_typed_without_false_unchanged(tmp_path, monkeypatch):
    args, _, _, _, _ = harness(tmp_path, monkeypatch, error=R.TRANSPORT_TIMEOUT)
    count = 0

    def authenticate_input(path):
        nonlocal count
        count += 1
        if count == 3:
            raise ValueError("CANARY_CHANGED_INPUT")
        return fixed_view()

    monkeypatch.setattr(execution, "authenticate_p01", authenticate_input)
    value = execution.execute_a03(**args)
    assert (value.diagnostic.stage, value.diagnostic.reason) == (
        S.AUTHENTICATE_FORECAST,
        R.FORECAST_IDENTITY_MISMATCH,
    )
    assert value.forecast_semantic_sha256_after is None and not value.forecast_immutability_verified
    assert not value.scoring_performed and "CANARY" not in pretty_json(value)


def test_report_storage_failure_does_not_falsely_claim_unscored(tmp_path, monkeypatch):
    args, _, _, _, _ = harness(tmp_path, monkeypatch)
    original = execution.persist_fallback

    def fail_report(value, **kwargs):
        if value.schema_version == "public-team-strength-p01-fallback-scorecard-v1":
            raise OSError("CANARY_STORAGE")
        return original(value, **kwargs)

    monkeypatch.setattr(execution, "persist_fallback", fail_report)
    value = execution.execute_a03(**args)
    assert value.scoring_performed and value.diagnostic is None
    assert value.post_score_failure.reason == R.PERSISTENCE_FAILED
    assert value.score_sha256 is not None and value.scorecard_sha256 is None
    assert "CANARY" not in pretty_json(value)


def test_installed_command_refuses_before_any_control_or_provider(tmp_path):
    from typer.testing import CliRunner

    from dmf_pulse.cli.app import app

    args = [
        "events",
        "team-strength",
        "p01-fallback",
        "execute-a03",
        "--forecast",
        str(tmp_path / "missing"),
        "--review",
        str(tmp_path / "missing-review"),
        "--review-binding",
        str(tmp_path / "missing-binding"),
        "--review-binding-sha256",
        "0" * 64,
        "--implementation-root",
        str(tmp_path),
        "--artifact-root",
        str(tmp_path / TICKET),
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    value = json.loads(result.stdout)
    assert (value["stage"], value["reason"]) == (
        S.AUTHENTICATE_REVIEW.value,
        R.REVIEW_INVALID.value,
    )
    assert value["diagnostics"]["provider_requests_attempted"] == 0
    assert not (tmp_path / TICKET).exists()


def test_source_checkout_cannot_authorize_different_running_package(tmp_path):
    root = tmp_path / "source"
    review, binding = reviewed(root)
    name = "src/dmf_pulse/ingestion/p01_a03_execution.py"
    (root / name).write_bytes(b"foreign implementation")
    files = tuple(
        A03ReviewedFile(
            path=row.path, byte_sha256=hashlib.sha256((root / row.path).read_bytes()).hexdigest()
        )
        for row in review.files
    )
    values = {
        key: getattr(review, key) for key in type(review).model_fields if key != "semantic_sha256"
    }
    values["files"] = files
    changed = seal(A03IndependentReview, **values)
    values = {
        key: getattr(binding, key) for key in type(binding).model_fields if key != "semantic_sha256"
    }
    values["file_review_sha256"] = changed.semantic_sha256
    rebound = seal(A03ReviewBinding, **values)
    a, b = tmp_path / "review.json", tmp_path / "binding.json"
    a.write_text(pretty_json(changed))
    b.write_text(pretty_json(rebound))
    with pytest.raises(ValueError, match="executing package differs"):
        authenticate_a03_review(a, b, implementation_root=root)
