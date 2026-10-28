"""Inactive, synthetic-only descriptive metadata compatibility experiment."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    FORECAST_SHA,
    P01FallbackContext,
    strict_json,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.p01_fallback import (
    ProjectedFinalFact,
    RegulationResultType,
    project_final_facts,
)


def require_synthetic_context(context: P01FallbackContext) -> None:
    authenticate(context)
    if context.semantic_sha256 == CONTEXT_SHA or context.forecast_sha256 == FORECAST_SHA:
        raise StrengthEvidenceError("SYNTHETIC_ONLY_ACTUAL_P01_REFUSED")


class ObservedDisplayName(FrozenEvidence):
    state: Literal["ABSENT", "NULL", "STRING"]
    value: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def valid_text(self) -> Self:
        if self.state == "STRING":
            if (
                self.value is None
                or not self.value.strip()
                or any(unicodedata.category(char).startswith("C") for char in self.value)
            ):
                raise ValueError("candidate descriptive text is invalid")
        elif self.value is not None:
            raise ValueError("absent or null description cannot have text")
        return self


class CandidateFinalFact(FrozenEvidence):
    canonical_fact: ProjectedFinalFact
    provider_display_name: ObservedDisplayName
    canonical_label_origin: Literal["FROZEN_CONTEXT_NOT_PROVIDER_OBSERVATION"] = (
        "FROZEN_CONTEXT_NOT_PROVIDER_OBSERVATION"
    )


class SyntheticMetadataCandidateV1(SealedEvidence):
    schema_version: Literal["p01-synthetic-metadata-candidate-v1"] = (
        "p01-synthetic-metadata-candidate-v1"
    )
    classification: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"
    policy_state: Literal["PROPOSED_UNAPPROVED"] = "PROPOSED_UNAPPROVED"
    activation: Literal["INACTIVE"] = "INACTIVE"
    context_sha256: SHA
    forecast_sha256: SHA
    original_synthetic_body_sha256: SHA
    normalization: Literal["TRANSIENT_CANONICAL_DISPLAY_LABEL_FOR_LEGACY_PROJECTOR"] = (
        "TRANSIENT_CANONICAL_DISPLAY_LABEL_FOR_LEGACY_PROJECTOR"
    )
    facts: tuple[CandidateFinalFact, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def synthetic_identity(self) -> Self:
        if self.context_sha256 == CONTEXT_SHA or self.forecast_sha256 == FORECAST_SHA:
            raise ValueError("candidate cannot bind actual P01")
        return self


def project_synthetic_candidate(
    body: bytes, *, context: P01FallbackContext, result_type: RegulationResultType
) -> SyntheticMetadataCandidateV1:
    """Reuse strict identity/finality; never wire this into acquisition or real admission.

    The original display state/value is retained separately. Only a transient copy
    gets the canonical label, explicitly disclosed in the returned candidate.
    """
    require_synthetic_context(context)
    if len(body) > 524288:
        raise StrengthEvidenceError("SYNTHETIC_MATCHDAY_TOO_LARGE")
    rows = strict_json(body)
    if not isinstance(rows, list) or len(rows) != 10 or any(not isinstance(r, dict) for r in rows):
        raise StrengthEvidenceError("SYNTHETIC_MATCHDAY_SHAPE_INVALID")
    observed: list[ObservedDisplayName] = []
    normalized: list[dict[str, object]] = []
    for row in rows:
        value = row.get("leagueName")
        state: Literal["ABSENT", "NULL", "STRING"] = (
            "ABSENT" if "leagueName" not in row else "NULL" if value is None else "STRING"
        )
        try:
            observed.append(ObservedDisplayName(state=state, value=value))
        except ValueError:
            raise StrengthEvidenceError("CANDIDATE_DISPLAY_NAME_INVALID") from None
        normalized.append({**row, "leagueName": context.league_name})
    facts = project_final_facts(
        json.dumps(normalized).encode(), context=context, result_type=result_type
    )
    return seal(
        SyntheticMetadataCandidateV1,
        context_sha256=context.semantic_sha256,
        forecast_sha256=context.forecast_sha256,
        original_synthetic_body_sha256=hashlib.sha256(body).hexdigest(),
        facts=tuple(
            CandidateFinalFact(canonical_fact=fact, provider_display_name=name)
            for fact, name in zip(facts, observed, strict=True)
        ),
    )
