from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.football_events.minutes_context import (
    Stage7MinutesContext,
    TeamMinutesProjectionIdentity,
    validate_stage7_context,
)
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionService,
    load_score_distribution_request,
)

pytestmark = pytest.mark.unit
FIXTURE = Path("fixtures/events/score/GCS-008/balanced_fixture.json")


def _payload() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_stage7_identity_adapter_extracts_only_frozen_public_lineage() -> None:
    payload = _payload()
    raw_context = payload["minutes_context"]
    assert isinstance(raw_context, dict)
    home = raw_context["home"]
    away = raw_context["away"]
    identity = TeamMinutesProjectionIdentity.from_projection(home)
    context = Stage7MinutesContext.from_projections(home, away)
    assert identity.schema_version == "team-minutes-projection-v1"
    assert context.home == identity
    assert context.source_as_of == datetime(2026, 8, 20, 11, 50, tzinfo=UTC)
    assert len(context.semantic_sha256) == 64
    assert set(identity.public_dict()) == {
        "as_of",
        "dataset_sha256",
        "fixture_id",
        "model_artifact_sha256",
        "model_family",
        "result_sha256",
        "sample_count",
        "scenario_set_sha256",
        "schema_version",
        "team_id",
    }


def test_stage7_context_rejects_fixture_team_and_cutoff_leakage() -> None:
    request = load_score_distribution_request(FIXTURE)
    with pytest.raises(ValueError, match="fixture_id"):
        validate_stage7_context(
            request.minutes_context,
            fixture_id=UUID("10000000-0000-7000-8000-000000000999"),
            home_team_id=request.home_team_id,
            away_team_id=request.away_team_id,
            information_cutoff=request.as_of,
        )
    with pytest.raises(ValueError, match="home team_id"):
        validate_stage7_context(
            request.minutes_context,
            fixture_id=request.fixture_id,
            home_team_id=UUID("20000000-0000-7000-8000-000000000099"),
            away_team_id=request.away_team_id,
            information_cutoff=request.as_of,
        )

    payload = _payload()
    context = payload["minutes_context"]
    assert isinstance(context, dict)
    for side in ("home", "away"):
        identity = context[side]
        assert isinstance(identity, dict)
        identity["as_of"] = "2026-08-20T12:00:01Z"
    with pytest.raises(ValidationError, match="POST_CUTOFF_MINUTES"):
        ScoreDistributionRequest.model_validate_json(json.dumps(payload))


def test_stage7_identity_mutation_changes_stage8_semantic_identity() -> None:
    original_request = load_score_distribution_request(FIXTURE)
    original = ScoreDistributionService().project(original_request)
    assert original.distribution is not None

    payload = _payload()
    context = payload["minutes_context"]
    assert isinstance(context, dict)
    home = context["home"]
    assert isinstance(home, dict)
    home["result_sha256"] = "f" * 64
    mutated_request = ScoreDistributionRequest.model_validate_json(json.dumps(payload))
    mutated = ScoreDistributionService().project(mutated_request)
    assert mutated.distribution is not None

    assert mutated.input_signature_sha256 != original.input_signature_sha256
    assert (
        mutated.distribution.source_home_minutes_sha256
        != original.distribution.source_home_minutes_sha256
    )
    assert mutated.distribution.result_sha256 != original.distribution.result_sha256


def test_stage7_context_pair_rejects_inconsistent_source_cutoffs() -> None:
    payload = _payload()
    context = payload["minutes_context"]
    assert isinstance(context, dict)
    away = context["away"]
    assert isinstance(away, dict)
    away["as_of"] = "2026-08-20T11:49:59Z"
    with pytest.raises(ValidationError, match="share one as_of"):
        Stage7MinutesContext.model_validate(context)
