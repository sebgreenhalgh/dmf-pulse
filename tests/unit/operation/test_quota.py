"""Owned quota headers, credential sentinels and offline HTTPS connections only."""

from __future__ import annotations

import ssl
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.odds.client import OddsHttpRequest, OddsHttpResponse
from dmf_pulse.operation import quota
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.quota import (
    NativeQuotaTransport,
    QuotaClient,
    QuotaHeaderValues,
    QuotaLookupError,
    QuotaRoute,
    QuotaSourceQualification,
    VerifiedQuotaPeriod,
    build_quota_request,
    parse_quota_header_values,
    parse_zero_cost_quota_headers,
)

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
OWNED_KEY = "OWNED_QUOTA_TEST_KEY_20261101"
HEADERS = {"x-requests-remaining": "498", "x-requests-used": "2", "x-requests-last": "0"}


@pytest.fixture
def qualification() -> QuotaSourceQualification:
    allowed = {
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.PRIVATE_INTERNAL_USE,
    }
    profile = RightsProfile(
        rights_profile_id=quota.QUOTA_PROFILE_ID,
        provider_key="the_odds_api",
        profile_version="1.0.0",
        status=RightsProfileStatus.HUMAN_APPROVED,
        capabilities={
            key: CapabilityValue.ALLOW if key in allowed else CapabilityValue.DENY
            for key in RightsCapability
        },
        retention_seconds=0,
        retention_reason="OWNED transient header-only fixture",
        termination_deletion_required=True,
        attribution_required=False,
        geography_scope=quota.QUOTA_GEOGRAPHY,
        account_scope="qualified private Odds account: odds-account-OWNED",
        approved_purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        terms_source="https://the-odds-api.com/terms-and-conditions.html",
        terms_version="OWNED_TEST",
        checked_at=NOW - timedelta(days=1),
        approved_at=NOW - timedelta(days=1),
        human_approval_id="OWNED_APPROVAL",
        approved_by="OWNED_OPERATOR",
    )
    return QuotaSourceQualification(
        qualification_id="OWNED_QUOTA",
        account_ref="odds-account-OWNED",
        profile=profile,
        profile_sha256=quota._profile_sha(profile),
        permission_basis="VENDOR_TERMS_AND_ACCOUNT",
        permission_evidence_sha256="1" * 64,
        account_review_sha256="2" * 64,
        independent_review_sha256="3" * 64,
        decision_ref="OWNED_DECISION",
        operator_country="IT",
        qualified_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=1),
        control_metadata_retention_approved=True,
    )


class Guard:
    def __init__(self, events: list[str], deny: str | None = None) -> None:
        self.events, self.deny = events, deny

    def preflight_send(self, provider: str, method: str, host: str, path: str) -> None:
        assert (provider, method, host, path) == ("ODDS", "GET", quota.QUOTA_HOST, quota.QUOTA_PATH)
        self.events.append("preflight")
        if self.deny == "preflight":
            raise RuntimeError(OWNED_KEY)

    def before_send(self, provider: str, method: str, host: str, path: str) -> None:
        assert (provider, method, host, path) == ("ODDS", "GET", quota.QUOTA_HOST, quota.QUOTA_PATH)
        self.events.append("before_send")
        if self.deny == "before_send":
            raise RuntimeError(OWNED_KEY)

    def before_transport(self) -> None:
        self.events.append("before_transport")
        if self.deny == "before_transport":
            raise RuntimeError(OWNED_KEY)


class Provider:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self.events, self.fail = events, fail

    def __repr__(self) -> str:
        return "Provider(<owned-redacted>)"

    def get_credential(self) -> str:
        self.events.append("credential")
        if self.fail:
            raise RuntimeError(OWNED_KEY)
        return OWNED_KEY


