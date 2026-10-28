"""One A03 execution using unchanged D1 diagnostics and accepted P01 kernels."""

from __future__ import annotations

import http.client
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.p01_a03_authority import (
    A03ReviewBinding,
    authenticate_a03_review,
    load_a03_authority,
)
from dmf_pulse.evaluation.p01_fallback import fallback_scorecard, score_p01_fallback
from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    authenticate_p01,
    load_context,
    require_openligadb_rights,
)
from dmf_pulse.evaluation.p01_fallback_store import persist_fallback
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.p01_a03_control import (
    A03ConsumptionReceipt,
    GitHubA03Control,
    RemoteConsumptionSeal,
    consumption_receipt,
)
from dmf_pulse.ingestion.p01_fallback import (
    SourceReceipt,
    admit_final_facts,
    project_final_facts,
    regulation_type,
    require_d_plus_2,
    source_receipt,
)
from dmf_pulse.ingestion.p01_fallback_consumption import load_consumption
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    DiagnosticProgress,
    P01FallbackExecutionFailure,
    ReasonFailure,
    RouteClass,
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
from dmf_pulse.ingestion.p01_fallback_transport import HttpOpenLigaTransport


class A03Control(Protocol):
    def verify(self, binding: A03ReviewBinding, *, expected_review_bytes: bytes) -> None: ...

    def consume(self, receipt: A03ConsumptionReceipt) -> RemoteConsumptionSeal: ...


class A03OutcomeBinding(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-a03-outcome-binding-v1"] = (
        "public-team-strength-p01-fallback-a03-outcome-binding-v1"
    )
    authority_sha256: SHA
    remote_consumption: RemoteConsumptionSeal
    outcome_artifact_sha256: SHA
    provenance: Literal["PUBLIC_FALLBACK_OUTCOME_SOURCE"] = "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    source: Literal["OpenLigaDB"] = "OpenLigaDB"
    production_active: Literal[False] = False

    @model_validator(mode="after")
    def authority_matches(self) -> Self:
        remote = authenticate(self.remote_consumption)
        if remote.receipt.authority_sha256 != self.authority_sha256:
            raise ValueError("A03 outcome authority differs from consumption")
        return self


class A03PostScoreFailure(FrozenEvidence):
    """Truthful exceptional storage/postcheck failure after scoring occurred.

    D1 stopped diagnostics describe an unscored acquisition. This separate safe
    record prevents attributing its scoring_performed=false literal to a later
    failure after the accepted scorer returned. No numeric scores are disclosed.
    """

    stage: S
    reason: R
    diagnostics: SafeDiagnostics
    scoring_performed: Literal[True] = True


