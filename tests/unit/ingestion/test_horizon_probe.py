"""Synthetic, provider-shaped observation tests; no live transport or model calls."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplDirectInputRequest, CurrentFplInputService
from dmf_pulse.ingestion.odds.client import OddsClient, OddsHttpResponse
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import StaticCredentialProvider
from dmf_pulse.ingestion.odds.horizon_probe import (
    classify_horizon,
    horizon_window,
    verify_observation,
)
from tests.unit.ingestion.current_manager_test_support import (
    _synthetic_bootstrap,
    _synthetic_fixtures,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 24, 10, tzinfo=UTC)
CUTOFF = NOW + timedelta(minutes=5)
ROOT = Path(__file__).resolve().parents[3]


def fpl_sources():
    bootstrap = _synthetic_bootstrap(ROOT)
    template = deepcopy(bootstrap["events"][0])
    bootstrap["events"] = [
        dict(
            template,
            id=gw,
            deadline_time=f"2026-09-{gw:02d}T10:00:00Z",
            finished=False,
            is_current=False,
            is_next=gw == 3,
            is_previous=False,
        )
        for gw in (3, 4, 5, 6)
    ]
    fixture = _synthetic_fixtures(ROOT)[0]
    fixtures = [
        dict(
            fixture,
            id=gw,
            code=10000 + gw,
            event=gw,
            team_h=1,
            team_a=2,
            kickoff_time=f"2026-09-{gw:02d}T14:00:00Z",
            finished=False,
            started=False,
        )
        for gw in (3, 4, 5, 6)
    ]
    return bootstrap, fixtures


@pytest.fixture
def fpl():
    bootstrap, fixtures = fpl_sources()
    return CurrentFplInputService(clock=lambda: NOW).compile_direct(
        CurrentFplDirectInputRequest(
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=3,
            captured_at=NOW,
            information_cutoff=CUTOFF,
            rights_profile_id="fpl_official_private_operator_initiated_read_v1",
        ),
        bootstrap_body=json.dumps(bootstrap).encode(),
        fixtures_body=json.dumps(fixtures).encode(),
    )


def event(gw=3):
    return {
        "id": f"synthetic-{gw}",
        "sport_key": "soccer_epl",
        "home_team": "Synthetic Club 1",
        "away_team": "Synthetic Club 2",
        "commence_time": f"2026-09-{gw:02d}T14:00:00Z",
        "bookmakers": [
            {
                "key": "synthetic",
                "title": "Synthetic",
                "last_update": NOW.isoformat(),
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Synthetic Club 1", "price": 2},
                            {"name": "Draw", "price": 3},
                            {"name": "Synthetic Club 2", "price": 4},
                        ],
                    }
                ],
            }
        ],
    }


class Transport:
    def __init__(self, body, cost=2, headers=None):
        self.body = body
        self.headers = (
            headers
            if headers is not None
            else {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": str(cost),
            }
        )
        self.calls = 0

    def send(self, request, credential):
        self.calls += 1
        return OddsHttpResponse(200, "application/json", self.headers, self.body)


def fetch(fpl, values, cost=None, headers=None):
    body = values if isinstance(values, bytes) else json.dumps(values).encode()
    transport = Transport(body, (0 if values == [] else 2) if cost is None else cost, headers)
    client = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider("synthetic-test-key"),
        transport_factory=lambda: transport,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )
    start, end = horizon_window(fpl)
    return client.fetch(commence_from=start, commence_to=end)


def observe(fpl, values, **kwargs):
    return classify_horizon(fetch(fpl, values), fpl, assessed_at=NOW, usable_at=NOW, **kwargs)


def test_root_only_is_valid_future_absence(fpl):
    result = observe(fpl, [event()])
    assert [row.status for row in result.fixtures] == ["MATCHED", "NOT_RETURNED", "NOT_RETURNED"]
    assert result.consensus == result.stage8_acceptance == "NOT_EVALUATED"
    assert result.model_stage_invocations == 0
    assert result.fixtures[0].books[0].h2h == "COMPLETE"
    assert result.fixtures[0].books[0].h2h_temporally_eligible


def test_exact_window_and_interleaved_outside(fpl):
    assert horizon_window(fpl) == (CUTOFF, datetime(2026, 9, 5, 14, 0, 1, tzinfo=UTC))
    result = observe(fpl, [event(5), event(6), event(3), event(4)])
    assert all(row.status == "MATCHED" for row in result.fixtures)
    assert result.outside_horizon_events == 1


@pytest.mark.parametrize("values", [[], [dict(event(), bookmakers=[])]])
def test_empty_is_an_observation(fpl, values):
    result = observe(fpl, values)
    assert result.status == "OBSERVATION_ONLY"
    assert result.quota.last_cost == (0 if not values else 2)


@pytest.mark.parametrize("change", ["orientation", "kickoff", "alias", "duplicate"])
def test_mapping_uncertainty_is_never_absence(fpl, change):
    row = event()
    if change == "orientation":
        row["home_team"], row["away_team"] = row["away_team"], row["home_team"]
    elif change == "kickoff":
        row["commence_time"] = "2026-09-03T14:00:01Z"
    elif change == "alias":
        row["home_team"] = "Unreviewed Club"
    values = [row] if change != "duplicate" else [row, dict(row, id="other-event")]
    result = observe(fpl, values)
    assert result.fixtures[0].status == "BLOCKED"


def test_observation_membership_tampering_rejected(fpl):
    source = fetch(fpl, [event()])
    result = classify_horizon(source, fpl, assessed_at=NOW, usable_at=NOW)
    with pytest.raises(IngestionError):
        verify_observation(replace(result, fixtures=result.fixtures[:-1]), source, fpl)


def totals(line=2.5):
    return {
        "key": "totals",
        "outcomes": [
            {"name": "Over", "price": 2, "point": line},
            {"name": "Under", "price": 2, "point": line},
        ],
    }


@pytest.mark.parametrize("line", [0.5, 2.5, 3.5])
def test_actual_supported_lines_not_fabricated(fpl, line):
    row = event()
    row["bookmakers"][0]["markets"].append(totals(line))
    book = observe(fpl, [row]).fixtures[0].books[0]
    assert book.paired_lines == (str(line),)
    assert book.totals == "PAIRED_HALF_GOAL"
    assert book.totals_temporally_eligible


@pytest.mark.parametrize("markets, expected", [([], "MISSING"), ([totals()], "PAIRED_HALF_GOAL")])
def test_absent_h2h_and_totals_only(fpl, markets, expected):
    row = event()
    row["bookmakers"][0]["markets"] = markets
    book = observe(fpl, [row]).fixtures[0].books[0]
    assert book.h2h == "ABSENT"
    assert not book.h2h_temporally_eligible
    assert book.totals == expected


@pytest.mark.parametrize(
    "age, market_timestamp, stale", [(1800, True, False), (1801, True, True), (1801, False, True)]
)
def test_staleness_and_explicit_fallback(fpl, age, market_timestamp, stale):
    row = event()
    book = row["bookmakers"][0]
    old = (NOW - timedelta(seconds=age)).isoformat()
    if market_timestamp:
        book["markets"][0]["last_update"] = old
    else:
        book["last_update"] = old
    result = observe(fpl, [row]).fixtures[0].books[0]
    assert result.h2h_stale == stale
    assert result.h2h_temporally_eligible != stale
    assert result.h2h_timestamp_source == ("MARKET" if market_timestamp else "BOOKMAKER")


@pytest.mark.parametrize(
    "damage", ["incomplete", "equal_duplicate", "point", "unknown", "late_market", "late_book"]
)
def test_malformed_supplied_h2h_blocks_not_absent(fpl, damage):
    row = event()
    book = row["bookmakers"][0]
    market = book["markets"][0]
    if damage == "incomplete":
        market["outcomes"].pop()
    elif damage == "equal_duplicate":
        market["outcomes"].append(deepcopy(market["outcomes"][0]))
    elif damage == "point":
        market["outcomes"][0]["point"] = 2.5
    elif damage == "unknown":
        market["outcomes"][0]["name"] = "Unknown"
    elif damage == "late_market":
        market["last_update"] = (NOW + timedelta(seconds=1)).isoformat()
    else:
        book["last_update"] = (NOW + timedelta(seconds=1)).isoformat()
    result = observe(fpl, [row])
    assert result.fixtures[0].status == "BLOCKED"
    assert result.fixtures[0].books[0].h2h == "INVALID"


@pytest.mark.parametrize(
    "damage, state",
    [
        ("integer", "UNSUPPORTED"),
        ("missing_side", "INVALID"),
        ("mismatch", "INVALID"),
        ("duplicate", "INVALID"),
        ("late", "INVALID"),
        ("unknown", "INVALID"),
        ("empty", "INVALID"),
    ],
)
def test_invalid_totals_are_separate_degradation(fpl, damage, state):
    row = event()
    market = totals()
    if damage == "integer":
        market = totals(2)
    elif damage == "missing_side":
        market["outcomes"].pop()
    elif damage == "mismatch":
        market["outcomes"][1]["point"] = 3.5
    elif damage == "duplicate":
        market["outcomes"].append(deepcopy(market["outcomes"][0]))
    elif damage == "late":
        market["last_update"] = (NOW + timedelta(seconds=1)).isoformat()
    elif damage == "unknown":
        market["outcomes"][0]["name"] = "Unknown"
    else:
        market["outcomes"] = []
    row["bookmakers"][0]["markets"].append(market)
    result = observe(fpl, [row])
    assert result.fixtures[0].status == "MATCHED"
    assert result.fixtures[0].books[0].h2h == "COMPLETE"
    assert result.fixtures[0].books[0].totals == state
    assert not result.fixtures[0].books[0].totals_temporally_eligible


@pytest.mark.parametrize("body", [b"[", b'[ {"id":1,"id":2} ]', b"[NaN]", b"[1e99999]"])
def test_strict_json_failures_are_not_empty_success(fpl, body):
    with pytest.raises(IngestionError):
        observe(fpl, body)


@pytest.mark.parametrize(
    "damage", ["sport", "secret", "timestamp", "duplicate_event", "duplicate_book", "price"]
)
def test_strict_source_integrity(fpl, damage):
    row = event()
    values = [row]
    if damage == "sport":
        row["sport_key"] = "upcoming"
    elif damage == "secret":
        row["api_key"] = "synthetic-do-not-echo"
    elif damage == "timestamp":
        row["commence_time"] = "invalid-time"
    elif damage == "duplicate_event":
        values.append(deepcopy(row))
    elif damage == "duplicate_book":
        row["bookmakers"].append(deepcopy(row["bookmakers"][0]))
    else:
        row["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = 0
    with pytest.raises(IngestionError) as failure:
        observe(fpl, values)
    assert "synthetic-do-not-echo" not in str(failure.value)
    assert failure.value.__context__ is None


@pytest.mark.parametrize("cost, values", [(0, [event()]), (1, [event()]), (2, []), (1, [])])
def test_unexpected_quota_cannot_prove_absence(fpl, cost, values):
    with pytest.raises(IngestionError):
        classify_horizon(fetch(fpl, values, cost=cost), fpl, assessed_at=NOW, usable_at=NOW)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-requests-last": "2"},
        {"x-requests-last": "x", "x-requests-used": "2", "x-requests-remaining": "498"},
    ],
)
def test_missing_and_invalid_quota_is_typed_failure(fpl, headers):
    with pytest.raises(IngestionError):
        fetch(fpl, [], headers=headers)


@pytest.mark.parametrize(
    "assessment, usable",
    [
        (NOW, CUTOFF + timedelta(seconds=1)),
        (NOW - timedelta(seconds=1), NOW),
        (NOW.replace(tzinfo=None), NOW),
    ],
)
def test_invalid_assessment_and_usability(fpl, assessment, usable):
    with pytest.raises(IngestionError):
        classify_horizon(fetch(fpl, [event()]), fpl, assessed_at=assessment, usable_at=usable)


def test_reordered_input_preserves_categories_not_original_body_hash(fpl):
    left = observe(fpl, [event(3), event(4), event(5)])
    right = observe(fpl, [event(5), event(3), event(4)])
    assert left.fixtures == right.fixtures and left.events == right.events
    assert left.body_sha256 != right.body_sha256
    summary = left.safe_summary()
    assert "price" not in json.dumps(summary)
    assert "Synthetic Club" not in json.dumps(summary)
    assert all(
        r["matched"] + r["not_returned"] + r["blocked"] == r["official_fixtures"]
        for r in summary["by_gameweek"]
    )


def test_ignored_lay_preserves_h2h(fpl):
    row = event()
    row["bookmakers"][0]["markets"].append({"key": "h2h_lay", "outcomes": []})
    result = observe(fpl, [row]).fixtures[0].books[0]
    assert result.ignored_h2h_lay and result.h2h == "COMPLETE"


def test_complete_source_hash_tampering(fpl):
    from dmf_pulse.ingestion.odds.client import OddsFetchResult

    source = fetch(fpl, [event()])
    changed = OddsFetchResult(
        body=b"[]",
        quota=source.quota,
        request_fingerprint=source.request_fingerprint,
        sanitized_target=source.sanitized_target,
        transport_call_count=source.transport_call_count,
        transport_id=source.transport_id,
        provider_request_id_sha256=source.provider_request_id_sha256,
        attempts=source.attempts,
    )
    with pytest.raises(IngestionError):
        classify_horizon(changed, fpl, assessed_at=NOW, usable_at=NOW)


def test_operator_rights_pending_before_any_transport(monkeypatch):
    from scripts import probe_horizon_market_coverage as script

    def forbidden(*args, **kwargs):
        pytest.fail("transport/model boundary must not be invoked")

    monkeypatch.setattr(script, "DirectFplClient", forbidden)
    monkeypatch.setattr(script, "OddsClient", forbidden)
    result = script.run_operator(12345, None, False, clock=lambda: NOW)
    assert result["status"] == "NOT_ATTEMPTED"
    assert result["reason"] == "CURRENT_TERMS_AND_APPLICABLE_ACCOUNT_REVIEW_PENDING"
    assert result["fpl_transport_attempts"] == result["odds_transport_attempts"] == 0


def test_safe_argument_error_never_echoes_input(capsys):
    from scripts.probe_horizon_market_coverage import main

    assert main(["--entry-id", "synthetic-private-value"]) == 2
    assert "synthetic-private-value" not in capsys.readouterr().err


@pytest.mark.parametrize("bad_body", [False, True])
def test_full_official_snapshot_to_probe_no_models(monkeypatch, bad_body):
    import dmf_pulse.private_v1.one_command as ordinary
    import dmf_pulse.private_v1.service as service
    from dmf_pulse.ingestion.fpl.direct import (
        DirectFplClient,
        DirectFplCredentialProvider,
        DirectFplRunAttestation,
    )
    from scripts import probe_horizon_market_coverage as script
    from tests.unit.ingestion.test_fpl_manager_provider import _context
    from tests.unit.ingestion.test_one_command_assembly import _DirectResponses

    def forbidden(*args, **kwargs):
        pytest.fail("model or OpenFootball invoked by diagnostic")

    for name in ("build_automatic_model_minutes", "build_automatic_rolling_model_minutes"):
        if hasattr(ordinary, name):
            monkeypatch.setattr(ordinary, name, forbidden)
    monkeypatch.setattr(service.PrivateV1RecommendationService, "run", forbidden)
    monkeypatch.setattr(ordinary.CurrentScorePriorService, "build", forbidden)
    bootstrap, fixtures = fpl_sources()
    _, _, _, current_team = _context(ROOT)
    direct_transport = _DirectResponses(
        (
            json.dumps(bootstrap).encode(),
            json.dumps(fixtures).encode(),
            b'{"id":42,"started_event":1,"summary_overall_points":0}',
            b'{"current":[]}',
            b"[]",
            json.dumps(current_team).encode(),
        )
    )
    marker = "synthetic-token"
    direct = DirectFplClient(
        DirectFplRunAttestation(attested_at=NOW),
        transport=direct_transport,
        credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker}),
        sleeper=lambda _: None,
        pace_seconds=0,
    )
    odds_transport = Transport(b"[" if bad_body else json.dumps([event(3), event(4)]).encode())
    odds = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider("synthetic-test-key"),
        transport_factory=lambda: odds_transport,
        clock=lambda: NOW,
    )
    if bad_body:
        with pytest.raises(IngestionError):
            script.acquire_probe(
                entry_id=42,
                approved_at=NOW,
                direct_client=direct,
                odds_client=odds,
                clock=lambda: NOW,
            )
    else:
        result = script.acquire_probe(
            entry_id=42, approved_at=NOW, direct_client=direct, odds_client=odds, clock=lambda: NOW
        )
        assert result["model_stage_invocations"] == result["openfootball_invocations"] == 0
        assert result["fpl_transport_attempts"] == 6
        assert result["transport_attempts"] == result["odds_logical_requests"] == 1
        assert result["by_gameweek"][2]["not_returned"] == 1
    assert direct.request_count == 6 and odds.transport_call_count == 1


def test_inherited_retry_limit_and_attempt_binding(fpl):
    class RetryTransport(Transport):
        def send(self, request, credential):
            self.calls += 1
            return OddsHttpResponse(
                503 if self.calls == 1 else 200, "application/json", self.headers, self.body
            )

    transport = RetryTransport(json.dumps([event()]).encode())
    client = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider("synthetic-test-key"),
        transport_factory=lambda: transport,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )
    start, end = horizon_window(fpl)
    fetched = client.fetch(commence_from=start, commence_to=end)
    result = classify_horizon(fetched, fpl, assessed_at=NOW, usable_at=NOW)
    assert result.transport_attempts == transport.calls == 2


@pytest.mark.parametrize(
    "damage", ["unscheduled", "started", "duplicate", "missing", "fractional_cutoff"]
)
def test_official_horizon_integrity(fpl, damage):
    if damage == "unscheduled":
        fpl = fpl.model_copy(
            update={
                "fixtures": (
                    fpl.fixtures[0].model_copy(update={"kickoff_at": None}),
                    *fpl.fixtures[1:],
                )
            }
        )
    elif damage == "started":
        fpl = fpl.model_copy(
            update={
                "fixtures": (
                    fpl.fixtures[0].model_copy(update={"started": True}),
                    *fpl.fixtures[1:],
                )
            }
        )
    elif damage == "duplicate":
        fpl = fpl.model_copy(update={"fixtures": (*fpl.fixtures, fpl.fixtures[0])})
    elif damage == "missing":
        fpl = fpl.model_copy(update={"fixtures": fpl.fixtures[1:]})
    else:
        fpl = fpl.model_copy(
            update={
                "provenance": fpl.provenance.model_copy(
                    update={"information_cutoff": CUTOFF.replace(microsecond=1)}
                )
            }
        )
    with pytest.raises(IngestionError):
        horizon_window(fpl)


@pytest.mark.parametrize(
    "body", [b"[" * 65 + b"]" * 65, b" " * (5242880 + 1)], ids=["depth", "bytes"]
)
def test_inherited_depth_and_body_limits(fpl, body):
    with pytest.raises(IngestionError):
        observe(fpl, body)


def test_existing_production_sources_unchanged():
    import hashlib

    # Parent bytes, independent of Git availability or CI clone depth.
    expected = {
        "private_v1/one_command.py": "843b68c6b2b11f09aad08feb671dfcc471f22525b93fafce8ade5862dc403294",
        "private_v1/rolling.py": "84e255cea1190d5ab7bcbdfd66b4510d25f2f1892006d6ef1b07255488edbafd",
        "ingestion/odds/parser.py": "d92f7dd0fd2bed1ebc031cdad70d8398de19180de57ddc6a446219521621feb0",
        "ingestion/odds/client.py": "9dbbd5f6e9c89a38b10bc02da517be088883ac01a1c39a791c9892aed64d28c9",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((ROOT / "src/dmf_pulse" / name).read_bytes()).hexdigest() == digest


def test_rights_flags_do_not_upgrade_profile():
    from scripts.probe_horizon_market_coverage import live_rights_blocker

    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    assert live_rights_blocker(profile, profile.human_approval_id, True, now) is not None
    # Synthetic-only later ratification object; never written or installed.
    revised = profile.model_copy(
        update={
            "checked_at": now,
            "approved_at": now,
            "account_scope": "synthetic approved account",
            "terms_version": "checked-2026-09-11",
        }
    )
    assert (
        live_rights_blocker(revised, None, False, now)
        == "EXISTING_PURPOSE_ACCOUNT_GEOGRAPHY_AUTHORITY_NOT_CONFIRMED"
    )
    assert live_rights_blocker(revised, revised.human_approval_id, True, now) is None
    revoked = revised.model_copy(update={"status": "REJECTED"})
    assert live_rights_blocker(revoked, revised.human_approval_id, True, now) == "RIGHTS_BLOCKED"


@pytest.mark.parametrize(
    "failure_code", [None, "CREDENTIAL_MISSING", "POST_CUTOFF", "QUALITY_BLOCKED", "OTHER"]
)
def test_operator_safe_exception_boundary(monkeypatch, failure_code):
    from types import SimpleNamespace

    from scripts import probe_horizon_market_coverage as script

    monkeypatch.setattr(script, "live_rights_blocker", lambda *args: None)
    monkeypatch.setattr(script.EnvironmentOddsCredentialProvider, "_configured", lambda _: True)
    monkeypatch.setenv("DMF_FPL_BEARER_TOKEN", "synthetic-token")
    monkeypatch.setattr(script, "DirectFplClient", lambda *args: SimpleNamespace(request_count=6))
    monkeypatch.setattr(
        script, "OddsClient", lambda *args, **kwargs: SimpleNamespace(transport_call_count=1)
    )

    def acquire(**kwargs):
        if failure_code is None:
            return {"status": "OBSERVATION_ONLY", "model_stage_invocations": 0}
        if failure_code == "OTHER":
            raise RuntimeError("synthetic-secret-never-echo")
        raise IngestionError(failure_code, "synthetic-secret-never-echo")

    monkeypatch.setattr(script, "acquire_probe", acquire)
    result = script.run_operator(12345, "synthetic-reference", True, clock=lambda: NOW)
    assert "synthetic-secret-never-echo" not in json.dumps(result)
    assert "12345" not in json.dumps(result)
    assert result["model_stage_invocations"] == 0
    assert result["status"] == ("OBSERVATION_ONLY" if failure_code is None else "FAILED")


@pytest.mark.parametrize("missing", ["odds", "fpl"])
def test_missing_credentials_not_attempted(monkeypatch, missing):
    from scripts import probe_horizon_market_coverage as script

    monkeypatch.setattr(script, "live_rights_blocker", lambda *args: None)
    monkeypatch.setattr(
        script.EnvironmentOddsCredentialProvider, "_configured", lambda _: missing != "odds"
    )
    monkeypatch.delenv("DMF_FPL_BEARER_TOKEN", raising=False)
    result = script.run_operator(42, None, False, clock=lambda: NOW)
    assert result["status"] == "NOT_ATTEMPTED"
    assert result["fpl_transport_attempts"] == result["odds_transport_attempts"] == 0


def test_main_safe_output_and_help(monkeypatch, capsys):
    from scripts import probe_horizon_market_coverage as script

    monkeypatch.setattr(script, "run_operator", lambda *args: {"status": "OBSERVATION_ONLY"})
    assert script.main(["--entry-id", "42"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "OBSERVATION_ONLY"
    assert script.main(["--help"]) == 0
    assert "--entry-id" in capsys.readouterr().out


@pytest.mark.parametrize(
    "time", [NOW.replace(tzinfo=None), NOW - timedelta(seconds=1), CUTOFF + timedelta(seconds=1)]
)
def test_acquisition_clock_rejects_before_network(time):
    from scripts.probe_horizon_market_coverage import acquire_probe

    with pytest.raises(IngestionError):
        acquire_probe(
            entry_id=42, approved_at=NOW, direct_client=None, odds_client=None, clock=lambda: time
        )


def test_invalid_entry_before_network():
    from scripts.probe_horizon_market_coverage import acquire_probe

    with pytest.raises(IngestionError):
        acquire_probe(
            entry_id=0, approved_at=NOW, direct_client=None, odds_client=None, clock=lambda: NOW
        )


def test_totals_canonical_duplicate_is_not_merged(fpl):
    row = event()
    market = totals()
    market["outcomes"].append({"name": " OVER ", "price": 2, "point": 2.5})
    row["bookmakers"][0]["markets"].append(market)
    book = observe(fpl, [row]).fixtures[0].books[0]
    assert book.totals == "INVALID"
    assert "TOTALS_DUPLICATE_OUTCOME" in book.degradations


def test_fpl_context_tampering_cannot_reuse_observation(fpl):
    source = fetch(fpl, [event()])
    result = classify_horizon(source, fpl, assessed_at=NOW, usable_at=NOW)
    altered = fpl.model_copy(
        update={
            "fixtures": (
                fpl.fixtures[0].model_copy(
                    update={"kickoff_at": fpl.fixtures[0].kickoff_at + timedelta(seconds=1)}
                ),
                *fpl.fixtures[1:],
            )
        }
    )
    with pytest.raises(IngestionError):
        verify_observation(result, source, altered)
