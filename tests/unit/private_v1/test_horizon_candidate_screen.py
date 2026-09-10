"""R5 horizon-screen adversaries use repository-owned synthetic players only."""

from types import SimpleNamespace

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.multi_gameweek_models import PlayerCatalogEntry, PlayerPriceState
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.service import (
    _bounded_private_incoming_ids,
    _horizon_private_incoming_ids,
)


def screen_fixture(count=30, *, same_club=False, tied=False):
    ids = tuple(f"candidate-{i:03d}" for i in range(count))
    catalog = {
        p: PlayerCatalogEntry(
            player_id=p, position=PlayerPosition.MID, club_id="same" if same_club else f"club-{p}"
        )
        for p in ids
    }
    prices = {p: PlayerPriceState(current_price_tenths=50) for p in ids}
    projections = []
    for gw in range(1, 4):
        points = {p: 100 if tied else 100 - i for i, p in enumerate(ids)}
        if gw > 1 and not tied:
            points[ids[-1]] = 500
        projections.append(
            SimpleNamespace(
                result_sha256=canonical_sha256({"gw": gw, "points": points}),
                scenario_set=SimpleNamespace(
                    gameweek_id=f"GW-{gw}",
                    scenarios=(
                        SimpleNamespace(
                            player_points=points, player_appeared={p: True for p in ids}
                        ),
                    ),
                ),
                player_summaries={
                    p: SimpleNamespace(expected_points=v, points_standard_deviation=0)
                    for p, v in points.items()
                },
            )
        )
    return ids, catalog, prices, tuple(projections)


def run_screen(fixture, *, maximum_transfers=1):
    ids, catalog, prices, projections = fixture
    return _horizon_private_incoming_ids(
        ids,
        catalog=catalog,
        prices=prices,
        gameweeks=projections,
        maximum_transfers=maximum_transfers,
    )


def test_future_star_excluded_by_r4_survives_horizon_screen():
    fixture = screen_fixture()
    ids, catalog, prices, projections = fixture
    old, _ = _bounded_private_incoming_ids(
        ids, catalog=catalog, prices=prices, gameweek=projections[0], maximum_transfers=1
    )
    assert ids[-1] not in old
    new = run_screen(fixture)
    assert ids[-1] in new.retained_incoming_ids
    assert set(old) <= set(new.retained_incoming_ids)
    assert new.horizon_gameweeks == (1, 2, 3)
    assert new.certified_dominated_candidates == 0


def test_root_false_dominance_is_not_a_horizon_certificate():
    fixture = screen_fixture(same_club=True)
    ids, catalog, prices, projections = fixture
    old, removed = _bounded_private_incoming_ids(
        ids, catalog=catalog, prices=prices, gameweek=projections[0], maximum_transfers=1
    )
    assert removed > 0 and ids[-1] not in old
    new = run_screen(fixture)
    assert new.certified_dominated_candidates == 0
    assert ids[-1] in new.retained_incoming_ids


def test_small_universe_keeps_every_valid_incoming_even_with_zero_root_ft():
    fixture = screen_fixture(count=4, same_club=True)
    assert run_screen(fixture, maximum_transfers=0).retained_incoming_ids == fixture[0]


def test_boundary_ties_are_complete_or_fail_closed_never_id_truncated():
    fixture = screen_fixture(count=8, tied=True)
    assert run_screen(fixture).retained_incoming_ids == fixture[0]
    with pytest.raises(PrivateV1Error, match="UNBOUNDED"):
        run_screen(screen_fixture(count=25, tied=True))


def test_screen_is_order_invariant_and_hash_binds_future_projection():
    fixture = screen_fixture()
    first = run_screen(fixture)
    ids, catalog, prices, projections = fixture
    reverse = run_screen((tuple(reversed(ids)), catalog, prices, projections))
    assert first == reverse
    projections[-1].result_sha256 = "f" * 64
    assert run_screen(fixture).semantic_sha256 != first.semantic_sha256


def test_aggregate_only_and_future_upside_buckets_have_independent_retention_paths():
    fixture = screen_fixture()
    ids, _, _, projections = fixture
    for index, projection in enumerate(projections):
        for i, p in enumerate(ids):
            projection.player_summaries[p].expected_points = 10 - i
        projection.player_summaries[ids[index * 10]].expected_points = 1000
        projection.player_summaries[ids[index * 10 + 1]].expected_points = 999
        projection.player_summaries[ids[15]].expected_points = 500
    projections[1].player_summaries[ids[29]].points_standard_deviation = 2000
    screen = run_screen(fixture)
    assert ids[15] in screen.retained_incoming_ids
    assert ids[29] in screen.retained_incoming_ids
    categories = dict(screen.retention_categories)
    assert categories["MID:HORIZON:EXPECTED"] >= 2
    assert categories["MID:GW2:UPSIDE"] == 1


def test_true_pointwise_horizon_superiority_still_does_not_certify_route_substitution():
    fixture = screen_fixture(count=4, same_club=True)
    ids, _, _, projections = fixture
    assert all(
        g.player_summaries[ids[0]].expected_points > g.player_summaries[ids[1]].expected_points
        for g in projections
    )
    screen = run_screen(fixture)
    assert screen.certified_dominated_candidates == 0
    assert {ids[0], ids[1]} <= set(screen.retained_incoming_ids)


@pytest.mark.parametrize("missing_hash", [False, True])
def test_unsealed_or_nonconsecutive_projection_horizon_is_rejected(missing_hash):
    fixture = screen_fixture()
    if missing_hash:
        fixture[3][-1].result_sha256 = None
    else:
        fixture[3][-1].scenario_set.gameweek_id = "GW-9"
    with pytest.raises(PrivateV1Error, match="HORIZON_SCREEN_INPUT_INVALID"):
        run_screen(fixture)


def test_disjoint_horizon_buckets_exceed_budget_without_silent_truncation():
    ids, catalog, prices, projections = screen_fixture(count=80)
    positions = tuple(PlayerPosition)
    catalog = {
        p: entry.model_copy(update={"position": positions[i % 4]})
        for i, (p, entry) in enumerate(catalog.items())
    }
    for gw, projection in enumerate(projections):
        for position in positions:
            members = [p for p in ids if catalog[p].position == position]
            projection.player_summaries[members[gw * 3]].expected_points = 1000
            projection.player_summaries[members[gw * 3 + 1]].expected_points = 999
            projection.player_summaries[members[gw * 3 + 2]].points_standard_deviation = 5000
    with pytest.raises(PrivateV1Error, match="PRIVATE_HORIZON_TRANSFER_SCREEN_UNBOUNDED"):
        run_screen((ids, catalog, prices, projections))
