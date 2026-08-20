"""CLI contract for the private transient Session-1 operator review."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import ingest_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.session1 import (
    Session1DownstreamSummary,
    Session1FixtureReviewRow,
    Session1OfficialFixtureOption,
    Session1OfficialTeamOption,
    Session1ReviewTemplate,
    Session1TeamReviewRow,
    _review_template_sha256,
)

pytestmark = pytest.mark.unit
runner = CliRunner()
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


class _Prepared:
    def __init__(self, review_template: Session1ReviewTemplate) -> None:
        self.review_template = review_template


class _Completed:
    def safe_summary(self) -> Session1DownstreamSummary:
        return Session1DownstreamSummary(
            information_cutoff=CUTOFF,
            decision_information_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
            fpl_player_count=640,
            fpl_team_count=20,
            target_fixture_count=10,
            source_provider_event_count=10,
            excluded_provider_event_count=0,
            mapped_provider_event_count=10,
            fpl_input_semantic_sha256="1" * 64,
            odds_identity_semantic_sha256="2" * 64,
            identity_map_semantic_sha256="3" * 64,
            downstream_semantic_sha256="4" * 64,
            review_template_sha256="5" * 64,
        )


def _template() -> Session1ReviewTemplate:
    provisional = Session1ReviewTemplate.model_construct(
        information_cutoff=CUTOFF,
        fpl_input_semantic_sha256="1" * 64,
        fpl_identity_view_sha256="2" * 64,
        odds_provider_provenance_sha256="3" * 64,
        odds_identity_semantic_sha256="4" * 64,
        source_provider_event_count=1,
        excluded_provider_event_count=0,
        provider_teams=(
            Session1TeamReviewRow(
                provider_team_text="Alpha Athletic", exact_name_candidate_team_ids=(1,)
            ),
            Session1TeamReviewRow(
                provider_team_text="Beta Borough", exact_name_candidate_team_ids=(2,)
            ),
        ),
        official_team_options=(
            Session1OfficialTeamOption(
                official_fpl_team_id=1, official_name="Alpha Athletic", short_name="ALP"
            ),
            Session1OfficialTeamOption(
                official_fpl_team_id=2, official_name="Beta Borough", short_name="BET"
            ),
        ),
        provider_events=(
            Session1FixtureReviewRow(
                provider_event_id="event-1",
                provider_home_team="Alpha Athletic",
                provider_away_team="Beta Borough",
                provider_commence_time=datetime(2026, 8, 22, 14, tzinfo=UTC),
                exact_text_and_kickoff_candidate_fixture_ids=(101,),
            ),
        ),
        official_fixture_options=(
            Session1OfficialFixtureOption(
                official_fpl_fixture_id=101,
                official_home_team_id=1,
                official_home_team_name="Alpha Athletic",
                official_away_team_id=2,
                official_away_team_name="Beta Borough",
                official_kickoff_at=datetime(2026, 8, 22, 14, tzinfo=UTC),
            ),
        ),
        template_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["template_sha256"] = _review_template_sha256(provisional)
    return Session1ReviewTemplate.model_validate(payload)


def _args(tmp_path: Path) -> list[str]:
    return [
        "ingest",
        "session1",
        "run",
        "--bootstrap",
        str(tmp_path / "bootstrap.json"),
        "--fixtures",
        str(tmp_path / "fixtures.json"),
        "--captured-at",
        "2026-08-20T12:00:00Z",
        "--information-cutoff",
        "2026-08-21T17:30:00Z",
        "--reviewer",
        "Sebastian Greenhalgh",
        "--database-url-ref",
        "env:DMF_TEST_DATABASE_URL",
        "--output",
        "json",
    ]


def test_session1_help_has_no_credential_or_plan_persistence_options() -> None:
    result = runner.invoke(app, ["ingest", "session1", "run", "--help"])

    assert result.exit_code == 0
    normalized = result.stdout.casefold().replace("_", "-")
    assert "api-key" not in normalized
    assert "mapping-plan" not in normalized
    assert "output-path" not in normalized


def test_session1_run_requires_manual_choices_and_exact_hash_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    template = _template()
    prepared = _Prepared(template)
    captured: dict[str, object] = {}

    def prepare(_self: object, request: object) -> _Prepared:
        captured["request"] = request
        return prepared

    def complete(_self: object, value: object, approval: object) -> _Completed:
        captured["prepared"] = value
        captured["approval"] = approval
        return _Completed()

    monkeypatch.setattr(ingest_cmd, "Session1PreparedInputs", _Prepared)
    monkeypatch.setattr(ingest_cmd.Session1CurrentInputService, "prepare", prepare)
    monkeypatch.setattr(ingest_cmd.Session1CurrentInputService, "complete", complete)

    result = runner.invoke(
        app,
        _args(tmp_path),
        input=f"1\n2\n101\n{template.template_sha256}\n",
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout.splitlines()[-1])
    assert output["contract"] == "SESSION1_DOWNSTREAM_INPUT"
    assert output["status"] == "COMPLETE"
    assert output["fpl_derived_storage"] == "DENY"
    approval = captured["approval"]
    assert [row.official_fpl_team_id for row in approval.team_approvals] == [1, 2]
    assert approval.fixture_approvals[0].official_fpl_fixture_id == 101
    assert approval.confirmed_template_sha256 == template.template_sha256
    assert captured["prepared"] is prepared
    combined = result.output
    assert "PRIVATE TRANSIENT REVIEW" in combined
    assert template.template_sha256 in combined


def test_session1_run_rejects_wrong_hash_without_calling_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    template = _template()
    called = False

    monkeypatch.setattr(ingest_cmd, "Session1PreparedInputs", _Prepared)
    monkeypatch.setattr(
        ingest_cmd.Session1CurrentInputService,
        "prepare",
        lambda _self, _request: _Prepared(template),
    )

    def complete(*_args: object) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(ingest_cmd.Session1CurrentInputService, "complete", complete)

    result = runner.invoke(app, _args(tmp_path), input=f"1\n2\n101\n{'f' * 64}\n")

    assert result.exit_code == 2
    assert called is False
    error = json.loads(result.stdout.splitlines()[-1])
    assert error["error"]["code"] == "MAPPING_CONFLICT"
    assert "invalid or incomplete" in error["error"]["message"]


def test_session1_invalid_scope_is_rejected_before_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called = False

    def prepare(*_args: object) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(ingest_cmd.Session1CurrentInputService, "prepare", prepare)
    args = _args(tmp_path)
    args.extend(("--gameweek", "2"))

    result = runner.invoke(app, args)

    assert result.exit_code == 3
    assert called is False
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"
