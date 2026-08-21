"""Offline-first player-history evidence and Stage-9 allocation candidate."""

from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.history import parse_history_past
from dmf_pulse.player_evidence.profiles import build_allocation_candidate

__all__ = ["build_allocation_candidate", "compile_posterior_artifact", "parse_history_past"]
