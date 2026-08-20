"""Checkpoint-2.1 current market-to-consensus integration acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

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
    Session1DownstreamInput,
    Session1FixtureApproval,
    Session1OperatorApproval,
    Session1TeamApproval,
)
from dmf_pulse.markets.current import (
    CurrentMarketConsensusBundle,
    build_current_market_consensus,
)
from dmf_pulse.markets.policy import POLICY_SHA256

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 20, 11, 55, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
ODDS_RECEIVED = datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
APPROVED = datetime(2026, 8, 20, 12, 2, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000002101")


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


def _odds_value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _source(
    repository_root: Path,
    tmp_path: Path,
    *,
    odds_value: object | None = None,
) -> Session1DownstreamInput:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = tmp_path / "bootstrap.json"
    fixtures = tmp_path / "fixtures.json"
    bootstrap.write_bytes((source / "bootstrap.json").read_bytes())
    fixtures.write_bytes((source / "fixtures.json").read_bytes())
    body = json.dumps(
        _odds_value(repository_root) if odds_value is None else odds_value,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
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
    approval = Session1OperatorApproval(
        reviewer="Sebastian Greenhalgh",
        approved_at=APPROVED,
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
    return service.complete(prepared, approval)


def test_current_h2h_books_produce_complete_transient_stage6_consensus(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _source(repository_root, tmp_path)

    result = build_current_market_consensus(source)
    summary = result.safe_summary()
    fixture = result.fixture_markets[0]

    assert result.contract == "GW1_CURRENT_MARKET_CONSENSUS"
    assert result.as_of == APPROVED
    assert result.mapping_cutoff == APPROVED
    assert (
        result.fixture_identity_mode == "DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"
    )
    assert result.policy_sha256 == POLICY_SHA256
    assert result.source_odds_market_semantic_sha256 == source.odds_input.market_semantic_sha256
    assert fixture.official_fpl_fixture_id == 101
    assert fixture.source_book_count == 2
    assert fixture.source_quote_count == 6
    assert fixture.consensus.operator_count == 2
    assert fixture.consensus.provider_count == 1
    assert fixture.consensus.eligible_operator_count == 2
    assert sum(row.consensus_probability for row in fixture.consensus.outcomes) == 1
    assert summary.status == "COMPLETE"
    assert summary.fixture_coverage == "COMPLETE"
    assert summary.persistence_performed is False
    assert summary.database_accessed is False
    assert summary.eligible_operator_count == 2
    assert summary.confidence_grades == {fixture.consensus.confidence_grade: 1}


def test_current_consensus_is_deterministic_and_revalidates_from_serialized_contract(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _source(repository_root, tmp_path)
    first = build_current_market_consensus(source)
    second = build_current_market_consensus(source)

    assert first == second
    assert CurrentMarketConsensusBundle.model_validate_json(first.model_dump_json()) == first


def test_price_change_changes_market_lineage_but_not_canonical_fixture_identity(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    first_source = _source(repository_root, tmp_path / "first")
    value = _odds_value(repository_root)
    value[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = 1.81
    second_source = _source(repository_root, tmp_path / "second", odds_value=value)

    first = build_current_market_consensus(first_source)
    second = build_current_market_consensus(second_source)

    assert first.source_odds_market_semantic_sha256 != second.source_odds_market_semantic_sha256
    assert first.semantic_sha256 != second.semantic_sha256
    assert (
        first.fixture_markets[0].transient_fixture_id
        == second.fixture_markets[0].transient_fixture_id
    )


def test_one_stale_book_is_excluded_and_propagated_as_degradation(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    value = _odds_value(repository_root)
    stale = value[0]["bookmakers"][1]
    stale["last_update"] = "2026-08-20T11:00:00Z"
    stale["markets"][0]["last_update"] = "2026-08-20T11:00:00Z"

    result = build_current_market_consensus(_source(repository_root, tmp_path, odds_value=value))
    fixture = result.fixture_markets[0]

    assert fixture.consensus.eligible_operator_count == 1
    assert [row.reason.value for row in fixture.excluded_books] == ["STALE"]
    assert "BOOK_EXCLUDED_STALE" in fixture.warnings
    assert result.safe_summary().excluded_book_count == 1


def test_missing_market_timestamp_uses_book_timestamp_with_explicit_warning(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    value = _odds_value(repository_root)
    value[0]["bookmakers"][0]["markets"][0].pop("last_update")

    fixture = build_current_market_consensus(
        _source(repository_root, tmp_path, odds_value=value)
    ).fixture_markets[0]

    assert "PROVIDER_MARKET_TIMESTAMP_NOT_PUBLISHED_USED_BOOKMAKER_TIMESTAMP" in fixture.warnings
    first_operator = next(
        row for row in fixture.consensus.operator_markets if row.operator_key == "book_alpha"
    )
    assert first_operator.observed_at == datetime(2026, 8, 20, 11, 59, tzinfo=UTC)


def test_all_stale_books_fail_closed_without_model_only_imputation(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    value = _odds_value(repository_root)
    for bookmaker in value[0]["bookmakers"]:
        bookmaker["last_update"] = "2026-08-20T11:00:00Z"
        bookmaker["markets"][0]["last_update"] = "2026-08-20T11:00:00Z"

    with pytest.raises(IngestionError, match="no fresh complete") as error:
        build_current_market_consensus(_source(repository_root, tmp_path, odds_value=value))

    assert error.value.code == "NO_ELIGIBLE_MARKET"
    assert len(error.value.details["excluded_books"]) == 2


def test_independent_revalidation_rejects_tampered_source_market_values(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    source = _source(repository_root, tmp_path)
    event = source.odds_input.events[0]
    bookmaker = event.bookmakers[0]
    market = bookmaker.markets[0]
    outcome = market.outcomes[0].model_copy(update={"decimal_price": Decimal("9.99")})
    tampered_market = market.model_copy(update={"outcomes": (outcome, *market.outcomes[1:])})
    tampered_book = bookmaker.model_copy(update={"markets": (tampered_market,)})
    tampered_event = event.model_copy(update={"bookmakers": (tampered_book, *event.bookmakers[1:])})
    tampered_odds = source.odds_input.model_copy(update={"events": (tampered_event,)})
    tampered_source = source.model_copy(update={"odds_input": tampered_odds})

    with pytest.raises(IngestionError, match="independent revalidation"):
        build_current_market_consensus(tampered_source)


def test_bundle_rejects_tampered_stage6_result_even_with_valid_shape(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    result = build_current_market_consensus(_source(repository_root, tmp_path))
    payload = json.loads(result.model_dump_json())
    payload["fixture_markets"][0]["consensus"]["result_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="lineage is inconsistent"):
        CurrentMarketConsensusBundle.model_validate_json(json.dumps(payload))


def test_bundle_rejects_missing_or_duplicated_fixture_coverage(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    result = build_current_market_consensus(_source(repository_root, tmp_path))
    missing = json.loads(result.model_dump_json())
    missing["fixture_markets"] = ()
    duplicated = json.loads(result.model_dump_json())
    duplicated["fixture_markets"] = (
        duplicated["fixture_markets"][0],
        duplicated["fixture_markets"][0],
    )

    with pytest.raises(ValidationError):
        CurrentMarketConsensusBundle.model_validate_json(json.dumps(missing))
    with pytest.raises(ValidationError, match="lineage is inconsistent"):
        CurrentMarketConsensusBundle.model_validate_json(json.dumps(duplicated))
