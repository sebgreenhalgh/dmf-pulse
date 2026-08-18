"""Contract tests for the durable 2026/27 target-season ruleset."""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.manager_state import selling_price_tenths
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.chips import (
    ChipManagerState,
    build_chip_rules_view,
    cancel_pending_chip,
    complete_chip_gameweek,
    confirm_chip_transfers,
    declarative_chip_blockers,
    finalise_chip_deadline,
    play_chip,
    replace_chip_squad,
    score_chip_gameweek,
    transfer_hit_points,
)
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import RuleCapability, RulesetStatus
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET = REPO_ROOT / "config/rules/fpl-2026-27"


@pytest.fixture(scope="module")
def compiled():
    return compile_ruleset(TARGET)


def _state(compiled, gameweek: int = 10) -> ChipManagerState:
    squad = tuple(f"p{index:02d}" for index in range(15))
    return ChipManagerState(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        gameweek=gameweek,
        saved_free_transfers=3,
        permanent_squad=squad,
        active_squad=squad,
        bank_tenths=10,
        purchase_prices_tenths={player_id: 50 for player_id in squad},
    )


def test_target_compiles_to_source_backed_full_season_capability(compiled) -> None:
    assert compiled.status is RulesetStatus.VERIFIED
    assert compiled.production_eligible
    assert compiled.unknown_blockers == ()
    artifact = compile_capability_artifact(compiled, RuleCapability.FULL_SEASON)
    assert artifact.source_backed
    assert artifact.ready_for_human_approval
    assert artifact.production_eligible
    assert artifact.blockers == ()
    assert all(source["content_sha256"] for source in compiled.rules["source_manifest"]["sources"])


def test_exact_squad_lineup_transfer_and_deadline_contract(compiled) -> None:
    positions = compiled.rules["positions"]["positions"]
    assert {key: value["squad_quota"] for key, value in positions.items()} == {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }
    assert compiled.rules["squad"] == {
        "initial_budget_tenths": 1000,
        "max_per_club": 3,
        "squad_size": 15,
    }
    assert compiled.rules["lineup"]["starting_size"] == 11
    assert compiled.rules["lineup"]["bench_size"] == 4
    transition = compiled.rules["transfers"]["transition"]
    assert transition["free_transfer_cap"] == 5
    assert transition["max_transfers_per_deadline"] == 20
    assert transition["hit_points"] == -4
    deadlines = compiled.rules["deadlines"]["gameweeks"]
    assert [row["number"] for row in deadlines] == list(range(1, 39))
    assert deadlines[0]["deadline_utc"] == "2026-08-21T17:30:00Z"
    assert deadlines[18]["deadline_utc"] == "2027-01-02T13:30:00Z"
    assert deadlines[-1]["deadline_utc"] == "2027-05-30T13:30:00Z"


def test_stage_11_consumes_twenty_transfer_cap_and_all_selling_branches(compiled) -> None:
    rules = build_multi_gameweek_transfer_rules(compiled, projection_mode=ProjectionMode.TEST)
    assert rules.max_transfers_per_deadline == 20
    assert rules.maximum_free_transfers == 5
    assert rules.hit_cost_per_paid_transfer == 4
    assert set(rules.event_rules) == {"NORMAL", "PRESEASON", "LATE_ENTRY"}
    expected = {(50, 54): 52, (50, 53): 51, (50, 50): 50, (50, 47): 47}
    for (purchase, current), selling in expected.items():
        assert (
            selling_price_tenths(
                purchase_price_tenths=purchase,
                current_price_tenths=current,
                rule=rules.selling_price_rule,
            )
            == selling
        )


def test_wildcard_pending_threshold_cancellation_hits_and_permanence(compiled) -> None:
    rules = build_chip_rules_view(compiled)
    original = _state(compiled)
    pending = play_chip(original, rules, "WILDCARD", confirmed_transfer_count=1)
    assert pending.pending_chip == "WILDCARD"
    assert cancel_pending_chip(pending, rules).pending_chip is None
    active = confirm_chip_transfers(pending, rules, confirmed_transfer_count=2)
    assert active.active_chip == "WILDCARD"
    assert transfer_hit_points(active, rules, transfer_count=20, available_free_transfers=1) == 0
    replacement = tuple(f"w{index:02d}" for index in range(15))
    changed = replace_chip_squad(
        active,
        rules,
        squad=replacement,
        bank_tenths=5,
        purchase_prices_tenths={player_id: 55 for player_id in replacement},
    )
    completed = complete_chip_gameweek(changed, rules, next_gameweek=11)
    assert completed.permanent_squad == replacement
    assert completed.active_squad == replacement
    assert completed.saved_free_transfers == 3


def test_free_hit_restores_squad_bank_prices_and_rejects_consecutive_use(compiled) -> None:
    rules = build_chip_rules_view(compiled)
    original = _state(compiled, gameweek=19)
    active = play_chip(original, rules, "FREE_HIT", confirmed_transfer_count=1)
    replacement = tuple(f"f{index:02d}" for index in range(15))
    changed = replace_chip_squad(
        active,
        rules,
        squad=replacement,
        bank_tenths=2,
        purchase_prices_tenths={player_id: 60 for player_id in replacement},
    )
    restored = complete_chip_gameweek(changed, rules, next_gameweek=20)
    assert restored.active_squad == original.permanent_squad
    assert restored.bank_tenths == original.bank_tenths
    assert restored.purchase_prices_tenths == original.purchase_prices_tenths
    assert restored.saved_free_transfers == original.saved_free_transfers
    with pytest.raises(ValueError, match="configured Gameweek gap"):
        play_chip(restored, rules, "FREE_HIT", confirmed_transfer_count=1)