class Transport:
    def __init__(
        self, events: list[str], response: OddsHttpResponse | Exception | None = None
    ) -> None:
        self.events = events
        self.response = response or OddsHttpResponse(
            200, "application/json", HEADERS, b"OWNED_UNUSED"
        )
        self.calls = 0

    def send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse:
        self.calls += 1
        self.events.append("transport")
        assert credential == OWNED_KEY and request.safe_parameters == ()
        assert request.path == "/v4/sports/" and request.host == quota.QUOTA_HOST
        assert OWNED_KEY not in repr(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def admit(events: list[str]):
    def admission(value: QuotaSourceQualification, *, checked_at: datetime) -> None:
        assert value.route == QuotaRoute() and checked_at == NOW
        events.append("admission")

    return admission


def parse(headers=HEADERS, **changes):
    values = dict(
        account_ref="odds-account-OWNED",
        qualification_sha256="4" * 64,
        request_started_at=NOW - timedelta(seconds=1),
        received_at=NOW,
        checked_at=NOW,
    )
    values.update(changes)
    return parse_zero_cost_quota_headers(headers, **values)


def test_headers_observed_without_inventing_a_period_or_plan():
    value = parse()
    assert (value.remaining_credits, value.used_credits, value.last_request_cost) == (498, 2, 0)
    assert value.period_status == "UNKNOWN" and value.period_anchor is None
    assert value.provider_date_at is None and value.source_body_retained is False
    assert len(value.request_identity_sha256) == len(value.request_fingerprint_sha256) == 64
    value.require_fresh(NOW + timedelta(seconds=60))
    with pytest.raises(OperationError, match="STALE"):
        value.require_fresh(NOW + timedelta(seconds=61))


@pytest.mark.parametrize(
    "bad",
    [
        "-1",
        "+1",
        " 1",
        "1 ",
        "1.0",
        "01",
        "1e2",
        "1,2",
        "True",
        chr(0x0661),
        "9" * 20,
        "9223372036854775808",
    ],
)
def test_noncanonical_counters_fail_closed(bad):
    with pytest.raises(OperationError):
        parse({**HEADERS, "x-requests-used": bad})


@pytest.mark.parametrize("name", list(HEADERS))
def test_each_required_header_is_mandatory(name):
    with pytest.raises(OperationError, match="HEADERS_INVALID"):
        parse({k: v for k, v in HEADERS.items() if k != name})


def test_case_alias_duplicates_cannot_overwrite_evidence():
    with pytest.raises(OperationError, match="HEADERS_INVALID"):
        parse({**HEADERS, "X-Requests-Used": "0"})
    with pytest.raises(OperationError, match="HEADERS_INVALID"):
        parse([*HEADERS.items(), ("x-requests-used", "2")])


def test_charged_response_parser_is_separate_and_retains_actual_cost():
    headers = {**HEADERS, "x-requests-last": "2"}
    assert parse_quota_header_values(headers, maximum_last_cost=2).last_request_cost == 2
    with pytest.raises(OperationError, match="UNEXPECTED_COST"):
        parse(headers)
    with pytest.raises(OperationError, match="UNEXPECTED_LAST_COST"):
        parse_quota_header_values(headers, expected_last_cost=0)
    excessive = {**HEADERS, "x-requests-used": "3", "x-requests-last": "3"}
    assert parse_quota_header_values(excessive).last_request_cost == 3
    with pytest.raises(OperationError, match="LIMIT_EXCEEDED"):
        parse_quota_header_values(excessive, maximum_last_cost=2)


@pytest.mark.parametrize("bound", [True, -1, 2**63])
def test_cost_limit_is_strict(bound):
    with pytest.raises(OperationError, match="COST_BOUND_INVALID"):
        parse_quota_header_values(HEADERS, maximum_last_cost=bound)


def test_counter_consistency_and_boolean_types():
    with pytest.raises(OperationError, match="INCONSISTENT"):
        parse_quota_header_values({**HEADERS, "x-requests-last": "3"})
    with pytest.raises(ValidationError):
        QuotaHeaderValues(remaining_credits=True, used_credits=0, last_request_cost=0)


def test_verified_period_requires_separate_anchor_and_contains_actual_receipt():
    period = VerifiedQuotaPeriod(
        period_started_at=NOW - timedelta(hours=12),
        resets_at=datetime(2026, 12, 1, tzinfo=UTC),
        evidence_sha256="5" * 64,
    )
    value = parse(period_anchor=period)
    assert value.period_status == "VERIFIED_ANCHOR" and value.period_anchor == period
    with pytest.raises(ValidationError):
        parse(period_anchor=period.model_copy(update={"resets_at": NOW}))
    with pytest.raises(ValidationError):
        VerifiedQuotaPeriod(period_started_at=NOW, resets_at=NOW, evidence_sha256="5" * 64)


@pytest.mark.parametrize(
    "changes",
    [
        {"received_at": NOW + timedelta(seconds=1)},
        {"checked_at": NOW + timedelta(seconds=61)},
        {"request_started_at": NOW + timedelta(seconds=1)},
        {"checked_at": NOW.replace(tzinfo=None)},
        {"maximum_age_seconds": True},
    ],
)
def test_freshness_chronology_and_aware_clock_are_strict(changes):
    with pytest.raises((OperationError, ValidationError)):
        parse(**changes)


def test_provider_date_is_optional_evidence_not_an_inferred_reset():
    value = parse({**HEADERS, "Date": "Sun, 01 Nov 2026 12:00:00 GMT"})
    assert value.provider_date_at == NOW and value.period_status == "UNKNOWN"
    with pytest.raises(OperationError, match="DATE_INVALID"):
        parse({**HEADERS, "Date": "not-a-date"})
    with pytest.raises(OperationError, match="DATE_STALE"):
        parse({**HEADERS, "Date": "Sun, 01 Nov 2026 11:00:00 GMT"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "other.invalid"),
        ("path", "/v4/sports/soccer_epl/odds"),
        ("method", "POST"),
        ("maximum_calls", 2),
        ("expected_credit_cost", 1),
        ("maximum_calls", True),
        ("expected_credit_cost", False),
    ],
)
def test_route_cannot_become_a_charged_or_arbitrary_endpoint(field, value):
    with pytest.raises(ValidationError):
        QuotaRoute.model_validate({field: value})


