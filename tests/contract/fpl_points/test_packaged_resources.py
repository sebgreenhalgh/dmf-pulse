from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def test_stage9_model_configs_are_wheel_packaged_and_byte_synchronized(
    repository_root: Path,
) -> None:
    resources = files("dmf_pulse.fpl_points").joinpath("resources")
    for name in (
        "event_allocation_baseline.yaml",
        "fpl_points_simulation.yaml",
        "gw1_private_player_allocation_acceptance_v1.json",
        "gw1_private_player_allocation_prior_v1.json",
    ):
        packaged = resources.joinpath(name).read_bytes()
        tracked = (repository_root / "config/models" / name).read_bytes()
        assert packaged == tracked
        assert packaged
