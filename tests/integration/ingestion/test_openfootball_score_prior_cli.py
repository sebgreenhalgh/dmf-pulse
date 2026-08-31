from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.cli import current_score_prior_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorSummary


class _FakeResult:
    def safe_summary(self) -> CurrentScorePriorSummary:
        body: dict[str, object] = {
            "away_goal_rate": "1.374561",
            "away_goal_total": 1567,
            "classification": "WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR",
            "current_team_strength_claim": False,
            "home_goal_rate": "1.613158",
            "home_goal_total": 1839,
            "information_cutoff": "2026-08-30T10:00:00Z",
            "market_evidence_used": False,
            "method_id": "PL_LEAGUE_HOME_AWAY_MEAN_3_COMPLETE_SEASONS_V1",
            "model_family": "INDEPENDENT_POISSON_V1",
            "production_active": False,
            "rights_profile_id": "openfootball_football_json_score_prior_v1",
            "sample_size": 1140,
            "schema_version": "current-score-prior-summary-v1",
            "source_commit_sha": "f27dcbef681db2c3195f9def62316ce497278781",
            "source_mode": "RECONSTRUCTED",
            "source_result_semantic_sha256": "b" * 64,
            "status": "CURRENT_SCORE_PRIOR_READY",
            "usable_at": "2026-08-30T09:00:00Z",
        }
        return CurrentScorePriorSummary.model_validate_json(
            json.dumps(
                {
                    **body,
                    "semantic_sha256": canonical_sha256(body),
                }
            )
        )


class _SuccessfulService:
    def build(self, request: object) -> _FakeResult:
        del request
        return _FakeResult()


class _BlockedService:
    def build(self, request: object) -> _FakeResult:
        del request
        raise IngestionError(
            "RIGHTS_BLOCKED",
            "operation is not permitted by the selected rights profile",
            details={"transport_call_count": 0},
        )


@pytest.mark.integration
def test_cli_emits_only_safe_private_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_score_prior_cmd, "CurrentScorePriorService", _SuccessfulService)

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "openfootball",
            "score-prior",
            "--information-cutoff",
            "2026-08-30T10:00:00Z",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["home_goal_rate"] == "1.613158"
    assert payload["away_goal_rate"] == "1.374561"
    assert payload["market_evidence_used"] is False
    assert payload["current_team_strength_claim"] is False
    assert payload["production_active"] is False
    assert "matches" not in payload
    assert "headers" not in payload


@pytest.mark.integration
def test_cli_rights_refusal_is_zero_call_and_secret_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_score_prior_cmd, "CurrentScorePriorService", _BlockedService)

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "openfootball",
            "score-prior",
            "--information-cutoff",
            "2026-08-30T10:00:00Z",
        ],
    )

    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "RIGHTS_BLOCKED"
    assert payload["error"]["details"]["transport_call_count"] == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ["--information-cutoff", "not-a-time"],
        ["--information-cutoff", "2026-08-30T10:00:00Z", "--output", "human"],
    ],
)
def test_cli_usage_errors_are_typed_and_json(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setattr(current_score_prior_cmd, "CurrentScorePriorService", _SuccessfulService)

    result = CliRunner().invoke(app, ["ingest", "openfootball", "score-prior", *arguments])

    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"


class _UnexpectedService:
    def build(self, request: object) -> _FakeResult:
        del request
        raise RuntimeError("sensitive implementation detail")


def test_cli_unexpected_failure_is_secret_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_score_prior_cmd, "CurrentScorePriorService", _UnexpectedService)

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "openfootball",
            "score-prior",
            "--information-cutoff",
            "2026-08-30T10:00:00Z",
        ],
    )

    assert result.exit_code == 8
    assert json.loads(result.stdout)["error"]["code"] == "INTERNAL_INVARIANT"
    assert "sensitive" not in result.stdout
