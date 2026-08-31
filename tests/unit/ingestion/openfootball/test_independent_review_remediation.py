from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dmf_pulse.cli import current_score_prior_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest as LeafScorePriorRequest
from dmf_pulse.football_events.service import ScorePriorRequest as LegacyScorePriorRequest
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.client import OpenFootballHttpRequest
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    OpenFootballProviderConfig,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorBundle,
    CurrentScorePriorResult,
    CurrentScorePriorService,
    CurrentScorePriorSummary,
    build_current_score_prior_bundle,
    score_prior_request_from_bundle,
)

from .conftest import FakeTransport, ticking_clock

_START = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
_CUTOFF = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
_PAST = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
_FIXTURE_ID = UUID("10000000-0000-7000-8000-000000000801")
_COMPETITION_ID = UUID("30000000-0000-7000-8000-000000000001")
_HOME_TEAM_ID = UUID("20000000-0000-7000-8000-000000000001")
_AWAY_TEAM_ID = UUID("20000000-0000-7000-8000-000000000002")


def _service(
    config: OpenFootballProviderConfig,
    transport: object,
) -> CurrentScorePriorService:
    return CurrentScorePriorService(
        provider_config=config,
        rights_profiles=load_rights_profiles(),
        transport=transport,  # type: ignore[arg-type]
        clock=ticking_clock(_START),
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    )


def _result(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> CurrentScorePriorResult:
    config, bodies = approved_snapshot
    return _service(config, FakeTransport(bodies)).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=_CUTOFF,
            rights_profile_id=APPROVED_PROFILE_ID,
        )
    )


def _bundle(result: CurrentScorePriorResult, **updates: object) -> CurrentScorePriorBundle:
    values: dict[str, object] = {
        "as_of": _CUTOFF,
        "away_team_id": _AWAY_TEAM_ID,
        "competition_id": _COMPETITION_ID,
        "fixture_id": _FIXTURE_ID,
        "home_team_id": _HOME_TEAM_ID,
    }
    values.update(updates)
    return build_current_score_prior_bundle(result, **values)  # type: ignore[arg-type]


def _convert(bundle: CurrentScorePriorBundle, **updates: object) -> LeafScorePriorRequest:
    values: dict[str, object] = {
        "as_of": bundle.as_of,
        "away_team_id": bundle.away_team_id,
        "competition_id": bundle.competition_id,
        "fixture_id": bundle.fixture_id,
        "home_team_id": bundle.home_team_id,
    }
    values.update(updates)
    return score_prior_request_from_bundle(bundle, **values)  # type: ignore[arg-type]


@pytest.mark.unit
def test_csp_ir_001_fixture_bundle_and_exact_conversion(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    result = _result(approved_snapshot)
    bundle = _bundle(result)

    assert bundle.fixture_id == _FIXTURE_ID
    assert bundle.competition_id == _COMPETITION_ID
    assert bundle.home_team_id == _HOME_TEAM_ID
    assert bundle.away_team_id == _AWAY_TEAM_ID
    assert bundle.source_result_semantic_sha256 == result.semantic_sha256
    assert bundle.source_usable_at == result.provenance.usable_at
    assert bundle.source_mode == "RECONSTRUCTED"
    assert _convert(bundle) is bundle.score_prior_request
    assert bundle.score_prior_request == LeafScorePriorRequest(
        home_goal_rate=Decimal("1.613158"),
        away_goal_rate=Decimal("1.374561"),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fixture_id", UUID("10000000-0000-7000-8000-000000000899")),
        ("competition_id", UUID("30000000-0000-7000-8000-000000000099")),
        ("home_team_id", UUID("20000000-0000-7000-8000-000000000099")),
        ("away_team_id", UUID("20000000-0000-7000-8000-000000000098")),
        ("as_of", datetime(2026, 8, 30, 10, 0, 1, tzinfo=UTC)),
    ],
)
def test_csp_ir_001_downstream_identity_substitution_blocks(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    field: str,
    value: object,
) -> None:
    bundle = _bundle(_result(approved_snapshot))

    with pytest.raises(IngestionError) as caught:
        _convert(bundle, **{field: value})

    assert caught.value.code == "FIXTURE_NOT_APPROVED"


