"""Disclosure-safe screen counts; identities are consumed transiently only."""

from decimal import Decimal, localcontext
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.football_events.team_strength_model import Number
from dmf_pulse.ingestion.openfootball.team_strength_data import FrozenEvidence


class ScreenComparisonMetrics(FrozenEvidence):
    schema_version: Literal["team-strength-safe-screen-metrics-v1"] = (
        "team-strength-safe-screen-metrics-v1"
    )
    screen_scope: Literal["ALLOWED_TRANSFER_IN_UNION_OVER_HORIZON"] = (
        "ALLOWED_TRANSFER_IN_UNION_OVER_HORIZON"
    )
    baseline_screen_count: int = Field(ge=0)
    shadow_screen_count: int = Field(ge=0)
    intersection_count: int = Field(ge=0)
    union_count: int = Field(ge=0)
    added_count: int = Field(ge=0)
    removed_count: int = Field(ge=0)
    jaccard_similarity: Number = Field(ge=0, le=1)
    protected_candidate_count: int = Field(ge=0)
    protected_candidate_retained_count: int = Field(ge=0)
    baseline_protected_retained_count: int = Field(ge=0)
    shadow_protected_retained_count: int = Field(ge=0)
    node_eligibility_added_count: int = Field(ge=0)
    node_eligibility_removed_count: int = Field(ge=0)
    exact_cross_screen_solving: Literal["OFF_BY_DEFAULT_NOT_IMPLEMENTED"] = (
        "OFF_BY_DEFAULT_NOT_IMPLEMENTED"
    )

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        b, s, i, u = (
            self.baseline_screen_count,
            self.shadow_screen_count,
            self.intersection_count,
            self.union_count,
        )
        if (
            i > min(b, s)
            or u != b + s - i
            or self.added_count != s - i
            or self.removed_count != b - i
        ):
            raise ValueError("screen metrics do not reconcile")
        with localcontext() as context:
            context.prec = 60
            expected = Decimal(i) / u if u else Decimal(1)
        if self.jaccard_similarity != expected:
            raise ValueError("screen Jaccard mismatch")
        if (
            self.protected_candidate_retained_count
            > min(
                i,
                self.protected_candidate_count,
                self.baseline_protected_retained_count,
                self.shadow_protected_retained_count,
            )
            or self.baseline_protected_retained_count > min(b, self.protected_candidate_count)
            or self.shadow_protected_retained_count > min(s, self.protected_candidate_count)
        ):
            raise ValueError("protected screen counts inconsistent")
        return self


def screen_metrics(
    baseline: frozenset[str],
    shadow: frozenset[str],
    *,
    protected: frozenset[str],
    baseline_node_eligibility: frozenset[tuple[str, int, str]] = frozenset(),
    shadow_node_eligibility: frozenset[tuple[str, int, str]] = frozenset(),
) -> ScreenComparisonMetrics:
    intersection, union = baseline & shadow, baseline | shadow
    with localcontext() as context:
        context.prec = 60
        return ScreenComparisonMetrics(
            baseline_screen_count=len(baseline),
            shadow_screen_count=len(shadow),
            intersection_count=len(intersection),
            union_count=len(union),
            added_count=len(shadow - baseline),
            removed_count=len(baseline - shadow),
            jaccard_similarity=Decimal(len(intersection)) / len(union) if union else Decimal(1),
            protected_candidate_count=len(protected),
            protected_candidate_retained_count=len(protected & intersection),
            baseline_protected_retained_count=len(protected & baseline),
            shadow_protected_retained_count=len(protected & shadow),
            node_eligibility_added_count=len(shadow_node_eligibility - baseline_node_eligibility),
            node_eligibility_removed_count=len(baseline_node_eligibility - shadow_node_eligibility),
        )
