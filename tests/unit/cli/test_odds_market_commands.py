"""Offline in-process CLI oracles for ODD-005 and raw market queries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import market_cmd, odds_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.models import (
    OddsIngestionResult,
    OddsQuality,
    ProviderFailure,
    ProviderFailureCode,
)
from dmf_pulse.ingestion.odds.service import OddsOperationOutcome
from dmf_pulse.markets.models import (
    MarketBook,
    MarketNormalisationResult,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
    NormalisationStatus,
)

pytestmark = pytest.mark.unit
runner = CliRunner()
AS_OF_TEXT = "2026-08-20T12:05:00Z"
AS_OF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)


def _complete_outcome() -> OddsOperationOutcome:
    return OddsOperationOutcome(
        result=OddsIngestionResult(
            status="COMPLETE",
            source_snapshot_id=UUID(int=1),
            events_seen=1,
            operator_books_seen=2,
            complete_books_created=2,
            incomplete_books_created=0,
            observations_created=6,
            observations_reused=0,
            quarantined=0,
            quota=None,
            quality=OddsQuality(status="PASS"),
            error=None,
        ),
        exit_code=0,
    )


def _blocked_outcome() -> OddsOperationOutcome:
    code = ProviderFailureCode.CREDENTIAL_UNAVAILABLE
    return OddsOperationOutcome(
        result=OddsIngestionResult(
            status="BLOCKED",
            source_snapshot_id=None,
            events_seen=0,
            operator_books_seen=0,
            complete_books_created=0,
            incomplete_books_created=0,
            observations_created=0,
            observations_reused=0,
            quarantined=0,
            quota=None,
            quality=OddsQuality(status="BLOCKING", blockers=(code.value,)),
            error=ProviderFailure(
                code=code,
                message="approved runtime credential is unavailable",
                retryable=False,
                transport_called=False,
            ),
        ),
        exit_code=4,
    )


def _validate_args(path: Path) -> list[str]:
    return [
        "ingest",
        "odds",
        "validate",
        "--provider",
        "the_odds_api",
        "--input",
        str(path),
        "--contract-version",
        "the-odds-api-v4-reference-v1",
        "--output",
        "json",
    ]


def test_odds_validate_cli_accepts_the_frozen_fixture(repository_root: Path) -> None:
    result = runner.invoke(
        app,
        _validate_args(repository_root / "fixtures/odds/ODD-005/happy_path.json"),
    )
    assert result.exit_code == 0
    value = json.loads(result.stdout)
    assert value["status"] == "VALID"
    assert value["events_seen"] == 1
    assert value["operator_books_seen"] == 2
    assert len(value["payload_semantic_sha256"]) == 64
    assert len(value["schema_fingerprint"]) == 64


def test_odds_replay_cli_builds_typed_request_and_emits_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def replay(_self: object, request: object) -> OddsOperationOutcome:
        captured["request"] = request
        return _complete_outcome()

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "replay", replay)
    fixture_set = tmp_path / "fixtures"
    result = runner.invoke(
        app,
        [
            "ingest",
            "odds",
            "replay",
            "--fixture-set",
            str(fixture_set),
            "--scenario",
            "happy_path",
            "--information-cutoff",
            "2026-08-21T17:30:00Z",
            "--rights-profile",
            "synthetic_the_odds_api_v1",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "COMPLETE"
    request = captured["request"]
    assert request.fixture_set == fixture_set
    assert request.scenario == "happy_path"
    assert request.information_cutoff == datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    assert request.rights_profile_id == "synthetic_the_odds_api_v1"
    assert request.database_url_ref == DATABASE_REF


def test_odds_import_cli_builds_typed_request_and_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def import_payload(_self: object, request: object) -> OddsOperationOutcome:
        captured["request"] = request
        return _complete_outcome()

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "import_payload", import_payload)
    base_args = [
        "ingest",
        "odds",
        "import",
        "--provider",
        "the_odds_api",
        "--input",
        str(tmp_path / "payload.json"),
        "--mapping-plan",
        str(tmp_path / "mapping.json"),
        "--captured-at",
        "2026-08-20T12:00:00Z",
        "--information-cutoff",
        "2026-08-21T17:30:00Z",
        "--rights-profile",
        "synthetic_the_odds_api_v1",
        "--output",
        "json",
    ]
    result = runner.invoke(app, base_args)
    assert result.exit_code == 0
    request = captured["request"]
    assert request.captured_at == datetime(2026, 8, 20, 12, tzinfo=UTC)
    assert request.information_cutoff == datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    assert request.database_url_ref == DATABASE_REF

    unsupported = base_args.copy()
    unsupported[unsupported.index("the_odds_api")] = "unknown"
    result = runner.invoke(app, unsupported)
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"


def test_odds_snapshot_cli_preserves_controlled_credential_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def snapshot(_self: object, **kwargs: object) -> OddsOperationOutcome:
        captured.update(kwargs)
        return _blocked_outcome()

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "snapshot", snapshot)
    result = runner.invoke(
        app,
        [
            "ingest",
            "odds",
            "snapshot",
            "--provider",
            "the_odds_api",
            "--competition-key",
            "PL",
            "--sport-key",
            "soccer_epl",
            "--region",
            "uk",
            "--market",
            "h2h",
            "--as-of",
            AS_OF_TEXT,
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 4
    value = json.loads(result.stdout)
    assert value["error"] == {
        "code": "CREDENTIAL_UNAVAILABLE",
        "message": "approved runtime credential is unavailable",
        "retryable": False,
        "transport_called": False,
    }
    assert captured == {
        "as_of": AS_OF,
        "competition_key": "PL",
        "database_url_ref": DATABASE_REF,
        "market": "h2h",
        "provider": "the_odds_api",
        "region": "uk",
        "sport_key": "soccer_epl",
    }


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    (
        ("CREDENTIAL_UNAVAILABLE", 4),
        ("TLS_ERROR", 5),
        ("POST_CUTOFF", 2),
        ("DATABASE_UNAVAILABLE", 6),
    ),
)
def test_odds_cli_failure_exit_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    code: str,
    expected_exit: int,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise IngestionError(code, "safe synthetic failure")

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "validate", fail)
    result = runner.invoke(app, _validate_args(tmp_path / "unused.json"))
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["error"]["code"] == code


@pytest.mark.parametrize("command", ("validate", "replay", "snapshot"))
def test_odds_cli_rejects_internal_result_type_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    monkeypatch.setattr(odds_cmd.OddsIngestionService, command, lambda *_a, **_k: object())
    if command == "validate":
        args = _validate_args(tmp_path / "unused.json")
    elif command == "replay":
        args = [
            "ingest",
            "odds",
            "replay",
            "--fixture-set",
            str(tmp_path),
            "--scenario",
            "happy_path",
            "--information-cutoff",
            "2026-08-21T17:30:00Z",
            "--rights-profile",
            "synthetic_the_odds_api_v1",
        ]
    else:
        args = [
            "ingest",
            "odds",
            "snapshot",
            "--provider",
            "the_odds_api",
            "--competition-key",
            "PL",
            "--sport-key",
            "soccer_epl",
            "--region",
            "uk",
            "--market",
            "h2h",
            "--as-of",
            AS_OF_TEXT,
        ]
    result = runner.invoke(app, args)
    assert result.exit_code == 6
    assert json.loads(result.stdout)["error"]["code"] == "INTERNAL_INVARIANT"


@pytest.mark.parametrize(
    ("extra_args", "message"),
    (
        (["--output", "text"], "--output must be json"),
        (["--information-cutoff", "not-a-time"], "--information-cutoff"),
    ),
)
def test_odds_replay_rejects_usage_before_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    extra_args: list[str],
    message: str,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("service must not be called")

    monkeypatch.setattr(odds_cmd.OddsIngestionService, "replay", forbidden)
    args = [
        "ingest",
        "odds",
        "replay",
        "--fixture-set",
        str(tmp_path),
        "--scenario",
        "happy_path",
        "--information-cutoff",
        "2026-08-21T17:30:00Z",
        "--rights-profile",
        "synthetic_the_odds_api_v1",
    ]
    option = extra_args[0]
    if option in args:
        args[args.index(option) + 1] = extra_args[1]
    else:
        args.extend(extra_args)
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    assert message in json.loads(result.stdout)["error"]["message"]


def _market_result() -> MarketQueryResult:
    observation = MarketObservation(
        fixture_id=UUID(int=1),
        market_id=UUID(int=2),
        selection_id=UUID(int=3),
        operator_id=UUID(int=4),
        outcome=MarketOutcome.HOME,
        decimal_odds=Decimal("1.80"),
        observed_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        received_at=datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
        usable_at=datetime(2026, 8, 20, 12, 2, tzinfo=UTC),
        source_snapshot_id=UUID(int=5),
        market_state=MarketState.INCOMPLETE,
        contract_version="the-odds-api-v4-reference-v1",
    )
    return MarketQueryResult(
        fixture_id=UUID(int=1),
        as_of=AS_OF,
        books=(
            MarketBook(
                operator_id=UUID(int=4),
                operator_key="SYNTHETIC_BOOK",
                market_state=MarketState.INCOMPLETE,
                observations=(observation,),
            ),
        ),
        observation_count=1,
    )


def _market_args(*extra: str) -> list[str]:
    return [
        "market",
        "observations",
        "--fixture-external-provider",
        "official_fpl",
        "--fixture-external-id",
        "101",
        "--season-code",
        "2026/27",
        "--as-of",
        AS_OF_TEXT,
        *extra,
    ]


def test_market_observations_cli_success_preserves_source_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def observations(_self: object, **kwargs: object) -> MarketQueryResult:
        captured.update(kwargs)
        return _market_result()

    monkeypatch.setattr(market_cmd.MarketService, "observations", observations)
    result = runner.invoke(app, _market_args("--output", "json"))
    assert result.exit_code == 0
    value = json.loads(result.stdout)
    assert value["books"][0]["observations"][0]["decimal_odds"] == "1.80"
    assert value["observation_count"] == 1
    assert captured == {
        "as_of": AS_OF,
        "database_url_ref": DATABASE_REF,
        "fixture_external_id": "101",
        "fixture_external_provider": "official_fpl",
        "season_code": "2026/27",
    }


@pytest.mark.parametrize(
    "args",
    (
        _market_args("--output", "text"),
        [*_market_args(), "--as-of", "invalid"],
    ),
)
def test_market_observations_cli_rejects_bad_usage_before_service(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
) -> None:
    monkeypatch.setattr(
        market_cmd.MarketService,
        "observations",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    (("MAPPING_CONFLICT", 3), ("NO_USABLE_BUNDLE", 2), ("DATABASE_UNAVAILABLE", 6)),
)
def test_market_observations_cli_service_error_exit_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    expected_exit: int,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise IngestionError(code, "safe market failure")

    monkeypatch.setattr(market_cmd.MarketService, "observations", fail)
    result = runner.invoke(app, _market_args())
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["error"]["code"] == code


def _normalise_args(*extra: str) -> list[str]:
    return [
        "market",
        "normalise",
        "--fixture-external-provider",
        "synthetic_fpl",
        "--fixture-external-id",
        "101",
        "--season-code",
        "2026/27",
        "--as-of",
        AS_OF_TEXT,
        *extra,
    ]


def _non_consensus_result(status: NormalisationStatus) -> MarketNormalisationResult:
    return MarketNormalisationResult(
        status=status,
        fixture_id=UUID(int=1) if status is NormalisationStatus.INSUFFICIENT else None,
        as_of=AS_OF,
        consensus=None,
        excluded_books=(),
        warnings=(),
        error_code=(
            "NO_ELIGIBLE_COMPLETE_BOOK"
            if status is NormalisationStatus.INSUFFICIENT
            else "MAPPING_UNAVAILABLE"
        ),
    )


@pytest.mark.parametrize(
    "args",
    (
        _normalise_args("--output", "text"),
        [*_normalise_args(), "--as-of", "invalid"],
    ),
)
def test_market_normalise_rejects_usage_before_service(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
) -> None:
    monkeypatch.setattr(
        market_cmd.MarketService,
        "normalise",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "USAGE_INVALID"


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    (("MAPPING_CONFLICT", 4), ("QUALITY_BLOCKED", 4), ("DATABASE_UNAVAILABLE", 1)),
)
def test_market_normalise_service_error_exit_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    expected_exit: int,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise IngestionError(code, "safe normalisation failure")

    monkeypatch.setattr(market_cmd.MarketService, "normalise", fail)
    result = runner.invoke(app, _normalise_args())
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["error"]["code"] == code


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    ((NormalisationStatus.INSUFFICIENT, 2), (NormalisationStatus.BLOCKED, 4)),
)
def test_market_normalise_emits_typed_non_success_status(
    monkeypatch: pytest.MonkeyPatch,
    status: NormalisationStatus,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        market_cmd.MarketService,
        "normalise",
        lambda *_a, **_k: _non_consensus_result(status),
    )
    result = runner.invoke(app, _normalise_args("--output", "json"))
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["status"] == status.value
