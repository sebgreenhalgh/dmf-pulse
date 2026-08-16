"""Rules-owned inputs and deterministic autosubstitution semantics for OPT-010.

This module deliberately consumes compiled rules rather than carrying FPL policy constants in
the optimiser.  Test/reference rules may be complete and explicitly marked REFERENCE_ONLY;
production requires the separately verified FULL_SEASON capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Any

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.models import OneGameweekRulesView
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
    RulesetStatus,
)


@dataclass(frozen=True)
class AutoSubstitutionResolution:
    player_out: str
    player_in: str
    slot: int
    position: PlayerPosition


def _plain(value: Any, path: str) -> Any:
    if isinstance(value, dict) and value.get("verification_status") in {"UNKNOWN", "CONFLICTED"}:
        raise RulesValidationError(
            "RULESET_VALUE_UNRESOLVED", f"required value is unresolved: {path}"
        )
    if isinstance(value, dict) and set(value) >= {"value", "verification_status"}:
        if value.get("value") is None:
            raise RulesValidationError(
                "RULESET_VALUE_UNRESOLVED", f"required value is unresolved: {path}"
            )
        return value["value"]
    return value


def _mapping(rules: dict[str, Any], path: str) -> dict[str, Any]:
    value: Any = rules
    for part in path.strip("/").split("/"):
        if not isinstance(value, dict) or part not in value:
            raise RulesValidationError(
                "RULESET_VALUE_MISSING", f"required value is absent: /{path}"
            )
        value = value[part]
    value = _plain(value, f"/{path}")
    if not isinstance(value, dict):
        raise RulesValidationError("RULESET_VALUE_INVALID", f"required mapping is invalid: /{path}")
    return value


def _int(value: Any, path: str) -> int:
    value = _plain(value, path)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RulesValidationError(
            "RULESET_VALUE_INVALID", f"required non-negative integer is invalid: {path}"
        )
    return int(value)


def _bool(value: Any, path: str) -> bool:
    value = _plain(value, path)
    if not isinstance(value, bool):
        raise RulesValidationError("RULESET_VALUE_INVALID", f"required boolean is invalid: {path}")
    return value


def _literal(value: Any, expected: str, path: str) -> str:
    value = _plain(value, path)
    if value != expected:
        raise RulesValidationError(
            "RULESET_VALUE_INVALID", f"required controlled value is invalid: {path}"
        )
    return expected


def _capability_allows_production(
    compiled: CompiledRuleset, capability: CapabilityArtifact | None
) -> None:
    if (
        compiled.status is not RulesetStatus.ACTIVE
        or not compiled.production_eligible
        or capability is None
        or capability.capability is not RuleCapability.FULL_SEASON
    ):
        raise RulesValidationError(
            "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE",
            "FULL_SEASON manager-tactics capability is not production eligible",
        )
    expected = compile_capability_artifact(compiled, RuleCapability.FULL_SEASON)
    if (
        capability.model_dump(mode="json") != expected.model_dump(mode="json")
        or not expected.source_backed
        or not expected.production_eligible
        or expected.blockers
    ):
        raise RulesValidationError(
            "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE",
            "FULL_SEASON manager-tactics capability does not match the compiled ruleset",
        )


def build_one_gameweek_rules_view(
    compiled: CompiledRuleset,
    *,
    projection_mode: ProjectionMode,
    capability: CapabilityArtifact | None = None,
) -> OneGameweekRulesView:
    """Resolve the minimum immutable rules view required by one-Gameweek search."""

    if projection_mode is ProjectionMode.PRODUCTION:
        _capability_allows_production(compiled, capability)
    elif compiled.status not in {
        RulesetStatus.REFERENCE_ONLY,
        RulesetStatus.ACTIVE,
        RulesetStatus.VERIFIED,
    }:
        raise RulesValidationError(
            "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE",
            "test/replay optimisation requires a complete reference or verified ruleset",
        )

    positions = _mapping(compiled.rules, "positions/positions")
    squad = _mapping(compiled.rules, "squad")
    lineup = _mapping(compiled.rules, "lineup")
    auto = _mapping(compiled.rules, "lineup/automatic_substitutions")
    quotas: dict[PlayerPosition, int] = {}
    mins: dict[PlayerPosition, int] = {}
    maxes: dict[PlayerPosition, int] = {}
    for position in PlayerPosition:
        raw = positions.get(position.value)
        if raw is None:  # pragma: no branch - complete compiled rules are required
            raise RulesValidationError(
                "RULESET_VALUE_MISSING", f"missing position rules: {position.value}"
            )
        raw = _plain(raw, f"/rules/positions/positions/{position.value}")
        if not isinstance(raw, dict):  # pragma: no branch - complete compiled rules are required
            raise RulesValidationError("RULESET_VALUE_INVALID", "position rules are invalid")
        quotas[position] = _int(
            raw.get("squad_quota"), f"/rules/positions/{position.value}/squad_quota"
        )
        mins[position] = _int(
            raw.get("lineup_min"), f"/rules/positions/{position.value}/lineup_min"
        )
        maxes[position] = _int(
            raw.get("lineup_max"), f"/rules/positions/{position.value}/lineup_max"
        )

    def get_int(name: str, source: dict[str, Any], path: str) -> int:
        return _int(source.get(name), f"/{path}/{name}")

    starting_size = get_int("starting_size", lineup, "rules/lineup")
    bench_size = get_int("bench_size", lineup, "rules/lineup")
    budget = _int(squad.get("initial_budget_tenths"), "/rules/squad/initial_budget_tenths")
    clubs = _int(squad.get("max_per_club"), "/rules/squad/max_per_club")
    multiplier = get_int("captain_multiplier", lineup, "rules/lineup")
    vice = _bool(lineup.get("vice_fallback"), "/rules/lineup/vice_fallback")
    timing = _literal(
        auto.get("evaluation_scope"),
        "AFTER_ALL_GAMEWEEK_FIXTURES",
        "/rules/lineup/automatic_substitutions/evaluation_scope",
    )
    _literal(
        auto.get("absent_definition"),
        "ZERO_OFFICIAL_APPEARANCE_MINUTES",
        "/rules/lineup/automatic_substitutions/absent_definition",
    )
    _literal(
        auto.get("goalkeeper_replacement"),
        "DESIGNATED_BENCH_GOALKEEPER_IF_APPEARED",
        "/rules/lineup/automatic_substitutions/goalkeeper_replacement",
    )
    _literal(
        auto.get("outfield_order"),
        "MANAGER_BENCH_ORDER",
        "/rules/lineup/automatic_substitutions/outfield_order",
    )
    return OneGameweekRulesView(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        projection_mode=projection_mode,
        squad_size=sum(quotas.values()),
        position_squad_quota=quotas,
        starting_size=starting_size,
        bench_size=bench_size,
        lineup_min=mins,
        lineup_max=maxes,
        initial_budget_tenths=budget,
        max_players_per_club=clubs,
        captain_multiplier=multiplier,
        vice_captain_fallback=vice,
        auto_substitution_timing=timing,
        auto_substitution_zero_appearance_minutes=0,
        designated_bench_goalkeeper_if_appeared=True,
        manager_bench_order=True,
        maintain_legal_formation=_bool(
            auto.get("maintain_legal_formation"),
            "/rules/lineup/automatic_substitutions/maintain_legal_formation",
        ),
        capability=RuleCapability.FULL_SEASON.value
        if projection_mode is ProjectionMode.PRODUCTION
        else "REFERENCE_ONLY",
    )


def resolve_outfield_substitutions(
    *,
    starting_outfield: tuple[str, ...],
    bench_outfield: tuple[str, ...],
    positions: dict[str, PlayerPosition],
    appeared: set[str],
    lineup_min: dict[PlayerPosition, int],
    lineup_max: dict[PlayerPosition, int],
) -> tuple[AutoSubstitutionResolution, ...]:
    """Apply the frozen reference/test bench-order semantics deterministically.

    The accepted fixture needs the complete maximum-cardinality subset of appearing bench
    players, with earlier bench slots preferred.  Audit pairs are then selected so each
    sequential substitution leaves a legal formation; this avoids the historical bug that
    paired an incoming forward with the lexically first absent defender merely for reporting.
    """

    absent = tuple(player for player in starting_outfield if player not in appeared)
    eligible = tuple(player for player in bench_outfield if player in appeared)
    if not absent or not eligible:
        return ()
    best: tuple[tuple[int, ...], tuple[str, ...]] | None = None
    n = len(eligible)
    for mask in range(1 << n):
        selected = tuple(eligible[i] for i in range(n) if mask & (1 << i))
        if len(selected) > len(absent):
            continue
        remaining = [player for player in starting_outfield if player not in absent]
        final = remaining + list(selected)
        outfield_positions = (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
        counts = {
            position: sum(positions[p] is position for p in final)
            for position in outfield_positions
        }
        if any(counts[p] < lineup_min[p] or counts[p] > lineup_max[p] for p in outfield_positions):
            continue
        vector = tuple(1 if mask & (1 << i) else 0 for i in range(n))
        candidate = (vector, selected)
        if best is None or (len(selected), vector) > (len(best[1]), best[0]):
            best = candidate
    if best is None:
        return ()
    selected = best[1]
    pairings: list[tuple[str, ...]] = []
    for outgoing in permutations(absent, len(selected)):
        active = list(starting_outfield)
        valid = True
        for player_out, player_in in zip(outgoing, selected, strict=True):
            if player_out not in active:
                valid = False
                break
            active[active.index(player_out)] = player_in
            counts = {
                position: sum(positions[player] is position for player in active)
                for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
            }
            if any(
                counts[position] < lineup_min[position] or counts[position] > lineup_max[position]
                for position in counts
            ):
                valid = False
                break
        if valid:
            pairings.append(outgoing)
    if not pairings:
        return ()
    outgoing = min(pairings)
    return tuple(
        AutoSubstitutionResolution(
            player_out=out,
            player_in=inc,
            slot=bench_outfield.index(inc) + 1,
            position=positions[inc],
        )
        for out, inc in zip(outgoing, selected, strict=True)
    )
