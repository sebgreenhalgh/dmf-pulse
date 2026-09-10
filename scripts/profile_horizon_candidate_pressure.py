"""Read-only V2 diagnostics on synthetic inputs; never changes a production bound."""

from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_right
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dmf_pulse.fpl_points.models import PlayerPosition  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_models import PlayerPriceState  # noqa: E402
from dmf_pulse.private_v1.errors import PrivateV1Error  # noqa: E402
from dmf_pulse.private_v1.service import _horizon_private_incoming_ids  # noqa: E402
from tests.unit.private_v1.horizon_oracle_support import oracle_fixture  # noqa: E402
from tests.unit.private_v1.test_horizon_candidate_screen import screen_fixture  # noqa: E402


def projected_legal_actions(fixture):
    """Exact positional/price count for this synthetic disjoint-club FT2 baseline.

    Incoming clubs are all distinct and absent from the owned squad; therefore no
    one/two-incoming combination can violate the club quota. No tactical work occurs.
    """
    ids, catalog, prices, _ = fixture
    base, _, _, _ = oracle_fixture()
    owned = base.initial_state.active_spells
    assert len({catalog[p].club_id for p in ids}) == len(ids)
    assert not {catalog[p].club_id for p in ids} & {p.club_id for p in owned}
    assert base.rules.max_players_per_club >= 2
    from dmf_pulse.optimisation.manager_state import selling_price_tenths

    selling = {
        p.player_id: selling_price_tenths(
            purchase_price_tenths=p.purchase_price_tenths,
            current_price_tenths=base.scenario_tree.root.prices[p.player_id].current_price_tenths,
            rule=base.rules.selling_price_rule,
        )
        for p in owned
    }
    counts = {}
    for count in (1, 2):
        costs = defaultdict(list)
        for incoming in combinations(ids, count):
            positions = tuple(sorted(catalog[p].position.value for p in incoming))
            costs[positions].append(sum(prices[p].current_price_tenths for p in incoming))
        for group in costs.values():
            group.sort()
        counts[str(count)] = sum(
            bisect_right(
                costs[tuple(sorted(p.position.value for p in outgoing))],
                base.initial_state.bank_tenths + sum(selling[p.player_id] for p in outgoing),
            )
            for outgoing in combinations(owned, count)
        )
    return {"baseline": "SYNTHETIC_ORACLE_INITIAL_SQUAD_AT_FT2", "legal_actions_by_count": counts}


def pressure_fixture(shape="large_tie"):
    count = 115 if shape == "large_tie" else 80 if shape == "low_overlap" else 600
    ids, catalog, prices, projections = screen_fixture(count=count)
    positions = tuple(PlayerPosition)
    catalog = {
        p: e.model_copy(update={"position": positions[i % 4]})
        for i, (p, e) in enumerate(catalog.items())
    }
    if shape == "large_tie":
        prices = {
            p: PlayerPriceState(current_price_tenths=80 if i < 4 else 40) for i, p in enumerate(ids)
        }
    for gw, projection in enumerate(projections):
        for i, p in enumerate(ids):
            projection.player_summaries[p].expected_points = 20 - i / 100
        if shape == "low_overlap":
            for position in positions:
                members = [p for p in ids if catalog[p].position == position]
                for rank in range(2):
                    projection.player_summaries[members[gw * 3 + rank]].expected_points = 40 - rank
                projection.player_summaries[members[gw * 3 + 2]].points_standard_deviation = 50
        elif gw > 0:
            projection.player_summaries[ids[-1]].expected_points = 50
        points = {p: projection.player_summaries[p].expected_points for p in ids}
        projection.scenario_set.scenarios[0].player_points = points
        from dmf_pulse.assurance.canonical import canonical_sha256

        projection.result_sha256 = canonical_sha256({"gw": gw + 1, "points": points})
    return ids, catalog, prices, projections


def v2_pressure(fixture):
    """Observe exact parent locals, including failure, without overriding its guards."""
    ids, catalog, prices, projections = fixture
    buckets = {}
    ties = []

    def observe(frame, event, arg):
        if event == "return" and frame.f_code.co_name == "_ranked_with_boundary_ties":
            values = frame.f_locals.get("values", {})
            if values:
                cutoff = sorted(values.values(), reverse=True)[frame.f_locals["limit"] - 1]
                group = sum(v == cutoff for v in values.values())
                ties.append((max(0, len(arg or ()) - frame.f_locals["limit"]), group))
        if event == "return" and frame.f_code is _horizon_private_incoming_ids.__code__:
            buckets.update(frame.f_locals.get("buckets", {}))

    previous = sys.getprofile()
    error = None
    try:
        sys.setprofile(observe)
        _horizon_private_incoming_ids(
            ids, catalog=catalog, prices=prices, gameweeks=projections, maximum_transfers=1
        )
    except PrivateV1Error as exc:
        error = str(exc)
    finally:
        sys.setprofile(previous)
    union = set().union(*buckets.values())
    cumulative = set()
    stages = {}
    selectors = (
        ("one_gw", lambda n: n == "ONE_GW_COUNTERFACTUAL_COMPATIBILITY"),
        ("per_gw_expected", lambda n: ":GW" in n and n.endswith(":EXPECTED")),
        ("per_gw_upside", lambda n: ":GW" in n and n.endswith(":UPSIDE")),
        ("per_gw_value", lambda n: ":GW" in n and n.endswith(":VALUE")),
        ("horizon_expected", lambda n: n.endswith(":HORIZON:EXPECTED")),
        ("horizon_value", lambda n: n.endswith(":HORIZON:VALUE")),
        ("price_route", lambda n: n.endswith(":PRICE_ROUTE")),
    )
    for category, selects in selectors:
        cumulative.update(set().union(*(v for n, v in buckets.items() if selects(n))))
        stages[category] = len(cumulative)
    return {
        "full_incoming": len(ids),
        "by_position": {
            pos.value: sum(catalog[p].position == pos for p in ids) for pos in PlayerPosition
        },
        "v2_union": len(union),
        "failure": error,
        "bucket_counts": {n: len(v) for n, v in buckets.items()},
        "unique_by_bucket": {
            n: len(v - set().union(*(other for key, other in buckets.items() if key != n)))
            for n, v in buckets.items()
        },
        "overlap_memberships": sum(map(len, buckets.values())) - len(union),
        "pairwise_overlap_nonzero": {
            f"{left}|{right}": len(buckets[left] & buckets[right])
            for left, right in combinations(sorted(buckets), 2)
            if buckets[left] & buckets[right]
        },
        "boundary_expansions": sum(e > 0 for e, _ in ties),
        "expanded_memberships": sum(e for e, _ in ties),
        "largest_boundary_tie": max((g for _, g in ties), default=0),
        "cumulative_union": stages,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = {}
    for shape in ("large_tie", "low_overlap", "high_overlap"):
        fixture = pressure_fixture(shape)
        payload[shape] = {
            **v2_pressure(fixture),
            "projected_actions": projected_legal_actions(fixture),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                shape: {
                    k: v
                    for k, v in data.items()
                    if k not in {"bucket_counts", "unique_by_bucket", "pairwise_overlap_nonzero"}
                }
                for shape, data in payload.items()
            }
        )
    )


if __name__ == "__main__":
    main()
