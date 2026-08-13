"""Wheel-contained synthetic TEST/REPLAY resources for Stage 7."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Final

RESOURCE_PACKAGE: Final = "dmf_pulse.availability.resources"
AVAILABILITY_RESOURCE_NAMES: Final[tuple[str, ...]] = (
    "MIN-007/canonical_history.json",
    "MIN-007/external_mapping_plan.json",
    "MIN-007/training_dataset.json",
    "MIN-007G/evaluation_dataset.json",
    "MIN-007G/minutes_baseline_policy.json",
    "MIN-007G/contexts/goalkeeper.json",
    "MIN-007G/contexts/hard_ineligible.json",
    "MIN-007G/contexts/high_rotation.json",
    "MIN-007G/contexts/insufficient_eligible_squad.json",
    "MIN-007G/contexts/new_manager.json",
    "MIN-007G/contexts/new_signing.json",
    "MIN-007G/contexts/promoted_team.json",
    "MIN-007G/contexts/rare_bench_60_plus.json",
    "MIN-007G/contexts/stable_xi.json",
)
_RESOURCE_ALLOWLIST: Final = frozenset(AVAILABILITY_RESOURCE_NAMES)


def availability_resource_bytes(name: str) -> bytes:
    """Read one allowlisted resource without relying on a repository checkout."""

    if name not in _RESOURCE_ALLOWLIST:
        raise ValueError("availability resource is not allowlisted")
    return files(RESOURCE_PACKAGE).joinpath(*name.split("/")).read_bytes()


def availability_resource_json(name: str) -> dict[str, Any]:
    """Decode one allowlisted resource as a JSON object."""

    try:
        value: Any = json.loads(availability_resource_bytes(name))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("availability resource is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("availability resource must contain a JSON object")
    return value


__all__ = [
    "AVAILABILITY_RESOURCE_NAMES",
    "availability_resource_bytes",
    "availability_resource_json",
]
