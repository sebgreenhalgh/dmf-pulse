"""Checkpoint-2.2 current availability/minutes integration acceptance."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.current import (
    CurrentAvailabilityApproval,
    CurrentAvailabilityBundle,
    CurrentAvailabilityEvidence,
    CurrentPlayerAvailabilityDecision,
    build_current_availability,
    build_current_availability_review,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputService
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput, build_current_odds_input
from dmf_pulse.ingestion.odds.live import LiveOddsOperationOutcome, LiveOddsSnapshotResult
from dmf_pulse.ingestion.odds.models import OddsQuality, QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.session1 import (
    Session1CurrentInputRequest,
    Session1CurrentInputService,
    Session1FixtureApproval,
    Session1OperatorApproval,
    Session1TeamApproval,
)
from dmf_pulse.markets.current import CurrentMarketConsensusBundle, build_current_market_consensus

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 20, 11, 55, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
ODDS_RECEIVED = datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
IDENTITY_APPROVED = datetime(2026, 8, 20, 12, 2, tzinfo=UTC)
AVAILABILITY_APPROVED = datetime(2026, 8, 20, 12, 3, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
KICKOFF = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000002201")
REVIEWER = "Sebastian Greenhalgh"


class _FakeOddsService:
    def __init__(self, current_input: OddsProviderCurrentInput) -> None:
        self.current_input = current_input

    def snapshot(self, **_kwargs: object) -> LiveOddsOperationOutcome:
        quota = QuotaState(
            remaining=499,
            used=1,
            last_cost=1,
            observed_at=ODDS_RECEIVED,
            source=QuotaSource.RESPONSE_HEADERS,
        )
        return LiveOddsOperationOutcome(
            result=LiveOddsSnapshotResult(
                status="COMPLETE",
                source_snapshot_id=SNAPSHOT_ID,
                events_seen=1,
                bookmaker_observations_seen=2,
                market_observations_seen=2,
                outcomes_seen=6,
                current_input=self.current_input,
                quota=quota,
                quality=OddsQuality(status="PASS"),
                error=None,
            ),
            exit_code=0,
        )


def _expanded_bootstrap(value: dict[str, Any], *, alert: bool = False) -> dict[str, Any]:
    result = deepcopy(value)
    template = result["elements"][0]
    positions = (1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4)
    elements: list[dict[str, Any]] = []
    for team_id in (1, 2):
        for index, position in enumerate(positions, start=1):
            player = deepcopy(template)
            player_id = team_id * 1000 + index
            player.update(
                {
                    "chance_of_playing_next_round": None,
                    "chance_of_playing_this_round": None,
                    "code": 200000 + player_id,
                    "element_type": position,
                    "first_name": f"Player{player_id}",
                    "id": player_id,
                    "news": "",
                    "news_added": None,
                    "now_cost": 45 + index,
                    "second_name": f"Test{player_id}",
                    "status": "a",
                    "team": team_id,
                    "web_name": f"P{player_id}",
                }
            )
            elements.append(player)
    if alert:
        elements[0].update(
            {
                "chance_of_playing_next_round": 75,
                "chance_of_playing_this_round": 50,
                "news": "Minor doubt",
                "news_added": "2026-08-20T11:30:00Z",
                "status": "d",
            }
        )
    result["elements"] = elements
    return result


def _market_source(
    repository_root: Path,
    tmp_path: Path,
    *,
    expand_rosters: bool = True,
    alert: bool = False,
) -> CurrentMarketConsensusBundle:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap_value = json.loads((source / "bootstrap.json").read_text(encoding="utf-8"))
    if expand_rosters:
        bootstrap_value = _expanded_bootstrap(bootstrap_value, alert=alert)
    bootstrap = tmp_path / "bootstrap.json"
    fixtures = tmp_path / "fixtures.json"
    bootstrap.write_text(json.dumps(bootstrap_value), encoding="utf-8")
    fixtures.write_bytes((source / "fixtures.json").read_bytes())

    odds_value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    body = json.dumps(odds_value, allow_nan=False, separators=(",", ":")).encode()
    quota = QuotaState(
        remaining=499,
        used=1,
        last_cost=1,
        observed_at=ODDS_RECEIVED,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    current = build_current_odds_input(
        parse_odds_payload(body),
        profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=SNAPSHOT_ID,
        request_started_at=ODDS_RECEIVED - timedelta(seconds=1),
        received_at=ODDS_RECEIVED,
        information_cutoff=CUTOFF,
        usable_at=ODDS_RECEIVED + timedelta(seconds=1),
        quota=quota,
        request_fingerprint="1" * 64,
        sanitized_target=(
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
            "regions=uk&markets=h2h&oddsFormat=decimal&dateFormat=iso&"
            "commenceTimeFrom=2026-08-21T17%3A30%3A00Z"
        ),
        attempt_count=1,
        transport_call_count=1,
        provider_request_id_sha256="2" * 64,
    )
    service = Session1CurrentInputService(
        fpl_service=CurrentFplInputService(clock=lambda: FPL_RECEIVED),
        odds_service=_FakeOddsService(current),  # type: ignore[arg-type]
    )
    prepared = service.prepare(
        Session1CurrentInputRequest(
            bootstrap_path=bootstrap,
            fixtures_path=fixtures,
            captured_at=CAPTURED,
            information_cutoff=CUTOFF,
            database_url_ref="env:DMF_TEST_DATABASE_URL",
        )
    )
    template = prepared.review_template
    identity_approval = Session1OperatorApproval(
        reviewer=REVIEWER,
        approved_at=IDENTITY_APPROVED,
        template_sha256=template.template_sha256,
        confirmed_template_sha256=template.template_sha256,
        team_approvals=tuple(
            Session1TeamApproval(
                provider_team_text=row.provider_team_text,
                official_fpl_team_id=row.exact_name_candidate_team_ids[0],
            )
            for row in template.provider_teams
        ),
        fixture_approvals=tuple(
            Session1FixtureApproval(
                provider_event_id=row.provider_event_id,
                official_fpl_fixture_id=row.exact_text_and_kickoff_candidate_fixture_ids[0],
            )
            for row in template.provider_events
        ),
    )
    return build_current_market_consensus(service.complete(prepared, identity_approval))


def _approval(
    source: CurrentMarketConsensusBundle,
    *,
    decisions: tuple[CurrentPlayerAvailabilityDecision, ...] = (),
    approved_at: datetime = AVAILABILITY_APPROVED,
) -> CurrentAvailabilityApproval:
    template = build_current_availability_review(source)
    return CurrentAvailabilityApproval(
        reviewer=REVIEWER,
        approved_at=approved_at,
        template_sha256=template.template_sha256,
        confirmed_template_sha256=template.template_sha256,
        reviewed_all_players=True,
        decisions=decisions,
    )


def _evidence(
    *,
    evidence_type: str,
    source_class: str,
    usable_at: datetime = IDENTITY_APPROVED,
    expires_at: datetime = KICKOFF + timedelta(days=1),
) -> CurrentAvailabilityEvidence:
    return CurrentAvailabilityEvidence.model_validate(
        {
            "evidence_type": evidence_type,
            "source_class": source_class,
            "source_locator": "https://official.example/evidence/fixture-101",
            "observed_at": usable_at - timedelta(minutes=1),
            "usable_at": usable_at,
            "expires_at": expires_at,
            "confidence": "HIGH",
            "summary": "Structured operator-reviewed evidence.",
            "reviewer": REVIEWER,
        }
    )


def _decision(
    player_id: int,
    adjustment: str,
    evidence: CurrentAvailabilityEvidence,
) -> CurrentPlayerAvailabilityDecision:
    return CurrentPlayerAvailabilityDecision.model_validate(
        {
            "official_fpl_player_id": player_id,
            "official_fpl_fixture_id": 101,
            "adjustment": adjustment,
            "evidence": (evidence,),
            "reason": "Explicit fixture-scoped operator review.",
        }
    )


def test_current_rosters_produce_complete_cold_start_minutes_bundle(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _market_source(repository_root, tmp_path)
    template = build_current_availability_review(source)

    result = build_current_availability(source, _approval(source))
    summary = result.safe_summary()

    assert len(template.players) == 44
    assert not any(row.explicit_decision_required for row in template.players)
    assert len(result.team_projections) == 2
    assert all(len(row.posterior_projection.players) == 22 for row in result.team_projections)
    assert all(
        row.posterior_projection.sum_p_start == "11.000000000000" for row in result.team_projections
    )
    assert all(
        row.posterior_projection.sum_p_bench == "9.000000000000" for row in result.team_projections
    )
    assert all(row.prior_projection == row.posterior_projection for row in result.team_projections)
    assert summary.status == "COMPLETE_WITH_MATERIAL_LIMITATIONS"
    assert summary.production_calibration_claim is False
    assert summary.model_evidence_mode == "SYNTHETIC_CONTRACT_BASELINE_COLD_START"
    assert summary.confidence_grades == {"D": 44}
    assert summary.persistence_performed is False
    assert CurrentAvailabilityBundle.model_validate_json(result.model_dump_json()) == result


def test_hard_new_signing_and_soft_evidence_obey_distinct_boundaries(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _market_source(repository_root, tmp_path)
    decisions = (
        _decision(
            1001,
            "HARD_INELIGIBLE",
            _evidence(
                evidence_type="OFFICIAL_SUSPENSION",
                source_class="OFFICIAL_COMPETITION_AUTHORITY",
            ),
        ),
        _decision(
            1002,
            "NEW_SIGNING",
            _evidence(
                evidence_type="OFFICIAL_TRANSFER_OR_REGISTRATION",
                source_class="OFFICIAL_CLUB",
            ),
        ),
        _decision(
            1003,
            "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
            _evidence(evidence_type="MANAGER_QUOTE", source_class="OFFICIAL_CLUB"),
        ),
    )

    result = build_current_availability(source, _approval(source, decisions=decisions))
    team = next(row for row in result.team_projections if row.official_fpl_team_id == 1)
    applications = {row.official_fpl_player_id: row for row in team.applied_decisions}
    posterior = {row.player_id: row for row in team.posterior_projection.players}

    hard = posterior[str(applications[1001].transient_player_id)]
    new_signing = posterior[str(applications[1002].transient_player_id)]
    assert (hard.p_start, hard.p_bench, hard.p_appearance, hard.p_zero_minutes) == (
        "0.000000000000",
        "0.000000000000",
        "0.000000000000",
        "1.000000000000",
    )
    assert applications[1001].direct_model_effect == "HARD_ZERO"
    assert applications[1002].direct_model_effect == "CONFIDENCE_ONLY"
    assert "NEW_SIGNING" in new_signing.confidence_reasons
    assert applications[1003].direct_model_effect == "NONE"
    assert result.safe_summary().hard_ineligible_count == 1
    assert result.safe_summary().new_signing_count == 1
    assert result.safe_summary().soft_evidence_count == 1


def test_fpl_alert_requires_explicit_soft_review(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _market_source(repository_root, tmp_path, alert=True)
    template = build_current_availability_review(source)
    flagged = [row for row in template.players if row.explicit_decision_required]
    assert [row.official_fpl_player_id for row in flagged] == [1001]

    with pytest.raises(IngestionError, match="every current FPL availability alert"):
        build_current_availability(source, _approval(source))

    decision = _decision(
        1001,
        "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
        _evidence(evidence_type="FPL_STATUS_ALERT", source_class="OFFICIAL_FPL"),
    )
    result = build_current_availability(source, _approval(source, decisions=(decision,)))
    application = next(
        item
        for team in result.team_projections
        for item in team.applied_decisions
        if item.official_fpl_player_id == 1001
    )
    assert application.direct_model_effect == "NONE"


@pytest.mark.parametrize(
    ("approval_mutation", "error_match"),
    [
        ({"confirmed_template_sha256": "0" * 64}, "not bound"),
        ({"approved_at": CUTOFF + timedelta(seconds=1)}, "outside the usable window"),
    ],
)
def test_review_binding_and_cutoff_fail_closed(
    repository_root: Path,
    tmp_path: Path,
    approval_mutation: dict[str, object],
    error_match: str,
) -> None:
    source = _market_source(repository_root, tmp_path)
    approval = _approval(source).model_copy(update=approval_mutation)
    with pytest.raises(IngestionError, match=error_match):
        build_current_availability(source, approval)


@pytest.mark.parametrize(
    ("decision", "error_match"),
    [
        (
            _decision(
                1001,
                "HARD_INELIGIBLE",
                _evidence(evidence_type="TRAINING_REPORT", source_class="OFFICIAL_CLUB"),
            ),
            "hard ineligibility requires",
        ),
        (
            _decision(
                1001,
                "NEW_SIGNING",
                _evidence(
                    evidence_type="ANALYST_JUDGEMENT",
                    source_class="ANALYST_REVIEW",
                ),
            ),
            "new-signing status requires",
        ),
        (
            _decision(
                1001,
                "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
                _evidence(
                    evidence_type="MANAGER_QUOTE",
                    source_class="OFFICIAL_CLUB",
                    usable_at=AVAILABILITY_APPROVED + timedelta(seconds=1),
                ),
            ),
            "not usable at decision time",
        ),
        (
            _decision(
                1001,
                "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
                _evidence(
                    evidence_type="MANAGER_QUOTE",
                    source_class="OFFICIAL_CLUB",
                    expires_at=KICKOFF - timedelta(seconds=1),
                ),
            ),
            "expires before",
        ),
        (
            _decision(
                1001,
                "HARD_INELIGIBLE",
                _evidence(
                    evidence_type="FIXTURE_CANCELLATION",
                    source_class="OFFICIAL_COMPETITION_AUTHORITY",
                ),
            ),
            "cancellation blocks the complete fixture",
        ),
        (
            _decision(
                1001,
                "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
                _evidence(
                    evidence_type="ANALYST_JUDGEMENT",
                    source_class="ANALYST_REVIEW",
                ).model_copy(update={"reviewer": "Different reviewer"}),
            ),
            "reviewer contradicts approval",
        ),
    ],
)
def test_unusable_or_unauthoritative_evidence_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    decision: CurrentPlayerAvailabilityDecision,
    error_match: str,
) -> None:
    source = _market_source(repository_root, tmp_path)
    with pytest.raises(IngestionError, match=error_match):
        build_current_availability(source, _approval(source, decisions=(decision,)))


def test_unknown_player_and_insufficient_squad_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _market_source(repository_root, tmp_path / "full")
    unknown = _decision(
        999999,
        "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
        _evidence(evidence_type="ANALYST_JUDGEMENT", source_class="ANALYST_REVIEW"),
    )
    with pytest.raises(IngestionError, match="outside current scope"):
        build_current_availability(source, _approval(source, decisions=(unknown,)))

    small = _market_source(repository_root, tmp_path / "small", expand_rosters=False)
    alert_decisions = tuple(
        _decision(
            row.official_fpl_player_id,
            "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
            _evidence(evidence_type="FPL_STATUS_ALERT", source_class="OFFICIAL_FPL"),
        )
        for row in build_current_availability_review(small).players
        if row.explicit_decision_required
    )
    with pytest.raises(IngestionError, match="insufficient eligible players"):
        build_current_availability(small, _approval(small, decisions=alert_decisions))


def test_serialized_player_or_output_tampering_is_rejected(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _market_source(repository_root, tmp_path)
    result = build_current_availability(source, _approval(source))

    output_tamper = json.loads(result.model_dump_json())
    output_tamper["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="lineage is inconsistent"):
        CurrentAvailabilityBundle.model_validate_json(json.dumps(output_tamper))

    source_tamper = json.loads(result.model_dump_json())
    source_tamper["source_market"]["source_input"]["fpl_input"]["players"][0]["status"] = "d"
    with pytest.raises((ValidationError, IngestionError)):
        CurrentAvailabilityBundle.model_validate_json(json.dumps(source_tamper))
