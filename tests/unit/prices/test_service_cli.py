from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.latent_pressure import initial_latent_pressure
from dmf_pulse.prices.models import (
    EarlyTransferAction,
    PriceEvaluationRow,
    PriceEvent,
    PriceMass,
    PricePmf,
    PriceProbabilityVector,
    PriceTrainingExample,
    PriceUpdateWindow,
)
from dmf_pulse.prices.service import PriceService
from tests.prices_helpers import (
    BASE,
    ZERO,
    alternative,
    config,
    fitted_model,
    flow_context,
    observation,
    projection,
    selling_rule,
    spell,
    vector,
)

pytestmark = pytest.mark.unit


def _json(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def _write(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _examples() -> tuple[PriceTrainingExample, ...]:
    return tuple(
        PriceTrainingExample(
            example_id=f"cli-example-{index}",
            feature_vector=vector(
                f"cli-vector-{index}",
                at=BASE - timedelta(days=5 - index),
                sign=sign,
            ),
            event=event,
            label_available_at=BASE - timedelta(days=5 - index, hours=-1),
            dataset_mode=DatasetMode.RECONSTRUCTED,
        )
        for index, (sign, event) in enumerate(
            (
                (-1, PriceEvent.FALL),
                (0, PriceEvent.NO_CHANGE),
                (1, PriceEvent.RISE),
            )
        )
    )


def _payloads() -> dict[str, dict[str, object]]:
    observations = (
        observation("cli-0", hour=0, transfers_in_total=1000, transfers_out_total=500),
        observation("cli-1", hour=2, transfers_in_total=1300, transfers_out_total=550),
    )
    state = initial_latent_pressure(
        state_id="cli-state", player_id="player-1", as_of=BASE, config=config()
    )
    probability = PriceProbabilityVector(
        probability_fall=Decimal("0.2"),
        probability_no_change=Decimal("0.5"),
        probability_rise=Decimal("0.3"),
    )
    market = PricePmf(
        support=(
            PriceMass(price_units=75, probability=Decimal("0.6")),
            PriceMass(price_units=76, probability=Decimal("0.4")),
        )
    )
    alternatives = (
        alternative(EarlyTransferAction.ACT_NOW, "3"),
        alternative(EarlyTransferAction.WAIT_FOR_INFORMATION, "5"),
        alternative(EarlyTransferAction.DO_NOT_TRANSFER, "0"),
    )
    evaluation_row = PriceEvaluationRow(
        row_id="cli-row",
        forecast_origin=BASE,
        label_available_at=BASE + timedelta(hours=1),
        probabilities=probability,
        observed_event=PriceEvent.RISE,
        price_pmf=market,
        observed_price_units=76,
    )
    return {
        "build-update-cycles": {
            "player_id": "player-1",
            "dataset_mode": "RECONSTRUCTED",
            "observations": _json(observations),
            "windows": _json(
                (
                    PriceUpdateWindow(
                        cycle_id="cli-cycle",
                        cycle_start=BASE + timedelta(hours=1),
                        cycle_end=BASE + timedelta(hours=3),
                        information_cutoff=BASE + timedelta(hours=1),
                    ),
                )
            ),
        },
        "build-features": {
            "player_id": "player-1",
            "dataset_mode": "RECONSTRUCTED",
            "information_cutoff": (BASE + timedelta(hours=2)).isoformat(),
            "observations": _json(observations),
            "context": _json(flow_context()),
        },
        "train-baseline": {
            "training_cutoff": (BASE - timedelta(days=1)).isoformat(),
            "examples": _json(_examples()),
        },
        "predict-next": {
            "player_id": "player-1",
            "current_price_units": 75,
            "feature_vector": _json(vector("cli-predict")),
            "model": _json(fitted_model()),
            "pressure_state": _json(state),
            "source_observation_ids": ["cli-source"],
            "source_semantic_hashes": [ZERO],
            "ruleset_id": "synthetic-rules",
            "ruleset_hash": ZERO,
            "dataset_mode": "RECONSTRUCTED",
        },
        "simulate-path": {
            "current_price_units": 75,
            "pressure_state": _json(state),
            "baseline": _json(probability),
            "model_lineage": ["cli-p1", "cli-p2"],
        },
        "selling-value": {
            "ownership_spell": _json(spell()),
            "market_price_pmf": _json(market),
            "selling_price_rule": _json(selling_rule()),
        },
        "price-scenarios": {
            "player_id": "player-1",
            "horizon": "24h",
            "market_price_pmf": _json(market),
            "maximum_support": 2,
            "route_budget_units": 75,
        },
        "act-or-wait": {
            "alternatives": _json(alternatives),
            "projection": _json(projection()),
            "dataset_mode": "RECONSTRUCTED",
        },
        "evaluate": {
            "rows": _json((evaluation_row,)),
            "evaluation_cutoff": (BASE + timedelta(days=1)).isoformat(),
            "alert_probability": "0.5",
        },
    }


def test_service_methods_share_models_with_every_cli_command(tmp_path) -> None:
    service = PriceService()
    methods = {
        "build-update-cycles": service.build_update_cycles,
        "build-features": service.build_features,
        "train-baseline": service.train_baseline,
        "predict-next": service.predict,
        "simulate-path": service.simulate,
        "selling-value": service.selling_value,
        "price-scenarios": service.price_scenarios,
        "act-or-wait": service.act_or_wait,
        "evaluate": service.evaluate,
    }
    runner = CliRunner()
    for command, payload in _payloads().items():
        expected = methods[command](payload)
        path = _write(tmp_path, command, payload)
        arguments = ["prices", command, "--input", str(path)]
        if command == "train-baseline":
            arguments.extend(["--artifact-root", str(tmp_path / "artifacts")])
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, (command, result.stdout, result.exception)
        actual = json.loads(result.stdout)
        if command == "train-baseline":
            assert actual["artifact_sha256"]
            assert actual["semantic_sha256"] == expected.artifact_sha256
        else:
            assert actual == _json(expected)


def test_cli_output_format_and_missing_input_fail_deterministically(tmp_path) -> None:
    valid = CliRunner().invoke(app, ["prices", "validate", "--output", "text"])
    assert valid.exit_code == 2
    missing = CliRunner().invoke(
        app,
        ["prices", "simulate-path", "--input", str(tmp_path / "missing.json")],
    )
    assert missing.exit_code == 2
    assert json.loads(missing.stdout)["error"]["code"] == "PRICE_INPUT_INVALID"
    empty_path = _write(tmp_path, "empty", {})
    missing_field = CliRunner().invoke(
        app,
        ["prices", "simulate-path", "--input", str(empty_path)],
    )
    assert json.loads(missing_field.stdout)["error"]["code"] == "PRICE_EXECUTION_INVALID"
    invalid_path = _write(
        tmp_path,
        "invalid-contract",
        {
            "current_price_units": 75,
            "pressure_state": {},
            "baseline": {
                "probability_fall": "0.2",
                "probability_no_change": "0.5",
                "probability_rise": "0.3",
            },
            "model_lineage": ["bad"],
        },
    )
    invalid = CliRunner().invoke(
        app,
        ["prices", "simulate-path", "--input", str(invalid_path)],
    )
    assert json.loads(invalid.stdout)["error"]["code"] == "PRICE_INPUT_INVALID"
