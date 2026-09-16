"""R9B synthetic contracts, hostile inputs and mathematical invariants."""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import (
    ALLOWED_PROFILE_FIELDS,
    RESOURCE_SHA,
    SOURCE_HASHES,
    CurrentPlayerAllocationShadow,
    HistoricalRateResource,
    gamma_poisson_update,
    load_historical_rate_resource,
)
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow, posterior_rate
from tests.unit.fpl_points.current_shadow_support import synthetic_inputs, synthetic_shadow

pytestmark = pytest.mark.unit


def test_pinned_three_world_resource_and_contract():
    resource = load_historical_rate_resource()
    assert resource.semantic_sha256 == RESOURCE_SHA
    assert sum(len(w.rates) for w in resource.worlds) == 1797
    assert tuple(w.source_posterior_artifact_sha256 for w in resource.worlds) == SOURCE_HASHES
    assert HistoricalRateResource.model_validate_json(resource.model_dump_json()) == resource


@pytest.mark.parametrize(
    "tamper",
    (
        "mean",
        "variance",
        "donor",
        "duplicate",
        "missing_world",
        "world",
        "source",
        "order",
        "lineage",
    ),
)
def test_resource_tamper_even_resealed_fails(tamper):
    payload = load_historical_rate_resource().model_dump(mode="json")
    world = payload["worlds"][0]
    if tamper == "mean":
        world["rates"][0]["assist_mean_per90"] += 0.01
    if tamper == "variance":
        world["rates"][0]["red_variance_per90"] += 0.01
    if tamper == "donor":
        world["rates"][0]["source_official_fpl_player_id"] = 9999
    if tamper == "duplicate":
        world["rates"][1] = world["rates"][0]
    if tamper == "missing_world":
        payload["worlds"].pop()
    if tamper == "world":
        world["sensitivity_world"] = "UNKNOWN"
    if tamper == "source":
        world["source_posterior_artifact_sha256"] = "f" * 64
    if tamper == "order":
        payload["worlds"].reverse()
    if tamper == "lineage":
        payload["originating_implementation_sha"] = "f" * 40
    payload["semantic_sha256"] = canonical_sha256(
        {k: v for k, v in payload.items() if k != "semantic_sha256"}
    )
    with pytest.raises(ValueError):
        HistoricalRateResource.model_validate_json(json.dumps(payload))


def test_formula_zero_exposure_and_strength():
    assert gamma_poisson_update(0.2, 0.02, 3, 180) == pytest.approx((5 / 12, 5 / 144))
    assert gamma_poisson_update(0.2, 0.02, 0, 0) == (0.2, 0.02)
    assert abs(gamma_poisson_update(0.2, 0.01, 3, 180)[0] - 0.2) < abs(
        gamma_poisson_update(0.2, 0.04, 3, 180)[0] - 0.2
    )


@given(st.integers(0, 100), st.integers(1, 10000))
def test_math_metamorphic(events, minutes):
    value = gamma_poisson_update(0.2, 0.02, events, minutes)[0]
    assert gamma_poisson_update(0.2, 0.02, events + 1, minutes)[0] > value
    assert gamma_poisson_update(0.2, 0.02, events, minutes + 90)[0] < value


@pytest.mark.parametrize(
    "arguments",
    (
        (0.0, 0.1, 0, 90),
        (0.1, 0.0, 0, 90),
        (0.1, 0.1, -1, 90),
        (0.1, 0.1, True, 90),
        (0.1, 0.1, 0, -1),
        (float("nan"), 0.1, 0, 90),
        (0.1, float("inf"), 0, 90),
        (0.1, 0.1, 1, 0),
        (0.1, 0.1, 10**1000, 90),
        (1e308, 1e-308, 1, 90),
        (1e-308, 1e308, 1, 90),
    ),
)
def test_invalid_math_fails(arguments):
    with pytest.raises(ValueError):
        gamma_poisson_update(*arguments)


def test_synthetic_three_worlds_exact_determinism_and_whitelist(repository_root):
    inputs = synthetic_inputs(repository_root)
    shadow = compile_current_player_shadow(**inputs)
    assert shadow == compile_current_player_shadow(**dict(reversed(tuple(inputs.items()))))
    assert shadow == CurrentPlayerAllocationShadow.model_validate_json(shadow.model_dump_json())
    for world in shadow.worlds:
        for stale, profile in zip(world.stale_profiles, world.profiles, strict=True):
            assert stale.model_dump(exclude=set(ALLOWED_PROFILE_FIELDS)) == profile.model_dump(
                exclude=set(ALLOWED_PROFILE_FIELDS)
            )
    assert all(
        not getattr(shadow, flag)
        for flag in ("model_training_performed", "persistence_performed", "new_network_requests")
    )


