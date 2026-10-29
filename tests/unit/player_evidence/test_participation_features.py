"""Adversarial schema, identity, vintage and explicit missingness acceptance."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_UP, Decimal, localcontext
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from dmf_pulse.player_evidence import qualification
from dmf_pulse.player_evidence.contracts import (
    EvidenceError,
    EvidenceFeatureSet,
    MinuteDistribution,
    ParticipationDataset,
    Ratio,
)
from dmf_pulse.player_evidence.demo import owned_demo, owned_request
from dmf_pulse.player_evidence.features import _player_features, build_features
from dmf_pulse.player_evidence.qualification import decode_dataset, owned_body, owned_source

pytestmark = pytest.mark.unit


def _raw() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(owned_body())
    return value


def _dataset(raw: dict[str, Any]) -> ParticipationDataset:
    return decode_dataset(json.dumps(raw).encode())


def _player(number: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"dmf-owned-accel003:player-p{number}"))


def _features(number: int, revised: bool = False) -> Any:
    result = owned_demo(datetime(2026, 10, 12, 12, tzinfo=UTC) if revised else None)
    return next(item for item in result.players if str(item.player_id) == _player(number))


def test_owned_transfer_cutoffs_and_field_specific_denominators() -> None:
    player = _features(1)
    assert player.opportunity_count == 7
    assert player.selected_count == 5
    assert player.role_counts == {"START": 2, "BENCH": 1, "OUT": 1, "UNKNOWN": 1}
    assert player.start_rate == Ratio(numerator=2, denominator=4, value=Decimal("0.5"))
    assert player.mean_minutes == Ratio(numerator=85, denominator=4, value=Decimal("21.25"))
    assert player.sixty_plus_rate == Ratio(numerator=1, denominator=4, value=Decimal("0.25"))
    assert player.starter_minutes.counts == {60: 1}
    assert player.bench_minutes.counts == {0: 1}
    assert player.missingness == {"MINUTES_UNKNOWN": 1, "OTHER_TEAM": 2, "ROLE_UNKNOWN": 1}
    assert player.coverage_status == "PARTIAL"
    assert player.latest_observation_age_seconds is not None


def test_positive_minutes_never_imply_start_and_unknown_is_never_zero() -> None:
    player = _features(1)
    assert player.all_minutes.counts[25] == 1
    assert 25 not in player.starter_minutes.counts
    assert player.role_counts["UNKNOWN"] == 1
    unknown = _features(4)
    assert unknown.selected_count == 1
    assert unknown.start_rate.value is None
    assert unknown.mean_minutes.value is None
    assert unknown.all_minutes.sample_count == 0
    assert unknown.missingness == {"MINUTES_UNKNOWN": 1, "ROLE_UNKNOWN": 1}


def test_revision_uses_latest_eligible_vintage_without_rewriting_earlier_features() -> None:
    original = _features(1)
    corrected = _features(1, revised=True)
    fixture = uuid5(NAMESPACE_URL, "dmf-owned-accel003:fixture-f3")
    first = next(item for item in original.selected if item.fixture_id == fixture)
    later = next(item for item in corrected.selected if item.fixture_id == fixture)
    assert first.revision == 0 and later.revision == 1
    assert first.participation_sha256 != later.participation_sha256
    assert corrected.starter_minutes.counts == {59: 1}
    assert corrected.sixty_plus_rate.numerator == 0
    assert corrected.missingness["UNSUPPORTED_MINUTE_CONVENTION"] == 1
    assert corrected.missingness["FIXTURE_NOT_FINAL"] == 1
    assert corrected.missingness["ROSTER_NOT_PROVEN"] == 1
    assert _features(1) == original


def test_empty_history_and_future_identity_are_explicit() -> None:
    result = owned_demo()
    assert result.unattributed_player_membership_count == 2
    empty = _features(3)
    late_mapping = _features(6)
    for player in (empty, late_mapping):
        assert player.coverage_status == "NO_ELIGIBLE_HISTORY"
        assert player.missingness == {"NO_ELIGIBLE_HISTORY": 1}
        assert player.start_rate.value is None
        assert player.mean_minutes.value is None
        assert player.latest_observation_age_seconds is None
    assert _features(6, revised=True).mean_minutes.value == Decimal(90)
    assert (
        owned_demo(datetime(2026, 10, 12, 12, tzinfo=UTC)).unattributed_player_membership_count == 1
    )
    assert _features(5).missingness == {"MAPPING_UNRESOLVED": 1}
    assert _features(5, revised=True).mean_minutes.value == Decimal(20)


def test_missing_observation_does_not_become_out_or_zero() -> None:
    player = _features(2)
    assert player.opportunity_count == 4
    assert player.selected_count == 3
    assert player.role_counts["OUT"] == 1
    assert player.missingness == {"NOT_REPORTED": 1}
    assert player.mean_minutes.value == Decimal(35)


def test_fixture_identity_preserves_two_close_fixtures_independently() -> None:
    selected = _features(1).selected
    for key in ("f3", "f4"):
        assert uuid5(NAMESPACE_URL, "dmf-owned-accel003:fixture-" + key) in {
            item.fixture_id for item in selected
        }
    assert len({item.fixture_id for item in selected}) == len(selected)
    assert uuid5(NAMESPACE_URL, "dmf-owned-accel003:fixture-prior") not in {
        item.fixture_id for item in selected
    }


def test_fixed_decimal_context_and_json_identity_roundtrip() -> None:
    expected = owned_demo()
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_UP
        actual = owned_demo()
        restored = EvidenceFeatureSet.model_validate_json(actual.model_dump_json())
    assert actual == expected == restored
    assert actual.semantic_sha256 == expected.semantic_sha256
    assert expected.production_activation is False
    assert expected.status == "EVIDENCE_ONLY_NOT_MODEL_INPUT"
    assert expected.predictive_uncertainty_status == "NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qualification", "PROPOSED"),
        ("qualification", "REVOKED"),
        ("mode", "LIVE_OBSERVED"),
        ("mode", "RECONSTRUCTED"),
        ("purpose", "MODEL_TRAINING"),
        ("purpose", "PRODUCTION_PREDICTION"),
        ("provider_id", "official_fpl"),
        ("source_id", "invented-owned-wrapper"),
        ("licence_id", "CC-BY-4.0"),
        ("approval_id", "owner-risk-acceptance"),
        ("payload_sha256", "0" * 64),
    ],
)
def test_unqualified_source_rejected_before_decode(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    def denied_decode(body: bytes) -> ParticipationDataset:
        raise AssertionError("unauthorized body was parsed")

    monkeypatch.setattr("dmf_pulse.player_evidence.features.decode_dataset", denied_decode)
    source = owned_source().model_copy(update={field: value})
    with pytest.raises(EvidenceError, match="SOURCE_NOT_QUALIFIED"):
        build_features(b"not JSON", source=source, request=owned_request())


@pytest.mark.parametrize(
    "body",
    [b"{}", b"", b"private provider body", b"x" * 262_145],
    ids=["wrong-json", "empty", "provider-text", "oversize"],
)
def test_wrong_source_bytes_and_bounds_fail_before_schema(body: bytes) -> None:
    with pytest.raises(EvidenceError, match=r"SOURCE_BYTES|BODY_BOUND"):
        build_features(body, source=owned_source(), request=owned_request())


def test_packaged_resource_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    body = owned_body()
    monkeypatch.setattr(qualification, "owned_body", lambda: b"changed resource")
    with pytest.raises(EvidenceError, match="PACKAGED_SOURCE_IDENTITY_CHANGED"):
        build_features(body, source=owned_source(), request=owned_request())


@pytest.mark.parametrize(
    "body",
    [
        b'{"schema_version": "x", "schema_version": "y"}',
        b'{"x": NaN}',
        b'{"x": Infinity}',
        b'{"x": 1.2}',
        b"{" + b'"x":[' * 24 + b"0" + b"]}" * 24,
        b'{"x":' + b"[" * 24 + b"0" + b"]" * 24 + b"}",
        b"\xff",
        b"x" * 262_145,
    ],
    ids=["duplicates", "nan", "infinity", "binary-float", "malformed", "depth", "utf8", "oversize"],
)
def test_strict_json_rejects_duplicates_numbers_depth_and_encoding(body: bytes) -> None:
    with pytest.raises(EvidenceError, match=r"SCHEMA_INVALID|BODY_BOUND"):
        decode_dataset(body)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("mappings", "effective_until", "2026-01-01T00:00:00Z"),
        ("mappings", "observed_at", "2028-01-01T00:00:00Z"),
        ("mappings", "usable_at", "2026-08-01T12:00:00"),
        ("fixtures", "away_provider_team_id", "a"),
        ("fixtures", "finished_at", "2026-09-01T11:00:00Z"),
        ("fixtures", "observed_at", "2026-09-01T13:00:00Z"),
        ("memberships", "provider_team_id", "wrong-team"),
        ("memberships", "provider_fixture_id", "not-a-fixture"),
        ("observations", "minutes", True),
        ("observations", "revision", True),
        ("observations", "minutes", 91),
        ("observations", "minutes", 0),
        ("observations", "minutes", None),
        ("observations", "minutes_missing_reason", "NOT_REPORTED"),
        ("observations", "role", "UNKNOWN"),
        ("observations", "supersedes_sha256", "0" * 64),
        ("observations", "observed_at", "2026-09-01T12:00:00Z"),
        ("observations", "extra_field", "not-accepted"),
    ],
)
def test_schema_attacks_fail_closed(section: str, field: str, value: object) -> None:
    raw = _raw()
    raw[section][0][field] = value
    with pytest.raises(EvidenceError, match="PARTICIPATION_SCHEMA_INVALID"):
        _dataset(raw)


@pytest.mark.parametrize("section", ["mappings", "fixtures", "memberships", "observations"])
def test_duplicate_identity_rejected(section: str) -> None:
    raw = _raw()
    raw[section].append(copy.deepcopy(raw[section][0]))
    with pytest.raises(EvidenceError, match="PARTICIPATION_SCHEMA_INVALID"):
        _dataset(raw)


@pytest.mark.parametrize(
    "attack", ["missing_parent", "wrong_hash", "same_time", "earlier_observed"]
)
def test_revision_lineage_attacks(attack: str) -> None:
    raw = _raw()
    correction = raw["observations"][-1]
    if attack == "missing_parent":
        correction["revision"] = 2
    elif attack == "wrong_hash":
        correction["supersedes_sha256"] = "0" * 64
    elif attack == "same_time":
        correction["observed_at"] = "2026-09-15T15:00:00Z"
        correction["usable_at"] = "2026-09-15T15:01:00Z"
    else:
        correction["observed_at"] = "2026-09-15T14:00:00Z"
    with pytest.raises(EvidenceError, match="PARTICIPATION_SCHEMA_INVALID"):
        _dataset(raw)


def test_out_positive_is_rejected_and_unused_bench_zero_is_supported() -> None:
    raw = _raw()
    item = next(item for item in raw["observations"] if item["role"] == "OUT")
    item["minutes"] = 1
    with pytest.raises(EvidenceError, match="PARTICIPATION_SCHEMA_INVALID"):
        _dataset(raw)
    assert _features(1).bench_minutes.counts == {0: 1}


def test_ambiguous_mapping_and_team_disagreement_fail_closed() -> None:
    raw = _raw()
    clone = copy.deepcopy(raw["mappings"][0])
    clone["mapping_id"] = "overlapping-player-map"
    raw["mappings"].append(clone)
    request = owned_request()
    scope = next(item for item in request.players if str(item.player_id) == _player(1))
    with pytest.raises(EvidenceError, match="CANONICAL_IDENTITY_AMBIGUOUS"):
        _player_features(_dataset(raw), request, scope)
    raw = _raw()
    observation = next(
        item
        for item in raw["observations"]
        if item["provider_player_id"] == "p2" and item["provider_fixture_id"] == "f3"
    )
    observation["provider_team_id"] = "o"
    scope = next(item for item in request.players if str(item.player_id) == _player(2))
    with pytest.raises(EvidenceError, match="MEMBERSHIP_TEAM_DISAGREEMENT"):
        _player_features(_dataset(raw), request, scope)


def test_post_cutoff_correction_and_future_fixture_do_not_change_earlier_statistics() -> None:
    raw = _raw()
    raw["observations"][-1]["minutes"] = 88
    future = next(item for item in raw["observations"] if item["provider_fixture_id"] == "f12")
    future["minutes"] = 1
    request = owned_request()
    scope = next(item for item in request.players if str(item.player_id) == _player(1))
    assert _player_features(_dataset(raw), request, scope) == _features(1)


def test_known_history_window_is_bounded_without_implicit_carry_forward() -> None:
    request = owned_request().model_copy(update={"maximum_fixtures": 2})
    result = build_features(owned_body(), source=owned_source(), request=request)
    player = next(item for item in result.players if str(item.player_id) == _player(1))
    assert player.opportunity_count == 2
    assert player.selected_count == 2
    assert player.missingness["OUTSIDE_WINDOW"] == 5
    assert player.mean_minutes.value == Decimal(0)
    assert player.role_counts["START"] == 1
    old = owned_request().model_copy(update={"history_start": datetime(2026, 9, 20, tzinfo=UTC)})
    result = build_features(owned_body(), source=owned_source(), request=old)
    player = next(item for item in result.players if str(item.player_id) == _player(1))
    assert player.missingness["OUTSIDE_WINDOW"] == 4


@pytest.mark.parametrize(
    "attack", ["naive", "after_target", "duplicate_player", "unordered", "zero_window"]
)
def test_request_attacks(attack: str) -> None:
    request = owned_request()
    changes: dict[str, Any]
    if attack == "naive":
        changes = {"cutoff": datetime(2026, 9, 30)}
    elif attack == "after_target":
        changes = {"cutoff": request.target_kickoff + timedelta(seconds=1)}
    elif attack == "duplicate_player":
        changes = {"players": (request.players[0], request.players[0])}
    elif attack == "unordered":
        changes = {"players": tuple(reversed(request.players))}
    else:
        changes = {"maximum_fixtures": 0}
    with pytest.raises(ValidationError):
        build_features(
            owned_body(), source=owned_source(), request=request.model_copy(update=changes)
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"numerator": 1, "denominator": 0, "value": None},
        {"numerator": 0, "denominator": 0, "value": Decimal(0)},
        {"numerator": 1, "denominator": 2, "value": Decimal("0.6")},
    ],
)
def test_ratio_never_loses_denominator_or_invents_zero(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Ratio.model_validate(kwargs)


@pytest.mark.parametrize("counts", [{91: 1}, {0: 0}, {1: -1}, {30: 2}])
def test_empirical_minute_support_is_validated(counts: dict[int, int]) -> None:
    with pytest.raises(ValidationError):
        MinuteDistribution(sample_count=1, counts=counts)


@pytest.mark.parametrize(
    "attack",
    [
        "source",
        "population",
        "mapping_receipt",
        "role_counts",
        "selected_count",
        "coverage",
        "age",
        "minute_support",
    ],
)
def test_report_contract_rejects_false_provenance_coverage_and_support(attack: str) -> None:
    body = owned_demo().model_dump(mode="json")
    player = next(item for item in body["players"] if item["selected_count"] > 0)
    if attack == "source":
        body["source"]["qualification"] = "PROPOSED"
    elif attack == "population":
        body["players"].pop()
    elif attack == "mapping_receipt":
        player["selected"][0]["identity_mapping_sha256s"].pop()
    elif attack == "role_counts":
        player["role_counts"]["OUT"] = -1
    elif attack == "selected_count":
        player["selected_count"] += 1
    elif attack == "coverage":
        player["coverage_status"] = "COMPLETE"
    elif attack == "age":
        player["latest_observation_age_seconds"] = None
    else:
        player["all_minutes"]["counts"] = {}
        player["all_minutes"]["sample_count"] = 0
    with pytest.raises(ValidationError):
        EvidenceFeatureSet.model_validate_json(json.dumps(body))
