"""Checkpoint-1.5 transient Session-1 application-service acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputService
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.live import LiveOddsOperationOutcome, LiveOddsSnapshotResult
from dmf_pulse.ingestion.odds.models import (
    OddsQuality,
    ProviderFailure,
    ProviderFailureCode,
    QuotaSource,
    QuotaState,
)
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.session1 import (
    Session1CurrentInputRequest,
    Session1CurrentInputService,
    Session1FixtureApproval,
    Session1OperatorApproval,
    Session1PreparedInputs,
    Session1TeamApproval,
    build_session1_review_template,
)

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 20, 11, 55, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
ODDS_RECEIVED = datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
APPROVED = datetime(2026, 8, 20, 12, 2, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000001501")


class _FakeOddsService:
    def __init__(self, outcome: LiveOddsOperationOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    def snapshot(self, **kwargs: object) -> LiveOddsOperationOutcome:
        self.calls.append(kwargs)
        return self.outcome


def _copy_fpl_pair(repository_root: Path, tmp_path: Path) -> tuple[Path, Path]:
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = tmp_path / "bootstrap.json"
    fixtures = tmp_path / "fixtures.json"
    bootstrap.write_bytes((source / "bootstrap.json").read_bytes())
    fixtures.write_bytes((source / "fixtures.json").read_bytes())
    return bootstrap, fixtures


def _odds_value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _complete_odds_outcome(
    repository_root: Path,
    *,
    value: object | None = None,
) -> LiveOddsOperationOutcome:
    body = json.dumps(
        _odds_value(repository_root) if value is None else value,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    quota = QuotaState(
        remaining=499,
        used=2,
        last_cost=2,
        observed_at=ODDS_RECEIVED,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    current = build_current_odds_input(
        parse_odds_payload(body),
        profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        request_started_at=ODDS_RECEIVED - timedelta(seconds=1),
        received_at=ODDS_RECEIVED,
        information_cutoff=CUTOFF,
        usable_at=ODDS_RECEIVED + timedelta(seconds=1),
        quota=quota,
        request_fingerprint="1" * 64,
        sanitized_target=(
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
            "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
            "commenceTimeFrom=2026-08-21T17%3A30%3A00Z"
        ),
        attempt_count=1,
        transport_call_count=1,
        provider_request_id_sha256="2" * 64,
    )
    return LiveOddsOperationOutcome(
        result=LiveOddsSnapshotResult(
            status="COMPLETE",
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            events_seen=1,
            bookmaker_observations_seen=2,
            market_observations_seen=2,
            outcomes_seen=6,
            current_input=current,
            quota=quota,
            quality=OddsQuality(status="PASS"),
            error=None,
        ),
        exit_code=0,
    )


def _prepare(
    repository_root: Path,
    tmp_path: Path,
    *,
    value: object | None = None,
) -> tuple[Session1CurrentInputService, Session1PreparedInputs, _FakeOddsService]:
    bootstrap, fixtures = _copy_fpl_pair(repository_root, tmp_path)
    fake_odds = _FakeOddsService(_complete_odds_outcome(repository_root, value=value))
    service = Session1CurrentInputService(
        fpl_service=CurrentFplInputService(clock=lambda: FPL_RECEIVED),
        odds_service=fake_odds,  # type: ignore[arg-type]
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
    return service, prepared, fake_odds


def _approval(
    prepared: Session1PreparedInputs,
    *,
    confirmed_sha256: str | None = None,
    approved_at: datetime = APPROVED,
    team_approvals: tuple[Session1TeamApproval, ...] | None = None,
    fixture_approvals: tuple[Session1FixtureApproval, ...] | None = None,
) -> Session1OperatorApproval:
    template = prepared.review_template
    teams = team_approvals or tuple(
        Session1TeamApproval(
            provider_team_text=row.provider_team_text,
            official_fpl_team_id=row.exact_name_candidate_team_ids[0],
        )
        for row in template.provider_teams
    )
    fixtures = fixture_approvals or tuple(
        Session1FixtureApproval(
            provider_event_id=row.provider_event_id,
            official_fpl_fixture_id=row.exact_text_and_kickoff_candidate_fixture_ids[0],
        )
        for row in template.provider_events
    )
    return Session1OperatorApproval(
        reviewer="Sebastian Greenhalgh",
        approved_at=approved_at,
        template_sha256=template.template_sha256,
        confirmed_template_sha256=confirmed_sha256 or template.template_sha256,
        team_approvals=teams,
        fixture_approvals=fixtures,
    )


def test_prepare_and_complete_produce_transient_hash_bound_downstream_input(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    service, prepared, fake_odds = _prepare(repository_root, tmp_path)

    template = prepared.review_template
    assert template.status == "REVIEW_REQUIRED"
    assert template.match_policy == "EXACT_CASE_SENSITIVE_ONLY_NO_AUTO_APPROVAL"
    assert [row.exact_name_candidate_team_ids for row in template.provider_teams] == [
        (1,),
        (2,),
    ]
    assert [
        row.exact_text_and_kickoff_candidate_fixture_ids for row in template.provider_events
    ] == [(101,)]
    assert fake_odds.calls == [
        {
            "provider": "the_odds_api",
            "competition_key": "PL",
            "sport_key": "soccer_epl",
            "region": "uk",
            "market": "h2h",
            "as_of": CUTOFF,
            "database_url_ref": "env:DMF_TEST_DATABASE_URL",
        }
    ]

    result = service.complete(prepared, _approval(prepared))
    summary = result.safe_summary()

    assert result.contract == "SESSION1_DOWNSTREAM_INPUT"
    assert result.decision_information_at == APPROVED
    assert result.identity_map.coverage.status == "COMPLETE"
    assert result.identity_map.fixture_mappings[0].official_fpl_fixture_id == 101
    assert result.persistence_performed is False
    assert result.fpl_input.rights.raw_storage_performed is False
    assert result.fpl_input.rights.derived_storage_performed is False
    assert result.fpl_input.rights.database_accessed is False
    assert result.odds_input.provenance.raw_payload_retained is False
    assert summary.status == "COMPLETE"
    assert summary.production_status == "NON_PRODUCTION"
    assert summary.decision_information_at == APPROVED
    assert summary.source_provider_event_count == 1
    assert summary.excluded_provider_event_count == 0
    assert summary.fpl_raw_storage == "DENY"
    assert summary.fpl_derived_storage == "DENY"
    assert summary.identity_coverage == "COMPLETE"


def test_review_template_is_deterministic_and_does_not_auto_approve(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    _service, prepared, _fake = _prepare(repository_root, tmp_path)

    rebuilt = build_session1_review_template(prepared.fpl_input, prepared.odds_input)

    assert rebuilt == prepared.review_template
    assert "APPROVED" not in rebuilt.model_dump_json()
    assert rebuilt.persistence_authorized is False


def test_spelling_variant_has_no_exact_candidate(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    value = _odds_value(repository_root)
    event = value[0]
    event["home_team"] = "Alpha A."
    for bookmaker in event["bookmakers"]:
        for outcome in bookmaker["markets"][0]["outcomes"]:
            if outcome["name"] == "Alpha Athletic":
                outcome["name"] = "Alpha A."
    _service, prepared, _fake = _prepare(repository_root, tmp_path, value=value)

    row = next(
        item
        for item in prepared.review_template.provider_teams
        if item.provider_team_text == "Alpha A."
    )
    event_row = prepared.review_template.provider_events[0]

    assert row.exact_name_candidate_team_ids == ()
    assert event_row.exact_text_and_kickoff_candidate_fixture_ids == ()


def test_prepare_scopes_upcoming_provider_events_to_the_official_gw_window(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    value = _odds_value(repository_root)
    later = json.loads(json.dumps(value[0]))
    later["id"] = "todapi-event-later"
    later["commence_time"] = "2026-08-29T14:00:00Z"
    value.append(later)

    _service, prepared, _fake = _prepare(repository_root, tmp_path, value=value)

    assert [event.provider_event_id for event in prepared.odds_input.events] == ["todapi-event-001"]
    assert prepared.review_template.source_provider_event_count == 2
    assert prepared.review_template.excluded_provider_event_count == 1
    assert (
        prepared.review_template.event_scope_policy == "OFFICIAL_TARGET_GW_MIN_MAX_KICKOFF_WINDOW"
    )


def test_exact_hash_confirmation_is_mandatory(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    _service, prepared, _fake = _prepare(repository_root, tmp_path)

    with pytest.raises(ValidationError, match="did not confirm"):
        _approval(prepared, confirmed_sha256="f" * 64)


def test_complete_rejects_incomplete_or_tampered_review(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    service, prepared, _fake = _prepare(repository_root, tmp_path)
    incomplete = _approval(
        prepared,
        team_approvals=(
            Session1TeamApproval(provider_team_text="Alpha Athletic", official_fpl_team_id=1),
            Session1TeamApproval(provider_team_text="Unreviewed Team", official_fpl_team_id=2),
        ),
    )
    tampered = prepared.model_copy(
        update={
            "review_template": prepared.review_template.model_copy(
                update={"template_sha256": "f" * 64}
            )
        }
    )

    with pytest.raises(IngestionError, match="coverage is incomplete"):
        service.complete(prepared, incomplete)
    with pytest.raises(IngestionError, match="not bound"):
        service.complete(tampered, _approval(prepared))


def test_complete_rejects_wrong_orientation_and_post_cutoff_approval(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    service, prepared, _fake = _prepare(repository_root, tmp_path)
    reversed_teams = tuple(
        Session1TeamApproval(
            provider_team_text=row.provider_team_text,
            official_fpl_team_id=2 if row.provider_team_text == "Alpha Athletic" else 1,
        )
        for row in prepared.review_template.provider_teams
    )

    with pytest.raises(IngestionError) as wrong_orientation:
        service.complete(
            prepared,
            _approval(prepared, team_approvals=reversed_teams),
        )
    assert wrong_orientation.value.details["reason"] == "HOME_AWAY_ORIENTATION_MISMATCH"
    with pytest.raises(IngestionError, match="usable window"):
        service.complete(
            prepared,
            _approval(prepared, approved_at=CUTOFF + timedelta(seconds=1)),
        )


def test_public_session1_models_reject_tampered_templates_approvals_and_outputs(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    service, prepared, _fake = _prepare(repository_root, tmp_path)
    template_payload = prepared.review_template.model_dump(mode="python")

    duplicate = dict(template_payload)
    duplicate["provider_teams"] = (
        prepared.review_template.provider_teams[0],
        prepared.review_template.provider_teams[0],
    )
    outside = dict(template_payload)
    outside_rows = list(prepared.review_template.provider_teams)
    outside_rows[0] = outside_rows[0].model_copy(update={"exact_name_candidate_team_ids": (999,)})
    outside["provider_teams"] = tuple(outside_rows)
    wrong_hash = dict(template_payload)
    wrong_hash["template_sha256"] = "f" * 64
    for payload, message in (
        (duplicate, "duplicated"),
        (outside, "outside"),
        (wrong_hash, "hash is inconsistent"),
    ):
        with pytest.raises(ValidationError, match=message):
            prepared.review_template.__class__.model_validate(payload)

    valid_approval = _approval(prepared)
    approval_payload = valid_approval.model_dump(mode="python")
    approval_payload["team_approvals"] = (
        valid_approval.team_approvals[0],
        valid_approval.team_approvals[0],
    )
    with pytest.raises(ValidationError, match="duplicate or ambiguous"):
        Session1OperatorApproval.model_validate(approval_payload)

    result = service.complete(prepared, valid_approval)
    with pytest.raises(ValueError, match="lineage"):
        result.model_copy(
            update={"information_cutoff": result.information_cutoff - timedelta(seconds=1)}
        ).validate_downstream_input()
    with pytest.raises(ValueError, match="retention rights"):
        result.model_copy(
            update={
                "fpl_input": result.fpl_input.model_copy(
                    update={
                        "rights": result.fpl_input.rights.model_copy(
                            update={"database_accessed": True}
                        )
                    }
                )
            }
        ).validate_downstream_input()
    with pytest.raises(ValueError, match="semantic hash"):
        result.model_copy(update={"semantic_sha256": "f" * 64}).validate_downstream_input()


def test_prepare_fails_before_or_at_unusable_live_odds_boundaries(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    bootstrap, fixtures = _copy_fpl_pair(repository_root, tmp_path)
    fpl_service = CurrentFplInputService(clock=lambda: FPL_RECEIVED)
    base_request = {
        "bootstrap_path": bootstrap,
        "fixtures_path": fixtures,
        "captured_at": CAPTURED,
        "database_url_ref": "env:DMF_TEST_DATABASE_URL",
    }
    not_called = _FakeOddsService(_complete_odds_outcome(repository_root))
    cutoff_service = Session1CurrentInputService(
        fpl_service=fpl_service,
        odds_service=not_called,  # type: ignore[arg-type]
    )
    with pytest.raises(IngestionError, match="must equal"):
        cutoff_service.prepare(
            Session1CurrentInputRequest(
                **base_request,
                information_cutoff=CUTOFF - timedelta(seconds=1),
            )
        )
    assert not_called.calls == []

    failure = ProviderFailure(
        code=ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
        message="approved runtime credential is unavailable",
        retryable=False,
        transport_called=False,
    )
    blocked = LiveOddsOperationOutcome(
        result=LiveOddsSnapshotResult(
            status="BLOCKED",
            source_snapshot_id=None,
            events_seen=0,
            bookmaker_observations_seen=0,
            market_observations_seen=0,
            outcomes_seen=0,
            current_input=None,
            quota=None,
            quality=OddsQuality(status="BLOCKING", blockers=(failure.code.value,)),
            error=failure,
        ),
        exit_code=4,
    )
    blocked_service = Session1CurrentInputService(
        fpl_service=fpl_service,
        odds_service=_FakeOddsService(blocked),  # type: ignore[arg-type]
    )
    with pytest.raises(IngestionError) as unavailable:
        blocked_service.prepare(
            Session1CurrentInputRequest(**base_request, information_cutoff=CUTOFF)
        )
    assert unavailable.value.code == "CREDENTIAL_UNAVAILABLE"
    assert unavailable.value.details == {"transport_called": False}

    quarantined = LiveOddsOperationOutcome(
        result=LiveOddsSnapshotResult(
            status="QUARANTINED",
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            events_seen=1,
            bookmaker_observations_seen=0,
            market_observations_seen=0,
            outcomes_seen=0,
            current_input=None,
            quota=None,
            quality=OddsQuality(status="BLOCKING", blockers=("QUALITY_BLOCKED",)),
            error=None,
        ),
        exit_code=3,
    )
    quality_service = Session1CurrentInputService(
        fpl_service=fpl_service,
        odds_service=_FakeOddsService(quarantined),  # type: ignore[arg-type]
    )
    with pytest.raises(IngestionError) as quality:
        quality_service.prepare(
            Session1CurrentInputRequest(**base_request, information_cutoff=CUTOFF)
        )
    assert quality.value.code == "QUALITY_BLOCKED"

    outside_value = _odds_value(repository_root)
    outside_value[0]["commence_time"] = "2026-08-29T14:00:00Z"
    outside_service = Session1CurrentInputService(
        fpl_service=fpl_service,
        odds_service=_FakeOddsService(  # type: ignore[arg-type]
            _complete_odds_outcome(repository_root, value=outside_value)
        ),
    )
    with pytest.raises(IngestionError, match="no event"):
        outside_service.prepare(
            Session1CurrentInputRequest(**base_request, information_cutoff=CUTOFF)
        )


def test_complete_rejects_missing_fixture_coverage_and_unknown_current_ids(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    service, prepared, _fake = _prepare(repository_root, tmp_path)
    template = prepared.review_template
    unknown_event = _approval(
        prepared,
        fixture_approvals=(
            Session1FixtureApproval(provider_event_id="unknown-event", official_fpl_fixture_id=101),
        ),
    )
    with pytest.raises(IngestionError, match="fixture review coverage"):
        service.complete(prepared, unknown_event)

    unknown_team = _approval(
        prepared,
        team_approvals=(
            Session1TeamApproval(
                provider_team_text=template.provider_teams[0].provider_team_text,
                official_fpl_team_id=999,
            ),
            Session1TeamApproval(
                provider_team_text=template.provider_teams[1].provider_team_text,
                official_fpl_team_id=2,
            ),
        ),
    )
    with pytest.raises(IngestionError, match="selected no current"):
        service.complete(prepared, unknown_team)

    unknown_fixture = _approval(
        prepared,
        fixture_approvals=(
            Session1FixtureApproval(
                provider_event_id=template.provider_events[0].provider_event_id,
                official_fpl_fixture_id=999,
            ),
        ),
    )
    with pytest.raises(IngestionError, match="selected no target"):
        service.complete(prepared, unknown_fixture)
