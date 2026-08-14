import json
from pathlib import Path

import pytest

from dmf_pulse.football_events.service import (
    ScoreDistributionService,
    load_score_distribution_request,
)

pytestmark = pytest.mark.golden
ROOT = Path("fixtures/events/score/GCS-008")


def test_balanced_fixture_matches_reviewed_golden_output() -> None:
    request = load_score_distribution_request(ROOT / "balanced_fixture.json")
    result = ScoreDistributionService().project(request)
    assert result.distribution is not None
    expected = json.loads((ROOT / "balanced_fixture.expected.json").read_text(encoding="utf-8"))
    assert result.distribution.model_dump(mode="json") == expected
    assert result.distribution.result_sha256 == (
        "31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e"
    )