def test_csp_ir_001_home_away_swap_blocks(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    bundle = _bundle(_result(approved_snapshot))

    with pytest.raises(IngestionError) as caught:
        _convert(
            bundle,
            home_team_id=bundle.away_team_id,
            away_team_id=bundle.home_team_id,
        )

    assert caught.value.code == "FIXTURE_NOT_APPROVED"


def test_csp_ir_001_past_as_of_and_identical_teams_block(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    result = _result(approved_snapshot)

    with pytest.raises(IngestionError) as past:
        _bundle(result, as_of=_PAST)
    assert past.value.code == "POST_CUTOFF"

    with pytest.raises(IngestionError) as identical:
        _bundle(result, away_team_id=_HOME_TEAM_ID)
    assert identical.value.code == "VALIDATION_FAILED"


def test_csp_ir_001_usable_at_equality_and_identity_variation(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    result = _result(approved_snapshot)
    baseline = _bundle(result, as_of=result.provenance.usable_at)
    variants = (
        _bundle(result, fixture_id=UUID(int=_FIXTURE_ID.int + 1)),
        _bundle(result, competition_id=UUID(int=_COMPETITION_ID.int + 1)),
        _bundle(result, home_team_id=UUID(int=_HOME_TEAM_ID.int + 10)),
        _bundle(result, away_team_id=UUID(int=_AWAY_TEAM_ID.int + 10)),
        _bundle(result, as_of=_CUTOFF.replace(microsecond=1)),
    )

    assert _convert(baseline).home_goal_rate == Decimal("1.613158")
    assert len({baseline.semantic_sha256, *(item.semantic_sha256 for item in variants)}) == 6


def _mutate_result(payload: dict[str, object], mutation: str) -> None:
    if mutation == "home_rate":
        payload["score_prior_request"]["home_goal_rate"] = "1.700000"  # type: ignore[index]
    elif mutation == "away_rate":
        payload["score_prior_request"]["away_goal_rate"] = "1.700000"  # type: ignore[index]
    elif mutation == "sample_size":
        payload["sample_size"] = 1139
    elif mutation == "home_total":
        payload["home_goal_total"] = 1838
    elif mutation == "source_commit":
        payload["provenance"]["source_commit_sha"] = "0" * 40  # type: ignore[index]
    elif mutation == "usable_at":
        payload["provenance"]["usable_at"] = "2026-08-30T09:00:05Z"  # type: ignore[index]
    elif mutation == "rights":
        payload["provenance"]["rights_profile_id"] = "wrong"  # type: ignore[index]
    else:
        payload["provenance"]["source_mode"] = "LIVE_OBSERVED"  # type: ignore[index]


@pytest.mark.parametrize(
    "mutation",
    [
        "home_rate",
        "away_rate",
        "sample_size",
        "home_total",
        "source_commit",
        "usable_at",
        "rights",
        "source_mode",
    ],
)
def test_csp_ir_002_result_json_tamper_is_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    mutation: str,
) -> None:
    payload = _result(approved_snapshot).model_dump(mode="json")
    _mutate_result(payload, mutation)

    with pytest.raises(ValidationError):
        CurrentScorePriorResult.model_validate_json(json.dumps(payload))


def test_csp_ir_002_result_arbitrary_hash_and_validated_copy_are_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    result = _result(approved_snapshot)
    arbitrary = result.model_dump(mode="json")
    arbitrary["semantic_sha256"] = "f" * 64

    with pytest.raises(ValidationError):
        CurrentScorePriorResult.model_validate(arbitrary)
    with pytest.raises(ValidationError):
        result.model_copy(
            update={
                "score_prior_request": LeafScorePriorRequest(
                    home_goal_rate=Decimal("1.700000"),
                    away_goal_rate=Decimal("1.374561"),
                )
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fixture_id", str(UUID(int=_FIXTURE_ID.int + 1))),
        ("competition_id", str(UUID(int=_COMPETITION_ID.int + 1))),
        ("home_team_id", str(UUID(int=_HOME_TEAM_ID.int + 10))),
        ("away_team_id", str(UUID(int=_AWAY_TEAM_ID.int + 10))),
        ("as_of", "2026-08-30T10:00:01Z"),
        ("source_usable_at", "2026-08-30T09:00:05Z"),
        ("source_mode", "LIVE_OBSERVED"),
    ],
)
def test_csp_ir_002_bundle_json_tamper_is_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    field: str,
    value: object,
) -> None:
    payload = _bundle(_result(approved_snapshot)).model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError):
        CurrentScorePriorBundle.model_validate_json(json.dumps(payload))


def test_csp_ir_002_nested_source_result_tamper_is_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    payload = _bundle(_result(approved_snapshot)).model_dump(mode="json")
    payload["source_result"]["score_prior_request"]["home_goal_rate"] = "1.700000"  # type: ignore[index]

    with pytest.raises(ValidationError):
        CurrentScorePriorBundle.model_validate_json(json.dumps(payload))


def test_csp_ir_002_bundle_request_and_source_identity_tamper_are_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    original = _bundle(_result(approved_snapshot)).model_dump(mode="json")
    request_tamper = json.loads(json.dumps(original))
    request_tamper["score_prior_request"]["home_goal_rate"] = "1.700000"
    source_identity_tamper = json.loads(json.dumps(original))
    source_identity_tamper["source_result_semantic_sha256"] = "f" * 64

    with pytest.raises(ValidationError):
        CurrentScorePriorBundle.model_validate_json(json.dumps(request_tamper))
    with pytest.raises(ValidationError):
        CurrentScorePriorBundle.model_validate_json(json.dumps(source_identity_tamper))


