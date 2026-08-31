from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.manual_override import (
    MANUAL_CONFIDENCE_REASON,
    MANUAL_MODEL_FAMILY,
    MANUAL_POLICY_SHA256,
    ManualFixtureMinutesInput,
    ManualOverrideError,
    build_manual_minutes_override,
    manual_fixture_input_sha256,
    manual_transient_policy_artifact,
)
from dmf_pulse.availability.projection import TeamMinutesProjection, canonical_sha256

from .manual_override_test_support import (
    deep_copy_input,
    valid_manual_input,
    with_always_out_player,
)

pytestmark = pytest.mark.unit


def _first_player(body: dict[str, object], *, role: str) -> dict[str, object]:
    home = body["home"]
    assert isinstance(home, dict)
    scenarios = home["scenarios"]
    assert isinstance(scenarios, list)
    players = scenarios[0]["players"]
    assert isinstance(players, list)
    return next(player for player in players if player["role"] == role)


def test_valid_manual_scenario_input_parses_and_hashes_complete_body() -> None:
    value = valid_manual_input()
    digest = manual_fixture_input_sha256(value)
    assert len(digest) == 64
    changed = value.model_dump(mode="json")
    changed["provenance"]["reason"] = "A different semantic reason."
    assert manual_fixture_input_sha256(ManualFixtureMinutesInput.model_validate(changed)) != digest


def test_counts_must_be_positive_integers_summing_exactly_256() -> None:
    body = deep_copy_input()
    body["home"]["scenarios"][0]["count"] = 63
    with pytest.raises(ValidationError, match="sum exactly to 256"):
        ManualFixtureMinutesInput.model_validate(body)
    body = deep_copy_input()
    body["home"]["scenarios"][0]["count"] = 64.0
    with pytest.raises(ValidationError):
        ManualFixtureMinutesInput.model_validate(body)


def test_start_zero_and_out_positive_minutes_are_rejected() -> None:
    body = deep_copy_input()
    _first_player(body, role="START")["official_minutes"] = 0
    with pytest.raises(ValidationError, match="START requires"):
        ManualFixtureMinutesInput.model_validate(body)
    body = deep_copy_input()
    _first_player(body, role="OUT")["official_minutes"] = 1
    with pytest.raises(ValidationError, match="OUT requires"):
        ManualFixtureMinutesInput.model_validate(body)


def test_duplicate_player_exact_starter_count_and_one_starting_gk_are_enforced() -> None:
    body = deep_copy_input()
    players = body["home"]["scenarios"][0]["players"]
    players[1]["player_id"] = players[0]["player_id"]
    with pytest.raises(ValidationError, match="duplicate player"):
        ManualFixtureMinutesInput.model_validate(body)

    body = deep_copy_input()
    _first_player(body, role="START")["role"] = "BENCH"
    with pytest.raises(ValidationError, match="exactly 11 START"):
        ManualFixtureMinutesInput.model_validate(body)

    body = deep_copy_input()
    starting_gk = _first_player(body, role="START")
    assert starting_gk["position"] == "GK"
    player_id = starting_gk["player_id"]
    for scenario in body["home"]["scenarios"]:
        row = next(item for item in scenario["players"] if item["player_id"] == player_id)
        row["position"] = "DEF"
    with pytest.raises(ValidationError, match="exactly one starting GK"):
        ManualFixtureMinutesInput.model_validate(body)


def test_invalid_or_noncanonical_uuid_and_post_cutoff_input_are_rejected() -> None:
    body = deep_copy_input()
    body["fixture_id"] = "unknown"
    with pytest.raises(ValidationError, match="canonical UUID"):
        ManualFixtureMinutesInput.model_validate(body)
    body = deep_copy_input()
    body["fixture_id"] = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    with pytest.raises(ValidationError, match="canonical UUID spelling"):
        ManualFixtureMinutesInput.model_validate(body)
    body = deep_copy_input()
    body["as_of"] = "2026-08-20T12:00:01Z"
    with pytest.raises(ValidationError, match="after information_cutoff"):
        ManualFixtureMinutesInput.model_validate(body)


