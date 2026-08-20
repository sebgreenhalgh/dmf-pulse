"""Scientific backtesting, calibration and benchmark framework."""

from dmf_pulse.evaluation.decision_regret import calculate_decision_regret
from dmf_pulse.evaluation.folds import build_walk_forward_folds
from dmf_pulse.evaluation.information_sets import build_information_set
from dmf_pulse.evaluation.point_metrics import score_forecast
from dmf_pulse.evaluation.policy_replay import replay_policy
from dmf_pulse.evaluation.prospective import (
    ProspectiveDecisionReceipt,
    build_prospective_receipt,
    persist_prospective_receipt,
)

__all__ = [
    "ProspectiveDecisionReceipt",
    "build_information_set",
    "build_prospective_receipt",
    "build_walk_forward_folds",
    "calculate_decision_regret",
    "persist_prospective_receipt",
    "replay_policy",
    "score_forecast",
]
