"""Finite exact current-FPL route sets; no wildcard or extra provider allowance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmf_pulse.dashboard.authorization import RouteBudget, SourceScope

pytestmark = pytest.mark.unit


def scope(provider: str, paths: tuple[str, ...]) -> SourceScope:
    return SourceScope.model_validate(
        {
            "provider": provider,
            "account_ref": "owned-account",
            "profile_id": "owned-profile",
            "profile_sha256": "b" * 64,
            "source_kind": "REPOSITORY_OWNED_SYNTHETIC",
            "routes": tuple(
                RouteBudget(host="fantasy.premierleague.com", path=path, maximum_calls=1)
                for path in paths
            ),
        }
    )


def test_current_fpl_twelve_finished_weeks_fit_without_changing_selection():
    # This is the actual acquisition shape: six fixed paths, one public picks
    # path and twelve distinct finished/data-checked event paths. Identifiers
    # here are owned invented fixtures, not an operator enrollment.
    paths = (
        "/api/bootstrap-static/",
        "/api/fixtures/",
        "/api/entry/999/",
        "/api/entry/999/history/",
        "/api/entry/999/transfers/",
        "/api/my-team/999/",
        "/api/entry/999/event/12/picks/",
        *(f"/api/event/{week}/live/" for week in range(1, 13)),
    )
    result = scope("FPL", paths)
    assert len(result.routes) == 19
    assert tuple(route.path for route in result.routes) == paths
    assert all(route.maximum_calls == 1 and route.method == "GET" for route in result.routes)


@pytest.mark.parametrize("count", [16, 17, 19, 24])
def test_fpl_scope_allows_only_a_bounded_explicit_route_list(count):
    paths = tuple(f"/api/event/{week}/live/" for week in range(1, count + 1))
    assert len(scope("FPL", paths).routes) == count


def test_fpl_scope_stays_within_the_existing_direct_client_twenty_four_cap():
    paths = tuple(f"/api/event/{week}/live/" for week in range(1, 26))
    with pytest.raises(ValidationError):
        scope("FPL", paths)


def test_other_public_source_keeps_its_original_sixteen_route_bound():
    paths = tuple(f"/resource/{index}/" for index in range(16))
    assert len(scope("OPENFOOTBALL", paths).routes) == 16
    with pytest.raises(ValidationError):
        scope("OPENFOOTBALL", (*paths, "/resource/16/"))


def test_odds_stays_exactly_one_route_and_duplicate_fpl_routes_still_fail():
    route = RouteBudget(
        host="api.the-odds-api.com", path="/v4/sports/soccer_epl/odds", maximum_calls=1
    )
    value = scope("FPL", ("/api/bootstrap-static/",)).model_dump()
    value.update(provider="ODDS", routes=(route,))
    assert SourceScope.model_validate(value).routes == (route,)
    value["routes"] = (route, route.model_copy(update={"path": "/other/"}))
    with pytest.raises(ValidationError):
        SourceScope.model_validate(value)
    with pytest.raises(ValidationError):
        scope("FPL", ("/api/bootstrap-static/", "/api/bootstrap-static/"))
