"""Finite owned quota provenance differences never mask other parity failures."""

from __future__ import annotations

import copy
import json
import runpy
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dmf_pulse.dashboard.synthetic import DEMO_TIME, demo_inputs
from dmf_pulse.ingestion.odds.client import OddsHttpRequest, _safe_parameters
from dmf_pulse.ingestion.odds.config import load_provider_config
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.private_v1.presentation import MarketQuotaReceipt

PROBE_PATH = Path(__file__).resolve().parents[3] / "scripts/accel003_wheel_probe.py"
compare = runpy.run_path(str(PROBE_PATH))["compare_exact"]
CURRENT_FINGERPRINTS = {
    1: "e44a3042e37d2f2cc1f755cf88e754da8466bfbbfbf75ec33e6269a421b99a48",
    3: "2517f66b813c2c5346c2cdb365647f55da77bf40dc9d3568b77a60da452df6ee",
}
REMAINING_PATH = "/presentation/market_quota_receipt/remaining_credits"
FINGERPRINT_PATH = "/presentation/market_quota_receipt/request_fingerprint"
pytestmark = pytest.mark.unit


def pair(horizon=1):
    compiled = {
        "source": "PROVIDER_RESPONSE_HEADERS",
        "remaining_credits": 100,
        "used_credits": 2,
        "last_request_cost": 2,
        "observed_at": "2026-09-01T12:00:00Z",
        "received_at": "2026-09-01T12:00:00Z",
        "request_fingerprint": "1" * 64,
        "transport_call_count": 1,
    }
    current = {
        **compiled,
        "remaining_credits": 98,
        "request_fingerprint": CURRENT_FINGERPRINTS[horizon],
    }
    gameweeks = [{"gameweek": value} for value in range(2, 2 + horizon)]
    left = {
        "presentation": {
            "market_quota_remaining": 98,
            "market_quota_receipt": current,
            "gameweeks": gameweeks,
        }
    }
    right = {
        "presentation": {
            "market_quota_remaining": 100,
            "market_quota_receipt": compiled,
            "gameweeks": copy.deepcopy(gameweeks),
        }
    }
    return left, right


@pytest.mark.parametrize("horizon", [1, 3])
def test_exact_owned_request_and_compiled_quota_origins_are_reproducible_without_key(horizon):
    inputs = demo_inputs()  # Authenticates every packaged owned body before use.
    bootstrap = json.loads(inputs["fpl-0.json"])
    targets = [row["id"] for row in bootstrap["events"] if row["is_next"]]
    assert targets == [2]
    fixtures = [
        row
        for row in json.loads(inputs["fpl-1.json"])
        if row["event"] in range(targets[0], targets[0] + horizon)
    ]
    end = max(datetime.fromisoformat(row["kickoff_time"]) for row in fixtures) + timedelta(
        seconds=1
    )
    config = load_provider_config()
    # Construct only secret-free request metadata. No credential provider,
    # transport, model engine or source/profile authority is invoked.
    request = OddsHttpRequest(
        method="GET",
        scheme=config.scheme,
        host=config.host,
        path=config.path,
        safe_parameters=_safe_parameters(config, DEMO_TIME, end),
    )
    assert request.request_fingerprint == CURRENT_FINGERPRINTS[horizon]
    compiled = MarketQuotaReceipt.from_odds(
        OddsProviderCurrentInput.model_validate_json(inputs["odds.json"])
    )
    assert (
        compiled.model_dump(mode="json") == pair(horizon)[1]["presentation"]["market_quota_receipt"]
    )


@pytest.mark.parametrize("horizon", [1, 3])
def test_only_three_exact_owned_control_leaves_are_excluded_and_all_values_retained(horizon):
    left, right = pair(horizon)
    receipt = compare(left, right)
    assert receipt["mismatches"] == []
    assert {row["path"] for row in receipt["excluded"]} == {
        "/presentation/market_quota_remaining",
        REMAINING_PATH,
        FINGERPRINT_PATH,
    }
    for row in receipt["excluded"]:
        assert row["left"] != row["right"] and row["reason"]
    # Used, cost and count remain compared as numbers, rather than discarded
    # with their parent receipt. The two differing numerical quota leaves are
    # explicitly disclosed exclusions, never counted as forecast equality.
    assert receipt["numeric_fields"] == 3 + horizon


