"""One typed FPL capture, reused by controlled and paid diagnostic computation.

No transport or authority is created here. The coordinator retains source objects
in memory and calls the existing accepted numerical implementation unchanged.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.fpl_points.models import MonteCarloPolicy, ProjectionMode
from dmf_pulse.fpl_points.player_prior import (
    build_automatic_current_gw_stale_prior_policy,
    load_packaged_player_prior,
)
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateBundle,
    CurrentManagerStateService,
)
from dmf_pulse.ingestion.odds.automatic_mapping import build_automatic_current_identity_map
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorResult
from dmf_pulse.markets.current import (
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
    build_transient_current_market_identity_view,
)
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1 import one_command as accepted
from dmf_pulse.private_v1.automatic_inputs import (
    build_automatic_model_minutes,
    build_automatic_ownership,
    build_automatic_player_identity_map,
    build_full_candidate_policy,
)
from dmf_pulse.private_v1.models import PrivateV1ExecutionInput, seal_execution_input
from dmf_pulse.private_v1.progress import NullProgress, ProgressSink
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    PrivateV1RunResult,
    load_packaged_event_allocation_config,
)
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.private_transient import PrivateTransientRulesAuthority


@dataclass(frozen=True, slots=True, repr=False)
class PreparedDiagnosticFpl:
    snapshot: DirectFplSnapshot
    manager: CurrentManagerStateBundle
    ruleset: CompiledRuleset
    capability: CapabilityArtifact
    rules_authority: PrivateTransientRulesAuthority

    @property
    def validation_sha256(self) -> str:
        return canonical_sha256(
            {
                "full_typed_snapshot": self.snapshot.model_dump(mode="json"),
                "manager": self.manager.semantic_sha256,
                "rules": self.ruleset.ruleset_hash,
                "capability": self.capability.capability_hash,
            }
        )


def prepare_diagnostic_fpl(
    snapshot: DirectFplSnapshot, *, approved_at: datetime, observed_at: datetime
) -> PreparedDiagnosticFpl:
    """Validate the already acquired manager under the original rules authority."""
    ruleset, capability, authority = accepted._rules_authority(approved_at)
    manager = CurrentManagerStateService(clock=lambda: observed_at).compile_provider_snapshot(
        snapshot.current_team,
        fpl_input=snapshot.fpl_input,
        ruleset=ruleset,
        capability=capability,
        observed_at=observed_at,
        overall_points=snapshot.entry.summary_overall_points,
        overall_rank=snapshot.entry.summary_overall_rank,
        private_rules_authority=authority,
    )
    return PreparedDiagnosticFpl(snapshot, manager, ruleset, capability, authority)


def inherited_monte_carlo_policy() -> MonteCarloPolicy:
    """Read the existing literal configuration; neither copy nor tune its values.

    The installed caller authenticates this protected module before entry. Only
    the one literal constructor in the accepted one-GW orchestration is data.
    """
    module = ast.parse(Path(accepted.__file__).read_text(encoding="utf-8"))
    classes = [
        item
        for item in module.body
        if isinstance(item, ast.ClassDef) and item.name == "PrivateV1OneCommandService"
    ]
    methods = (
        [
            item
            for item in classes[0].body
            if isinstance(item, ast.FunctionDef) and item.name == "run"
        ]
        if len(classes) == 1
        else []
    )
    assignments = (
        [
            item
            for item in ast.walk(methods[0])
            if isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "mc_policy" for target in item.targets
            )
        ]
        if len(methods) == 1
        else []
    )
    if len(assignments) != 1:
        raise OperationError("DIAGNOSTIC_ACCEPTED_CONFIGURATION_UNRESOLVED")
    value = assignments[0].value
    if (
        not isinstance(value, ast.Call)
        or not isinstance(value.func, ast.Name)
        or value.func.id != "MonteCarloPolicy"
        or value.args
        or any(item.arg is None for item in value.keywords)
    ):
        raise OperationError("DIAGNOSTIC_ACCEPTED_CONFIGURATION_UNRESOLVED")
    fields = {item.arg: ast.literal_eval(item.value) for item in value.keywords}
    if len(fields) != len(value.keywords):
        raise OperationError("DIAGNOSTIC_ACCEPTED_CONFIGURATION_UNRESOLVED")
    return MonteCarloPolicy.model_validate(fields)


def assemble_diagnostic_execution(
    prepared: PreparedDiagnosticFpl,
    odds: OddsProviderCurrentInput,
    prior: CurrentScorePriorResult,
    request: accepted.OneCommandRequest,
    *,
    resolved_at: datetime,
    progress: ProgressSink | None = None,
) -> PrivateV1ExecutionInput:
    """Existing one-GW assembly calls on one retained typed snapshot; no GETs."""
    if request.horizon_gameweeks != 1:
        raise OperationError("DIAGNOSTIC_ONE_GAMEWEEK_REQUIRED")
    snapshot = prepared.snapshot
    if snapshot.fpl_input.provenance.information_cutoff != request.run_at:
        raise OperationError("DIAGNOSTIC_SNAPSHOT_CUTOFF_MISMATCH")
    active_progress = progress or NullProgress()
    bridge = build_automatic_current_identity_map(
        snapshot.fpl_input, odds, decided_at=resolved_at, event_scope="FULL_RESPONSE"
    )
    unified = bind_current_unified_state_request(
        snapshot.fpl_input, odds, bridge, prepared.manager, prepared.ruleset, prepared.capability
    )
    current = CurrentUnifiedStateService().compose(
        unified,
        fpl_input=snapshot.fpl_input,
        odds_input=odds,
        identity_map=bridge,
        manager_state=prepared.manager,
        ruleset=prepared.ruleset,
        capability=prepared.capability,
        private_rules_authority=prepared.rules_authority,
    )
    market_view = build_transient_current_market_identity_view(current, resolved_at=resolved_at)
    markets = CurrentMarketConstraintService().build(
        bind_current_market_constraint_request(current, market_view),
        source=current,
        identity_view=market_view,
    )
    player_map = build_automatic_player_identity_map(snapshot, prepared.manager)
    minutes = build_automatic_model_minutes(
        snapshot, player_map, market_view, progress=active_progress
    )
    ownership = build_automatic_ownership(snapshot, prepared.manager)
    candidates = build_full_candidate_policy(snapshot, prepared.manager, prepared.ruleset)
    score_priors = accepted._score_priors(
        prior, snapshot=snapshot, market_view=market_view, identity_map=player_map
    )
    player_prior = load_packaged_player_prior()
    carry_forward = (
        None
        if snapshot.target_gameweek == 1
        else build_automatic_current_gw_stale_prior_policy(
            player_prior,
            snapshot.fpl_input,
            current_official_fpl_element_ids=tuple(
                item.official_fpl_element_id for item in player_map.players
            ),
            declared_at=request.run_at,
        )
    )
    mc_policy = inherited_monte_carlo_policy()
    allocation = load_packaged_event_allocation_config()
    return seal_execution_input(
        PrivateV1ExecutionInput.model_construct(
            run_id=request.run_id,
            code_sha=request.code_sha,
            projection_mode=ProjectionMode.REPLAY,
            retention_class="PRIVATE_TRANSIENT_NO_RETENTION",
            synthetic_source_attestation=None,
            current_state=current,
            player_identity_map=player_map,
            market_identity_view=market_view,
            market_constraints=markets,
            score_priors=score_priors,
            manual_minutes=minutes,
            ownership=ownership,
            candidate_action_policy=candidates,
            ruleset=prepared.ruleset,
            full_season_capability=prepared.capability,
            private_rules_authority=prepared.rules_authority,
            player_prior_carry_forward_policy=carry_forward,
            current_penalty_hierarchy=snapshot.current_penalty_hierarchy,
            entry_quality=snapshot.entry_quality,
            root_seed=request.root_seed,
            scenario_count=request.scenario_count,
            stage9_monte_carlo_policy=mc_policy,
            stage9_monte_carlo_policy_sha256=canonical_sha256(mc_policy.model_dump(mode="json")),
            event_allocation_config=allocation,
            event_allocation_config_sha256=canonical_sha256(allocation.model_dump(mode="json")),
            expected_stage8_policy_sha256=load_score_baseline_policy().sha256,
            expected_player_prior_artifact_sha256=player_prior.artifact.artifact_sha256,
            expected_player_prior_acceptance_sha256=player_prior.historical_acceptance.acceptance_sha256,
            require_stage9_mc_pass=True,
            semantic_sha256="0" * 64,
        )
    )


@dataclass(frozen=True, slots=True, repr=False)
class DiagnosticKernelResult:
    classification: Literal["CONTROLLED_MARKET_ENGINEERING", "REAL_MARKET_KERNEL_NOT_PUBLICATION"]
    execution: PrivateV1ExecutionInput
    result: PrivateV1RunResult

    def controlled_proof(self) -> dict[str, Any]:
        if self.classification != "CONTROLLED_MARKET_ENGINEERING":
            raise OperationError("DIAGNOSTIC_CONTROLLED_PROOF_REQUIRED")
        return {
            "classification": "REAL_FPL_CONTROLLED_MARKET_ENGINEERING",
            "fpl_input_sha256": self.execution.current_state.fpl_input.semantic_sha256,
            "execution_input_sha256": self.execution.semantic_sha256,
            "decision_sha256": self.result.decision.semantic_sha256,
            "stage8_stage9_stage12_passed": True,
            "real_recommendation_publication": False,
            "paid_provider_gets_in_controlled_computation": 0,
        }


def run_diagnostic_kernel(
    execution: PrivateV1ExecutionInput,
    *,
    controlled: bool,
    progress: ProgressSink | None = None,
) -> DiagnosticKernelResult:
    transport = execution.current_state.odds_input.provenance.transport_id
    if (controlled and transport != "injected") or (not controlled and transport == "injected"):
        raise OperationError("DIAGNOSTIC_MARKET_PROVENANCE_CLASS_MISMATCH")
    result = PrivateV1RecommendationService().run(execution, progress=progress)
    return DiagnosticKernelResult(
        "CONTROLLED_MARKET_ENGINEERING" if controlled else "REAL_MARKET_KERNEL_NOT_PUBLICATION",
        execution,
        result,
    )
