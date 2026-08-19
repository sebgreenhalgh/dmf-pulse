"""Synthetic rights-safe Stage-15 fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

from dmf_pulse.fpl_points.models import (
    BpsCompletenessMode,
    GameweekAssemblyMode,
    GameweekPointScenario,
    GameweekScenarioSet,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    OneGameweekRulesView,
    TacticalConfiguration,
)
from dmf_pulse.rank_strategy.models import (
    CohortKind,
    CohortMember,
    CohortSample,
    ManagerChip,
    ManagerMultiplierPolicy,
    ManagerTeamPlan,
    SampleRightsStatus,
)

POINT_COMPONENTS = (
    "appearance",
    "goals",
    "assists",
    "clean_sheet",
    "saves",
    "penalty_saves",
    "defensive_contributions",
    "goals_conceded",
    "penalty_misses",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "bonus",
)
RULESET_HASH = "1" * 64


def rank_players(*, include_extra: bool = False) -> dict[str, CandidatePlayer]:
    values: list[CandidatePlayer] = []
    for index in range(16 if include_extra else 15):
        position = (
            PlayerPosition.GK
            if index < 2
            else PlayerPosition.DEF
            if index < 7
            else PlayerPosition.MID
            if index < 12 or index == 15
            else PlayerPosition.FWD
        )
        values.append(
            CandidatePlayer(
                player_id=f"p{index:02d}",
                club_id=f"club-{index}",
                position=position,
            )
        )
    return {item.player_id: item for item in values}


def rank_rules() -> OneGameweekRulesView:
    return OneGameweekRulesView(
        ruleset_id="synthetic-rank",
        ruleset_version="1.0.0",
        ruleset_hash=RULESET_HASH,
        projection_mode=ProjectionMode.TEST,
        squad_size=15,
        position_squad_quota={
            PlayerPosition.GK: 2,
            PlayerPosition.DEF: 5,
            PlayerPosition.MID: 5,
            PlayerPosition.FWD: 3,
        },
        starting_size=11,
        bench_size=4,
        lineup_min={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 3,
            PlayerPosition.MID: 2,
            PlayerPosition.FWD: 1,
        },
        lineup_max={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 5,
            PlayerPosition.MID: 5,
            PlayerPosition.FWD: 3,
        },
        initial_budget_tenths=None,
        max_players_per_club=3,
        captain_multiplier=2,
        vice_captain_fallback=True,
        auto_substitution_timing="AFTER_ALL_GAMEWEEK_FIXTURES",
        auto_substitution_zero_appearance_minutes=0,
        designated_bench_goalkeeper_if_appeared=True,
        manager_bench_order=True,
        maintain_legal_formation=True,
        manager_capability="REFERENCE_ONLY",
        manager_capability_hash=None,
    )


def multiplier_policy() -> ManagerMultiplierPolicy:
    return ManagerMultiplierPolicy(triple_captain_multiplier=3)


def tactic(
    *, free_hit: bool = False, captain: str = "p12", vice: str = "p13"
) -> TacticalConfiguration:
    starting_mid = "p15" if free_hit else "p10"
    bench_mid = "p10" if free_hit else "p11"
    return TacticalConfiguration(
        starting_xi=(
            "p00",
            "p02",
            "p03",
            "p04",
            "p07",
            "p08",
            "p09",
            starting_mid,
            "p12",
            "p13",
            "p14",
        ),
        bench_goalkeeper="p01",
        bench_order=("p05", bench_mid, "p06"),
        captain=captain,
        vice_captain=vice,
    )


def manager_plan(
    manager_id: str,
    *,
    chip: ManagerChip = ManagerChip.NONE,
    free_hit: bool = False,
    captain: str = "p12",
    vice: str = "p13",
    hit_points: int = 0,
    cumulative_points: int = 100,
    counted_transfers: int = 5,
) -> ManagerTeamPlan:
    permanent = tuple(f"p{index:02d}" for index in range(15))
    temporary = (
        tuple(sorted((*[item for item in permanent if item != "p11"], "p15"))) if free_hit else None
    )
    return ManagerTeamPlan(
        plan_id=f"plan-{manager_id}-{chip.value.lower()}",
        manager_id=manager_id,
        permanent_squad=permanent,
        tactical_configuration=tactic(free_hit=free_hit, captain=captain, vice=vice),
        active_chip=chip,
        temporary_free_hit_squad=temporary,
        cumulative_points=cumulative_points,
        counted_transfers=counted_transfers,
        transfer_hit_points=hit_points,
    )


def scenario_set(
    *point_maps: dict[str, int],
    appearances: tuple[dict[str, bool], ...] | None = None,
    weights: tuple[float, ...] | None = None,
    include_extra: bool = False,
) -> GameweekScenarioSet:
    player_ids = tuple(rank_players(include_extra=include_extra))
    if not point_maps:
        point_maps = ({player_id: 2 for player_id in player_ids},)
    weights = weights or tuple(1.0 / len(point_maps) for _ in point_maps)
    scenarios: list[GameweekPointScenario] = []
    for index, source_points in enumerate(point_maps):
        source_appearance = appearances[index] if appearances is not None else {}
        appeared = {player_id: source_appearance.get(player_id, True) for player_id in player_ids}
        points = {player_id: source_points.get(player_id, 0) for player_id in player_ids}
        components = {
            player_id: {
                component: points[player_id] if component == "appearance" else 0
                for component in POINT_COMPONENTS
            }
            for player_id in player_ids
        }
        scenarios.append(
            GameweekPointScenario(
                scenario_id=f"scenario-{index}",
                outcome_draw_id=f"draw-{index}",
                weight=weights[index],
                gameweek_id="GW1",
                fixture_ids=("fixture-1",),
                player_points=points,
                player_components=components,
                player_bps={player_id: 0 for player_id in player_ids},
                player_bonus={player_id: 0 for player_id in player_ids},
                player_minutes={
                    player_id: 90 if appeared[player_id] else 0 for player_id in player_ids
                },
                player_appeared=appeared,
                assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
                approximation_labels=(),
            )
        )
    return GameweekScenarioSet(
        gameweek_id="GW1",
        scenarios=tuple(scenarios),
        player_ids=player_ids,
        ruleset_hash=RULESET_HASH,
        assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
        bps_completeness_mode=BpsCompletenessMode.EVENT_LINKED_ONLY,
        confidence_grade="A",
        model_version_ids=("synthetic-rank-v1",),
        dataset_version_ids=("synthetic-rank-dataset-v1",),
        source_bundle_ids=("synthetic-rank-source",),
        upstream_stage8_sha256s=(),
        fixture_result_sha256_by_fixture={"fixture-1": "2" * 64},
        warnings=(),
    )


def cohort(
    *plans: ManagerTeamPlan,
    weights: tuple[float, ...] | None = None,
    rights: SampleRightsStatus = SampleRightsStatus.SYNTHETIC_APPROVED,
    kind: CohortKind = CohortKind.SYNTHETIC,
) -> CohortSample:
    weights = weights or tuple(1.0 for _ in plans)
    return CohortSample(
        sample_id="synthetic-cohort",
        kind=kind,
        rights_status=rights,
        observed_at=datetime(2026, 8, 20, 10, tzinfo=UTC),
        information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
        members=tuple(
            CohortMember(
                sample_unit_id=f"sample-{index}",
                manager_plan=plan,
                weight=weights[index],
            )
            for index, plan in enumerate(plans)
        ),
        confidence="A",
    )
