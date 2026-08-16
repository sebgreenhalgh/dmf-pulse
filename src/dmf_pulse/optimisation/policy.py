"""Load the packaged immutable optimiser policy."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from dmf_pulse.optimisation.models import OneGameweekOptimiserPolicy


def load_policy(path: Path | None = None) -> OneGameweekOptimiserPolicy:
    selected = path or Path(__file__).resolve().parent / "resources" / "one_gameweek.yaml"
    value = yaml.safe_load(selected.read_text(encoding="utf-8"))
    return OneGameweekOptimiserPolicy.model_validate(value)