class A03ExecutionHandoff(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-a03-execution-handoff-v1"] = (
        "public-team-strength-p01-fallback-a03-execution-handoff-v1"
    )
    authority_sha256: SHA
    implementation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    review_sha256: SHA
    exact_sha_review_binding_sha256: SHA
    one_attempt_consumed: bool = Field(
        description=(
            "Human authority retired for this execution; never grants a retry. "
            "Only consumption_verified plus remote_consumption proves a remote seal exists."
        )
    )
    consumption_verified: bool
    remote_consumption: RemoteConsumptionSeal | None
    status: Literal["P01_A03_COMPLETE", "P01_A03_STOPPED_TYPED", "P01_A03_PRECHECK_STOPPED"]
    execution_stage: S
    started_at: datetime
    stopped_at: datetime
    forecast_semantic_sha256_before: SHA
    forecast_semantic_sha256_after: SHA | None
    forecast_byte_sha256_before: SHA
    forecast_byte_sha256_after: SHA | None
    forecast_immutability_verified: bool
    diagnostic: StoppedExecutionDiagnostic | None
    post_score_failure: A03PostScoreFailure | None = None
    outcome_artifact_sha256: SHA | None = None
    outcome_authority_binding_sha256: SHA | None = None
    score_sha256: SHA | None = None
    scorecard_sha256: SHA | None = None
    scoring_performed: bool = False
    production_active: Literal[False] = False
    retry_performed: Literal[False] = False
    source_switch_performed: Literal[False] = False
    private_provider_requests: Literal[0] = 0
    credentials_inspected: Literal[0] = 0

    @model_validator(mode="after")
    def coherent_execution(self) -> Self:
        if self.stopped_at < self.started_at:
            raise ValueError("A03 handoff chronology differs")
        if self.remote_consumption is not None:
            remote = authenticate(self.remote_consumption)
            receipt = authenticate(remote.receipt)
            if (
                not self.one_attempt_consumed
                or not self.consumption_verified
                or receipt.authority_sha256 != self.authority_sha256
                or receipt.implementation_sha != self.implementation_sha
                or receipt.independent_review_sha256 != self.review_sha256
                or receipt.exact_sha_review_binding_sha256 != self.exact_sha_review_binding_sha256
            ):
                raise ValueError("A03 handoff consumption binding differs")
        elif self.consumption_verified:
            raise ValueError("A03 verified consumption lacks a seal")
        if self.forecast_immutability_verified != (
            self.forecast_semantic_sha256_after == self.forecast_semantic_sha256_before
            and self.forecast_byte_sha256_after == self.forecast_byte_sha256_before
        ):
            raise ValueError("A03 forecast immutability evidence differs")
        if self.status == "P01_A03_COMPLETE":
            if (
                self.execution_stage != S.COMPLETE
                or self.diagnostic is not None
                or self.post_score_failure is not None
                or not self.scoring_performed
                or not self.forecast_immutability_verified
                or not self.consumption_verified
                or any(
                    value is None
                    for value in (
                        self.outcome_artifact_sha256,
                        self.outcome_authority_binding_sha256,
                        self.score_sha256,
                        self.scorecard_sha256,
                    )
                )
            ):
                raise ValueError("A03 complete handoff lacks successful gates")
        elif self.execution_stage == S.COMPLETE:
            raise ValueError("A03 stopped handoff cannot be complete")
        if (
            self.scoring_performed
            and self.status != "P01_A03_COMPLETE"
            and (self.post_score_failure is None or self.diagnostic is not None)
        ):
            raise ValueError("post-score failure must retain truthful scoring state")
        if not self.scoring_performed and (
            self.post_score_failure is not None or self.score_sha256 is not None
        ):
            raise ValueError("unscored handoff cannot contain score evidence")
        return self