def test_csp_ir_002_summary_has_own_authenticated_identity(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    result = _result(approved_snapshot)
    summary = result.safe_summary()
    payload = summary.model_dump(mode="json")
    payload["home_goal_rate"] = "1.700000"

    assert summary.source_result_semantic_sha256 == result.semantic_sha256
    assert summary.semantic_sha256 != result.semantic_sha256
    with pytest.raises(ValidationError):
        CurrentScorePriorSummary.model_validate_json(json.dumps(payload))

    forged = CurrentScorePriorResult.model_construct(
        **{
            name: getattr(result, name)
            for name in CurrentScorePriorResult.model_fields
            if name != "semantic_sha256"
        },
        semantic_sha256="f" * 64,
    )
    with pytest.raises(ValueError, match="semantic identity"):
        forged.safe_summary()


def test_csp_ir_003_leaf_is_legacy_canonical_contract() -> None:
    assert LeafScorePriorRequest is LegacyScorePriorRequest
    prior = LeafScorePriorRequest.model_validate_json(
        '{"away_goal_rate":"1.374561","home_goal_rate":"1.613158",'
        '"model_family":"INDEPENDENT_POISSON_V1"}'
    )
    assert prior.public_dict() == {
        "away_goal_rate": "1.374561",
        "home_goal_rate": "1.613158",
        "model_family": "INDEPENDENT_POISSON_V1",
    }
    assert prior.model_copy() == prior
    assert prior.model_copy(
        update={"home_goal_rate": Decimal("1.700000")}
    ).home_goal_rate == Decimal("1.700000")
    with pytest.raises(ValidationError):
        LeafScorePriorRequest.model_validate_json(
            '{"away_goal_rate":"1.374561","home_goal_rate":"1.7",'
            '"model_family":"INDEPENDENT_POISSON_V1"}'
        )


def test_csp_ir_003_fresh_import_does_not_load_markets() -> None:
    code = """
import sys
class BlockMarkets:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'dmf_pulse.markets' or fullname.startswith('dmf_pulse.markets.'):
            raise ModuleNotFoundError('market import blocked')
        return None
sys.meta_path.insert(0, BlockMarkets())
from decimal import Decimal
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorBundle, CurrentScorePriorResult
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
value = ScorePriorRequest(home_goal_rate=Decimal('1.613158'), away_goal_rate=Decimal('1.374561'))
assert value.public_dict()['home_goal_rate'] == '1.613158'
assert 'dmf_pulse.markets' not in sys.modules
assert CurrentScorePriorBundle.__name__ == 'CurrentScorePriorBundle'
assert CurrentScorePriorResult.__name__ == 'CurrentScorePriorResult'
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


class _MaliciousTransport(FakeTransport):
    def __init__(self, bodies: dict[str, bytes], *, fail_on: int) -> None:
        super().__init__(bodies)
        self._fail_on = fail_on

    def send(self, request: OpenFootballHttpRequest) -> object:
        if len(self.requests) + 1 == self._fail_on:
            self.requests.append(request)
            raise RuntimeError("SECRET_SENTINEL_DO_NOT_LEAK")
        return super().send(request)


@pytest.mark.parametrize("fail_on", [1, 2, 3, 4])
def test_csp_ir_004_unexpected_transport_exception_is_sanitized(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    fail_on: int,
) -> None:
    config, bodies = approved_snapshot
    transport = _MaliciousTransport(bodies, fail_on=fail_on)

    with pytest.raises(IngestionError) as caught:
        _service(config, transport).build(
            CurrentScorePriorBuildRequest(
                information_cutoff=_CUTOFF,
                rights_profile_id=APPROVED_PROFILE_ID,
            )
        )

    error = caught.value
    serialized = json.dumps(error.as_error_object(), sort_keys=True)
    assert error.code == "SOURCE_UNAVAILABLE"
    assert error.details["transport_call_count"] == fail_on
    assert "SECRET_SENTINEL_DO_NOT_LEAK" not in str(error)
    assert "SECRET_SENTINEL_DO_NOT_LEAK" not in repr(error)
    assert "SECRET_SENTINEL_DO_NOT_LEAK" not in serialized


def test_csp_ir_004_cli_is_disclosure_safe_for_malicious_transport(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, bodies = approved_snapshot
    service = _service(config, _MaliciousTransport(bodies, fail_on=1))
    monkeypatch.setattr(current_score_prior_cmd, "CurrentScorePriorService", lambda: service)

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

    assert result.exit_code == 6
    assert "SECRET_SENTINEL_DO_NOT_LEAK" not in result.stdout
    assert "SECRET_SENTINEL_DO_NOT_LEAK" not in (result.stderr or "")
    assert json.loads(result.stdout)["error"]["details"]["transport_call_count"] == 1


@pytest.mark.parametrize("signal", [KeyboardInterrupt, SystemExit])
def test_csp_ir_004_does_not_catch_base_exception_control_signals(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    signal: type[BaseException],
) -> None:
    config, bodies = approved_snapshot

    class SignalTransport(FakeTransport):
        def send(self, request: OpenFootballHttpRequest) -> object:
            self.requests.append(request)
            raise signal()

    with pytest.raises(signal):
        _service(config, SignalTransport(bodies)).build(
            CurrentScorePriorBuildRequest(
                information_cutoff=_CUTOFF,
                rights_profile_id=APPROVED_PROFILE_ID,
            )
        )
