"""Stage-7 fixture progress and typed current-adapter failure boundaries."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

import dmf_pulse.private_v1.automatic_inputs as automatic_inputs
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.private_v1.progress import HumanCliProgress

pytestmark = pytest.mark.unit


def _stage7_inputs() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    target_event = SimpleNamespace(identity="target-event")
    fixture = SimpleNamespace(
        provider_fixture_id=101,
        event_identity=target_event.identity,
        home_team_identity=SimpleNamespace(external_id_text="1"),
        away_team_identity=SimpleNamespace(external_id_text="2"),
    )
    snapshot = SimpleNamespace(
        captured_at=datetime(2026, 9, 2, 12, tzinfo=UTC),
        target_gameweek=4,
        fpl_input=SimpleNamespace(
            target_event=target_event,
            fixtures=(fixture,),
            players=(),
            provenance=SimpleNamespace(information_cutoff=datetime(2026, 9, 2, 12, tzinfo=UTC)),
        ),
    )
    identities = SimpleNamespace(
        teams=(
            SimpleNamespace(
                official_fpl_team_id=1,
                canonical_team_id=UUID("10000000-0000-4000-8000-000000000001"),
            ),
            SimpleNamespace(
                official_fpl_team_id=2,
                canonical_team_id=UUID("10000000-0000-4000-8000-000000000002"),
            ),
        ),
        players=(),
    )
    market_view = SimpleNamespace(
        fixtures=(
            SimpleNamespace(
                official_fpl_fixture_id=101,
                canonical_fixture_id=UUID("20000000-0000-4000-8000-000000000001"),
            ),
        )
    )
    return snapshot, identities, market_view


def _patch_stage7_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(automatic_inputs, "_read_resource", lambda _: {})
    monkeypatch.setattr(automatic_inputs, "fit_projection_artifact", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        automatic_inputs,
        "_current_history",
        lambda *_args: ({"rows": [], "rosters": {}}, ()),
    )


def _projected_result() -> SimpleNamespace:
    return SimpleNamespace(status="PROJECTED", projection=object(), error_code=None)


def test_stage7_progress_reports_home_away_and_reconciliation_without_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stage7_setup(monkeypatch)
    monkeypatch.setattr(
        automatic_inputs, "predict_minutes_baseline", lambda *_args, **_kwargs: _projected_result()
    )
    monkeypatch.setattr(
        automatic_inputs,
        "build_current_model_fixture_minutes",
        lambda *_args, **_kwargs: SimpleNamespace(
            fixture_id="20000000-0000-4000-8000-000000000001"
        ),
    )
    output: list[str] = []
    tick = -1

    def clock() -> float:
        nonlocal tick
        tick += 1
        return float(tick)

    progress = HumanCliProgress(write=output.append, clock=clock)
    snapshot, identities, market_view = _stage7_inputs()

    result = automatic_inputs.build_automatic_model_minutes(
        snapshot, identities, market_view, progress=progress
    )

    assert len(result) == 1
    rendered = "\n".join(output)
    expected_order = (
        "Stage 7 fixture 1/1: predicting home team...",
        "Stage 7 fixture 1/1: home prediction ready",
        "Stage 7 fixture 1/1: predicting away team...",
        "Stage 7 fixture 1/1: away prediction ready",
        "Stage 7 fixture 1/1: reconciling team scenarios...",
        "Stage 7 fixture 1/1 ready",
    )
    offsets = [rendered.index(value) for value in expected_order]
    assert offsets == sorted(offsets)
    home_match = re.search(r"home prediction ready \(([0-9.]+)s\)", rendered)
    fixture_match = re.search(r"fixture 1/1 ready \(([0-9.]+)s\)", rendered)
    assert home_match is not None
    assert fixture_match is not None
    home_duration = float(home_match.group(1))
    fixture_duration = float(fixture_match.group(1))
    assert fixture_duration > home_duration
    assert "10000000-0000-4000-8000-000000000001" not in rendered
    assert "20000000-0000-4000-8000-000000000001" not in rendered


def test_stage7_blocked_prediction_preserves_safe_typed_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stage7_setup(monkeypatch)
    monkeypatch.setattr(
        automatic_inputs,
        "predict_minutes_baseline",
        lambda *_args, **_kwargs: SimpleNamespace(
            status="BLOCKED",
            projection=None,
            error_code="INSUFFICIENT_ELIGIBLE_GOALKEEPERS",
        ),
    )
    output: list[str] = []
    progress = HumanCliProgress(write=output.append, clock=lambda: 10.0)
    snapshot, identities, market_view = _stage7_inputs()

    with pytest.raises(IngestionError) as error:
        automatic_inputs.build_automatic_model_minutes(
            snapshot, identities, market_view, progress=progress
        )

    assert error.value.code == "INSUFFICIENT_ELIGIBLE_GOALKEEPERS"
    rendered = "\n".join(output)
    assert "FAILED: Stage 7 fixture 1/1 home team prediction" in rendered
    assert "INSUFFICIENT_ELIGIBLE_GOALKEEPERS" in rendered


def test_stage7_predictor_exception_keeps_generic_model_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stage7_setup(monkeypatch)

    def fail_prediction(*_args: object, **_kwargs: object) -> object:
        raise ValueError("private model detail")

    monkeypatch.setattr(automatic_inputs, "predict_minutes_baseline", fail_prediction)
    output: list[str] = []
    progress = HumanCliProgress(write=output.append, clock=lambda: 10.0)
    snapshot, identities, market_view = _stage7_inputs()

    with pytest.raises(IngestionError) as error:
        automatic_inputs.build_automatic_model_minutes(
            snapshot, identities, market_view, progress=progress
        )

    assert error.value.code == "CURRENT_MINUTES_MODEL_BLOCKED"
    rendered = "\n".join(output)
    assert "FAILED: Stage 7 fixture 1/1 home team prediction" in rendered
    assert "CURRENT_MINUTES_MODEL_BLOCKED" in rendered
    assert "private model detail" not in rendered


@pytest.mark.parametrize(
    "adapter_error",
    (ValueError("private structural detail"), KeyError("private missing PMF detail")),
)
def test_stage7_scenario_adaptation_has_distinct_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
    adapter_error: Exception,
) -> None:
    _patch_stage7_setup(monkeypatch)
    monkeypatch.setattr(
        automatic_inputs, "predict_minutes_baseline", lambda *_args, **_kwargs: _projected_result()
    )

    def fail_adaptation(*_args: object, **_kwargs: object) -> object:
        raise adapter_error

    monkeypatch.setattr(automatic_inputs, "build_current_model_fixture_minutes", fail_adaptation)
    output: list[str] = []
    progress = HumanCliProgress(write=output.append, clock=lambda: 10.0)
    snapshot, identities, market_view = _stage7_inputs()

    with pytest.raises(IngestionError) as error:
        automatic_inputs.build_automatic_model_minutes(
            snapshot, identities, market_view, progress=progress
        )

    assert error.value.code == "CURRENT_STAGE7_SCENARIO_ROSTER_INVALID"
    rendered = "\n".join(output)
    assert "FAILED: Stage 7 fixture 1/1 scenario adaptation" in rendered
    assert "CURRENT_STAGE7_SCENARIO_ROSTER_INVALID" in rendered
    assert "private structural detail" not in rendered
    assert "private missing PMF detail" not in rendered
