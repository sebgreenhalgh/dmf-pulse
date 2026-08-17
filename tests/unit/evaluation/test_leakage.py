from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.evaluation.models import LeakageKind
from dmf_pulse.evaluation.service import EvaluationService, load_json

pytestmark = pytest.mark.unit

CASES = {
    "future_leakage_canary": LeakageKind.FUTURE_LEAKAGE_CANARY,
    "fixture_moved_after_cutoff": LeakageKind.FIXTURE_MOVED_AFTER_CUTOFF,
    "price_correction": LeakageKind.PRICE_CORRECTION_AFTER_CUTOFF,
    "closing_odds_trap": LeakageKind.CLOSING_ODDS_AFTER_CUTOFF,
    "postdeadline_lineup": LeakageKind.POSTDEADLINE_LINEUP,
    "late_entity_mapping": LeakageKind.LATE_ENTITY_MAPPING,
    "late_provider_correction": LeakageKind.LATE_PROVIDER_CORRECTION,
    "future_result_recent_window": LeakageKind.FUTURE_RESULT_IN_RECENT_WINDOW,
    "outer_fold_contamination": LeakageKind.OUTER_FOLD_CONTAMINATION,
    "current_vintage_contamination": LeakageKind.CURRENT_VINTAGE_CONTAMINATION,
}


@pytest.mark.parametrize(("directory", "expected"), CASES.items())
def test_required_adversarial_leakage_cases_block(directory: str, expected: LeakageKind) -> None:
    path = Path("fixtures/historical") / directory / "leakage_input.json"
    report = EvaluationService().leakage(load_json(path))
    assert report.status == "BLOCKED"
    assert expected in {item.kind for item in report.findings}
    assert all(item.blocking for item in report.findings)


def test_clean_historical_record_passes() -> None:
    report = EvaluationService().leakage(
        load_json(Path("fixtures/historical/synthetic_five_gw/leakage_clean_input.json"))
    )
    assert report.status == "PASS"
    assert report.findings == ()
