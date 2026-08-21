"""Offline-first player-history evidence and Stage-9 allocation candidate."""

from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.history import parse_history_past
from dmf_pulse.player_evidence.profiles import build_allocation_candidate
from dmf_pulse.player_evidence.role_priors import (
    RolePriorCandidateArtifact,
    candidate_eb_parameters_from_role_prior,
    load_role_prior_candidate,
    role_priors_from_candidate,
)

__all__ = [
    "RolePriorCandidateArtifact",
    "build_allocation_candidate",
    "candidate_eb_parameters_from_role_prior",
    "compile_posterior_artifact",
    "load_role_prior_candidate",
    "parse_history_past",
    "role_priors_from_candidate",
]
