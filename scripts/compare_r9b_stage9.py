"""Offline-only paired Stage-9 ablations. No CLI, transport or production binding.

Callers supply explicitly synthetic requests; this development harness never reads
or writes a fixture or a current-player posterior artifact.
"""

from __future__ import annotations

from math import fsum

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import CurrentPlayerAllocationShadowWorld
from dmf_pulse.fpl_points.current_player_shadow_diagnostics import quantile
from dmf_pulse.fpl_points.models import (
    FixtureSimulationRequest,
    PlayerAllocationProfile,
    ProjectionMode,
)
from dmf_pulse.fpl_points.rules_adapter import RulesEngine
from dmf_pulse.fpl_points.service import generate_fixture_scenarios

COMPONENTS = {
    "STALE": (),
    "ASSIST_ONLY": ("assist_share",),
    "DISCIPLINE_ONLY": ("yellow_cards_per90", "red_cards_per90"),
    "GK_SAVE_ONLY": ("goalkeeper_saves_per90",),
    "ALL_SUPPORTED": (
        "assist_share",
        "yellow_cards_per90",
        "red_cards_per90",
        "goalkeeper_saves_per90",
    ),
}


def ablation_requests(request: FixtureSimulationRequest, world: CurrentPlayerAllocationShadowWorld):
    request = FixtureSimulationRequest.model_validate(request.model_dump(mode="python"))
    world = CurrentPlayerAllocationShadowWorld.model_validate(world.model_dump(mode="python"))
    if (
        request.projection_mode is not ProjectionMode.TEST
        or request.allocation_config.source_tag != "TEST_SYNTHETIC"
    ):
        raise ValueError("R9B comparison is explicitly synthetic TEST-only")
    if (
        request.information_cutoff_utc.replace("Z", "+00:00")
        != world.posterior.information_cutoff.isoformat()
    ):
        raise ValueError("offline fixture and shadow cutoff differ")
    stale = {p.player_id: p for p in world.stale_profiles}
    shadow = {p.player_id: p for p in world.profiles}
    if any(stale.get(p.player_id) != p for p in request.allocation_profiles):
        raise ValueError("offline stale request must use exact bound donor profiles")
    for name, fields in COMPONENTS.items():
        profiles = tuple(
            PlayerAllocationProfile.model_validate(
                p.model_dump(mode="python")
                | {field: getattr(shadow[p.player_id], field) for field in fields}
            )
            for p in request.allocation_profiles
        )
        # The harness envelope supplies shadow lineage. Do not label substituted
        # profiles as the unchanged active PlayerPriorIdentity source type.
        yield (
            name,
            FixtureSimulationRequest.model_validate(
                request.model_dump(mode="python")
                | {"allocation_profiles": profiles, "player_prior_identity": None}
            ),
        )


def compare_stage9(
    request: FixtureSimulationRequest,
    world: CurrentPlayerAllocationShadowWorld,
    rules: RulesEngine,
    *,
    frozen_squad: tuple[str, ...],
) -> dict[str, object]:
    ids = tuple(sorted(p.player_id for p in request.allocation_profiles))
    if (
        not frozen_squad
        or len(set(frozen_squad)) != len(frozen_squad)
        or not set(frozen_squad) <= set(ids)
    ):
        raise ValueError("frozen squad must be unique and inside fixture universe")
    outputs = {}
    baseline = None
    for name, variant in ablation_requests(request, world):
        scenarios = generate_fixture_scenarios(variant, rules, range(variant.scenario_count))
        if baseline is None:
            baseline = scenarios
        if any(
            (
                a.scenario_index,
                a.upstream_scoreline,
                a.participation_scenario_id,
                a.stage7_player_projection_sha256s,
            )
            != (
                b.scenario_index,
                b.upstream_scoreline,
                b.participation_scenario_id,
                b.stage7_player_projection_sha256s,
            )
            for a, b in zip(baseline, scenarios, strict=True)
        ):
            raise ValueError("offline paired upstream invariants differ")
        means_a = {pid: fsum(s.players[pid].total for s in baseline) / len(baseline) for pid in ids}
        means_b = {
            pid: fsum(s.players[pid].total for s in scenarios) / len(scenarios) for pid in ids
        }
        deltas = tuple(means_b[p] - means_a[p] for p in ids)
        totals_a = tuple(float(sum(s.players[p].total for p in frozen_squad)) for s in baseline)
        totals_b = tuple(float(sum(s.players[p].total for p in frozen_squad)) for s in scenarios)
        paired = tuple(b - a for a, b in zip(totals_a, totals_b, strict=True))
        mean = fsum(paired) / len(paired)
        rank_a = sorted(ids, key=lambda p: (-means_a[p], p))
        rank_b = sorted(ids, key=lambda p: (-means_b[p], p))
        outputs[name] = {
            "mean_player_xp_delta": fsum(deltas) / len(deltas),
            "stage9_mean_absolute_player_xp_change": fsum(abs(d) for d in deltas) / len(deltas),
            "stage9_p90_absolute_player_xp_change": quantile(tuple(abs(d) for d in deltas), 0.9),
            "squad_expected_points_delta": mean,
            "paired_squad_delta": {
                "mean": mean,
                "median": quantile(paired, 0.5),
                "p10": quantile(paired, 0.1),
                "p90": quantile(paired, 0.9),
                "probability_shadow_greater": sum(d > 0 for d in paired) / len(paired),
            },
            "squad_points_p10": quantile(totals_b, 0.1),
            "squad_points_p90": quantile(totals_b, 0.9),
            "squad_points_variance": fsum(
                (v - fsum(totals_b) / len(totals_b)) ** 2 for v in totals_b
            )
            / len(totals_b),
            "rank_position_changed_count": sum(a != b for a, b in zip(rank_a, rank_b, strict=True)),
            "numeric_scenario_sha256": canonical_sha256(
                [[s.players[p].total for p in ids] for s in scenarios]
            ),
        }
    return {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "interpretation": "MODEL_MOVEMENT_NOT_MODEL_ACCURACY",
        "shadow_world_sha256": world.semantic_sha256,
        "world": world.posterior.sensitivity_world,
        "stage8_sha256": request.score_distribution.result_sha256,
        "scenario_count": request.scenario_count,
        "root_seed": request.root_seed,
        "player_count": len(ids),
        "frozen_squad_size": len(frozen_squad),
        "frozen_squad_interpretation": "RAW_POINTS_SUM_OF_DECLARED_PLAYER_SUBSET_NOT_MANAGER_TACTICS",
        "paired_stage7_stage8_equal": True,
        "variants": outputs,
        "comparison_limitations": (
            "REFERENCE_RULES_SYNTHETIC_EXPERIMENT_NOT_TARGET_SEASON_ACCEPTANCE",
            "FIXED_NAMED_STREAMS_AND_SCENARIO_INDEXES; CONDITIONAL_EVENT_BRANCHES_CAN_CHANGE_DOWNSTREAM_DRAWS",
            "PAIRED_FINITE_MONTE_CARLO_ESTIMATES_NOT_NOISE_FREE_ANALYTIC_EFFECTS",
            "COMPONENT_EFFECTS_CAN_INTERACT; ABLATION_DELTAS_NEED_NOT_ADD",
        ),
    }
