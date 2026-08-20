"""One shared transient GW1 decision pipeline from reviewed inputs to Stage 12."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current import (
    CurrentAvailabilityApproval,
    CurrentAvailabilityBundle,
    CurrentAvailabilityReviewTemplate,
    build_current_availability,
    build_current_availability_review,
)
from dmf_pulse.evaluation.prospective import (
    ProspectiveDecisionReceipt,
    build_prospective_receipt,
    persist_prospective_receipt,
)
from dmf_pulse.fpl_points.current import (
    CurrentFootballEventApproval,
    CurrentFootballEventBundle,
    CurrentFootballEventReviewTemplate,
    build_current_football_event_review,
    build_current_football_events,
)
from dmf_pulse.fpl_points.current_points import (
    CurrentFplPointsBundle,
    build_current_fpl_points,
    build_current_fpl_points_run_config,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.session1 import Session1DownstreamInput
from dmf_pulse.markets.current import CurrentMarketConsensusBundle, build_current_market_consensus
from dmf_pulse.optimisation.current_initial_squad import (
    CurrentInitialSquadDecision,
    optimise_current_initial_squad,
)
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.models import RuleCapability

AvailabilityApprovalProvider = Callable[
    [CurrentAvailabilityReviewTemplate], CurrentAvailabilityApproval
]
EventApprovalProvider = Callable[[CurrentFootballEventReviewTemplate], CurrentFootballEventApproval]


class Gw1DecisionPipelineSummary(BaseModel):
    """Non-disclosing orchestration result safe for logs and persisted evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_DECISION_PIPELINE_SUMMARY"] = "GW1_DECISION_PIPELINE_SUMMARY"
    status: Literal["SUCCESS", "BLOCKED"]
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    session1_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prospective_receipt_sha256: str | None
    blocker_codes: tuple[str, ...]
    detailed_output_persisted: Literal[False] = False
    raw_provider_content_persisted: Literal[False] = False
    automated_fpl_account_action: Literal[False] = False
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if (
            (self.status == "SUCCESS") != (not self.blocker_codes)
            or (self.status == "SUCCESS") != (self.prospective_receipt_sha256 is not None)
            or self.blocker_codes != tuple(sorted(set(self.blocker_codes)))
            or self.summary_sha256 != _summary_sha256(self)
        ):
            raise ValueError("GW1 decision-pipeline summary is inconsistent")
        return self


def _summary_sha256(value: Gw1DecisionPipelineSummary) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"summary_sha256"}))


@dataclass(frozen=True)
class Gw1DecisionPipelineResult:
    """Private in-memory result; only the receipt and safe summary may be persisted."""

    market: CurrentMarketConsensusBundle
    availability: CurrentAvailabilityBundle
    events: CurrentFootballEventBundle
    projection: CurrentFplPointsBundle
    decision: CurrentInitialSquadDecision
    prospective_receipt: ProspectiveDecisionReceipt | None
    prospective_receipt_path: Path | None
    summary: Gw1DecisionPipelineSummary


def _build_summary(
    source: Session1DownstreamInput,
    market: CurrentMarketConsensusBundle,
    availability: CurrentAvailabilityBundle,
    events: CurrentFootballEventBundle,
    projection: CurrentFplPointsBundle,
    decision: CurrentInitialSquadDecision,
    receipt: ProspectiveDecisionReceipt | None,
) -> Gw1DecisionPipelineSummary:
    values: dict[str, object] = {
        "status": decision.status,
        "session1_semantic_sha256": source.semantic_sha256,
        "market_semantic_sha256": market.semantic_sha256,
        "availability_semantic_sha256": availability.semantic_sha256,
        "event_semantic_sha256": events.semantic_sha256,
        "projection_semantic_sha256": projection.semantic_sha256,
        "decision_sha256": decision.semantic_sha256,
        "prospective_receipt_sha256": receipt.receipt_sha256 if receipt else None,
        "blocker_codes": decision.blocker_codes,
    }
    provisional = Gw1DecisionPipelineSummary.model_construct(
        **values,  # type: ignore[arg-type]
        summary_sha256="0" * 64,
    )
    return Gw1DecisionPipelineSummary.model_validate(
        {**values, "summary_sha256": _summary_sha256(provisional)}
    )


def run_gw1_decision_pipeline(
    source: Session1DownstreamInput,
    *,
    availability_approval_provider: AvailabilityApprovalProvider,
    event_approval_provider: EventApprovalProvider,
    ruleset_path: Path,
    mc_policy_path: Path,
    root_seed: int,
    scenario_count: int,
    code_commit: str,
    receipt_clock: Callable[[], datetime],
    prospective_artifact_root: Path,
) -> Gw1DecisionPipelineResult:
    """Execute Stages 6-10 once and persist only a successful hash-only receipt."""

    market = build_current_market_consensus(source)
    availability_review = build_current_availability_review(market)
    availability = build_current_availability(
        market, availability_approval_provider(availability_review)
    )
    event_review = build_current_football_event_review(availability)
    events = build_current_football_events(availability, event_approval_provider(event_review))
    config = build_current_fpl_points_run_config(
        events,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
        root_seed=root_seed,
        scenario_count=scenario_count,
    )
    projection = build_current_fpl_points(
        events,
        config,
        ruleset_path=ruleset_path,
        mc_policy_path=mc_policy_path,
    )
    compiled = load_compiled_ruleset(ruleset_path)
    capability = compile_capability_artifact(compiled, RuleCapability.GW1_INITIAL_SQUAD)
    decision = optimise_current_initial_squad(events, projection, compiled, capability)

    receipt: ProspectiveDecisionReceipt | None = None
    receipt_path: Path | None = None
    if decision.status == "SUCCESS":
        assert projection.gameweek_projection.result_sha256 is not None
        receipt = build_prospective_receipt(
            recorded_at=receipt_clock(),
            information_cutoff=projection.run_config.information_cutoff,
            code_commit=code_commit,
            ruleset_hash=compiled.ruleset_hash,
            manager_capability_hash=capability.capability_hash,
            session1_semantic_sha256=source.semantic_sha256,
            market_semantic_sha256=market.semantic_sha256,
            availability_semantic_sha256=availability.semantic_sha256,
            event_semantic_sha256=events.semantic_sha256,
            projection_config_sha256=config.config_sha256,
            projection_semantic_sha256=projection.semantic_sha256,
            gameweek_result_sha256=projection.gameweek_projection.result_sha256,
            scenario_set_sha256=canonical_sha256(
                projection.gameweek_projection.scenario_set.model_dump(mode="json")
            ),
            decision_sha256=decision.semantic_sha256,
        )
        if receipt.recorded_at > source.information_cutoff:
            raise IngestionError(
                "POST_CUTOFF", "the completed GW1 decision was recorded after its deadline"
            )
        receipt_path = persist_prospective_receipt(receipt, artifact_root=prospective_artifact_root)
    summary = _build_summary(source, market, availability, events, projection, decision, receipt)
    return Gw1DecisionPipelineResult(
        market=market,
        availability=availability,
        events=events,
        projection=projection,
        decision=decision,
        prospective_receipt=receipt,
        prospective_receipt_path=receipt_path,
        summary=summary,
    )


__all__ = [
    "AvailabilityApprovalProvider",
    "EventApprovalProvider",
    "Gw1DecisionPipelineResult",
    "Gw1DecisionPipelineSummary",
    "run_gw1_decision_pipeline",
]
