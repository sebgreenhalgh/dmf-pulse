"""Offline canonical-mapping and market-effect boundary oracles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from psycopg.types.range import Range
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

import dmf_pulse.ingestion.odds.persistence as persistence_module
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
    attest_publication_batch,
    ensure_provider,
)
from dmf_pulse.markets.models import MarketOutcome, MarketState
from dmf_pulse.markets.repository import MarketObservationRepository
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

    def scalar(self, *_args: object, **_kwargs: object) -> object:
        value = self.values.pop(0) if self.values else None
        if isinstance(value, BaseException):
            raise value
        return value


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
            valid_during=Range(NOW, None, bounds="[)"),
            resolution_cutoff=NOW,
            system_known_at=NOW,
            evidence_class="TEST_ONLY",
            reviewer="NRM-006 synthetic test",
        )

    with pytest.raises(IngestionError, match="lower bound"):
        _ensure_external_mapping(
            _SequenceSession([None, None]),  # type: ignore[arg-type]
            provider_id=UUID(int=1),
            season_id=None,
            namespace="synthetic.namespace",
            entity_type="BETTING_OPERATOR",
            external_id="external",
            canonical_id=UUID(int=3),
            product="synthetic",
            snapshot_id=UUID(int=4),
            valid_during=Range(None, None, bounds="()"),
            resolution_cutoff=NOW,
            system_known_at=NOW,
            evidence_class="TEST_ONLY",
            reviewer="NRM-006 synthetic test",
        )


def test_publication_attestation_converges_or_fails_retryably() -> None:
    created = NOW + timedelta(seconds=1)
    assert (
        attest_publication_batch(
            _SequenceSession([created]),  # type: ignore[arg-type]
            publication_batch_id=UUID(int=1),
            usable_at=created,
        )
        == created
    )
    assert (
        attest_publication_batch(
            _SequenceSession([None, created]),  # type: ignore[arg-type]
            publication_batch_id=UUID(int=1),
            usable_at=created,
        )
        == created
    )
    with pytest.raises(IngestionError) as raced:
        attest_publication_batch(
            _SequenceSession([None, None]),  # type: ignore[arg-type]
            publication_batch_id=UUID(int=1),
            usable_at=created,
        )
    assert raced.value.code == "DATABASE_RETRYABLE"
    assert raced.value.retryable is True


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
        lambda _self: (UUID(int=1), UUID(int=2), Range(NOW, None, bounds="[)")),
    )
    with pytest.raises(IngestionError, match="lookup season"):
        fixture_drift.resolve_fixture(event)

    unresolved_fixture = _persistence(
        session=_SequenceSession([[]]),
        mapping_plan=plan,
        captured_at=NOW,
        mapping_cutoff=NOW,
    )
    with pytest.raises(IngestionError, match="fixture mapping is unresolved"):
        unresolved_fixture.resolve_fixture(event)

    ambiguous_provider = _persistence(
        session=_SequenceSession(
            [
                [
                    {
                        "canonical_entity_id": UUID(int=10),
                        "external_identifier_id": UUID(int=30),
                        "provider_id": UUID(int=20),
                        "provider_key": "synthetic_fpl",
                    },
                    {
                        "canonical_entity_id": UUID(int=10),
                        "external_identifier_id": UUID(int=31),
                        "provider_id": UUID(int=21),
                        "provider_key": "synthetic_fpl",
                    },
                ]
            ]
        ),
        mapping_plan=plan,
        captured_at=NOW,
        mapping_cutoff=NOW,
    )
    with pytest.raises(IngestionError, match="provider is ambiguous"):
        ambiguous_provider.resolve_fixture(event)

    fixture_id = UUID(int=10)
    non_test_plan = plan.model_copy(update={"evidence_class": "OFFICIAL"})
    missing_fixture = _persistence(
        session=_SequenceSession(
            [
                [
                    {
                        "canonical_entity_id": fixture_id,
                        "external_identifier_id": UUID(int=30),
                        "provider_key": "official_fpl",
                    }
                ],
                None,
            ]
        ),
        mapping_plan=non_test_plan,
        captured_at=NOW,
        mapping_cutoff=NOW,
    )
    with pytest.raises(IngestionError, match="mapped fixture context"):
        missing_fixture.resolve_fixture(event)

    commence_conflict = _persistence(
        session=_SequenceSession(
            [
                [
                    {
                        "canonical_entity_id": fixture_id,
                        "external_identifier_id": UUID(int=30),
                        "provider_key": "official_fpl",
                    }
                ],
                {
                    "home_team_id": UUID(int=20),
                    "away_team_id": UUID(int=21),
                },
                None,
            ]
        ),
        mapping_plan=non_test_plan,
        captured_at=NOW,
        mapping_cutoff=NOW,
    )
    with monkeypatch.context() as local_patch:
        local_patch.setattr(OddsPersistence, "_validate_team_mapping", lambda *_a, **_k: None)
        with pytest.raises(IngestionError, match="commence time"):
            commence_conflict.resolve_fixture(event)

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

    wrong_team = _persistence(
        session=_SequenceSession(
            [
                [
                    {
                        "canonical_entity_id": UUID(int=99),
                        "external_identifier_id": UUID(int=1),
                    }
                ]
            ]
        ),
        mapping_cutoff=NOW,
    )
    with pytest.raises(IngestionError, match="participant mapping"):
        wrong_team._validate_team_mapping(
            UUID(int=1),
            UUID(int=2),
            "1",
            "Home",
            lookup_provider="synthetic_fpl",
            domain_instant=NOW,
        )

    wrong_alias = _persistence(
        session=_SequenceSession(
            [
                [
                    {
                        "canonical_entity_id": UUID(int=2),
                        "external_identifier_id": UUID(int=1),
                    }
                ],
                [],
            ]
        ),
        mapping_cutoff=NOW,
    )
    with pytest.raises(IngestionError, match="participant label"):
        wrong_alias._validate_team_mapping(
            UUID(int=1),
            UUID(int=2),
            "1",
            "Home",
            lookup_provider="synthetic_fpl",
            domain_instant=NOW,
        )


def test_official_fixture_resolution_reuses_unique_mapping_lineage(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping_path = repository_root / "fixtures/odds/ODD-005/mapping_plan.json"
    value = json.loads(mapping_path.read_text(encoding="utf-8"))
    value["evidence_class"] = "OFFICIAL"
    value["status"] = "APPROVED"
    value["fixture_mappings"][0]["canonical_fixture_lookup"]["provider"] = "official_fpl"
    plan = OddsMappingPlan.model_validate(value)
    event = _parsed(repository_root).events[0]
    fixture_id = UUID(int=10)
    season_id = UUID(int=11)
    competition_id = UUID(int=12)
    home_team_id = UUID(int=20)
    away_team_id = UUID(int=21)
    kickoff_at = plan.fixture(event.id).expected_commence_time
    session = _SequenceSession(
        [
            [
                {
                    "canonical_entity_id": fixture_id,
                    "external_identifier_id": UUID(int=30),
                    "provider_id": UUID(int=31),
                    "provider_key": "official_fpl",
                }
            ],
            {"home_team_id": home_team_id, "away_team_id": away_team_id},
            {"fixture_observation_id": UUID(int=50), "kickoff_at": kickoff_at},
        ]
    )
    persistence = _persistence(
        session=session,
        mapping_plan=plan,
        captured_at=NOW,
        mapping_cutoff=NOW,
        odds_provider_id=UUID(int=32),
        snapshot_id=UUID(int=33),
    )
    team_lineage = {home_team_id: UUID(int=40), away_team_id: UUID(int=41)}
    monkeypatch.setattr(
        OddsPersistence,
        "_season_context",
        lambda _self: (season_id, competition_id, Range(NOW, None, bounds="[)")),
    )
    monkeypatch.setattr(
        OddsPersistence,
        "_validate_team_mapping",
        lambda _self, _season_id, team_id, *_args, **_kwargs: [team_lineage[team_id]],
    )
    monkeypatch.setattr(
        persistence_module,
        "_ensure_external_mapping",
        lambda *_args, **_kwargs: UUID(int=60),
    )

    resolved = persistence.resolve_fixture(event)

    assert resolved.fixture_mapping_id == UUID(int=30)
    assert resolved.home_team_mapping_id == UUID(int=40)
    assert resolved.away_team_mapping_id == UUID(int=41)
    assert resolved.event_mapping_id == UUID(int=60)


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

    test_only_official = json.loads(json.dumps(value))
    test_only_official["fixture_mappings"][0]["canonical_fixture_lookup"]["provider"] = (
        "official_fpl"
    )
    with pytest.raises(ValidationError, match="only synthetic_fpl"):
        OddsMappingPlan.model_validate(test_only_official)

    production_synthetic = json.loads(json.dumps(value))
    production_synthetic["evidence_class"] = "OFFICIAL"
    production_synthetic["status"] = "APPROVED"
    with pytest.raises(ValidationError, match="cannot use synthetic"):
        OddsMappingPlan.model_validate(production_synthetic)

    production_wrong_status = json.loads(json.dumps(value))
    production_wrong_status["evidence_class"] = "OFFICIAL"
    production_wrong_status["fixture_mappings"][0]["canonical_fixture_lookup"]["provider"] = (
        "official_fpl"
    )
    with pytest.raises(ValidationError, match="production mapping"):
        OddsMappingPlan.model_validate(production_wrong_status)

    production = json.loads(json.dumps(production_wrong_status))
    production["status"] = "APPROVED"
    assert OddsMappingPlan.model_validate(production).evidence_class == "OFFICIAL"

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


def test_public_fixture_resolution_requires_exactly_one_temporal_mapping() -> None:
    repository = MarketObservationRepository(_SequenceSession([[]]))  # type: ignore[arg-type]
    with pytest.raises(IngestionError) as missing:
        repository.resolve_fixture(
            external_provider="synthetic_fpl",
            external_id="101",
            season_code="2026/27",
            as_of=NOW,
        )
    assert missing.value.code == "MAPPING_CONFLICT"

    fixture_id = UUID(int=101)
    repository = MarketObservationRepository(
        _SequenceSession([[fixture_id]])  # type: ignore[arg-type]
    )
    assert (
        repository.resolve_fixture(
            external_provider="synthetic_fpl",
            external_id="101",
            season_code="2026/27",
            as_of=NOW,
        )
        == fixture_id
    )