def test_source_provenance_cannot_claim_supplier_authentication(qualification):
    assert qualification.permission_provenance == "OWNER_ATTESTED_SUPPLIER_PERMISSION"
    assert qualification.supplier_issuer_authenticated is False
    fields = qualification.model_dump(exclude={"profile"}) | {"profile": qualification.profile}
    with pytest.raises(ValidationError):
        QuotaSourceQualification.model_validate(fields | {"supplier_issuer_authenticated": True})
    with pytest.raises(ValidationError):
        QuotaSourceQualification.model_validate(fields | {"profile_sha256": "0" * 64})


def test_client_admits_before_credentials_and_sends_exactly_once(qualification):
    events = []
    transport = Transport(events)
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=transport,
        clock=lambda: NOW,
    )
    value = client.fetch(qualification, admission=admit(events))
    assert events == [
        "admission",
        "preflight",
        "credential",
        "before_send",
        "before_transport",
        "transport",
    ]
    assert value.last_request_cost == 0 and value.transport_call_count == 1
    with pytest.raises(QuotaLookupError, match="ALREADY_ATTEMPTED"):
        client.fetch(qualification, admission=admit(events))
    assert transport.calls == 1


@pytest.mark.parametrize(
    "deny", ["admission", "preflight", "before_send", "before_transport", "credential", "transport"]
)
def test_every_failure_is_secret_safe_and_never_retried(qualification, deny):
    events = []
    transport = Transport(events, RuntimeError(OWNED_KEY) if deny == "transport" else None)
    client = QuotaClient(
        guard=Guard(events, deny),
        credential_provider=Provider(events, deny == "credential"),
        transport=transport,
        clock=lambda: NOW,
    )

    def admission(value, *, checked_at):
        if deny == "admission":
            raise RuntimeError(OWNED_KEY)

    with pytest.raises(QuotaLookupError) as caught:
        client.fetch(qualification, admission=admission)
    assert (
        OWNED_KEY not in str(caught.value)
        and OWNED_KEY not in caught.value.evidence.model_dump_json()
    )
    assert OWNED_KEY not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__context__ is None
    assert transport.calls == (1 if deny == "transport" else 0)
    if deny in {"admission", "preflight"}:
        assert "credential" not in events


def test_expired_qualification_fails_before_admission_or_credential(qualification):
    events = []
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=Transport(events),
        clock=lambda: NOW,
    )
    expired = qualification.model_copy(update={"valid_until": NOW})
    with pytest.raises(QuotaLookupError, match="ADMISSION_DENIED"):
        client.fetch(expired, admission=admit(events))
    assert events == []


