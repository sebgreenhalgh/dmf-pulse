"""Sealed standalone rate/world contracts cannot silently accept inconsistent copies."""

from datetime import datetime

import pytest

from dmf_pulse.fpl_points.current_player_posterior import CurrentPlayerPosteriorRate, seal
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.ingestion.fpl.current_player_history import build_current_player_history_evidence
from tests.unit.fpl_points.current_shadow_support import synthetic_inputs

pytestmark = pytest.mark.unit


@pytest.fixture
def compiled(repository_root):
    return compile_current_player_shadow(**synthetic_inputs(repository_root))


@pytest.mark.parametrize(
    "updates",
    (
        {"observed_rows": 5},
        {"included_events": None},
        {"included_minutes": 0},
        {"status": "STRUCTURAL_NON_GK_ZERO"},
        {"posterior_variance_per90": 123.0},
    ),
)
def test_rate_internal_inconsistency_fails(compiled, updates):
    rate = next(
        r for e in compiled.worlds[0].posterior.entries for r in e.rates if r.status == "UPDATED"
    )
    with pytest.raises(ValueError):
        CurrentPlayerPosteriorRate.model_validate(rate.model_dump(mode="python") | updates)


@pytest.mark.parametrize(
    "mutation",
    (
        "hash",
        "channels",
        "order",
        "historical_source",
        "window",
        "naive",
        "profile_coverage",
        "profile_identity",
        "worlds",
    ),
)
def test_sealed_artifacts_and_copies_fail(compiled, mutation):
    world = compiled.worlds[0]
    posterior = world.posterior
    if mutation == "hash":
        with pytest.raises(ValueError):
            compiled.model_copy(update={"semantic_sha256": "f" * 64})
    if mutation == "channels":
        entry = posterior.entries[0]
        with pytest.raises(ValueError):
            seal(type(entry).model_construct(**(entry.__dict__ | {"rates": entry.rates[:-1]})))
    if mutation in ("order", "historical_source", "window", "naive"):
        updates = {
            "order": {"entries": tuple(reversed(posterior.entries))},
            "historical_source": {"source_posterior_sha256": "f" * 64},
            "window": {"source_gameweeks": (1, 2, 3, 5)},
            "naive": {"information_cutoff": datetime(2026, 9, 16)},
        }[mutation]
        with pytest.raises(ValueError):
            seal(type(posterior).model_construct(**(posterior.__dict__ | updates)))
    if mutation == "profile_coverage":
        with pytest.raises(ValueError):
            seal(
                type(world).model_construct(**(world.__dict__ | {"profiles": world.profiles[:-1]}))
            )
    if mutation == "profile_identity":
        stale = world.stale_profiles[0].model_copy(
            update={"team_id": "00000000-0000-4000-8000-000000000999"}
        )
        with pytest.raises(ValueError):
            seal(
                type(world).model_construct(
                    **(world.__dict__ | {"stale_profiles": (stale, *world.stale_profiles[1:])})
                )
            )
    if mutation == "worlds":
        with pytest.raises(ValueError):
            seal(
                type(compiled).model_construct(
                    **(compiled.__dict__ | {"worlds": compiled.worlds[::-1]})
                )
            )


def test_failed_r9a_reconciliation_is_rejected_even_when_truthfully_sealed(repository_root):
    inputs, snapshot = synthetic_inputs(repository_root, with_snapshot=True)
    fpl = inputs["current_fpl"]
    first = fpl.players[0].model_copy(update={"season_minutes": 999})
    changed_fpl = fpl.model_copy(update={"players": (first, *fpl.players[1:])})
    changed_snapshot = snapshot.model_copy(update={"fpl_input": changed_fpl})
    evidence = build_current_player_history_evidence(changed_snapshot)
    assert evidence.coverage.failed_minutes_reconciliation_count == 1
    with pytest.raises(ValueError, match="reconciliation failed"):
        compile_current_player_shadow(
            **(inputs | {"current_fpl": changed_fpl, "history": evidence})
        )


@pytest.mark.parametrize(
    "kind", ("duplicate_player", "duplicate_gameweek", "unfinished", "non_gk_saves")
)
def test_source_catalogue_and_structure_fails(repository_root, kind):
    inputs = synthetic_inputs(repository_root)
    fpl = inputs["current_fpl"]
    if kind == "duplicate_player":
        fpl = fpl.model_copy(update={"players": (*fpl.players, fpl.players[0])})
    if kind == "duplicate_gameweek":
        fpl = fpl.model_copy(update={"events": (*fpl.events, fpl.events[0])})
    if kind == "unfinished":
        fpl = fpl.model_copy(
            update={
                "events": (
                    fpl.events[0].model_copy(update={"data_checked": False}),
                    *fpl.events[1:],
                )
            }
        )
    if kind == "non_gk_saves":
        inputs = synthetic_inputs(repository_root, changes={(10002, 1): {"saves": 2}})
        fpl = inputs["current_fpl"]
    with pytest.raises(ValueError):
        compile_current_player_shadow(**(inputs | {"current_fpl": fpl}))


def test_no_current_history_never_claims_current_history_present(repository_root):
    inputs = synthetic_inputs(repository_root)
    ids = [e.official_fpl_element_id for e in inputs["history"].entries]
    missing = tuple((element_id, gw) for element_id in ids for gw in range(1, 5))
    absent = synthetic_inputs(repository_root, missing_rows=missing)
    result = compile_current_player_shadow(**absent)
    assert all(
        w.posterior.confidence == "CURRENT_HISTORY_UNAVAILABLE_SHADOW_NOT_ACCEPTED"
        for w in result.worlds
    )
    assert all(w.profiles == w.stale_profiles for w in result.worlds)


def test_published_outfield_saves_fail_even_when_minutes_are_missing(repository_root):
    inputs = synthetic_inputs(repository_root, changes={(10002, 1): {"saves": 2, "minutes": None}})
    with pytest.raises(ValueError, match="structural zero"):
        compile_current_player_shadow(**inputs)
