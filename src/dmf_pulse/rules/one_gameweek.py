"""Rules-owned inputs and deterministic autosubstitution semantics for OPT-010.

This module deliberately consumes compiled rules rather than carrying FPL policy constants in
the optimiser.  Test/reference rules may be complete and explicitly marked REFERENCE_ONLY;
production requires the separately verified FULL_SEASON capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.models import OneGameweekRulesView
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


def _capability_allows_production(
    compiled: CompiledRuleset, capability: CapabilityArtifact | None
) -> None:
    if (  # pragma: no branch - every production capability failure is fail-closed
        compiled.status is not RulesetStatus.ACTIVE
        or not compiled.production_eligible
        or capability is None
        or capability.capability is not RuleCapability.FULL_SEASON
        or not capability.source_backed
        or not capability.production_eligible
        or capability.blockers
    ):
        raise RulesValidationError(
            "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE",
            "FULL_SEASON manager-tactics capability is not production eligible",
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
    budget = _int(squad.get("budget_tenths"), "/rules/squad/budget_tenths")
    clubs = _int(squad.get("max_players_per_club"), "/rules/squad/max_players_per_club")
    multiplier = get_int("captain_multiplier", lineup, "rules/lineup")
    vice = _bool(lineup.get("vice_captain_fallback"), "/rules/lineup/vice_captain_fallback")
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
        auto_substitution_timing=str(
            _plain(auto.get("timing"), "/rules/lineup/automatic_substitutions/timing")
        ),
        auto_substitution_zero_appearance_minutes=_int(
            auto.get("zero_official_appearance_minutes"),
            "/rules/lineup/automatic_substitutions/zero_official_appearance_minutes",
        ),
        designated_bench_goalkeeper_if_appeared=_bool(
            auto.get("designated_bench_goalkeeper_if_appeared"),
            "/rules/lineup/automatic_substitutions/designated_bench_goalkeeper_if_appeared",
        ),
        manager_bench_order=_bool(
            auto.get("manager_bench_order"),
            "/rules/lineup/automatic_substitutions/manager_bench_order",
        ),
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
    """Apply the frozen reference/test multiple-absence algorithm deterministically."""

    absent = tuple(player for player in starting_outfield if player not in appeared)
    eligible = tuple(player for player in bench_outfield if player in appeared)
    if not absent or not eligible:
        return ()
    best: tuple[tuple[int, ...], tuple[str, ...], tuple[tuple[str, str], ...]] | None = None
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
        incoming = tuple(sorted(selected))
        outgoing = tuple(sorted(absent[: len(selected)]))
        vector = tuple(1 if mask & (1 << i) else 0 for i in range(n))
        candidate = (vector, incoming, tuple(zip(outgoing, selected, strict=True)))
        if best is None or (len(selected), vector, tuple(-ord(c) for c in "".join(incoming))) > (
            len(best[2]),
            best[0],
            tuple(-ord(c) for c in "".join(best[1])),
        ):
            best = candidate
    if best is None:
        return ()
    return tuple(
        AutoSubstitutionResolution(
            player_out=out,
            player_in=inc,
            slot=bench_outfield.index(inc) + 1,
            position=positions[inc],
        )
        for out, inc in best[2]
    )