@pytest.mark.parametrize("side", ["left", "right", "both"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("used_credits", 3),
        ("used_credits", True),
        ("used_credits", 2.0),
        ("last_request_cost", 1),
        ("last_request_cost", "2"),
        ("transport_call_count", 2),
        ("transport_call_count", True),
        ("source", "SYNTHETIC_FIXTURE"),
        ("observed_at", "2026-09-01T12:00:01Z"),
        ("received_at", "2026-09-01T12:00:01Z"),
        ("observed_at", "2026-09-01T12:00:00"),
        ("received_at", "2026-09-01T12:00:00+01:00"),
    ],
)
def test_changed_or_mutually_drifted_family_cannot_enable_either_new_exception(side, field, value):
    left, right = pair()
    if side in {"left", "both"}:
        left["presentation"]["market_quota_receipt"][field] = value
    if side in {"right", "both"}:
        right["presentation"]["market_quota_receipt"][field] = value
    receipt = compare(left, right)
    assert {REMAINING_PATH, FINGERPRINT_PATH} <= {row["path"] for row in receipt["mismatches"]}
    assert not {REMAINING_PATH, FINGERPRINT_PATH} & {row["path"] for row in receipt["excluded"]}


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("mutation", ["missing", "extra", "null", "list", "legacy_drift"])
def test_full_receipt_shape_and_legacy_reconciliation_required_before_exclusion(side, mutation):
    values = list(pair())
    presentation = values[side]["presentation"]
    quota = presentation["market_quota_receipt"]
    if mutation == "missing":
        del quota["source"]
    elif mutation == "extra":
        quota["unexpected"] = "owned"
    elif mutation == "null":
        presentation["market_quota_receipt"] = None
    elif mutation == "list":
        presentation["market_quota_receipt"] = list(quota.values())
    else:
        presentation["market_quota_remaining"] += 1
    receipt = compare(*values)
    assert receipt["mismatches"]
    assert not {REMAINING_PATH, FINGERPRINT_PATH} & {row["path"] for row in receipt["excluded"]}


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("value", ["2" * 64, "A" * 64, "1" * 63, "not-a-fingerprint", 123, None])
def test_unknown_malformed_or_drifted_request_identity_cannot_be_excluded(side, value):
    values = list(pair())
    values[side]["presentation"]["market_quota_receipt"]["request_fingerprint"] = value
    receipt = compare(*values)
    assert {REMAINING_PATH, FINGERPRINT_PATH} <= {row["path"] for row in receipt["mismatches"]}


def test_reversing_known_origin_order_does_not_qualify():
    left, right = pair()
    receipt = compare(right, left)
    assert {REMAINING_PATH, FINGERPRINT_PATH} <= {row["path"] for row in receipt["mismatches"]}


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("field", ["remaining_credits", "request_fingerprint"])
def test_hybrid_families_with_one_identical_leaf_cannot_hide_the_other_difference(side, field):
    values = list(pair())
    changed = values[side]["presentation"]["market_quota_receipt"]
    other = values[1 - side]["presentation"]["market_quota_receipt"]
    changed[field] = other[field]
    receipt = compare(*values)
    expected_path = FINGERPRINT_PATH if field == "remaining_credits" else REMAINING_PATH
    assert expected_path in {row["path"] for row in receipt["mismatches"]}
    assert not {REMAINING_PATH, FINGERPRINT_PATH} & {row["path"] for row in receipt["excluded"]}


@pytest.mark.parametrize("horizon", [1, 3])
def test_known_fingerprint_from_other_horizon_is_provenance_drift(horizon):
    left, right = pair(horizon)
    left["presentation"]["market_quota_receipt"]["request_fingerprint"] = CURRENT_FINGERPRINTS[
        4 - horizon
    ]
    receipt = compare(left, right)
    assert {REMAINING_PATH, FINGERPRINT_PATH} <= {row["path"] for row in receipt["mismatches"]}


@pytest.mark.parametrize("side", ["left", "right", "both"])
@pytest.mark.parametrize(
    "weeks",
    [[], [2, 2, 4], [2, 4, 3], [2, 3], [3], [2, True, 4], ["2", 3, 4], None, (2, 3, 4)],
)
def test_incoherent_or_mutually_drifted_gameweek_context_cannot_qualify(side, weeks):
    left, right = pair(3)
    rows = [{"gameweek": value} for value in weeks] if isinstance(weeks, list) else weeks
    if side in {"left", "both"}:
        left["presentation"]["gameweeks"] = rows
    if side in {"right", "both"}:
        right["presentation"]["gameweeks"] = rows
    receipt = compare(left, right)
    assert {REMAINING_PATH, FINGERPRINT_PATH} <= {row["path"] for row in receipt["mismatches"]}


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_points", 1.25),
        ("points_variance", 0.2),
        ("minutes", 60),
        ("probability", 0.3),
        ("hit_points", 4),
        ("model_version_ids", ["accepted-owned-model"]),
        ("ruleset_hash", "a" * 64),
    ],
)
def test_known_quota_pair_never_masks_football_model_or_rule_difference(field, value):
    left, right = pair(3)
    left["presentation"]["gameweeks"][0]["summaries"] = {"owned": {field: value}}
    right["presentation"]["gameweeks"] = copy.deepcopy(left["presentation"]["gameweeks"])
    right["presentation"]["gameweeks"][0]["summaries"]["owned"][field] = None
    receipt = compare(left, right)
    assert len(receipt["mismatches"]) == 1
    assert receipt["mismatches"][0]["path"].endswith("/" + field)
    assert {REMAINING_PATH, FINGERPRINT_PATH} <= {row["path"] for row in receipt["excluded"]}
