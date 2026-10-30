"""Historical metadata is paired, available without Refresh and never a vault query."""

import json
from importlib.resources import files

import pytest

from dmf_pulse.dashboard import app as app_module
from dmf_pulse.dashboard.app import create_app
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.player_lab.recovery import RecoveryError
from tests.unit.dashboard.test_dashboard import CODE, pair, request

pytestmark = pytest.mark.unit


def test_current_session_shows_existing_match_freeze_without_worker_or_credentials():
    def never_start(_):
        pytest.fail("performance metadata cannot start a worker or acquire data")

    runtime = DeskRuntime(demo=False, worker_factory=never_start)
    app = create_app(runtime=runtime, pairing_code=CODE, port=8765)
    assert request(app, "/api/performance")[0] == 401
    cookie = pair(app)
    status, headers, body = request(app, "/api/performance", browser_header=cookie)
    assert status == 200 and headers["cache-control"].startswith("no-store")
    report = json.loads(body)
    assert "synthetic_report" not in report
    assert report["real_cohort_scope"].startswith("PLAYER_COHORT")
    assert report["recovery"]["families"][0]["level"] == "MATCH"
    assert report["recovery"]["families"][0]["classification"] == "REAL_PRE_OUTCOME_FROZEN"
    assert report["recovery"]["families"][0]["real_accuracy_metrics"] is None
    assert report["recovery"]["additional_owner_report"] == "UNRESOLVED_NOT_DISPROVED"
    assert not report["recovery"]["scoring_performed"]
    assert request(app, "/api/performance?artifact=arbitrary", browser_header=cookie)[0] == 403
    runtime.close()


def test_catalogue_failure_is_typed_503_not_false_empty_success(monkeypatch):
    def failed():
        raise RecoveryError("RECOVERY_CATALOGUE_UNAVAILABLE")

    monkeypatch.setattr(app_module, "recovery_catalogue", failed)
    runtime = DeskRuntime(demo=False)
    app = create_app(runtime=runtime, pairing_code=CODE, port=8765)
    cookie = pair(app)
    status, _, body = request(app, "/api/performance", browser_header=cookie)
    assert status == 503
    assert json.loads(body) == {"error_code": "RECOVERY_CATALOGUE_UNAVAILABLE"}
    runtime.close()


def test_browser_displays_recovery_before_optional_synthetic_metrics_and_no_vault():
    source = (
        files("dmf_pulse.dashboard").joinpath("resources", "desk.js").read_text(encoding="utf-8")
    )
    assert source.index("Recovered forecast evidence") < source.index(
        "if (!report.synthetic_report)"
    )
    assert "missing labels are not zero" in source
    assert "Player evaluation:" in source
    assert "The fixture outcome count is" in source
    assert "does not prove absence elsewhere" in source
    assert "Inventory observed at" in source and "receipts were recorded later" in source
    assert "vault" not in source.lower()