def persist_a03(
    value: A03ExecutionHandoff | A03OutcomeBinding | RemoteConsumptionSeal, root: Path
) -> Path:
    """Exclusive internal evidence, post-write authenticated; no provider payloads."""
    require_openligadb_rights()
    value = authenticate(value)
    if root.is_symlink():
        raise ReasonFailure(R.PERSISTENCE_FAILED)
    directory = root.resolve()
    path = directory / value.schema_version / (value.semantic_sha256 + ".json")
    if path.is_symlink() or not path.resolve().is_relative_to(directory):
        raise ReasonFailure(R.PERSISTENCE_FAILED)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.resolve().is_relative_to(directory):
        raise ReasonFailure(R.PERSISTENCE_FAILED)
    payload = pretty_json(value).encode()
    descriptor, name = tempfile.mkstemp(prefix=".a03-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                raise ReasonFailure(R.PERSISTENCE_FAILED) from None
    finally:
        temporary.unlink()
    if authenticate(type(value).model_validate_json(path.read_bytes())) != value:
        raise ReasonFailure(R.PERSISTENCE_FAILED)
    return path


def execute_a03(
    *,
    forecast_path: Path,
    review_path: Path,
    binding_path: Path,
    expected_binding_sha256: str,
    implementation_root: Path,
    artifact_root: Path,
    control: A03Control | None = None,
    transport_factory: Callable[[], HttpOpenLigaTransport] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: DiagnosticProgress | None = None,
) -> A03ExecutionHandoff:
    """All provider connections are constructed only after a verified fresh seal.

    Dependency injection exists for offline tests; the operational script exposes
    no control, transport, source, context, force or retry override.
    """
    state = progress or DiagnosticProgress()
    started = clock()
    authority = state.run(S.LOAD_CONTEXT, R.CONTEXT_INVALID, load_a03_authority)
    context = state.run(S.LOAD_CONTEXT, R.CONTEXT_INVALID, load_context)
    state.run(S.LOAD_CONTEXT, R.CONTEXT_INVALID, load_consumption)
    rights = state.run(S.AUTHENTICATE_RIGHTS, R.RIGHTS_IDENTITY_MISMATCH, require_openligadb_rights)
    review, binding = state.run(
        S.AUTHENTICATE_REVIEW,
        R.REVIEW_INVALID,
        lambda: authenticate_a03_review(
            review_path, binding_path, implementation_root=implementation_root
        ),
    )
    if binding.semantic_sha256 != expected_binding_sha256:
        raise P01FallbackExecutionFailure(S.AUTHENTICATE_REVIEW, R.REVIEW_INVALID, state.safe)
    governance = control or GitHubA03Control(implementation_root)
    state.run(
        S.AUTHENTICATE_REVIEW,
        R.REVIEW_INVALID,
        lambda: governance.verify(binding, expected_review_bytes=review_path.read_bytes()),
    )
    forecast = state.run(
        S.AUTHENTICATE_FORECAST,
        R.FORECAST_IDENTITY_MISMATCH,
        lambda: authenticate_p01(forecast_path),
    )

    def root_check() -> Path:
        if artifact_root.is_symlink() or artifact_root.name != authority.ticket:
            raise ReasonFailure(R.ACQUISITION_ROOT_INVALID)
        root = artifact_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        if clock() < binding.bound_at or clock() < review.reviewed_at:
            raise ReasonFailure(R.REVIEW_INVALID)
        return root

    root = state.run(S.VALIDATE_ACQUISITION_ROOT, R.ACQUISITION_ROOT_INVALID, root_check)
    remote: RemoteConsumptionSeal | None = None
    consumed = False
    failure: P01FallbackExecutionFailure | None = None
    outcome_sha = outcome_binding_sha = score_sha = scorecard_sha = None
    scored = False
    try:
        # Retire this human authorization on this execution even if governance
        # I/O is ambiguous. consumption_verified separately identifies a proven
        # remote seal; no remote fact is inferred from an unconfirmed write.
        consumed = True
        remote = state.run(
            S.SEAL_ONE_ATTEMPT_MARKER,
            R.MARKER_PERSISTENCE_FAILED,
            lambda: governance.consume(consumption_receipt(binding, at=clock())),
        )
        state.run(
            S.SEAL_ONE_ATTEMPT_MARKER,
            R.MARKER_PERSISTENCE_FAILED,
            lambda: persist_a03(remote, root),
        )
        # Reauthenticate immediately before enabling a native HTTPS connection.
        state.run(
            S.AUTHENTICATE_FORECAST,
            R.FORECAST_IDENTITY_MISMATCH,
            lambda: authenticate_p01(forecast_path),
        )
        client = (
            transport_factory()
            if transport_factory is not None
            else HttpOpenLigaTransport(connection_factory=http.client.HTTPSConnection)
        )
        receipts: list[SourceReceipt] = []

        def fetch(index: int, stage: S) -> bytes:
            def operation() -> bytes:
                at = clock()
                state.begin(tuple(RouteClass)[index], at)
                body = client.get(context.allowed_routes[index], progress=state, clock=clock)
                receipts.append(
                    source_receipt(
                        context.allowed_routes[index], body, started=at, received=clock()
                    )
                )
                return body

            return state.run(stage, R.TRANSPORT_UNAVAILABLE, operation)

        global_body = fetch(0, S.FETCH_GLOBAL_RESULT_TYPES)
        league_body = fetch(1, S.FETCH_LEAGUE_RESULT_INFO)
        result_type = state.run(
            S.RESOLVE_REGULATION_RESULT_TYPE,
            R.REGULATION_METADATA_AMBIGUOUS,
            lambda: regulation_type(global_body, league_body, diagnostics=state),
        )
        body = fetch(2, S.FETCH_MATCHDAY_RESPONSE)
        facts = state.run(
            S.PROJECT_FINAL_FACTS,
            R.MATCHDAY_RESPONSE_INVALID,
            lambda: project_final_facts(
                body, context=context, result_type=result_type, diagnostics=state
            ),
        )
        outcomes = state.run(
            S.ADMIT_EXACT_TEN,
            R.FALLBACK_ADMISSION_INVALID,
            lambda: admit_final_facts(
                facts,
                context=context,
                retrievals=tuple(receipts),
                result_type=result_type,
                validated_at=clock(),
                usable_at=clock(),
                attribution=rights.attribution_text or "",
                independent_review_sha256=review.semantic_sha256,
                independently_reviewed_at=review.reviewed_at,
                diagnostics=state,
            ),
        )
        state.run(
            S.PERSIST_OUTCOME_ARTIFACT,
            R.PERSISTENCE_FAILED,
            lambda: persist_fallback(outcomes, artifact_root=root),
        )
        identity = seal(
            A03OutcomeBinding,
            authority_sha256=authority.semantic_sha256,
            remote_consumption=remote,
            outcome_artifact_sha256=outcomes.semantic_sha256,
        )
        state.run(
            S.PERSIST_OUTCOME_ARTIFACT, R.PERSISTENCE_FAILED, lambda: persist_a03(identity, root)
        )
        state.run(
            S.VALIDATE_D_PLUS_2,
            R.D_PLUS_2_NOT_COMPLETE,
            lambda: require_d_plus_2(outcomes, as_of=clock()),
        )
        # Pure accepted score-envelope admission, after all outcome gates. No fit,
        # draw generation, numerical change or source selection is reachable here.
        score = state.run(
            S.ADMIT_EXACT_TEN,
            R.FALLBACK_ADMISSION_INVALID,
            lambda: score_p01_fallback(forecast, outcomes=outcomes, as_of=clock()),
        )
        scored, score_sha = True, score.semantic_sha256
        report = state.run(
            S.ADMIT_EXACT_TEN,
            R.FALLBACK_ADMISSION_INVALID,
            lambda: fallback_scorecard(score, outcomes=outcomes),
        )
        state.run(
            S.PERSIST_OUTCOME_ARTIFACT,
            R.PERSISTENCE_FAILED,
            lambda: persist_fallback(score, artifact_root=root),
        )
        state.run(
            S.PERSIST_OUTCOME_ARTIFACT,
            R.PERSISTENCE_FAILED,
            lambda: persist_fallback(report, artifact_root=root),
        )
        outcome_sha, outcome_binding_sha = outcomes.semantic_sha256, identity.semantic_sha256
        scorecard_sha = report.semantic_sha256
    except P01FallbackExecutionFailure as exc:
        failure = exc
    except Exception:
        failure = P01FallbackExecutionFailure(
            state.stage, R.UNKNOWN_P01_OUTCOME_FAILURE, state.safe
        )
    # The same nongenerative pinned reader verifies both success and stopped paths.
    after = None
    try:
        after = state.run(
            S.AUTHENTICATE_FORECAST,
            R.FORECAST_IDENTITY_MISMATCH,
            lambda: authenticate_p01(forecast_path),
        )
        if after.semantic_sha256 != forecast.semantic_sha256:
            after = None
            raise P01FallbackExecutionFailure(
                S.AUTHENTICATE_FORECAST, R.FORECAST_IDENTITY_MISMATCH, state.safe
            )
    except P01FallbackExecutionFailure as exc:
        failure = exc
    diagnostic = None
    post_score_failure = None
    if failure is not None:
        if scored:
            post_score_failure = A03PostScoreFailure(
                stage=failure.stage, reason=failure.reason, diagnostics=failure.diagnostics
            )
        else:
            diagnostic = stopped_record(
                failure,
                started_at=started,
                stopped_at=clock(),
                context_sha256=CONTEXT_SHA,
                one_attempt_consumed=consumed,
            )
            persist_stopped(diagnostic, root=root)
    else:
        state.stage = S.COMPLETE
    handoff = seal(
        A03ExecutionHandoff,
        authority_sha256=authority.semantic_sha256,
        implementation_sha=binding.implementation_sha,
        review_sha256=review.semantic_sha256,
        exact_sha_review_binding_sha256=binding.semantic_sha256,
        one_attempt_consumed=consumed,
        consumption_verified=remote is not None,
        remote_consumption=remote,
        status="P01_A03_STOPPED_TYPED" if failure else "P01_A03_COMPLETE",
        execution_stage=state.stage if failure is None else failure.stage,
        started_at=started,
        stopped_at=clock(),
        forecast_semantic_sha256_before=forecast.semantic_sha256,
        forecast_semantic_sha256_after=None if after is None else after.semantic_sha256,
        forecast_byte_sha256_before=context.forecast_byte_sha256,
        forecast_byte_sha256_after=None if after is None else context.forecast_byte_sha256,
        forecast_immutability_verified=after is not None,
        diagnostic=diagnostic,
        post_score_failure=post_score_failure,
        outcome_artifact_sha256=outcome_sha,
        outcome_authority_binding_sha256=outcome_binding_sha,
        score_sha256=score_sha,
        scorecard_sha256=scorecard_sha,
        scoring_performed=scored,
    )
    state.stage = S.PERSIST_OUTCOME_ARTIFACT
    persist_a03(handoff, root)
    state.stage = handoff.execution_stage
    return handoff
