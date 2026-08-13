"""Contract between repository fixture authority and packaged Stage-7 mirrors."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.availability.resources import (
    AVAILABILITY_RESOURCE_NAMES,
    availability_resource_bytes,
    availability_resource_json,
)

pytestmark = pytest.mark.contract


def test_packaged_availability_resources_are_complete_and_byte_synchronized(
    repository_root: Path,
) -> None:
    expected = {
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
    }
    assert set(AVAILABILITY_RESOURCE_NAMES) == expected
    for relative in AVAILABILITY_RESOURCE_NAMES:
        fixture = repository_root / "fixtures" / "availability" / relative
        assert availability_resource_bytes(relative) == fixture.read_bytes()
        assert availability_resource_json(relative)


def test_packaged_availability_resource_loader_rejects_unknown_paths() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        availability_resource_bytes("../../pyproject.toml")
