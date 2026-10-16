"""One-attempt, rights/review-gated public P01 acquisition; no raw-body storage."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import pretty_json, sha256_file
from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    authenticate_p01,
    load_context,
    require_openligadb_rights,
    strict_json,
)
from dmf_pulse.evaluation.p01_fallback_store import persist_fallback
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
)
from dmf_pulse.ingestion.p01_fallback import (
    PublicP01FallbackOutcomesV1,
    SourceReceipt,
    admit_final_facts,
    project_final_facts,
    regulation_type,
    require_d_plus_2,
    source_receipt,
)
from dmf_pulse.ingestion.p01_fallback_consumption import require_unconsumed_synthetic_context
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    DiagnosticProgress,
    ExecutionStage,
    FailureReason,
    P01FallbackExecutionFailure,
    ReasonFailure,
    RouteClass,
)
from dmf_pulse.ingestion.p01_fallback_transport import (
    HttpOpenLigaTransport as HttpOpenLigaTransport,
)

REVIEWED_PATHS = (
    "config/evaluation/team_strength_p01_fallback_a02.json",
    "config/rights/openligadb_p01_fallback.json",
    "src/dmf_pulse/evaluation/p01_fallback_context.py",
    "src/dmf_pulse/evaluation/p01_frozen_view.py",
    "src/dmf_pulse/evaluation/p01_fallback.py",
    "src/dmf_pulse/evaluation/p01_fallback_store.py",
    "src/dmf_pulse/evaluation/team_strength_prospective.py",
    "src/dmf_pulse/ingestion/p01_fallback.py",
    "src/dmf_pulse/ingestion/p01_fallback_acquisition.py",
    "src/dmf_pulse/cli/p01_fallback.py",
    "src/dmf_pulse/cli/team_strength.py",
    "scripts/run_p01_fallback_a02.py",
    "scripts/verify_p01_fallback_a02_wheel.py",
    "tests/unit/evaluation/test_p01_fallback_a02.py",
    "tests/fixtures/evaluation/a02_legacy_score_oracle.json",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A02/CONTRACT.md",
)


class ReviewedFile(FrozenEvidence):
    path: str
    byte_sha256: SHA


class P01IndependentReview(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a02-independent-review-v1"] = (
        "public-team-strength-p01-a02-independent-review-v1"
    )
    context_sha256: Literal["6bb80a9c0b17b673044be5b5c53a2eda6c4e4110ef09f7a586e87e0d8432c259"]
    reviewer_identity: str = Field(min_length=1)
    reviewed_at: datetime
    verdict: Literal["CLEAR_FOR_P01_OPENLIGADB_DESCRIPTIVE_SCORING"]
    unresolved_p0_p1: Literal[0] = 0
    no_live_labels_acquired: Literal[True] = True
    no_p01_performance_metrics_inspected: Literal[True] = True
    files: tuple[ReviewedFile, ...]
    assessment: tuple[str, ...] = Field(min_length=8)

    @model_validator(mode="after")
    def review_scope(self) -> Self:
        if tuple(row.path for row in self.files) != REVIEWED_PATHS:
            raise ValueError("independent review file scope differs")
        return self


def authenticate_review(
    path: Path, *, expected_sha256: str, implementation_root: Path
) -> P01IndependentReview:
    data = path.read_bytes()
    strict_json(data)
    review = authenticate(P01IndependentReview.model_validate_json(data), expected_sha256)
    context = load_context()
    if review.reviewed_at < context.amended_at or review.context_sha256 != CONTEXT_SHA:
        raise StrengthEvidenceError("independent review predates A02 authority")
    root = implementation_root.resolve()
    for item in review.files:
        candidate = root / item.path
        if (
            candidate.is_symlink()
            or not candidate.resolve().is_relative_to(root)
            or sha256_file(candidate) != item.byte_sha256
        ):
            raise StrengthEvidenceError("implementation changed after independent review")
    return review


class OpenLigaTransport(Protocol):
    def get(self, url: str) -> bytes: ...


def _acquire_p01_once(
    *,
    forecast_path: Path,
    review_path: Path,
    expected_review_sha256: str,
    implementation_root: Path,
    artifact_root: Path,
    transport: OpenLigaTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: DiagnosticProgress | None = None,
) -> PublicP01FallbackOutcomesV1:
    """D1 denies consumed A02 globally; only synthetic injected transports run."""
    state = progress or DiagnosticProgress()
    context = state.run(ExecutionStage.LOAD_CONTEXT, FailureReason.CONTEXT_INVALID, load_context)
    rights = state.run(
        ExecutionStage.AUTHENTICATE_RIGHTS,
        FailureReason.RIGHTS_IDENTITY_MISMATCH,
        require_openligadb_rights,
    )
    state.run(
        ExecutionStage.SEAL_ONE_ATTEMPT_MARKER,
        FailureReason.CONTEXT_INVALID,
        lambda: require_unconsumed_synthetic_context(
            context.semantic_sha256,
            explicit_fake=transport is not None
            and not isinstance(transport, HttpOpenLigaTransport),
        ),
    )
    review = state.run(
        ExecutionStage.AUTHENTICATE_REVIEW,
        FailureReason.REVIEW_INVALID,
        lambda: authenticate_review(
            review_path,
            expected_sha256=expected_review_sha256,
            implementation_root=implementation_root,
        ),
    )
    state.run(
        ExecutionStage.AUTHENTICATE_FORECAST,
        FailureReason.FORECAST_IDENTITY_MISMATCH,
        lambda: authenticate_p01(forecast_path),
    )
    state.stage = ExecutionStage.VALIDATE_ACQUISITION_ROOT
    started = clock()

    def valid_root() -> Path:
        at = FrozenEvidence.utc_datetimes(started)
        if at < review.reviewed_at:
            raise ReasonFailure(FailureReason.REVIEW_INVALID)
        if artifact_root.is_symlink():
            raise ReasonFailure(FailureReason.ACQUISITION_ROOT_INVALID)
        root = artifact_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    root = state.run(
        ExecutionStage.VALIDATE_ACQUISITION_ROOT, FailureReason.ACQUISITION_ROOT_INVALID, valid_root
    )
    marker = root / "OPENLIGADB-P01-ONE-ATTEMPT.json"
    marker_payload = {
        "context_sha256": context.semantic_sha256,
        "independent_review_sha256": review.semantic_sha256,
        "forecast_sha256": context.forecast_sha256,
        "forecast_byte_sha256": context.forecast_byte_sha256,
        "source": "OpenLigaDB",
        "started_at": started.isoformat(),
        "source_policy_locked_before_metrics": True,
        "no_metrics_inspected": True,
        "no_retry_or_polling": True,
    }

    def seal_marker() -> None:
        try:
            with marker.open("xb") as stream:
                stream.write(pretty_json(marker_payload).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise ReasonFailure(FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED) from None

    state.run(
        ExecutionStage.SEAL_ONE_ATTEMPT_MARKER, FailureReason.MARKER_PERSISTENCE_FAILED, seal_marker
    )
    # The guard above proves explicit injection. There is no default/live client.
    if transport is None:
        raise P01FallbackExecutionFailure(
            state.stage, FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED, state.safe
        )
    client = transport
    receipts: list[SourceReceipt] = []

    def fetch(index: int, stage: ExecutionStage) -> bytes:
        def operation() -> bytes:
            url = context.allowed_routes[index]
            request_start = FrozenEvidence.utc_datetimes(clock())
            state.begin(tuple(RouteClass)[index], request_start)
            try:
                body = client.get(url)
            except TimeoutError:
                raise ReasonFailure(FailureReason.TRANSPORT_TIMEOUT) from None
            except OSError:
                raise ReasonFailure(FailureReason.TRANSPORT_UNAVAILABLE) from None
            received = FrozenEvidence.utc_datetimes(clock())
            if type(body) is not bytes:
                raise ReasonFailure(FailureReason.TRANSPORT_UNAVAILABLE)
            observed = body[:524289]
            state.receipt(
                response_bytes=len(observed), response_sha256=hashlib.sha256(observed).hexdigest()
            )
            if len(body) > 524288:
                raise ReasonFailure(FailureReason.TRANSPORT_RESPONSE_TOO_LARGE)
            state.receipt(response_received_at=received, response_complete=True)
            receipts.append(source_receipt(url, body, started=request_start, received=received))
            return body

        return state.run(stage, FailureReason.TRANSPORT_UNAVAILABLE, operation)

    global_body = fetch(0, ExecutionStage.FETCH_GLOBAL_RESULT_TYPES)
    league_body = fetch(1, ExecutionStage.FETCH_LEAGUE_RESULT_INFO)
    result_type = state.run(
        ExecutionStage.RESOLVE_REGULATION_RESULT_TYPE,
        FailureReason.REGULATION_METADATA_AMBIGUOUS,
        lambda: regulation_type(global_body, league_body, diagnostics=state),
    )
    body = fetch(2, ExecutionStage.FETCH_MATCHDAY_RESPONSE)
    facts = state.run(
        ExecutionStage.PROJECT_FINAL_FACTS,
        FailureReason.MATCHDAY_RESPONSE_INVALID,
        lambda: project_final_facts(
            body, context=context, result_type=result_type, diagnostics=state
        ),
    )
    state.stage = ExecutionStage.ADMIT_EXACT_TEN
    validated = FrozenEvidence.utc_datetimes(clock())
    outcomes = state.run(
        ExecutionStage.ADMIT_EXACT_TEN,
        FailureReason.FALLBACK_ADMISSION_INVALID,
        lambda: admit_final_facts(
            facts,
            context=context,
            retrievals=tuple(receipts),
            result_type=result_type,
            validated_at=validated,
            usable_at=FrozenEvidence.utc_datetimes(clock()),
            attribution=rights.attribution_text or "",
            independent_review_sha256=review.semantic_sha256,
            independently_reviewed_at=review.reviewed_at,
            diagnostics=state,
        ),
    )
    state.run(
        ExecutionStage.PERSIST_OUTCOME_ARTIFACT,
        FailureReason.PERSISTENCE_FAILED,
        lambda: persist_fallback(outcomes, artifact_root=root),
    )
    state.run(
        ExecutionStage.VALIDATE_D_PLUS_2,
        FailureReason.D_PLUS_2_NOT_COMPLETE,
        lambda: require_d_plus_2(outcomes, as_of=FrozenEvidence.utc_datetimes(clock())),
    )
    state.stage = ExecutionStage.COMPLETE
    return outcomes


def acquire_p01_once(
    *,
    forecast_path: Path,
    review_path: Path,
    expected_review_sha256: str,
    implementation_root: Path,
    artifact_root: Path,
    transport: OpenLigaTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: DiagnosticProgress | None = None,
) -> PublicP01FallbackOutcomesV1:
    state = progress or DiagnosticProgress()
    try:
        return _acquire_p01_once(
            forecast_path=forecast_path,
            review_path=review_path,
            expected_review_sha256=expected_review_sha256,
            implementation_root=implementation_root,
            artifact_root=artifact_root,
            transport=transport,
            clock=clock,
            progress=state,
        )
    except P01FallbackExecutionFailure:
        raise
    except Exception:
        raise P01FallbackExecutionFailure(
            state.stage, FailureReason.UNKNOWN_P01_OUTCOME_FAILURE, state.safe
        ) from None
