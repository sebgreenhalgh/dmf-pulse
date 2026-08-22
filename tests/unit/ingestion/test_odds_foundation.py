"""Isolated oracles for the bounded odds provider foundation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    OddsFetchFailure,
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
    UnavailableCredentialProvider,
    _safe_parameters,
    _validate_request,
    build_request,
    parse_quota_headers,
)
from dmf_pulse.ingestion.odds.config import (
    effective_config_sha256,
    load_provider_config,
    load_rights_profiles,
    provider_config_sha256,
)
from dmf_pulse.ingestion.odds.mapping import OddsMappingPlan, load_mapping_plan
from dmf_pulse.ingestion.odds.models import (
    OddsIngestionResult,
    OddsQuality,
    ProviderFailure,
    ProviderFailureCode,
    QuotaSource,
    QuotaState,
)
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.odds.persistence import OddsPersistence
from dmf_pulse.ingestion.odds.service import OddsImportRequest, OddsIngestionService
from dmf_pulse.markets.models import (
    MarketBook,
    MarketObservation,
    MarketOutcome,
    MarketQueryResult,
    MarketState,
    canonical_decimal_text,
    source_decimal_text,
)

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 20, 12, tzinfo=UTC)
VALID_QUOTA_HEADERS = {
    "x-requests-remaining": "499",
    "x-requests-used": "1",
    "x-requests-last": "1",
}


def _fixture(root: Path, name: str) -> bytes:
    return (root / "fixtures/odds/ODD-005" / name).read_bytes()


def _happy(root: Path) -> list[dict[str, object]]:
    value = json.loads(_fixture(root, "happy_path.json"))
    assert isinstance(value, list)
    return value


def _body(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode()


def test_supplied_payload_scenarios_have_frozen_semantics(repository_root: Path) -> None:
    happy = parse_odds_payload(_fixture(repository_root, "happy_path.json"))
    changed = parse_odds_payload(_fixture(repository_root, "changed_quote.json"))
    incomplete = parse_odds_payload(_fixture(repository_root, "incomplete_book.json"))
    unknown = parse_odds_payload(_fixture(repository_root, "unknown_market.json"))

    assert (len(happy.events), happy.operator_books_seen) == (1, 2)
    assert happy.warnings == ()
    assert changed.semantic_sha256 != happy.semantic_sha256
    assert incomplete.operator_books_seen == 1
    assert unknown.warnings == ("ADDITIVE_UNSUPPORTED_MARKET:synthetic_unknown_market",)
    assert len({happy.schema_fingerprint, changed.schema_fingerprint}) == 1


def test_additive_order_does_not_change_semantic_or_type_fingerprint(repository_root: Path) -> None:
    source = _happy(repository_root)
    source[0]["future"] = {"b": 2, "a": "x"}
    first = parse_odds_payload(_body(source))
    reordered = json.loads(_body(source), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
    second = parse_odds_payload(_body(reordered))
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.schema_fingerprint == second.schema_fingerprint
    assert first.body_sha256 != second.body_sha256


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda value: value[0].__setitem__("sport_key", "soccer_other"), "VALIDATION_FAILED"),
        (
            lambda value: value[0].__setitem__("home_team", value[0]["away_team"]),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0]["outcomes"][0].__setitem__(
                "price", "1.80"
            ),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0]["outcomes"][0].__setitem__(
                "price", 1
            ),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value[0]["bookmakers"].append(value[0]["bookmakers"][0].copy()),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value.append(value[0].copy()),
            "VALIDATION_FAILED",
        ),
    ),
)
def test_required_semantic_contradictions_fail_typed(
    repository_root: Path, mutation: object, code: str
) -> None:
    value = _happy(repository_root)
    assert callable(mutation)
    mutation(value)
    with pytest.raises(IngestionError) as raised:
        parse_odds_payload(_body(value))
    assert raised.value.code == code
    assert (
        "invalid_paths" not in raised.value.details
        or len(raised.value.details["invalid_paths"]) <= 20
    )


@pytest.mark.parametrize(
    ("body", "code"),
    (
        (b'{"not":"an array"}', "VALIDATION_FAILED"),
        (b'[{"id":"a","id":"b"}]', "DUPLICATE_JSON_KEY"),
        (b"[", "MALFORMED_JSON"),
        (b'[{"x":NaN}]', "MALFORMED_JSON"),
        (b"\xff", "MALFORMED_JSON"),
        ((b"[" * 65) + (b"]" * 65), "PAYLOAD_TOO_DEEP"),
    ),
)
def test_structural_failures_are_bounded(body: bytes, code: str) -> None:
    with pytest.raises(IngestionError) as raised:
        parse_odds_payload(body)
    assert raised.value.code == code


def test_additive_text_unicode_and_numeric_limits_fail_closed(repository_root: Path) -> None:
    value = _happy(repository_root)
    value[0]["future"] = "x" * 501
    with pytest.raises(IngestionError, match="text exceeds"):
        parse_odds_payload(_body(value))

    value = _happy(repository_root)
    value[0]["future"] = "\ud800"
    with pytest.raises(IngestionError, match="invalid Unicode"):
        parse_odds_payload(_body(value))

    value = _happy(repository_root)
    value[0]["future"] = "NUMBER_PLACEHOLDER"
    exponent = _body(value).replace(b'"NUMBER_PLACEHOLDER"', b"1e10000")
    with pytest.raises(IngestionError, match="number exceeds"):
        parse_odds_payload(exponent)


def test_conflicting_duplicates_and_invalid_line_are_rejected(repository_root: Path) -> None:
    with pytest.raises(IngestionError) as conflict:
        parse_odds_payload(_fixture(repository_root, "duplicate_conflict.json"))
    assert conflict.value.code == "VALIDATION_FAILED"

    value = _happy(repository_root)
    value[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["point"] = "0"
    with pytest.raises(IngestionError) as wrong_point:
        parse_odds_payload(_body(value))
    assert wrong_point.value.code == "VALIDATION_FAILED"


def test_canonical_draw_duplicates_emit_exact_evidence_or_fail_closed(
    repository_root: Path,
) -> None:
    value = _happy(repository_root)
    outcomes = value[0]["bookmakers"][0]["markets"][0]["outcomes"]
    assert isinstance(outcomes, list)
    draw = next(item for item in outcomes if item["name"] == "Draw")
    equal_duplicate = dict(draw)
    equal_duplicate["name"] = "draw"
    outcomes.append(equal_duplicate)

    parsed = parse_odds_payload(_body(value))

    parsed_outcomes = parsed.events[0].bookmakers[0].markets[0].outcomes
    assert len(parsed_outcomes) == 3
    assert parsed.warnings == ("DUPLICATE_OUTCOME_DEDUPED",)
    assert len(parsed.duplicate_outcomes) == 1
    evidence = parsed.duplicate_outcomes[0]
    assert evidence.bookmaker_key == "book_alpha"
    assert evidence.market_key == "h2h"
    assert evidence.outcome == "DRAW"
    assert evidence.duplicate_count == 1
    assert len(evidence.event_external_id_sha256) == 64

    equal_duplicate["price"] = 9.99
    with pytest.raises(IngestionError) as conflicting:
        parse_odds_payload(_body(value))
    assert conflicting.value.code == "VALIDATION_FAILED"

    equal_duplicate["price"] = draw["price"]
    equal_duplicate["point"] = 0.5
    with pytest.raises(IngestionError) as line_bearing_duplicate:
        parse_odds_payload(_body(value))
    assert line_bearing_duplicate.value.code == "VALIDATION_FAILED"


def test_provider_and_rights_configuration_is_strict_and_hash_bound(
    repository_root: Path, tmp_path: Path
) -> None:
    config = load_provider_config()
    profiles = load_rights_profiles()
    assert config.sport_keys == ("soccer_epl",)
    assert config.regions == ("uk",)
    assert config.markets == ("h2h", "totals")
    assert config.request_cost == 2
    assert set(profiles) == {
        "synthetic_the_odds_api_v1",
        "the_odds_api_private_analytics_v1",
    }
    assert len(provider_config_sha256()) == len(effective_config_sha256()) == 64

    wrong = json.loads((repository_root / "config/providers/the_odds_api.json").read_text())
    wrong["request_cost"] = "1"
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_provider_config(path)
    assert raised.value.code == "CONFIGURATION_INVALID"


def test_mapping_plan_is_explicit_unique_and_hash_bound(
    repository_root: Path, tmp_path: Path
) -> None:
    path = repository_root / "fixtures/odds/ODD-005/mapping_plan.json"
    plan = load_mapping_plan(path)
    assert plan.fixture("todapi-event-001").canonical_fixture_lookup.external_id == "101"
    assert plan.operator("book_alpha").canonical_operator_key == "SYNTHETIC_BOOK_ALPHA"
    assert len(plan.sha256) == 64
    with pytest.raises(IngestionError):
        plan.fixture("missing")
    with pytest.raises(IngestionError):
        plan.operator("missing")

    value = json.loads(path.read_text(encoding="utf-8"))
    value["operator_mappings"].append(value["operator_mappings"][0])
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_mapping_plan(duplicate)
    assert raised.value.code == "MAPPING_CONFLICT"


def test_decimal_rendering_is_context_independent_and_exact() -> None:
    assert source_decimal_text(Decimal("1.80")) == "1.80"
    assert source_decimal_text(Decimal("2.00")) == "2.00"
    assert canonical_decimal_text(Decimal("1.800")) == "1.8"
    assert canonical_decimal_text(Decimal("1.80")) == canonical_decimal_text(Decimal("1.8"))
    assert canonical_decimal_text(Decimal("-0.000")) == "0"
    assert canonical_decimal_text(Decimal("1E+3")) == "1000"
    long = Decimal("1.12345678901234567890123456789012345")
    assert canonical_decimal_text(long) == "1.12345678901234567890123456789012345"
    with pytest.raises(ValueError, match="finite"):
        canonical_decimal_text(Decimal("NaN"))


def test_provider_source_scale_is_separate_from_semantic_hash(repository_root: Path) -> None:
    source_scale = _fixture(repository_root, "happy_path.json")
    shorter_scale = source_scale.replace(b"1.80", b"1.8", 1)
    source_parsed = parse_odds_payload(source_scale)
    shorter_parsed = parse_odds_payload(shorter_scale)

    assert source_parsed.body_sha256 != shorter_parsed.body_sha256
    assert source_parsed.semantic_sha256 == shorter_parsed.semantic_sha256
    assert source_parsed.events[0].bookmakers[0].markets[0].outcomes[0].price == Decimal("1.80")
    assert (
        source_parsed.events[0].bookmakers[0].markets[0].outcomes[0].price.as_tuple().exponent == -2
    )


@pytest.mark.parametrize("lexical", ("1.80", "1.01", "2", "2.00"))
def test_market_observation_accepts_approved_source_decimal_lexemes(lexical: str) -> None:
    value = _observation().model_dump(mode="json")
    value["decimal_odds"] = lexical
    observation = MarketObservation.model_validate_json(json.dumps(value))
    assert observation.model_dump(mode="json")["decimal_odds"] == lexical


@pytest.mark.parametrize("lexical", ("1", "1.0", "1.00", "01.80", "+1.80", "-1.80", "1.8e0"))
def test_market_observation_rejects_unapproved_decimal_lexemes(lexical: str) -> None:
    value = _observation().model_dump(mode="json")
    value["decimal_odds"] = lexical
    with pytest.raises(ValidationError, match="decimal odds"):
        MarketObservation.model_validate_json(json.dumps(value))


def test_provider_price_rejects_exponent_token_without_rejecting_additive_number(
    repository_root: Path,
) -> None:
    body = _fixture(repository_root, "happy_path.json")
    with pytest.raises(IngestionError, match="reference contract"):
        parse_odds_payload(body.replace(b"1.80", b"1.8e0", 1))

    source = _happy(repository_root)
    source[0]["future_numeric"] = "EXPONENT_PLACEHOLDER"
    additive = _body(source).replace(b'"EXPONENT_PLACEHOLDER"', b"1.8e0")
    parsed = parse_odds_payload(additive)
    assert "ADDITIVE_UNKNOWN:$.future_numeric" in parsed.warnings


def test_empty_h2h_book_is_explicitly_unavailable(repository_root: Path) -> None:
    parsed = parse_odds_payload(_fixture(repository_root, "happy_path.json"))
    event = parsed.events[0]
    market = event.bookmakers[0].markets[0].model_copy(update={"outcomes": ()})

    prices, state, missing = OddsPersistence._outcomes(event, market)

    assert prices == {}
    assert state is MarketState.UNAVAILABLE
    assert missing == ("HOME", "DRAW", "AWAY")


def _observation(
    *,
    outcome: MarketOutcome = MarketOutcome.HOME,
    market_state: MarketState = MarketState.INCOMPLETE,
    market_id: UUID | None = None,
    operator_id: UUID | None = None,
    usable_at: datetime = CAPTURED,
) -> MarketObservation:
    return MarketObservation(
        fixture_id=UUID(int=1),
        market_id=market_id or UUID(int=2),
        selection_id=UUID(int=10 + list(MarketOutcome).index(outcome)),
        operator_id=operator_id or UUID(int=4),
        outcome=outcome,
        decimal_odds=Decimal("2.0"),
        observed_at=CAPTURED - timedelta(minutes=2),
        received_at=CAPTURED - timedelta(minutes=1),
        usable_at=usable_at,
        source_snapshot_id=UUID(int=5),
        market_state=market_state,
        contract_version="the-odds-api-v4-reference-v1",
    )


def test_market_public_models_reject_false_complete_and_future_information() -> None:
    incomplete = MarketBook(
        operator_id=UUID(int=4),
        operator_key="BOOK",
        market_state=MarketState.INCOMPLETE,
        observations=(_observation(),),
    )
    result = MarketQueryResult(
        fixture_id=UUID(int=1), as_of=CAPTURED, books=(incomplete,), observation_count=1
    )
    assert result.model_dump(mode="json")["books"][0]["observations"][0]["decimal_odds"] == "2.0"

    with pytest.raises(ValidationError, match="complete book"):
        MarketBook(
            operator_id=UUID(int=4),
            operator_key="BOOK",
            market_state=MarketState.COMPLETE,
            observations=(_observation(market_state=MarketState.COMPLETE),),
        )
    with pytest.raises(ValidationError, match="ineligible"):
        MarketQueryResult(
            fixture_id=UUID(int=1),
            as_of=CAPTURED,
            books=(
                MarketBook(
                    operator_id=UUID(int=4),
                    operator_key="BOOK",
                    market_state=MarketState.INCOMPLETE,
                    observations=(_observation(usable_at=CAPTURED + timedelta(seconds=1)),),
                ),
            ),
            observation_count=1,
        )


def test_quality_failure_and_ingestion_models_reject_false_success() -> None:
    with pytest.raises(ValidationError, match="quality status"):
        OddsQuality(status="PASS", warnings=("warning",))
    with pytest.raises(ValidationError, match="pre-transport"):
        ProviderFailure(
            code=ProviderFailureCode.CREDENTIAL_UNAVAILABLE,
            message="unavailable",
            retryable=False,
            transport_called=True,
        )
    with pytest.raises(ValidationError, match="complete result"):
        OddsIngestionResult(
            status="COMPLETE",
            source_snapshot_id=None,
            events_seen=0,
            operator_books_seen=0,
            complete_books_created=0,
            incomplete_books_created=0,
            observations_created=0,
            observations_reused=0,
            quarantined=0,
            quota=None,
            quality=OddsQuality(status="PASS"),
            error=None,
        )


class _Transport:
    def __init__(self, responses: list[OddsHttpResponse | IngestionError]) -> None:
        self.responses = responses
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest, _credential: str) -> OddsHttpResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, IngestionError):
            raise response
        return response


def _response(
    root: Path, *, status: int = 200, content_type: str = "application/json"
) -> OddsHttpResponse:
    return OddsHttpResponse(
        status_code=status,
        content_type=content_type,
        headers={
            "x-requests-remaining": "499",
            "x-requests-used": "1",
            "x-requests-last": "1",
            "x-request-id": "safe-id-1",
        },
        body=_fixture(root, "happy_path.json"),
    )


def _fake_credential(root: Path) -> str:
    return (
        (root / "fixtures/odds/ODD-005/security_fake_credential.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def test_request_fingerprint_and_sanitized_target_never_include_credential(
    repository_root: Path,
) -> None:
    credential = _fake_credential(repository_root)
    request = build_request(
        credential,
        commence_from=CAPTURED,
        commence_to=CAPTURED + timedelta(hours=1),
    )
    assert request.method == "GET" and request.scheme == "https"
    assert credential not in request.sanitized_target
    assert "apiKey" not in request.sanitized_target
    assert len(request.request_fingerprint) == 64
    assert credential not in repr(request)
    assert credential not in repr(StaticCredentialProvider(credential))
    assert UnavailableCredentialProvider().get_credential() is None


def test_client_gates_quota_and_credential_before_transport(repository_root: Path) -> None:
    private = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    constructed = 0

    def forbidden() -> _Transport:
        nonlocal constructed
        constructed += 1
        raise AssertionError("transport must not be constructed")

    client = OddsClient(private, transport_factory=forbidden, clock=lambda: CAPTURED)
    with pytest.raises(IngestionError) as missing:
        client.fetch()
    assert missing.value.code == "CREDENTIAL_UNAVAILABLE"
    assert missing.value.details["transport_call_count"] == 0

    client = OddsClient(
        private,
        credential_provider=StaticCredentialProvider(_fake_credential(repository_root)),
        transport_factory=forbidden,
        clock=lambda: CAPTURED,
    )
    exhausted = QuotaState(
        remaining=0,
        used=500,
        last_cost=1,
        observed_at=CAPTURED,
        source=QuotaSource.SYNTHETIC_FIXTURE,
    )
    with pytest.raises(IngestionError) as blocked:
        client.fetch(quota=exhausted)
    assert blocked.value.code == "QUOTA_EXHAUSTED"
    assert constructed == 0


def test_client_success_and_bounded_retry_are_typed(repository_root: Path) -> None:
    private = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    transient = IngestionError("READ_TIMEOUT", "timed out", retryable=True)
    transport = _Transport([transient, _response(repository_root)])
    client = OddsClient(
        private,
        credential_provider=StaticCredentialProvider(_fake_credential(repository_root)),
        transport_factory=lambda: transport,
        clock=lambda: CAPTURED,
    )
    fetched = client.fetch()
    assert fetched.transport_call_count == 2
    assert fetched.quota.remaining == 499
    assert fetched.provider_request_id_sha256 is not None
    assert len(transport.requests) == 2
    assert len(fetched.attempts) == 2
    assert fetched.attempts[0].body_capture_state == "ABSENT"
    assert fetched.attempts[0].failure_code == ProviderFailureCode.READ_TIMEOUT
    assert fetched.attempts[1].body_capture_state == "COMPLETE"
    assert fetched.attempts[1].failure_code is None


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    (
        (
            OddsHttpResponse(
                302,
                "text/plain",
                VALID_QUOTA_HEADERS,
                b"",
                "https://elsewhere",
            ),
            "REDIRECT_BLOCKED",
            False,
        ),
        (
            OddsHttpResponse(400, "application/json", VALID_QUOTA_HEADERS, b""),
            "HTTP_4XX",
            False,
        ),
        (
            OddsHttpResponse(429, "application/json", VALID_QUOTA_HEADERS, b""),
            "HTTP_429",
            True,
        ),
        (
            OddsHttpResponse(503, "application/json", VALID_QUOTA_HEADERS, b""),
            "HTTP_5XX",
            True,
        ),
        (
            OddsHttpResponse(501, "application/json", VALID_QUOTA_HEADERS, b""),
            "HTTP_5XX",
            False,
        ),
        (
            OddsHttpResponse(201, "application/json", VALID_QUOTA_HEADERS, b""),
            "SOURCE_UNAVAILABLE",
            False,
        ),
        (
            OddsHttpResponse(200, "text/html", VALID_QUOTA_HEADERS, b""),
            "CONTENT_TYPE_INVALID",
            False,
        ),
    ),
)
def test_client_response_matrix_is_typed(
    response: OddsHttpResponse, code: str, retryable: bool, repository_root: Path
) -> None:
    private = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    transport = _Transport([response, response] if retryable else [response])
    client = OddsClient(
        private,
        credential_provider=StaticCredentialProvider(_fake_credential(repository_root)),
        transport_factory=lambda: transport,
        clock=lambda: CAPTURED,
        sleeper=lambda _seconds: None,
    )
    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert client.transport_call_count == (2 if retryable else 1)


def test_quota_and_request_validation_reject_naive_or_inconsistent_values(
    repository_root: Path,
) -> None:
    with pytest.raises(IngestionError, match="timestamp"):
        parse_quota_headers(
            {"x-requests-remaining": "1", "x-requests-used": "1", "x-requests-last": "1"},
            datetime(2026, 1, 1),
        )
    with pytest.raises(IngestionError, match="quota headers"):
        parse_quota_headers({}, CAPTURED)
    with pytest.raises(IngestionError, match="range"):
        _safe_parameters(load_provider_config(), CAPTURED, CAPTURED)
    with pytest.raises(IngestionError, match="UTC-aware"):
        _safe_parameters(load_provider_config(), datetime(2026, 1, 1), None)
    with pytest.raises(IngestionError, match="allowlisted"):
        _validate_request(
            OddsHttpRequest(
                method="POST",
                scheme="https",
                host="api.the-odds-api.com",
                path="/v4/sports/soccer_epl/odds",
                safe_parameters=(),
            ),
            load_provider_config(),
        )


def test_response_quota_depletion_suppresses_the_next_retry(repository_root: Path) -> None:
    private = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    depleted = OddsHttpResponse(
        status_code=429,
        content_type="application/json",
        headers={
            "x-requests-remaining": "0",
            "x-requests-used": "500",
            "x-requests-last": "1",
        },
        body=b"{}",
    )
    transport = _Transport([depleted])
    client = OddsClient(
        private,
        credential_provider=StaticCredentialProvider(_fake_credential(repository_root)),
        transport_factory=lambda: transport,
        clock=lambda: CAPTURED,
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "HTTP_429"
    assert raised.value.retryable is False
    assert len(raised.value.attempts) == 1
    assert raised.value.attempts[0].quota is not None
    assert raised.value.attempts[0].quota.remaining == 0
    assert client.transport_call_count == 1


def test_failed_attempt_metadata_never_retains_response_body(repository_root: Path) -> None:
    private = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    body = _fixture(repository_root, "raw_forbidden_canary.json")
    transport = _Transport(
        [
            OddsHttpResponse(
                400,
                "application/json",
                {
                    "x-requests-remaining": "10",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                },
                body,
            )
        ]
    )
    client = OddsClient(
        private,
        credential_provider=StaticCredentialProvider(_fake_credential(repository_root)),
        transport_factory=lambda: transport,
        clock=lambda: CAPTURED,
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    attempt = raised.value.attempts[0]
    assert attempt.body_size == len(body)
    assert attempt.body_sha256 == hashlib.sha256(body).hexdigest()
    assert body.decode("utf-8") not in repr(raised.value)
    assert body.decode("utf-8") not in repr(attempt)


def test_quota_model_rejects_impossible_cost() -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        QuotaState(
            remaining=1,
            used=0,
            last_cost=1,
            observed_at=CAPTURED,
            source=QuotaSource.SYNTHETIC_FIXTURE,
        )


def test_mapping_model_rejects_duplicate_operator_identity(repository_root: Path) -> None:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/mapping_plan.json").read_text(encoding="utf-8")
    )
    value["operator_mappings"][1]["canonical_operator_key"] = value["operator_mappings"][0][
        "canonical_operator_key"
    ]
    with pytest.raises(ValidationError, match="canonical operator"):
        OddsMappingPlan.model_validate(value)


def test_import_rejects_unknown_rights_profile_before_ingestion(repository_root: Path) -> None:
    fixture_root = repository_root / "fixtures/odds/ODD-005"
    request = OddsImportRequest(
        input_path=fixture_root / "happy_path.json",
        mapping_plan_path=fixture_root / "mapping_plan.json",
        captured_at=CAPTURED,
        information_cutoff=CAPTURED + timedelta(days=1),
        rights_profile_id="missing_synthetic_profile",
    )

    with pytest.raises(IngestionError) as raised:
        OddsIngestionService(repository_root=repository_root).import_payload(request)

    assert raised.value.code == "RIGHTS_BLOCKED"
    assert raised.value.message == "odds rights profile is unavailable"
    assert raised.value.retryable is False


@pytest.mark.parametrize(
    "headers",
    (
        {"x-requests-remaining": "499"},
        {"x-requests-used": "1", "x-requests-last": "1"},
    ),
)
def test_client_rejects_partial_required_quota_headers(
    repository_root: Path,
    headers: dict[str, str],
) -> None:
    private = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    response = OddsHttpResponse(
        200,
        "application/json",
        headers,
        _fixture(repository_root, "happy_path.json"),
    )
    transport = _Transport([response])
    client = OddsClient(
        private,
        credential_provider=StaticCredentialProvider(_fake_credential(repository_root)),
        transport_factory=lambda: transport,
        clock=lambda: CAPTURED,
    )

    with pytest.raises(OddsFetchFailure) as raised:
        client.fetch()

    assert raised.value.code == "SOURCE_UNAVAILABLE"
    assert raised.value.retryable is False
    assert client.transport_call_count == 1
    assert len(raised.value.attempts) == 1
    assert raised.value.attempts[0].quota_header_state == "INVALID"
    assert raised.value.attempts[0].quota is None
