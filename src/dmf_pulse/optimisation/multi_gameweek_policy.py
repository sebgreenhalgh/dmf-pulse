"""Load the deterministic Stage-11 bounded-search policy."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from dmf_pulse.optimisation.multi_gameweek_errors import InputInvalidError
from dmf_pulse.optimisation.multi_gameweek_models import (
    SearchPolicy,
    TerminalValuePolicy,
    seal_search_policy,
    seal_terminal_policy,
)
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.yaml_loader import load_rules_yaml_bytes


def _load_policy_mapping(path: Path | None, resource_name: str) -> dict[str, object]:
    raw = (
        path.read_bytes()
        if path is not None
        else files("dmf_pulse.optimisation.resources").joinpath(resource_name).read_bytes()
    )
    return load_rules_yaml_bytes(raw)


def load_multi_gameweek_search_policy(path: Path | None = None) -> SearchPolicy:
    """Load strict YAML, inject its semantic hash, and return a frozen policy."""

    try:
        raw = _load_policy_mapping(path, "multi_gameweek.yaml")
        required_v2 = {
            "max_cumulative_legal_actions",
            "max_generated_policy_candidates",
            "max_retained_pareto_candidates",
        }
        missing = sorted(required_v2 - raw.keys())
        if missing:
            raise ValueError(
                "current policy requires distinct v2 physical-work governance: "
                + ", ".join(missing)
            )
        if raw.get("schema_version") != "multi-gameweek-search-policy-v2":
            raise ValueError("current policy must use multi-gameweek-search-policy-v2")
        if "max_policy_candidates" in raw:
            raise ValueError("current v2 policy must not retain overloaded max_policy_candidates")
        raw["policy_sha256"] = "0" * 64
        return seal_search_policy(SearchPolicy.model_validate(raw))
    except (OSError, RulesValidationError, ValidationError, ValueError) as exc:
        raise InputInvalidError(f"invalid multi-Gameweek search policy: {exc}") from exc


def load_terminal_value_policy(path: Path | None = None) -> TerminalValuePolicy:
    """Load the authorised transparent terminal baseline from strict YAML."""

    try:
        raw = _load_policy_mapping(path, "multi_gameweek_terminal.yaml")
        raw["policy_sha256"] = "0" * 64
        return seal_terminal_policy(TerminalValuePolicy.model_validate(raw))
    except (OSError, RulesValidationError, ValidationError, ValueError) as exc:
        raise InputInvalidError(f"invalid terminal-value policy: {exc}") from exc
