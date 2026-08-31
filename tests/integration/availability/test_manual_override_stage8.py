from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.availability.manual_override import build_manual_minutes_override
from dmf_pulse.football_events.minutes_context import Stage7MinutesContext
from dmf_pulse.football_events.service import ScoreDistributionRequest, ScoreDistributionService
from tests.unit.availability.manual_override_test_support import valid_manual_input

pytestmark = pytest.mark.integration


def test_manual_stage7_context_is_accepted_by_score_distribution_service(
    repository_root: Path,
) -> None:
    bundle = build_manual_minutes_override(valid_manual_input())
    context = Stage7MinutesContext.from_projections(bundle.home, bundle.away)
    payload = json.loads(
        (repository_root / "fixtures/events/score/GCS-008/balanced_fixture.json").read_text(
            encoding="utf-8"
        )
    )
    payload["minutes_context"] = context.public_dict()
    request = ScoreDistributionRequest.model_validate_json(json.dumps(payload))
    result = ScoreDistributionService().project(request)
    assert result.status == "PROJECTED"
    assert result.distribution is not None
    assert result.distribution.source_minutes_context.home.model_family == (
        "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1"
    )
    assert result.distribution.source_home_minutes_sha256 == bundle.home.result_sha256
    assert result.distribution.source_away_minutes_sha256 == bundle.away.result_sha256