def test_exact_player_projection_math_and_manual_provenance() -> None:
    bundle = build_manual_minutes_override(valid_manual_input())
    assert bundle.model_family == MANUAL_MODEL_FAMILY
    assert bundle.transformation_policy_sha256 == MANUAL_POLICY_SHA256
    assert bundle.classification == "PRIVATE_TRANSIENT"
    assert bundle.persistence_class == "TRANSIENT_PRIVATE"
    assert bundle.model_derived is False
    assert bundle.production_suitable is False
    for team in (bundle.home, bundle.away):
        assert team.sample_count == 256
        assert team.sum_p_start == "11.000000000000"
        assert team.sum_p_bench == "9.000000000000"
        for player in team.players:
            pmf = tuple(Decimal(item) for item in player.minute_pmf)
            assert len(pmf) == 91
            assert sum(pmf) == Decimal(1)
            assert Decimal(player.p_start) + Decimal(player.p_bench) + Decimal(
                player.p_out_of_squad
            ) == Decimal(1)
            assert player.p_zero_minutes == player.minute_pmf[0]
            assert Decimal(player.p_appearance) == Decimal(1) - pmf[0]
            assert Decimal(player.p_60_plus) == sum(pmf[60:])
            assert Decimal(player.expected_minutes) == sum(
                Decimal(index) * probability for index, probability in enumerate(pmf)
            )
            assert player.confidence_grade == "D"
            assert MANUAL_CONFIDENCE_REASON in player.confidence_reasons


def test_repeat_generation_is_byte_and_hash_identical() -> None:
    first = build_manual_minutes_override(valid_manual_input())
    second = build_manual_minutes_override(valid_manual_input())
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.semantic_sha256 == second.semantic_sha256


def test_semantic_minutes_change_updates_scenario_player_and_team_hashes() -> None:
    original = build_manual_minutes_override(valid_manual_input())
    body = deep_copy_input()
    player = _first_player(body, role="START")
    player_id = player["player_id"]
    player["official_minutes"] -= 1
    changed = build_manual_minutes_override(ManualFixtureMinutesInput.model_validate(body))
    assert changed.home.scenario_set_sha256 != original.home.scenario_set_sha256
    original_player = next(item for item in original.home.players if item.player_id == player_id)
    changed_player = next(item for item in changed.home.players if item.player_id == player_id)
    assert changed_player.projection_sha256 != original_player.projection_sha256
    assert changed.home.result_sha256 != original.home.result_sha256


def test_manual_output_cannot_masquerade_as_empirical_bayes() -> None:
    projection = build_manual_minutes_override(valid_manual_input()).home
    body = projection.model_dump(mode="json")
    body["model_family"] = "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
    hash_body = dict(body)
    hash_body.pop("result_sha256")
    body["result_sha256"] = canonical_sha256(hash_body)
    with pytest.raises(ValidationError, match="cannot contain manual provenance"):
        TeamMinutesProjection.model_validate(body)


def test_soft_degenerate_out_is_rejected_and_hard_ineligibility_is_authoritative() -> None:
    soft = ManualFixtureMinutesInput.model_validate(
        with_always_out_player(include_hard_override=False)
    )
    with pytest.raises(ManualOverrideError) as error:
        build_manual_minutes_override(soft)
    assert error.value.code == "SOFT_DEGENERATE_ROLE"

    hard = ManualFixtureMinutesInput.model_validate(
        with_always_out_player(include_hard_override=True)
    )
    bundle = build_manual_minutes_override(hard)
    hard_player_id = hard.home.hard_overrides[0].player_id
    projection = next(item for item in bundle.home.players if item.player_id == hard_player_id)
    assert projection.p_out_of_squad == "1.000000000000"
    assert projection.p_zero_minutes == "1.000000000000"
    assert "HARD_INELIGIBLE_OVERRIDE" in projection.confidence_reasons


def test_policy_artifact_copy_is_immutable_from_the_callers_perspective() -> None:
    first = manual_transient_policy_artifact()
    first["model_family"] = "TAMPERED"
    second = manual_transient_policy_artifact()
    assert second["model_family"] == MANUAL_MODEL_FAMILY
    assert canonical_sha256(second) == MANUAL_POLICY_SHA256