@pytest.mark.parametrize(
    "status,redirect,code",
    [
        (302, "PRESENT", "REDIRECT_BLOCKED"),
        (401, None, "HTTP_REJECTED"),
        (429, None, "HTTP_REJECTED"),
        (503, None, "HTTP_REJECTED"),
    ],
)
def test_http_failures_do_not_retry_or_follow_redirects(qualification, status, redirect, code):
    events = []
    transport = Transport(
        events, OddsHttpResponse(status, "application/json", HEADERS, b"OWNED", redirect)
    )
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=transport,
        clock=lambda: NOW,
    )
    with pytest.raises(QuotaLookupError, match=code) as caught:
        client.fetch(qualification, admission=admit(events))
    assert transport.calls == 1 and caught.value.evidence.http_status == status


def test_unexpected_free_route_spend_is_preserved_in_failure_evidence(qualification):
    events = []
    headers = {**HEADERS, "x-requests-last": "2"}
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=Transport(events, OddsHttpResponse(200, "application/json", headers, b"")),
        clock=lambda: NOW,
    )
    with pytest.raises(QuotaLookupError, match="UNEXPECTED_COST") as caught:
        client.fetch(qualification, admission=admit(events))
    assert caught.value.evidence.observed_headers.last_request_cost == 2


class Response:
    status = 200

    def __init__(self, headers=None):
        self.headers = headers or [("content-type", "application/json"), *HEADERS.items()]

    def getheaders(self):
        return self.headers

    def read(self, size):
        raise AssertionError("catalog body must never be read")


class Connection:
    def __init__(self, response):
        self.response = response
        self.sock = None
        self.requests = []
        self.closed = 0

    def connect(self):
        return None

    def request(self, method, url, body=None, headers=None):
        self.requests.append((method, url, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed += 1


def test_native_transport_uses_only_fixed_https_and_discards_catalog_body():
    connection = Connection(Response())
    calls = []

    def factory(host, timeout, context):
        calls.append((host, timeout, context))
        return connection

    transport = NativeQuotaTransport(connection_factory=factory)
    result = transport.send(build_quota_request(), OWNED_KEY)
    assert (
        result.body == b""
        and calls[0][0] == quota.QUOTA_HOST
        and calls[0][2].verify_mode == ssl.CERT_REQUIRED
    )
    assert connection.requests[0][0:3] == ("GET", "/v4/sports/?apiKey=" + OWNED_KEY, None)
    assert connection.closed == 1


@pytest.mark.parametrize(
    "bad_request",
    [
        OddsHttpRequest("GET", "https", "other.invalid", quota.QUOTA_PATH, ()),
        OddsHttpRequest("GET", "https", quota.QUOTA_HOST, "/v4/sports/soccer_epl/odds", ()),
        OddsHttpRequest("GET", "https", quota.QUOTA_HOST, quota.QUOTA_PATH, (("regions", "uk"),)),
        OddsHttpRequest("POST", "https", quota.QUOTA_HOST, quota.QUOTA_PATH, ()),
    ],
)
def test_native_transport_refuses_other_routes_before_connect(bad_request):
    def forbidden(*args):
        raise AssertionError("must not connect")

    with pytest.raises(Exception):
        NativeQuotaTransport(connection_factory=forbidden).send(bad_request, OWNED_KEY)


def test_construction_does_not_read_existing_credentials_or_start_transport(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must stay lazy")

    monkeypatch.setattr(quota._StoredOddsCredentialProvider, "get_credential", forbidden)
    monkeypatch.setattr(NativeQuotaTransport, "send", forbidden)
    client = QuotaClient(guard=Guard([]))
    assert "zero-credit" in repr(client)


def test_default_stored_adapter_never_selects_environment_key(monkeypatch):
    seen = []

    class OwnedAutomatic:
        def __init__(self, *, environment):
            seen.append(environment)

        def get_credential(self):
            return OWNED_KEY

    monkeypatch.setenv("DMF_ODDS_CREDENTIAL_SOURCE", "environment")
    monkeypatch.setenv("THE_ODDS_API_KEY", "OWNED_IGNORED_ENV_VALUE")
    monkeypatch.setattr(quota, "AutomaticOddsCredentialProvider", OwnedAutomatic)
    assert quota._StoredOddsCredentialProvider().get_credential() == OWNED_KEY
    assert seen[0]["DMF_ODDS_CREDENTIAL_SOURCE"] == "auto" and "THE_ODDS_API_KEY" not in seen[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("transport_call_count", True),
        ("automatic_retries", False),
        ("source_body_retained", 0),
        ("request_fingerprint_sha256", "0" * 64),
        ("request_identity_sha256", "0" * 64),
    ],
)
def test_observation_rejects_boolean_counts_and_unrelated_request_identity(field, value):
    with pytest.raises(ValidationError):
        quota.QuotaObservation.model_validate(parse().model_dump() | {field: value})


@pytest.mark.parametrize(
    "headers",
    [
        {**HEADERS, "x-request-id": "bad\r\nheader"},
        {**HEADERS, "x-requests-used": 2},
        {**HEADERS, "Date": "x" * 1025},
        [("x-requests-used", "2", "extra")],
    ],
)
def test_malformed_headers_are_bounded_and_never_revealed(headers):
    with pytest.raises(OperationError, match="QUOTA_HEADERS_INVALID"):
        parse_quota_header_values(headers)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rights_profile_id", "the_odds_api_private_operator_recommendations_v1"),
        ("geography_scope", "GLOBAL"),
        ("approved_purpose", "RESEARCH"),
        ("account_scope", "another account"),
        ("terms_source", "https://other.invalid/terms"),
        ("retention_seconds", 3600),
        ("unresolved_rights", ("UNRESOLVED",)),
    ],
)
def test_other_profiles_cannot_authorize_quota_key_resolution(qualification, field, value):
    events = []
    changed = qualification.profile.model_copy(update={field: value})
    invalid = qualification.model_copy(
        update={"profile": changed, "profile_sha256": quota._profile_sha(changed)}
    )
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=Transport(events),
        clock=lambda: NOW,
    )
    with pytest.raises(QuotaLookupError, match="ADMISSION_DENIED"):
        client.fetch(invalid, admission=admit(events))
    assert events == []


