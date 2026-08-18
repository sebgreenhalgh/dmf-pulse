from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from dmf_pulse.prices.configuration import PriceConfig, load_price_config
from dmf_pulse.prices.errors import PriceError
from tests.prices_helpers import config

pytestmark = pytest.mark.unit


def _payload():
    return config().model_dump(mode="json")


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda p: p["transfer_features"].update(short_half_life_hours="12"), "half-life"),
        (lambda p: p["transfer_features"].update(low_ownership_percent="25"), "thresholds"),
        (
            lambda p: p["transfer_features"].update(low_global_transfer_activity=3000000),
            "activity thresholds",
        ),
        (
            lambda p: p["transfer_features"]["status_uncertainty"].update(AVAILABLE="2"),
            "status uncertainty",
        ),
        (
            lambda p: p["transfer_features"]["chip_uncertainty"].pop("UNKNOWN"),
            "chip uncertainty",
        ),
        (
            lambda p: p["transfer_features"]["status_uncertainty"].pop("UNKNOWN"),
            "every price status",
        ),
        (
            lambda p: p["competing_logit"].update(feature_names=["z", "a"]),
            "sorted, unique",
        ),
        (
            lambda p: p["competing_logit"]["feature_scales"].pop("acceleration"),
            "positively cover",
        ),
        (lambda p: p["price_paths"].update(minimum_price_units=200), "bounds"),
        (lambda p: p["price_paths"].update(updates_24h=4), "horizons"),
        (lambda p: p["price_paths"].update(maximum_exact_scenarios=10), "scenario cap"),
        (
            lambda p: p["activation"]["production_statuses"].append("PRODUCTION_ELIGIBLE"),
            "production eligible",
        ),
        (
            lambda p: p["activation"].update(
                production_statuses=["TARGET_SEASON_UNCALIBRATED", "RIGHTS_BLOCKED"]
            ),
            "sorted and unique",
        ),
        (
            lambda p: p["early_transfer"].update(
                actionable_dataset_modes=["RECONSTRUCTED", "COUNTERFACTUAL"]
            ),
            "sorted and unique",
        ),
        (
            lambda p: p["early_transfer"].update(actionable_dataset_modes=["LIVE_OBSERVED"]),
            "cannot action LIVE_OBSERVED",
        ),
        (lambda p: p.update(benchmark_ids=["P0_NO_CHANGE"]), "mandatory"),
        (lambda p: p["benchmark_ids"].reverse(), "sorted and unique"),
    ),
)
def test_configuration_invariants_fail_closed(mutate, message: str) -> None:
    payload = deepcopy(_payload())
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        PriceConfig.model_validate(payload)


def test_configuration_loader_wraps_invalid_yaml_as_typed_failure(tmp_path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("anchor: &blocked 1\ncopy: *blocked\n", encoding="utf-8")
    with pytest.raises(PriceError, match="configuration is unavailable") as captured:
        load_price_config(path)
    assert captured.value.code == "PRICE_CONFIGURATION_INVALID"
