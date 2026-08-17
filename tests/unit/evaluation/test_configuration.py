from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.configuration import EvaluationConfig, load_evaluation_config
from dmf_pulse.evaluation.models import DatasetMode, FoldWindow, ProbabilityBoundaryPolicy

pytestmark = pytest.mark.unit


def test_default_evaluation_config_and_schema_are_validated() -> None:
    value = load_evaluation_config(Path("config/evaluation/default.yaml"))
    assert value.dataset_mode is DatasetMode.COUNTERFACTUAL
    assert value.walk_forward.window is FoldWindow.EXPANDING
    assert value.probability_scoring.boundary_policy is ProbabilityBoundaryPolicy.EXACT
    assert value.policy_replay.execute_root_action_only
    compiled = value.walk_forward.compile(dataset_mode=value.dataset_mode)
    assert compiled.dataset_mode is DatasetMode.COUNTERFACTUAL
    assert compiled.minimum_training_origins == 1

    stored = json.loads(
        Path("config/evaluation/evaluation.schema.json").read_text(encoding="utf-8")
    )
    assert stored == EvaluationConfig.model_json_schema()
    assert (
        Path("config/evaluation/default.yaml").read_bytes()
        == Path("src/dmf_pulse/evaluation/resources/default.yaml").read_bytes()
    )


def test_configuration_blocks_implicit_probability_clipping_and_duplicate_benchmarks() -> None:
    value = load_evaluation_config(Path("config/evaluation/default.yaml"))
    payload = value.model_dump(mode="python")
    probability = dict(payload["probability_scoring"])
    probability["declared_epsilon"] = Decimal("0.01")
    payload["probability_scoring"] = probability
    with pytest.raises(ValidationError, match="cannot declare epsilon"):
        EvaluationConfig.model_validate(payload)

    payload = value.model_dump(mode="python")
    payload["benchmark_ids"] = (
        "B0A_RECENT_POINTS_LAST_3",
        "B0A_RECENT_POINTS_LAST_3",
    )
    with pytest.raises(ValidationError, match="unique"):
        EvaluationConfig.model_validate(payload)

    payload = value.model_dump(mode="python")
    payload["benchmark_ids"] = ("NOT_A_BENCHMARK",)
    with pytest.raises(ValidationError, match="canonical"):
        EvaluationConfig.model_validate(payload)


def test_configuration_yaml_rejects_duplicates_aliases_and_binary_floats(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        Path("config/evaluation/default.yaml").read_text(encoding="utf-8")
        + "dataset_mode: RECONSTRUCTED\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid YAML"):
        load_evaluation_config(duplicate)

    alias = tmp_path / "alias.yaml"
    alias.write_text("value: &shared x\nother: *shared\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_evaluation_config(alias)

    floating = tmp_path / "float.yaml"
    floating.write_text("value: 0.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_evaluation_config(floating)
