"""FULL retains fresh complete-engine execution and every retained field."""

from datetime import timedelta

import pytest

from dmf_pulse.dashboard.synthetic import DEMO_TIME, run_synthetic_recommendation
from dmf_pulse.dashboard.views import desk_view
from dmf_pulse.operation.analysis_models import AnalysisSnapshot
from dmf_pulse.private_v1.progress import NullProgress
from tests.unit.operation.analysis_test_support import load_owned_snapshot

pytestmark = pytest.mark.integration


def test_full_owned_analysis_fixture_equals_fresh_complete_engine(tmp_path):
    result = run_synthetic_recommendation(1, NullProgress())
    view = desk_view(
        result,
        job_id="quality-owned",
        mode="SYNTHETIC_DEMONSTRATION",
        generated_at=DEMO_TIME,
        expires_at=DEMO_TIME + timedelta(minutes=15),
    )
    fresh = AnalysisSnapshot(
        run_id=view.job_id,
        provenance_class="OWNED_SYNTHETIC",
        permission_origin="OWNED_FIXTURE",
        implementation_sha="1" * 40,
        policy_sha256="2" * 64,
        wheel_sha256="3" * 64,
        recorded_at=DEMO_TIME,
        view=view,
        presentation=result.presentation,
    )
    retained = load_owned_snapshot()
    (tmp_path / "fresh-owned-analysis.json").write_text(fresh.model_dump_json(), encoding="utf-8")
    assert fresh.model_dump(mode="json") == retained.model_dump(mode="json")
    assert fresh.semantic_sha256 == retained.semantic_sha256
