"""Owned native formations only: exact identities, late vintages and unknown minutes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.player_evidence import qualification as q
from dmf_pulse.player_evidence import wyscout as w
from dmf_pulse.player_evidence.contracts import EvidenceError
from dmf_pulse.player_evidence.features import build_features

pytestmark = pytest.mark.unit


def _bodies():
    return json.loads(q.owned_wyscout_native_body()), json.loads(q.owned_wyscout_bindings_body())


def test_owned_native_adapter_matches_fixed_derived_body_and_all_dependency_pins():
    dataset = w.adapt_owned_wyscout(
        q.owned_wyscout_native_body(), source=q.owned_wyscout_native_source()
    )
    assert canonical_json_bytes(dataset) == q.owned_wyscout_body()
    assert hashlib.sha256(q.owned_wyscout_body()).hexdigest() == q.OWNED_WYSCOUT_PAYLOAD_SHA256
    assert (
        hashlib.sha256(q.owned_wyscout_bindings_body()).hexdigest()
        == q.OWNED_WYSCOUT_BINDINGS_SHA256
    )
    assert dataset.source_id == q.owned_wyscout_source().source_id
    assert dataset.mode == "SYNTHETIC"
    assert len(dataset.fixtures) == 2 and len(dataset.observations) == 8
    assert sum(row.role == "START" for row in dataset.observations) == 4
    assert sum(row.role == "BENCH" for row in dataset.observations) == 4
    assert all(
        row.minutes is None and row.minutes_missing_reason == "NOT_SUPPORTED"
        for row in dataset.observations
    )
    assert all(
        row.minute_convention == "UNSUPPORTED"
        and row.revision == 0
        and row.supersedes_sha256 is None
        for row in dataset.observations
    )


def test_native_lineup_bench_and_red_card_never_infer_minutes_or_nonappearance():
    dataset = w.adapt_owned_wyscout(
        q.owned_wyscout_native_body(), source=q.owned_wyscout_native_source()
    )
    observations = {
        (row.provider_fixture_id, row.provider_player_id): row for row in dataset.observations
    }
    assert observations[("1001", "11")].role == "START"  # owned red-card row
    assert observations[("1001", "13")].role == "BENCH"  # owned substitute at 60
    assert observations[("1001", "14")].role == "BENCH"  # no substitution record
    assert observations[("1002", "21")].role == "BENCH"  # owned substitute at 45
    assert all(row.minutes is None for row in observations.values())
    assert not any(row.role == "OUT" for row in observations.values())
    assert not any(row.provider_player_id == "99" for row in dataset.memberships)
    assert not any(
        row.provider_team_id == "111" and row.provider_fixture_id == "1002"
        for row in dataset.memberships
    )


def test_descriptive_features_have_matchday_denominators_unknown_minutes_and_no_model_claim():
    report = w.owned_wyscout_demo()
    assert report == w.owned_wyscout_demo()
    assert report.mode == "SYNTHETIC" and report.features.production_activation is False
    assert report.real_release_qualification == "CLOSED_NOT_ACQUIRED"
    assert report.denominator_scope == "REPORTED_MATCHDAY_SQUAD_ONLY_NOT_FULL_CLUB_ROSTER"
    assert report.unreported_formation_team_fixture_count == 1
    assert report.reported_matchday_membership_count == 8
    assert len(report.features.players) == 7
    assert sum(row.selected_count for row in report.features.players) == 8
    assert all(
        row.mean_minutes.denominator == row.sixty_plus_rate.denominator == 0
        for row in report.features.players
    )
    assert all(
        row.mean_minutes.value is None and row.sixty_plus_rate.value is None
        for row in report.features.players
    )
    assert sum(row.role_counts["OUT"] for row in report.features.players) == 0
    unseen = [row for row in report.features.players if row.opportunity_count == 0]
    assert len(unseen) == 1 and unseen[0].start_rate.value is None
    assert report.features.predictive_uncertainty_status == "NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY"


def test_retrospective_release_vintage_cannot_leak_into_historical_cutoff():
    before = w.owned_wyscout_demo(cutoff=datetime(2018, 5, 1, tzinfo=UTC))
    assert all(
        row.selected_count == 0 and row.start_rate.denominator == 0
        for row in before.features.players
    )
    dataset = w.adapt_owned_wyscout(
        q.owned_wyscout_native_body(), source=q.owned_wyscout_native_source()
    )
    assert all(
        row.usable_at.year == 2019 and row.observed_at.year == 2019 for row in dataset.observations
    )
    assert all(row.kickoff_at.year == 2018 for row in dataset.fixtures)
    assert before.semantic_sha256 != w.owned_wyscout_demo().semantic_sha256


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "RECONSTRUCTED"},
        {"mode": "LIVE_OBSERVED"},
        {"qualification": "PROPOSED"},
        {"purpose": "MODEL_TRAINING"},
        {"licence_id": "CC-BY-4.0"},
        {"provider_id": "wyscout-real"},
        {"payload_sha256": "a" * 64},
    ],
)
def test_real_or_forged_native_sources_rejected_before_any_parse_or_resource_read(
    changes, monkeypatch
):
    source = q.owned_wyscout_native_source().model_copy(update=changes)

    def denied(*_, **__):
        pytest.fail("unqualified native source reached a parser or packaged dependency")

    monkeypatch.setattr(w, "_adapt_schema", denied)
    monkeypatch.setattr(q, "owned_wyscout_native_body", denied)
    monkeypatch.setattr(w, "owned_wyscout_bindings_body", denied)
    with pytest.raises(EvidenceError, match="SOURCE_NOT_QUALIFIED"):
        w.adapt_owned_wyscout(b"unqualified-real-body-not-retained", source=source)


def test_changed_native_or_bindings_bytes_fail_before_schema(monkeypatch):
    body = q.owned_wyscout_native_body()
    source = q.owned_wyscout_native_source()
    monkeypatch.setattr(
        w, "_adapt_schema", lambda *_: pytest.fail("unauthenticated body reached schema")
    )
    with pytest.raises(EvidenceError, match="SOURCE_BYTES_NOT_AUTHENTICATED"):
        w.adapt_owned_wyscout(body + b" ", source=source)
    monkeypatch.setattr(w, "owned_wyscout_bindings_body", lambda: b"changed-owned-binding")
    with pytest.raises(EvidenceError, match="NATIVE_BINDINGS_NOT_AUTHENTICATED"):
        w.adapt_owned_wyscout(body, source=source)


@pytest.mark.parametrize("dependency", ["native", "bindings", "derived"])
def test_every_fixed_retained_dependency_is_authenticated_before_features(dependency, monkeypatch):
    body = q.owned_wyscout_body()
    request = w.owned_wyscout_demo().features.request
    getter = {
        "native": "owned_wyscout_native_body",
        "bindings": "owned_wyscout_bindings_body",
        "derived": "owned_wyscout_body",
    }[dependency]
    monkeypatch.setattr(q, getter, lambda: b"changed-owned-packaged-dependency")
    with pytest.raises(EvidenceError):
        build_features(body, source=q.owned_wyscout_source(), request=request)


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate_match",
        "missing_match",
        "extra_match",
        "competition",
        "season",
        "kickoff",
        "postponed",
        "extra_time",
        "team_key",
        "same_side",
        "wrong_fixture_side",
        "bool_id",
        "bool_formation",
        "unknown_formation_with_roles",
        "missing_formation",
        "duplicate_starter",
        "starter_on_bench",
        "opponent_player",
        "invalid_sub_in",
        "invalid_sub_out",
        "sub_order",
        "bool_sub_minute",
        "mapping_missing",
        "mapping_ambiguous",
        "mapping_late",
        "mapping_interval",
        "player_alias",
        "team_alias",
        "float",
        "duplicate_json",
    ],
)
def test_schema_and_canonical_temporal_identity_attacks_fail_closed(attack):
    native, bindings = _bodies()
    match = native["matches"][0]
    team = match["teamsData"]["111"]
    formation = team["formation"]
    if attack == "duplicate_match":
        native["matches"].append(match)
    elif attack == "missing_match":
        native["matches"].pop()
    elif attack == "extra_match":
        import copy

        extra = copy.deepcopy(match)
        extra["wyId"] = 1999
        native["matches"].append(extra)
    elif attack in ("competition", "season", "kickoff", "postponed", "extra_time"):
        field, value = {
            "competition": ("competitionId", 9999),
            "season": ("seasonId", 9999),
            "kickoff": ("dateutc", "2018-04-01 13:00:00"),
            "postponed": ("status", "Postponed"),
            "extra_time": ("duration", "ExtraTime"),
        }[attack]
        match[field] = value
    elif attack == "team_key":
        match["teamsData"]["0111"] = match["teamsData"].pop("111")
    elif attack == "same_side":
        match["teamsData"]["222"]["side"] = "home"
    elif attack == "wrong_fixture_side":
        (
            bindings["fixtures"][0]["home_provider_team_id"],
            bindings["fixtures"][0]["away_provider_team_id"],
        ) = "222", "111"
    elif attack == "bool_id":
        formation["lineup"][0]["playerId"] = True
    elif attack == "bool_formation":
        team["hasFormation"] = True
    elif attack == "unknown_formation_with_roles":
        team["hasFormation"] = 0
    elif attack == "missing_formation":
        team["formation"] = None
    elif attack == "duplicate_starter":
        formation["lineup"].append(formation["lineup"][0])
    elif attack == "starter_on_bench":
        formation["bench"].append(formation["lineup"][0])
    elif attack == "opponent_player":
        match["teamsData"]["222"]["formation"]["lineup"][0]["playerId"] = 11
    elif attack == "invalid_sub_in":
        formation["substitutions"][0]["playerIn"] = 9999
    elif attack == "invalid_sub_out":
        formation["substitutions"][0]["playerOut"] = 14
    elif attack == "sub_order":
        formation["substitutions"].append({"playerIn": 14, "playerOut": 11, "minute": 45})
    elif attack == "bool_sub_minute":
        formation["substitutions"][0]["minute"] = True
    elif attack == "mapping_missing":
        bindings["mappings"] = [
            row for row in bindings["mappings"] if row["mapping_id"] != "owned-player-11"
        ]
    elif attack == "mapping_ambiguous":
        import copy

        extra = copy.deepcopy(bindings["mappings"][2])
        extra["mapping_id"] = "owned-ambiguous"
        bindings["mappings"].append(extra)
    elif attack == "mapping_late":
        bindings["mappings"][2]["usable_at"] = "2019-03-01T00:00:00Z"
    elif attack == "mapping_interval":
        bindings["mappings"][2]["effective_until"] = "2018-04-01T12:00:00Z"
    elif attack == "player_alias":
        bindings["mappings"][3]["canonical_id"] = bindings["mappings"][2]["canonical_id"]
    elif attack == "team_alias":
        bindings["mappings"][1]["canonical_id"] = bindings["mappings"][0]["canonical_id"]
    elif attack == "float":
        formation["substitutions"][0]["minute"] = 60.0
    body = canonical_json_bytes(native)
    if attack == "duplicate_json":
        body = body.replace(b'"wyId":1001', b'"wyId":1001,"wyId":1001')
    with pytest.raises((ValueError, TypeError)):
        w._adapt_schema(body, canonical_json_bytes(bindings))
