from __future__ import annotations

import inspect
from importlib import resources

import pytest
import yaml

import dmf_pulse.evaluation as evaluation
from dmf_pulse.evaluation.benchmarks import benchmark_suite
from dmf_pulse.evaluation.models import BenchmarkFamily, DatasetMode

pytestmark = pytest.mark.contract


def test_required_public_interfaces_are_exported() -> None:
    expected = {
        "build_walk_forward_folds",
        "build_information_set",
        "score_forecast",
        "replay_policy",
        "calculate_decision_regret",
    }
    assert set(evaluation.__all__) == expected
    assert all(callable(getattr(evaluation, name)) for name in expected)
    assert "records" in inspect.signature(evaluation.build_information_set).parameters


def test_authoritative_dataset_modes_are_exact() -> None:
    assert tuple(item.value for item in DatasetMode) == (
        "LIVE_OBSERVED",
        "RAW_OBSERVED",
        "RECONSTRUCTED",
        "FINAL_OUTCOME",
        "COUNTERFACTUAL",
    )


def test_benchmark_contract_covers_b0_to_b5_without_near_duplicate_family() -> None:
    suite = benchmark_suite()
    assert {item.family for item in suite} == set(BenchmarkFamily)
    assert len({item.benchmark_id for item in suite}) == len(suite)
    assert all(item.oracle == (item.family is BenchmarkFamily.B5) for item in suite)


def test_default_evaluation_config_is_packaged_and_root_action_only() -> None:
    text = resources.files("dmf_pulse.evaluation.resources").joinpath("default.yaml").read_text()
    payload = yaml.safe_load(text)
    assert payload["policy_replay"]["execute_root_action_only"] is True
    assert payload["probability_scoring"]["boundary_policy"] == "EXACT"
    assert len(payload["benchmark_ids"]) == len(benchmark_suite())
