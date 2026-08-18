"""Stable model and external predictor benchmark identities."""

from __future__ import annotations

from dmf_pulse.prices.configuration import PriceConfig
from dmf_pulse.prices.models import ChallengerStatus


def configured_benchmark_ids(config: PriceConfig) -> tuple[str, ...]:
    return config.benchmark_ids


def gbdt_challenger_status(config: PriceConfig) -> ChallengerStatus:
    return ChallengerStatus(config.activation.challenger_status)