def test_new_player_likelihood_never_mutates_fallback_donor(repository_root):
    base = synthetic_shadow(repository_root)
    changed = synthetic_shadow(
        repository_root,
        changes={
            (10002, gw): {"assists": 5, "yellow_cards": 2, "red_cards": 1} for gw in range(1, 5)
        },
    )
    for left, right in zip(base.worlds, changed.worlds, strict=True):
        a = {e.binding.source_player_id: e for e in left.posterior.entries}
        b = {e.binding.source_player_id: e for e in right.posterior.entries}
        current = b[10002]
        assert current.binding.assignment_level == "FPL_POSITION_FALLBACK"
        donor = current.binding.donor_source_player_id
        assert donor != 10002
        assert a[donor].rates == b[donor].rates
        assert a[10002].rates != b[10002].rates
        # Whole-source digests change for all rows; rates and identity must not.
        assert all(
            a[k].rates == b[k].rates and a[k].binding == b[k].binding for k in a if k != 10002
        )
    assert load_historical_rate_resource().semantic_sha256 == RESOURCE_SHA


def test_659_current_599_donor_scale(repository_root):
    shadow = synthetic_shadow(repository_root, count=659)
    assert all(len(w.posterior.entries) == 659 for w in shadow.worlds)
    assert len(load_historical_rate_resource().worlds[0].rates) == 599
    assert any(
        e.binding.assignment_level == "INDIVIDUAL_SAME_TEAM"
        for e in shadow.worlds[0].posterior.entries
    )


@pytest.mark.parametrize(
    "field,channel",
    (("assists", "assist"), ("yellow_cards", "yellow"), ("saves", "save"), ("minutes", "assist")),
)
def test_partial_fields_preserve_stale_not_zero(repository_root, field, channel):
    shadow = synthetic_shadow(repository_root, changes={(10004, 2): {field: None}})
    world = shadow.worlds[0]
    entry = next(e for e in world.posterior.entries if e.binding.source_player_id == 10004)
    rate = next(r for r in entry.rates if r.channel == channel)
    assert rate.status == "CURRENT_HISTORY_FIELD_PARTIAL_NO_UPDATE"
    assert rate.posterior_mean_per90 == rate.historical_mean_per90


def test_absent_rows_and_discipline_zero_exposure(repository_root):
    inputs = synthetic_inputs(repository_root, missing_rows=((10002, 1),))
    shadow = compile_current_player_shadow(**inputs)
    current = next(
        e for e in shadow.worlds[0].posterior.entries if e.binding.source_player_id == 10002
    )
    assert current.rates[0].observed_rows == 3
    assert current.rates[0].status == "UPDATED"
    excluded = shadow.worlds[0].posterior.entries[0].rates[1]
    assert excluded.zero_exposure_discipline_excluded_rows == 4
    assert excluded.zero_exposure_discipline_excluded_events == 4
    assert excluded.status == "NO_CURRENT_EXPOSURE"


@pytest.mark.parametrize("field", ("assists", "goals_scored", "saves"))
def test_zero_minutes_positive_rate_event_blocked(repository_root, field):
    with pytest.raises(ValueError, match="zero exposure"):
        synthetic_shadow(repository_root, changes={(110, 1): {field: 1}})


def test_unsupported_mutation_and_model_copy_fail_closed(repository_root):
    shadow = synthetic_shadow(repository_root)
    for field in ("goal_share", "penalty_taker_share", "clearances_per90", "bps_auxiliary"):
        payload = shadow.worlds[0].model_dump(mode="json")
        profile = payload["profiles"][0]
        if field == "bps_auxiliary":
            profile[field]["recoveries_per90"] += 1
        else:
            profile[field] += 1
        payload["semantic_sha256"] = canonical_sha256(
            {k: v for k, v in payload.items() if k != "semantic_sha256"}
        )
        with pytest.raises(ValueError):
            type(shadow.worlds[0]).model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError):
        shadow.model_copy(update={"model_training_performed": True})
    payload = shadow.model_dump(mode="python")
    payload["worlds"][0]["posterior"]["entries"][0]["rates"][0]["posterior_mean_per90"] += 0.1
    with pytest.raises(ValueError):
        CurrentPlayerAllocationShadow.model_validate(payload)


def test_degenerate_prior_is_typed_not_epsilon(repository_root):
    inputs = synthetic_inputs(repository_root)
    history = next(e for e in inputs["history"].entries if e.official_fpl_element_id == 10002)
    row = inputs["historical"].worlds[0].rates[0]
    for field in ("assist_mean_per90", "assist_variance_per90"):
        rate = posterior_rate(
            "assist", row.model_copy(update={field: 0.0}), history, is_goalkeeper=False
        )
        assert rate.status == "HISTORICAL_RATE_DEGENERATE_NO_UPDATE"
