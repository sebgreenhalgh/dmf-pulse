"""Offline canonical-mapping and market-effect boundary oracles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.mapping import (
    OddsMappingPlan,
    _strict_object,
    load_mapping_plan,
)
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.odds.persistence import (
    OddsPersistence,
    _advisory_lock,
    _ensure_external_mapping,
    _uuid,
    ensure_provider,
)
from dmf_pulse.markets.models import MarketOutcome, MarketState
from dmf_pulse.markets.repository import _uuid as market_uuid

pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


class _Result:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> object:
        return self.value

    def one(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalars(self) -> object:
        return self.value

    def __iter__(self):
        return iter(self.value if isinstance(self.value, list) else ())


class _SequenceSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def execute(self, *_args: object, **_kwargs: object) -> _Result:
        value = self.values.pop(0) if self.values else None
        if isinstance(value, BaseException):
            raise value
        return _Result(value)


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("synthetic database failure")
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("synthetic", {}, _SqlStateError(sqlstate))


def _parsed(repository_root: Path):
    return parse_odds_payload(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
    )


def test_odds_persistence_identifier_and_lock_failures_are_typed() -> None:
    with pytest.raises(IngestionError, match="invalid identifier"):
        _uuid("not-a-uuid")
    with pytest.raises(IngestionError) as retryable:
        _advisory_lock(_SequenceSession([_db_error("55P03")]), "synthetic")  # type: ignore[arg-type]
    assert retryable.value.code == "DATABASE_RETRYABLE"
    assert retryable.value.retryable is True
    with pytest.raises(IngestionError) as unavailable:
        _advisory_lock(_SequenceSession([_db_error("08006")]), "synthetic")  # type: ignore[arg-type]
    assert unavailable.value.code == "DATABASE_UNAVAILABLE"


def test_provider_and_external_mapping_conflicts_are_rejected() -> None:
    provider_session = _SequenceSession(
        [
            None,
            None,
            {
                "display_name": "conflict",
                "provider_id": UUID(int=1),
                "provider_type": "ODDS_PROVIDER",
                "rights_profile_key": None,
            },
        ]
    )
    with pytest.raises(IngestionError, match="provider identity"):
        ensure_provider(
            provider_session,  # type: ignore[arg-type]
            provider_key="synthetic",
            display_name="Synthetic",
            provider_type="ODDS_PROVIDER",
            rights_profile_key=None,
        )

    mapping_session = _SequenceSession(
        [
            None,
            None,
            {
                "canonical_entity_id": UUID(int=99),
                "external_identifier_id": UUID(int=2),
            },
        ]
    )
    with pytest.raises(IngestionError, match="maps ambiguously"):
        _ensure_external_mapping(
            mapping_session,  # type: ignore[arg-type]
            provider_id=UUID(int=1),
            season_id=None,
            namespace="synthetic.namespace",
            entity_type="BETTING_OPERATOR",
            external_id="external",
            canonical_id=UUID(int=3),
            product="synthetic",
            snapshot_id=UUID(int=4),
            observed_at=NOW,
        )


def _persistence(**values: object) -> OddsPersistence:
    persistence = object.__new__(OddsPersistence)
    for key, value in values.items():
        setattr(persistence, key, value)
    return persistence


def test_season_fixture_operator_and_team_mapping_conflicts_fail_closed(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = load_mapping_plan(repository_root / "fixtures/odds/ODD-005/mapping_plan.json")
    parsed = _parsed(repository_root)
    event = parsed.events[0]
    bookmaker = event.bookmakers[0]

    missing_season = _persistence(session=_SequenceSession([None]), mapping_plan=plan)
    with pytest.raises(IngestionError, match="season context"):
        missing_season._season_context()

    drifted_plan = plan.model_copy(update={"season_code": "wrong-season"})
    fixture_drift = _persistence(session=_SequenceSession([]), mapping_plan=drifted_plan)
    monkeypatch.setattr(
        OddsPersistence,
        "_season_context",
        lambda _self: (UUID(int=1), UUID(int=2)),
    )
    with pytest.raises(IngestionError, match="lookup season"):
        fixture_drift.resolve_fixture(event)

    unresolved_fixture = _persistence(
        session=_SequenceSession([[]]), mapping_plan=plan, captured_at=NOW
    )
    with pytest.raises(IngestionError, match="official fixture mapping"):
        unresolved_fixture.resolve_fixture(event)

    fixture_id = UUID(int=10)
    missing_fixture = _persistence(
        session=_SequenceSession(
            [
                [
                    {
                        "canonical_entity_id": fixture_id,
                        "provider_key": "official_fpl",
                    }
                ],
                None,
            ]
        ),
        mapping_plan=plan,
        captured_at=NOW,
    )
    with pytest.raises(IngestionError, match="mapped fixture context"):
        missing_fixture.resolve_fixture(event)

    title_drift = _persistence(mapping_plan=plan, session=_SequenceSession([]))
    with pytest.raises(IngestionError, match="title contradicts"):
        title_drift.resolve_operator(bookmaker.model_copy(update={"title": "Wrong"}))

    operator_drift = _persistence(
        mapping_plan=plan,
        session=_SequenceSession(
            [None, None, {"display_name": "Wrong", "operator_id": UUID(int=11)}]
        ),
    )
    with pytest.raises(IngestionError, match="canonical operator conflicts"):
        operator_drift.resolve_operator(bookmaker)

    wrong_team = _persistence(session=_SequenceSession([[UUID(int=99)]]))
    with pytest.raises(IngestionError, match="participant mapping"):
        wrong_team._validate_team_mapping(UUID(int=1), UUID(int=2), "1", "Home")

    wrong_alias = _persistence(session=_SequenceSession([[UUID(int=2)], []]))
    with pytest.raises(IngestionError, match="participant label"):
        wrong_alias._validate_team_mapping(UUID(int=1), UUID(int=2), "1", "Home")


def test_pre_match_and_outcome_semantics_reject_unsupported_effects(
    repository_root: Path,
) -> None:
    parsed = _parsed(repository_root)
    event = parsed.events[0]
    bookmaker = event.bookmakers[0]
    market = bookmaker.markets[0]
    persistence = _persistence(captured_at=bookmaker.last_update - timedelta(seconds=1))
    with pytest.raises(IngestionError, match="future-dated"):
        persistence._validate_pre_match(bookmaker, market, event.commence_time)

    lined = market.model_copy(
        update={"outcomes": (market.outcomes[0].model_copy(update={"point": Decimal("1")}),)}
    )
    with pytest.raises(IngestionError, match="must not contain a line"):
        OddsPersistence._outcomes(event, lined)

    unknown = market.model_copy(
        update={"outcomes": (market.outcomes[0].model_copy(update={"name": "Unknown"}),)}
    )
    with pytest.raises(IngestionError, match="contradicts fixture"):
        OddsPersistence._outcomes(event, unknown)

    conflicting = market.model_copy(
        update={
            "outcomes": (
                market.outcomes[0],
                market.outcomes[0].model_copy(update={"price": Decimal("9.99")}),
            )
        }
    )
    with pytest.raises(IngestionError, match="conflicting"):
        OddsPersistence._outcomes(event, conflicting)

    mapped, state, missing = OddsPersistence._outcomes(
        event,
        market.model_copy(update={"outcomes": ()}),
    )
    assert mapped == {}
    assert state is MarketState.UNAVAILABLE
    assert set(missing) == {item.value for item in MarketOutcome}


def test_mapping_plan_and_representation_boundary_conflicts(
    repository_root: Path,
) -> None:
    mapping_path = repository_root / "fixtures/odds/ODD-005/mapping_plan.json"
    value = json.loads(mapping_path.read_text(encoding="utf-8"))

    invalid_time = json.loads(json.dumps(value))
    invalid_time["fixture_mappings"][0]["expected_commence_time"] = 1
    with pytest.raises(ValidationError, match="RFC3339"):
        OddsMappingPlan.model_validate(invalid_time)

    duplicate_event = json.loads(json.dumps(value))
    duplicate_event["fixture_mappings"].append(duplicate_event["fixture_mappings"][0])
    with pytest.raises(ValidationError, match="provider event"):
        OddsMappingPlan.model_validate(duplicate_event)

    with pytest.raises(ValueError, match="duplicate mapping-plan key"):
        _strict_object([("duplicate", 1), ("duplicate", 2)])

    plan = load_mapping_plan(mapping_path)
    representation = _persistence(
        session=_SequenceSession([None, {"provider_id": UUID(int=99)}]),
        odds_provider_id=UUID(int=1),
        mapping_plan=plan,
    )
    with pytest.raises(IngestionError, match="market representation conflicts"):
        representation._representation(
            fixture_mapping_id=UUID(int=2),
            operator_mapping_id=UUID(int=3),
            market_id=UUID(int=4),
        )

    with pytest.raises(IngestionError, match="invalid identifier"):
        market_uuid("not-a-uuid")
