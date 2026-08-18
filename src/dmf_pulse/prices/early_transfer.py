"""Complete ACT-versus-WAIT utility comparison without price chasing."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256, verify_sealed
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.artifacts import seal_early_transfer_decision
from dmf_pulse.prices.configuration import PriceConfig, price_config_sha256
from dmf_pulse.prices.models import (
    EarlyTransferAction,
    EarlyTransferAlternative,
    EarlyTransferDecision,
    PriceProjection,
)


def evaluate_act_now_vs_wait(
    alternatives: tuple[EarlyTransferAlternative, ...],
    *,
    projection: PriceProjection,
    dataset_mode: DatasetMode,
    config: PriceConfig,
) -> EarlyTransferDecision:
    """Select by complete utility; P(rise) is lineage context, never a decision rule."""

    verify_sealed(projection, "projection_sha256")
    if dataset_mode is not projection.lineage.dataset_mode:
        raise ValueError("ACT/WAIT dataset mode differs from its sealed price projection")
    if projection.lineage.configuration_sha256 != price_config_sha256(config):
        raise ValueError("ACT/WAIT price projection differs from the active configuration")
    if projection.activation_statuses != config.activation.production_statuses:
        raise ValueError("ACT/WAIT projection activation status differs from active policy")
    if not alternatives:
        raise ValueError("ACT/WAIT evaluation requires alternatives")
    keys = tuple((item.action, item.route_id) for item in alternatives)
    if len(keys) != len(set(keys)):
        raise ValueError("ACT/WAIT alternatives must be unique")
    required = {
        EarlyTransferAction.ACT_NOW,
        EarlyTransferAction.WAIT_FOR_INFORMATION,
        EarlyTransferAction.DO_NOT_TRANSFER,
    }
    if not required <= {item.action for item in alternatives}:
        raise ValueError("ACT, WAIT and DO_NOT_TRANSFER alternatives are mandatory")
    ranked = tuple(
        sorted(
            alternatives,
            key=lambda item: (-item.components.net_utility, item.action.value, item.route_id),
        )
    )
    selected = ranked[0]
    actionable = dataset_mode in set(config.early_transfer.actionable_dataset_modes)
    if actionable:
        recommendation: EarlyTransferAction = selected.action
        selected_route_id = selected.route_id
        rationale = (
            "COMPLETE_UTILITY_MAXIMUM",
            "PRICE_PROBABILITY_COMPONENT_ONLY",
        )
    else:
        recommendation = EarlyTransferAction.MANUAL_REVIEW
        selected_route_id = None
        rationale = (
            "ACTIVATION_FAIL_CLOSED",
            "TARGET_SEASON_UNCALIBRATED_OR_RIGHTS_BLOCKED",
        )
    decision_identity = semantic_sha256(
        {
            "projection_sha256": projection.projection_sha256,
            "dataset_mode": dataset_mode.value,
            "alternatives": [item.model_dump(mode="json") for item in alternatives],
        }
    )
    value = EarlyTransferDecision(
        decision_id=f"early-transfer-{decision_identity[:24]}",
        recommended_action=recommendation,
        selected_route_id=selected_route_id,
        actionable=actionable,
        expected_utility=ranked[0].components.net_utility,
        second_best_utility=ranked[1].components.net_utility,
        utility_gap=ranked[0].components.net_utility - ranked[1].components.net_utility,
        alternatives=tuple(
            sorted(alternatives, key=lambda item: (item.action.value, item.route_id))
        ),
        activation_statuses=projection.activation_statuses,
        dataset_mode=dataset_mode,
        information_cutoff=projection.lineage.information_cutoff,
        rationale_codes=rationale,
        decision_sha256="0" * 64,
    )
    return seal_early_transfer_decision(value)
