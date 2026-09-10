"""Versioned private node-specific heuristic scope, separate from exact optimisation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import GameweekProjectionResult, PlayerPosition
from dmf_pulse.optimisation.multi_gameweek_models import PlayerCatalogEntry, PlayerPriceState
from dmf_pulse.private_v1.errors import PrivateV1Error

PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3 = "PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3"
# Four nominal slots per position plus at most two actual comparator incoming players.
# Residual ties are never cut to satisfy this budget. It does not guarantee solve time.
V3_STANDARD_MAX_RETAINED = 18
V3_STANDARD_MAX_ACTION_COMBINATIONS = 17000


@dataclass(frozen=True)
class NodeCandidateScreen:
    horizon_gameweeks: tuple[int, ...]
    retained_incoming_ids: tuple[str, ...]
    retention_categories: tuple[tuple[str, int], ...]
    protected_count: int
    tie_expansion: int
    largest_final_tie: int


@dataclass(frozen=True)
class BoundedHorizonScreen:
    nodes: tuple[NodeCandidateScreen, ...]
    full_incoming_count: int
    semantic_sha256: str
    policy: str = PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3
    maximum_retained: int = V3_STANDARD_MAX_RETAINED
    maximum_action_combinations: int = V3_STANDARD_MAX_ACTION_COMBINATIONS
    certified_dominated_candidates: int = 0
    equivalence_removed: int = 0


def _select(scores: dict[str, tuple[Decimal, ...]], limit: int) -> tuple[set[str], int, int]:
    if not scores:
        return set(), 0, 0
    cutoff = sorted(scores.values(), reverse=True)[min(limit, len(scores)) - 1]
    retained = {p for p, score in scores.items() if score >= cutoff}
    return retained, max(0, len(retained) - limit), sum(s == cutoff for s in scores.values())


def bounded_horizon_screen(
    player_ids: tuple[str, ...],
    *,
    catalog: dict[str, PlayerCatalogEntry],
    prices: dict[str, PlayerPriceState],
    gameweeks: tuple[GameweekProjectionResult, ...],
    protected_incoming_ids: tuple[str, ...],
) -> BoundedHorizonScreen:
    """Admit expected/value/price routes against each node's remaining cutoff horizon.

    Upside is an explicitly heuristic escape bucket required by DMFP-12 section 25.4,
    not a variance bonus in Stage 11. No dominance/equivalence theorem is asserted:
    identities, co-ownership and club/cohort routes preclude pairwise substitution.
    """
    ids = tuple(sorted(set(player_ids)))
    protected = set(protected_incoming_ids)
    horizon = tuple(int(g.scenario_set.gameweek_id.removeprefix("GW-")) for g in gameweeks)
    if (
        len(horizon) != 3
        or horizon != tuple(range(horizon[0], horizon[0] + 3))
        or any(g.result_sha256 is None for g in gameweeks)
        or not protected <= set(ids)
        or len(protected) > 2
    ):
        raise PrivateV1Error(
            "HORIZON_SCREEN_INPUT_INVALID",
            "sealed consecutive three-GW projections and at most two valid protected incoming required",
        )
    nodes: list[NodeCandidateScreen] = []
    memberships: list[dict[str, tuple[str, ...]]] = []
    by_position = {
        pos: tuple(p for p in ids if catalog[p].position == pos) for pos in PlayerPosition
    }
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        for index in range(3):
            buckets: dict[str, set[str]] = {
                "ACTUAL_ONE_GW_ACTION": protected if index == 0 else set()
            }
            expansion = largest = 0
            for position, members in by_position.items():
                if len(members) <= 4:
                    buckets[f"{position.value}:SMALL_UNIVERSE"] = set(members)
                    continue
                means = {
                    p: tuple(
                        Decimal(str(g.player_summaries[p].expected_points))
                        for g in gameweeks[index:]
                    )
                    for p in members
                }
                total = {p: sum(means[p], Decimal(0)) for p in members}
                costs = {p: Decimal(prices[p].current_price_tenths) for p in members}
                upside = {
                    p: total[p]
                    + sum(
                        (
                            Decimal(str(g.player_summaries[p].points_standard_deviation))
                            for g in gameweeks[index:]
                        ),
                        Decimal(0),
                    )
                    for p in members
                }
                # Every hierarchy uses only already-modelled football/economic quantities.
                # Sorting IDs below canonicalises membership; it never resolves a rank tie.
                metrics = (
                    (
                        "REMAINING_EXPECTED",
                        2,
                        {p: (total[p], means[p][0], -costs[p], *means[p]) for p in members},
                    ),
                    (
                        "PRICE_ROUTE",
                        1,
                        {p: (-costs[p], total[p], means[p][0], *means[p]) for p in members},
                    ),
                    (
                        "HEURISTIC_UPSIDE_ESCAPE",
                        1,
                        {
                            p: (upside[p], total[p], means[p][0], -costs[p], *means[p])
                            for p in members
                        },
                    ),
                )
                for reason, limit, scores in metrics:
                    selected, extra, tie = _select(scores, limit)
                    buckets[f"{position.value}:{reason}"] = selected
                    expansion += extra
                    largest = max(largest, tie)
                position_union = set().union(
                    *(v for name, v in buckets.items() if name.startswith(f"{position.value}:"))
                )
                if len(position_union) < 3:
                    # Two leaders can both be owned after FT2 recourse. When buckets
                    # overlap, use spare scope for the next expected-point routes.
                    # This is a disclosed heuristic escape, not an ownership proof.
                    selected, extra, tie = _select(
                        {p: score for p, score in metrics[0][2].items() if p not in position_union},
                        3 - len(position_union),
                    )
                    buckets[f"{position.value}:REMAINING_EXPECTED_DEPTH_ESCAPE"] = selected
                    expansion += extra
                    largest = max(largest, tie)
            retained = tuple(sorted(set().union(*buckets.values())))
            if len(retained) > V3_STANDARD_MAX_RETAINED:
                raise PrivateV1Error(
                    "PRIVATE_HORIZON_V3_FINAL_MODEL_TIE_CAPACITY",
                    f"full={len(ids)}; node=GW{horizon[index]}; protected={len(buckets['ACTUAL_ONE_GW_ACTION'])}; "
                    f"by_position={','.join(f'{p.value}:{len(m)}' for p, m in by_position.items())}; "
                    f"bucket_counts={','.join(f'{n}:{len(v)}' for n, v in sorted(buckets.items()))}; "
                    f"retained={len(retained)}; tie_expansion={expansion}; largest_final_tie={largest}; "
                    f"STANDARD_bound={V3_STANDARD_MAX_RETAINED}; policy={PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3}; "
                    "no valid bounded scope without splitting final metric ties; no identity truncation",
                )
            nodes.append(
                NodeCandidateScreen(
                    horizon_gameweeks=horizon[index:],
                    retained_incoming_ids=retained,
                    retention_categories=tuple((n, len(v)) for n, v in sorted(buckets.items())),
                    protected_count=len(buckets["ACTUAL_ONE_GW_ACTION"]),
                    tie_expansion=expansion,
                    largest_final_tie=largest,
                )
            )
            memberships.append({n: tuple(sorted(v)) for n, v in sorted(buckets.items())})
    digest = canonical_sha256(
        {
            "policy": PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3,
            "maximum_retained": V3_STANDARD_MAX_RETAINED,
            "maximum_action_combinations": V3_STANDARD_MAX_ACTION_COMBINATIONS,
            "projections": tuple(g.result_sha256 for g in gameweeks),
            "horizon": horizon,
            "catalog": {p: catalog[p].model_dump(mode="json") for p in ids},
            "prices": {p: prices[p].model_dump(mode="json") for p in ids},
            "protected": tuple(sorted(protected)),
            "buckets": memberships,
            "retained": tuple(n.retained_incoming_ids for n in nodes),
            "dominance": "CONSERVATIVE_NO_HORIZON_REMOVALS",
            "equivalence_compression": "NONE",
        }
    )
    return BoundedHorizonScreen(
        nodes=tuple(nodes), full_incoming_count=len(ids), semantic_sha256=digest
    )
