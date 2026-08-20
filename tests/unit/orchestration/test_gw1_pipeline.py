"""Shared GW1 orchestration acceptance without provider or account access."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.availability.current import build_current_availability
from dmf_pulse.orchestration.gw1 import run_gw1_decision_pipeline
from dmf_pulse.rules.compiler import compile_ruleset, write_compiled_ruleset
from tests.unit.availability.test_current_availability import _approval, _market_source
from tests.unit.fpl_points.test_current_football_events import _event_approval

pytestmark = pytest.mark.unit


def test_shared_pipeline_fails_closed_before_decision_or_receipt(
    repository_root: Path, tmp_path: Path
) -> None:
    market = _market_source(repository_root, tmp_path / "source")
    availability = build_current_availability(market, _approval(market))
    ruleset_path = tmp_path / "fpl-2026-27.json"
    write_compiled_ruleset(
        compile_ruleset(repository_root / "config/rules/fpl-2026-27"), ruleset_path
    )
    receipt_root = tmp_path / "prospective"

    result = run_gw1_decision_pipeline(
        market.source_input,
        availability_approval_provider=lambda _review: _approval(market),
        event_approval_provider=lambda _review: _event_approval(availability),
        ruleset_path=ruleset_path,
        mc_policy_path=repository_root / "config/models/fpl_points_simulation.yaml",
        root_seed=2026270001,
        scenario_count=32,
        code_commit="a" * 40,
        receipt_clock=lambda: datetime(2026, 8, 20, 12, 5, tzinfo=UTC),
        prospective_artifact_root=receipt_root,
    )

    assert result.decision.status == "BLOCKED"
    assert result.summary.status == "BLOCKED"
    assert result.summary.session1_semantic_sha256 == market.source_input.semantic_sha256
    assert result.summary.prospective_receipt_sha256 is None
    assert result.prospective_receipt is None
    assert result.prospective_receipt_path is None
    assert not receipt_root.exists()
    assert result.summary.detailed_output_persisted is False
    assert result.summary.automated_fpl_account_action is False
