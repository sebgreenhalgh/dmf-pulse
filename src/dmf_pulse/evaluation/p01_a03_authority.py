"""Explicit execution-only A03 authority; no provider I/O at import."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import sha256_file
from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    FORECAST_BYTE_SHA,
    FORECAST_SHA,
    RIGHTS_SHA,
    ROUTES,
    load_context,
    resource_bytes,
    strict_json,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
)

D1_SHA = "f96eaa3e7261d0db6f23bc8eb7dee18917272d00"
D1_REVIEW_SHA = "26b793baa8ea272fdfd54ab3ba6e9cce8f8054d20c01406bbe39e338df868fe2"
REPOSITORY = "sebgreenhalgh/dmf-pulse"
BRANCH = "readiness/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03-one-shot-reauthorization"
CONSUMED_REF = "refs/heads/evidence/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03-consumed"
# Generated from the literal human request and pinned frozen context.
AUTHORITY_SHA = "1b9cde4d72416dc0ada2c20bb60da097106046033d00b4ed28c95c88e7676400"

REVIEW_PATHS = (
    "config/evaluation/team_strength_p01_fallback_a03.json",
    "config/evaluation/team_strength_p01_fallback_a02.json",
    "config/evaluation/team_strength_p01_a02_consumption.json",
    "config/rights/openligadb_p01_fallback.json",
    "src/dmf_pulse/evaluation/p01_a03_authority.py",
    "src/dmf_pulse/evaluation/p01_fallback_context.py",
    "src/dmf_pulse/evaluation/p01_frozen_view.py",
    "src/dmf_pulse/evaluation/p01_fallback.py",
    "src/dmf_pulse/evaluation/p01_fallback_store.py",
    "src/dmf_pulse/evaluation/team_strength_prospective.py",
    "src/dmf_pulse/ingestion/p01_fallback.py",
    "src/dmf_pulse/ingestion/p01_fallback_acquisition.py",
    "src/dmf_pulse/ingestion/p01_fallback_consumption.py",
    "src/dmf_pulse/ingestion/p01_fallback_diagnostics.py",
    "src/dmf_pulse/ingestion/p01_fallback_transport.py",
    "src/dmf_pulse/ingestion/p01_a03_control.py",
    "src/dmf_pulse/ingestion/p01_a03_execution.py",
    "src/dmf_pulse/cli/p01_a03.py",
    "src/dmf_pulse/cli/p01_fallback.py",
    "scripts/run_p01_fallback_a03.py",
    "scripts/verify_p01_fallback_a02_wheel.py",
    "tests/unit/evaluation/test_p01_fallback_a03.py",
    "tests/fixtures/evaluation/a02_d1_parent_semantics.json",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03/CONTRACT.md",
    "tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03/ACCEPTANCE.md",
)


class A03ExecutionAuthority(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-a03-execution-authority-v1"]
    ticket: Literal["CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03"]
    human_decision_status: Literal["A03_PUBLIC_OPENLIGADB_ONE_SHOT_AUTHORIZED"]
    decision: Literal["HUMAN_REAUTHORIZATION_AFTER_D1"]
    human_request_byte_sha256: SHA
    d1_implementation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    d1_review_sha256: SHA
    context_sha256: SHA
    forecast_sha256: SHA
    forecast_byte_sha256: SHA
    fixture_registry_sha256: SHA
    rights_profile_id: Literal["openligadb_public_final_score_labels_v1"]
    rights_profile_sha256: SHA
    source: Literal["OpenLigaDB"]
    permitted_routes: tuple[str, ...]
    attempt_number: Literal[1]
    maximum_attempts: Literal[1]
    retry_permitted: Literal[False]
    source_switch_permitted: Literal[False]
    production_active: Literal[False]
    promotion_permitted: Literal[False]
    model_tuning_permitted: Literal[False]
    private_provider_access_permitted: Literal[False]
    evaluation_epoch: Literal["EVALUATION_EPOCH_003"]
    classification: Literal["DESCRIPTIVE_P01_PILOT"]
    repository: Literal["sebgreenhalgh/dmf-pulse"]
    consumption_ref: str

    @model_validator(mode="after")
    def pinned_identity(self) -> Self:
        if (
            self.d1_implementation_sha != D1_SHA
            or self.d1_review_sha256 != D1_REVIEW_SHA
            or self.context_sha256 != CONTEXT_SHA
            or self.forecast_sha256 != FORECAST_SHA
            or self.forecast_byte_sha256 != FORECAST_BYTE_SHA
            or self.rights_profile_sha256 != RIGHTS_SHA
            or self.permitted_routes != ROUTES
            or self.consumption_ref != CONSUMED_REF
        ):
            raise ValueError("A03 pinned authority differs")
        return self


def load_a03_authority() -> A03ExecutionAuthority:
    raw = resource_bytes("evaluation/team_strength_p01_fallback_a03.json")
    strict_json(raw)
    value = authenticate(A03ExecutionAuthority.model_validate_json(raw), AUTHORITY_SHA)
    if value.fixture_registry_sha256 != load_context().fixture_registry_sha256:
        raise StrengthEvidenceError("A03 fixture registry differs")
    return value


class A03ReviewedFile(FrozenEvidence):
    path: str
    byte_sha256: SHA


class A03IndependentReview(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a03-independent-review-v1"]
    authority_sha256: SHA
    reviewer_identity: str = Field(min_length=1)
    reviewed_at: datetime
    verdict: Literal["CLEAR_FOR_P01_A03_ONE_SHOT_EXECUTION"]
    answers: tuple[Literal[True], ...] = Field(min_length=15, max_length=15)
    unresolved_p0_p1_material_p2: Literal[0]
    p01_scores_exist: Literal[False]
    provider_requests: Literal[0]
    files: tuple[A03ReviewedFile, ...]
    assessment: tuple[str, ...] = Field(min_length=8)

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        if tuple(row.path for row in self.files) != REVIEW_PATHS:
            raise ValueError("A03 independent review scope differs")
        return self


class A03ReviewBinding(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a03-exact-sha-review-binding-v1"]
    authority_sha256: SHA
    file_review_sha256: SHA
    implementation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    immutable_parent: Literal["f96eaa3e7261d0db6f23bc8eb7dee18917272d00"]
    reviewer_identity: str = Field(min_length=1)
    bound_at: datetime
    verdict: Literal["CLEAR_FOR_P01_A03_ONE_SHOT_EXECUTION"]
    ci_run_id: int = Field(gt=0)
    ci_conclusion: Literal["success"]
    successful_required_jobs: Literal[20]


def authenticate_a03_review(
    review_path: Path, binding_path: Path, *, implementation_root: Path
) -> tuple[A03IndependentReview, A03ReviewBinding]:
    authority = load_a03_authority()
    review_raw, binding_raw = review_path.read_bytes(), binding_path.read_bytes()
    strict_json(review_raw)
    strict_json(binding_raw)
    review = authenticate(A03IndependentReview.model_validate_json(review_raw))
    binding = authenticate(A03ReviewBinding.model_validate_json(binding_raw))
    if (
        review.authority_sha256 != authority.semantic_sha256
        or binding.authority_sha256 != authority.semantic_sha256
        or binding.file_review_sha256 != review.semantic_sha256
        or binding.reviewer_identity != review.reviewer_identity
        or binding.bound_at < review.reviewed_at
    ):
        raise StrengthEvidenceError("A03 review authority or timing differs")
    root = implementation_root.resolve()
    package = Path(__file__).resolve().parents[1]
    for row in review.files:
        path = root / row.path
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or sha256_file(path) != row.byte_sha256
        ):
            raise StrengthEvidenceError("A03 reviewed implementation differs")
        if row.path.startswith("src/dmf_pulse/"):
            running = package.joinpath(*Path(row.path).parts[2:])
            if running.is_symlink() or sha256_file(running) != row.byte_sha256:
                raise StrengthEvidenceError("A03 executing package differs from reviewed source")
    return review, binding