def test_chip_inventory_windows_gw1_and_one_chip_constraint(compiled) -> None:
    rules = build_chip_rules_view(compiled)
    gw1 = _state(compiled, gameweek=1)
    with pytest.raises(ValueError, match="outside its configured inventory window"):
        play_chip(gw1, rules, "FREE_HIT", confirmed_transfer_count=1)
    bench_boost = play_chip(gw1, rules, "BENCH_BOOST")
    with pytest.raises(ValueError, match="only one chip"):
        play_chip(bench_boost, rules, "TRIPLE_CAPTAIN")
    cancelled = cancel_pending_chip(bench_boost, rules)
    assert cancelled.pending_chip is None

    used = finalise_chip_deadline(play_chip(gw1, rules, "TRIPLE_CAPTAIN"), rules)
    next_state = complete_chip_gameweek(used, rules, next_gameweek=2).model_copy(
        update={"gameweek": 20}
    )
    second = finalise_chip_deadline(play_chip(next_state, rules, "TRIPLE_CAPTAIN"), rules)
    assert len(second.use_history) == 2


def test_triple_captain_vice_fallback_and_bench_boost_scoring(compiled) -> None:
    rules = build_chip_rules_view(compiled)
    base = _state(compiled)
    points = {player_id: 1 for player_id in base.active_squad}
    starters = base.active_squad[:11]
    bench = base.active_squad[11:]
    triple = finalise_chip_deadline(play_chip(base, rules, "TRIPLE_CAPTAIN"), rules)
    result = score_chip_gameweek(
        triple,
        rules,
        player_points=points,
        starter_ids=starters,
        bench_ids=bench,
        captain_id=starters[0],
        vice_captain_id=starters[1],
        appeared_player_ids=frozenset({starters[1]}),
        normal_captain_multiplier=2,
    )
    assert result.effective_captain == starters[1]
    assert result.captain_multiplier == 3
    assert result.total_points == 13

    boosted = finalise_chip_deadline(play_chip(base, rules, "BENCH_BOOST"), rules)
    result = score_chip_gameweek(
        boosted,
        rules,
        player_points=points,
        starter_ids=starters,
        bench_ids=bench,
        captain_id=starters[0],
        vice_captain_id=starters[1],
        appeared_player_ids=frozenset(starters),
        normal_captain_multiplier=2,
    )
    assert result.bench_included
    assert result.total_points == 16


def test_captain_multiplier_is_executed_from_rules_data(compiled) -> None:
    chips = copy.deepcopy(compiled.rules["chips"])
    triple_data = next(chip for chip in chips["chips"] if chip["key"] == "TRIPLE_CAPTAIN")
    triple_data["effects"][0]["parameters"]["multiplier"] = 4
    assert declarative_chip_blockers(chips) == ()

    rules = build_chip_rules_view(compiled)
    triple_index = next(
        index for index, chip in enumerate(rules.chips) if chip.key == "TRIPLE_CAPTAIN"
    )
    triple_rule = rules.chips[triple_index]
    effect = triple_rule.effects[0].model_copy(
        update={"parameters": {"multiplier": 4, "vice_fallback": True}}
    )
    data_driven_rule = triple_rule.model_copy(update={"effects": (effect,)})
    data_driven_rules = rules.model_copy(
        update={
            "chips": tuple(
                data_driven_rule if index == triple_index else chip
                for index, chip in enumerate(rules.chips)
            )
        }
    )
    base = _state(compiled)
    active = finalise_chip_deadline(
        play_chip(base, data_driven_rules, "TRIPLE_CAPTAIN"), data_driven_rules
    )
    points = {player_id: 1 for player_id in base.active_squad}
    result = score_chip_gameweek(
        active,
        data_driven_rules,
        player_points=points,
        starter_ids=base.active_squad[:11],
        bench_ids=base.active_squad[11:],
        captain_id=base.active_squad[0],
        vice_captain_id=base.active_squad[1],
        appeared_player_ids=frozenset(base.active_squad[:11]),
        normal_captain_multiplier=2,
    )
    assert result.captain_multiplier == 4
    assert result.total_points == 14


def test_official_source_captures_are_locatable_and_digest_bound(compiled) -> None:
    for source in compiled.rules["source_manifest"]["sources"]:
        capture = REPO_ROOT / source["content_path"]
        assert capture.is_file()
        assert hashlib.sha256(capture.read_bytes()).hexdigest() == source["content_sha256"]


def test_reference_and_synthetic_hashes_remain_unchanged() -> None:
    root = REPO_ROOT / "fixtures/rules/RUL-002"
    assert compile_ruleset(root / "reference_2025_26").ruleset_hash == (
        "12271ab0b32a461baa3778f2e914f45744ccf9d5302c37c4a5f2ffb89e0c1139"
    )
    assert compile_ruleset(root / "synthetic_complete").ruleset_hash == (
        "98e8614d9971ec2b1e45a357e89f79172bbc5dd4dc87044c3c131b3de6b0aab8"
    )


def test_target_policy_is_not_a_runtime_season_conditional() -> None:
    violations: list[str] = []
    paths = [
        *(REPO_ROOT / "src/dmf_pulse/rules").rglob("*.py"),
        REPO_ROOT / "src/dmf_pulse/optimisation/manager_state.py",
        REPO_ROOT / "src/dmf_pulse/optimisation/multi_gameweek_models.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                continue
            constants = {
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, (str, int))
            }
            if 2026 in constants or constants.intersection({"2026/27", "2026/2027"}):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert violations == []


def test_temporary_transport_machinery_is_absent() -> None:
    assert not list((REPO_ROOT / "automation").glob("rules-readiness-payload.part-*"))
    assert not list((REPO_ROOT / ".github/workflows").glob("rules-readiness-*.yml"))
