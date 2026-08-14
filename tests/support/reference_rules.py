"""Load the accepted test-only rules artifact through the production adapter."""

from __future__ import annotations

from pathlib import Path

from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter


def load_reference_rules(path: Path) -> AcceptedRulesAdapter:
    """Exercise the canonical compiled-rules loader used by the public CLI."""

    return AcceptedRulesAdapter.from_paths(path)


__all__ = ["load_reference_rules"]
