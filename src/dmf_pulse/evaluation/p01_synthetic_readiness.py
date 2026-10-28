"""Exercise accepted P01 gates offline; return no actual labels or score artifact."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator

from dmf_pulse.evaluation.p01_fallback import _score_admitted, fallback_scorecard
from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    FORECAST_SHA,
    P01FallbackContext,
    require_forecast_binding,
    require_openligadb_rights,
)
from dmf_pulse.evaluation.p01_frozen_view import P01FrozenScoringView
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.p01_fallback import (
    admit_final_facts,
    project_final_facts,
    regulation_type,
    require_d_plus_2,
    source_receipt,
)
from dmf_pulse.ingestion.p01_metadata_candidate import (
    project_synthetic_candidate,
    require_synthetic_context,
)


class SyntheticPipelineReceiptV1(SealedEvidence):
    schema_version: Literal["p01-synthetic-pipeline-receipt-v1"] = (
        "p01-synthetic-pipeline-receipt-v1"
    )
    classification: Literal["SYNTHETIC_ONLY_NOT_PROSPECTIVE_EVIDENCE"] = (
        "SYNTHETIC_ONLY_NOT_PROSPECTIVE_EVIDENCE"
    )
    metadata_policy: Literal["LEGACY_STRICT", "INACTIVE_CANDIDATE_V1"]
    forecast_sha256: SHA
    context_sha256: SHA
    synthetic_source_sha256: tuple[SHA, SHA, SHA]
    synthetic_scorecard_sha256: SHA
    as_of: datetime
    fixture_count: Literal[10] = 10
    product_rows: Literal[30] = 30
    checks: tuple[
        Literal[
            "RIGHTS",
            "SYNTHETIC_BINDING",
            "RESULT_TYPES",
            "PROJECTION",
            "EXACT_TEN",
            "D_PLUS_2",
            "ACCEPTED_SCORER",
            "SCORECARD",
        ],
        ...,
    ]
    actual_p01_scored: Literal[False] = False
    acquisition_permitted: Literal[False] = False
    policy_accepted: Literal[False] = False
    production_active: Literal[False] = False

    @model_validator(mode="after")
    def complete_exercise(self) -> Self:
        if (
            self.context_sha256 == CONTEXT_SHA
            or self.forecast_sha256 == FORECAST_SHA
            or self.checks
            != (
                "RIGHTS",
                "SYNTHETIC_BINDING",
                "RESULT_TYPES",
                "PROJECTION",
                "EXACT_TEN",
                "D_PLUS_2",
                "ACCEPTED_SCORER",
                "SCORECARD",
            )
        ):
            raise ValueError("synthetic receipt identity or gate sequence differs")
        return self


def exercise_synthetic_pipeline(
    forecast: P01FrozenScoringView,
    *,
    context: P01FallbackContext,
    global_types: bytes,
    league_types: bytes,
    matchday: bytes,
    as_of: datetime,
    candidate: bool = False,
) -> SyntheticPipelineReceiptV1:
    """Pure injected-byte exercise; legacy intermediates never leave this function.

    This is neither a provider request nor the operational score_p01_fallback API.
    The only returned artifact is a distinct synthetic receipt without score values.
    """
    require_synthetic_context(context)
    if type(forecast) is not P01FrozenScoringView or forecast.dataset_mode != "RECONSTRUCTED":
        raise StrengthEvidenceError("SYNTHETIC_RECONSTRUCTED_FORECAST_REQUIRED")
    if forecast.semantic_sha256 == FORECAST_SHA:
        raise StrengthEvidenceError("SYNTHETIC_ONLY_ACTUAL_P01_REFUSED")
    authenticate(forecast)
    require_forecast_binding(forecast, context=context)
    require_openligadb_rights()
    as_of = FrozenEvidence.utc_datetimes(as_of)
    if any(len(body) > 524288 for body in (global_types, league_types, matchday)):
        raise StrengthEvidenceError("SYNTHETIC_SOURCE_TOO_LARGE")
    result_type = regulation_type(global_types, league_types)
    if candidate:
        projected = project_synthetic_candidate(matchday, context=context, result_type=result_type)
        facts = tuple(row.canonical_fact for row in projected.facts)
    else:
        facts = project_final_facts(matchday, context=context, result_type=result_type)
    receipts = tuple(
        source_receipt(url, body, started=as_of, received=as_of)
        for url, body in zip(
            context.allowed_routes, (global_types, league_types, matchday), strict=True
        )
    )
    outcomes = admit_final_facts(
        facts,
        context=context,
        retrievals=receipts,
        result_type=result_type,
        validated_at=as_of,
        usable_at=as_of,
        attribution="SYNTHETIC_ONLY_OFFLINE_EXERCISE_NO_PROVIDER_OBSERVATION",
        independent_review_sha256="0" * 64,
        independently_reviewed_at=context.amended_at,
    )
    require_d_plus_2(outcomes, as_of=as_of)
    score = _score_admitted(forecast, outcomes=outcomes, as_of=as_of)
    scorecard = fallback_scorecard(score, outcomes=outcomes)
    return seal(
        SyntheticPipelineReceiptV1,
        metadata_policy="INACTIVE_CANDIDATE_V1" if candidate else "LEGACY_STRICT",
        forecast_sha256=forecast.semantic_sha256,
        context_sha256=context.semantic_sha256,
        synthetic_source_sha256=tuple(row.response_sha256 for row in receipts),
        synthetic_scorecard_sha256=scorecard.semantic_sha256,
        as_of=as_of,
        fixture_count=len(outcomes.outcomes),
        product_rows=len(score.metrics.scores),
        checks=(
            "RIGHTS",
            "SYNTHETIC_BINDING",
            "RESULT_TYPES",
            "PROJECTION",
            "EXACT_TEN",
            "D_PLUS_2",
            "ACCEPTED_SCORER",
            "SCORECARD",
        ),
    )
