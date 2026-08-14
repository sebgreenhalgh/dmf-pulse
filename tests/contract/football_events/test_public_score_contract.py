import json
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.football_events.score_distribution import JointScoreDistribution
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionResult,
    ScoreDistributionService,
    load_score_distribution_request,
)

pytestmark = pytest.mark.contract
FIXTURE = Path("fixtures/events/score/GCS-008/stage6_consensus_fixture.json")


def _walk(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    else:
        yield value


def test_public_request_and_output_schemas_are_versioned_and_closed() -> None:
    request_schema = ScoreDistributionRequest.model_json_schema()
    output_schema = JointScoreDistribution.model_json_schema()
    assert request_schema["additionalProperties"] is False
    assert output_schema["additionalProperties"] is False
    assert request_schema["properties"]["schema_version"]["const"] == (
        "score-distribution-request-v1"
    )
    market_contracts = request_schema["properties"]["market_consensus"]["anyOf"]
    assert {item.get("$ref") for item in market_contracts if "$ref" in item} == {
        "#/$defs/MarketConsensus",
        "#/$defs/MarketNormalisationResult",
    }
    assert output_schema["properties"]["schema_version"]["const"] == ("joint-score-distribution-v1")


def test_stage6_fixture_is_accepted_by_the_frozen_stage6_contract() -> None:
    from dmf_pulse.markets.models import MarketConsensus

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["market_consensus"]
    consensus = MarketConsensus.model_validate_json(json.dumps(payload, sort_keys=True))
    assert str(consensus.fixture_id) == "10000000-0000-7000-8000-000000000808"
    assert consensus.eligible_operator_count == 1
    assert consensus.result_sha256 == "c" * 64


def test_stage6_to_stage8_contract_emits_no_binary_float() -> None:
    result = ScoreDistributionService().project(load_score_distribution_request(FIXTURE))
    assert result.distribution is not None
    payload = result.distribution.model_dump(mode="json")
    assert not any(isinstance(item, float) for item in _walk(payload))
    json.dumps(payload, allow_nan=False)
    assert result.distribution.source_market_sha256 == "c" * 64
    assert result.distribution.source_minutes_context.semantic_sha256 == (
        result.distribution.source_minutes_context_sha256
    )


def test_packaged_json_schemas_match_runtime_models() -> None:
    from importlib.resources import files

    resources = files("dmf_pulse.football_events.resources")
    expected = {
        "score_distribution_request.schema.json": ScoreDistributionRequest.model_json_schema(),
        "joint_score_distribution.schema.json": JointScoreDistribution.model_json_schema(),
        "score_distribution_result.schema.json": ScoreDistributionResult.model_json_schema(),
    }
    repository_contracts = Path("public_contracts")
    for name, schema in expected.items():
        packaged = json.loads(resources.joinpath(name).read_text(encoding="utf-8"))
        repository = json.loads((repository_contracts / name).read_text(encoding="utf-8"))
        assert packaged == schema
        assert repository == schema
