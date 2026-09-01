from __future__ import annotations

from pathlib import Path

from dmf_pulse.private_v1.artifacts import write_synthetic_replay_bundle
from dmf_pulse.private_v1.service import PrivateV1RecommendationService

from .e2e_test_support import build_execution_input


def test_complete_synthetic_run_and_offline_replay(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    execution = build_execution_input(repository_root, tmp_path / "source")
    service = PrivateV1RecommendationService()
    first = service.run(execution)

    assert first.decision.engineering_status == (
        "PRIVATE_V1_E2E_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"
    )
    assert first.decision.activation_status == "NOT_PRODUCTION_ACTIVE"
    assert first.decision.paired_comparison.scenario_count == len(
        first.gameweek_projection.scenario_set.scenarios
    )
    assert "IDENTICAL JOINT SCENARIOS" in first.report
    assert "Confidence: LOW" in first.report

    bundle = tmp_path / "replay"
    manifest = write_synthetic_replay_bundle(execution, first.decision, first.report, bundle)
    replay = service.replay(bundle)

    assert replay.manifest_sha256 == manifest.manifest_sha256
    assert replay.run.decision == first.decision
    assert replay.run.report == first.report