def test_only_explicit_none_admission_result_permits_credentials(qualification):
    events = []
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=Transport(events),
        clock=lambda: NOW,
    )
    with pytest.raises(QuotaLookupError, match="ADMISSION_REQUIRED"):
        client.fetch(qualification, admission=lambda value, **kwargs: False)
    assert events == []


def test_expiry_while_stored_key_resolution_waits_prevents_transport(qualification):
    events = []
    clock_value = [NOW]

    class WaitingProvider(Provider):
        def get_credential(self):
            clock_value[0] = qualification.valid_until
            return super().get_credential()

    transport = Transport(events)
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=WaitingProvider(events),
        transport=transport,
        clock=lambda: clock_value[0],
    )
    with pytest.raises(QuotaLookupError, match="ADMISSION_OR_CLOCK_INVALID"):
        client.fetch(qualification, admission=admit(events))
    assert transport.calls == 0


def test_two_threads_cannot_repeat_the_same_client_attempt(qualification):
    events = []
    transport = Transport(events)
    client = QuotaClient(
        guard=Guard(events),
        credential_provider=Provider(events),
        transport=transport,
        clock=lambda: NOW,
    )

    def run():
        try:
            client.fetch(qualification, admission=admit(events))
            return "SUCCESS"
        except QuotaLookupError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == ["QUOTA_LOOKUP_ALREADY_ATTEMPTED", "SUCCESS"]
    assert transport.calls == 1


def test_native_transport_requires_tls_validation_before_connect():
    context = ssl.create_default_context()
    context.check_hostname = False

    def forbidden(*args):
        raise AssertionError("must not connect")

    with pytest.raises(Exception) as caught:
        NativeQuotaTransport(
            connection_factory=forbidden, ssl_context_factory=lambda: context
        ).send(build_quota_request(), OWNED_KEY)
    assert caught.value.code == "TLS_ERROR"
    assert OWNED_KEY not in str(caught.value)


def test_native_total_deadline_and_connection_cleanup():
    connection = Connection(Response())
    times = iter([0.0, 0.0, 0.0, 31.0])
    transport = NativeQuotaTransport(
        connection_factory=lambda *args: connection, monotonic=lambda: next(times)
    )
    with pytest.raises(Exception) as caught:
        transport.send(build_quota_request(), OWNED_KEY)
    assert caught.value.code == "TOTAL_TIMEOUT"
    assert connection.closed == 1


def test_native_bad_content_type_closes_without_catalog_read():
    connection = Connection(Response(list(HEADERS.items())))
    with pytest.raises(Exception) as caught:
        NativeQuotaTransport(connection_factory=lambda *args: connection).send(
            build_quota_request(), OWNED_KEY
        )
    assert caught.value.code == "CONTENT_TYPE_INVALID" and connection.closed == 1
