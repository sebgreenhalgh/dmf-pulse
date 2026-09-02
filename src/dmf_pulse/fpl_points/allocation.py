"""Coherent current-stack player-event allocation for one sampled fixture path."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from math import exp

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    PENALTY_GOAL_SHARE_PROXY_WARNING,
    AssistClassification,
    BpsCompletenessMode,
    BpsEvents,
    DefensiveActions,
    EventAllocationConfig,
    FixtureEventScenario,
    GoalEvent,
    GoalkeeperSaveEvent,
    GoalMechanism,
    ParticipantState,
    ParticipationScenario,
    PenaltyEvent,
    PenaltyHierarchyExhaustionPolicy,
    PenaltyOutcome,
    PenaltyTakerHierarchyEntry,
    PlayerAllocationProfile,
    PlayerEventVector,
    PlayerPosition,
    ProjectionMode,
    RulesetIdentity,
    ScorelineCell,
)
from dmf_pulse.fpl_points.seed import NamedRandom, rng_for, stable_identifier
from dmf_pulse.rules.models import (
    AssistAction,
    AssistDecisionContext,
    AssistGoalKind,
    AssistSetPieceRoute,
)


def validate_goal_share_simplex(
    profiles: tuple[PlayerAllocationProfile, ...], team_id: str
) -> None:
    total = sum(profile.goal_share for profile in profiles if profile.team_id == team_id)
    if total <= 0.0:
        raise FplPointsError(
            "GOAL_SHARE_SIMPLEX_EMPTY", f"team {team_id} has no positive scorer share"
        )


def validate_assist_share_constraints(
    profiles: tuple[PlayerAllocationProfile, ...], team_id: str
) -> None:
    if any(profile.assist_share < 0.0 for profile in profiles if profile.team_id == team_id):
        raise FplPointsError("ASSIST_SHARE_INVALID", "assist shares must be non-negative")


def _sample_weighted[T](items: tuple[T, ...], weights: tuple[float, ...], rng: NamedRandom) -> T:
    if len(items) != len(weights) or not items:
        raise FplPointsError("WEIGHTED_SAMPLE_INVALID", "weighted sample inputs do not align")
    total = float(sum(weights))
    if total <= 0.0:
        raise FplPointsError("WEIGHTED_SAMPLE_EMPTY", "weighted sample has no positive mass")
    draw = float(rng.random()) * total
    cumulative = 0.0
    for item, weight in zip(items, weights, strict=True):
        cumulative += weight
        if draw < cumulative:
            return item
    return items[-1]


def sample_scoreline(
    cells: tuple[ScorelineCell, ...], *, root_seed: int, scenario_index: int
) -> ScorelineCell:
    """Sample the accepted 12-place Stage-8 simplex without binary-float conversion."""

    if not cells:
        raise FplPointsError("WEIGHTED_SAMPLE_INVALID", "score matrix is empty")
    scale = 10**12
    integer_weights = tuple(int(Decimal(cell.probability) * scale) for cell in cells)
    if sum(integer_weights) != scale:
        raise FplPointsError("STAGE8_PROBABILITY_INVALID", "score matrix is not an exact simplex")
    draw = rng_for(root_seed, "scoreline", scenario_index).randbelow(scale)
    cumulative = 0
    for cell, weight in zip(cells, integer_weights, strict=True):
        cumulative += weight
        if draw < cumulative:
            return cell
    raise FplPointsError("STAGE8_PROBABILITY_INVALID", "score matrix sampling failed")


def sample_participation(
    scenarios: tuple[ParticipationScenario, ...], *, root_seed: int, scenario_index: int
) -> ParticipationScenario:
    return _sample_weighted(
        scenarios,
        tuple(scenario.probability for scenario in scenarios),
        rng_for(root_seed, "participation", scenario_index),
    )


@dataclass
class _Accumulator:
    participant: ParticipantState
    profile: PlayerAllocationProfile
    minutes: int
    effective_end: float | None
    dismissed_at: float | None = None
    goals_non_penalty: int = 0
    goals_penalty: int = 0
    eligible_assists: int = 0
    goals_conceded_while_eligible: int = 0
    saves: int = 0
    penalty_saves: int = 0
    penalty_misses: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    own_goals: int = 0
    team_goals_after_dismissal: int = 0
    defensive: dict[str, int] = field(
        default_factory=lambda: {
            "ball_recoveries": 0,
            "blocks": 0,
            "clearances": 0,
            "interceptions": 0,
            "tackles": 0,
        }
    )
    bps: dict[str, int] = field(
        default_factory=lambda: {
            "big_chances_created": 0,
            "big_chance_saves": 0,
            "big_chances_missed": 0,
            "errors_leading_attempt": 0,
            "errors_leading_goal": 0,
            "fouls_conceded": 0,
            "fouls_won": 0,
            "goal_line_clearances": 0,
            "key_passes": 0,
            "match_winning_goals": 0,
            "offsides": 0,
            "pass_attempts": 0,
            "passes_completed": 0,
            "penalties_conceded": 0,
            "recoveries": 0,
            "saves_inside_box": 0,
            "saves_outside_box": 0,
            "shots_off_target": 0,
            "shots_on_target": 0,
            "successful_dribbles": 0,
            "successful_open_play_crosses": 0,
            "successful_tackles": 0,
            "times_tackled": 0,
        }
    )

    def on_pitch(self, minute: float) -> bool:
        interval = self.participant.interval
        if interval is None:
            return False
        end = self.effective_end if self.effective_end is not None else interval.end_minute
        return interval.start_minute <= minute < end

    def to_model(self, auxiliary_source_tag: str) -> PlayerEventVector:
        return PlayerEventVector(
            player_id=self.participant.player_id,
            team_id=self.participant.team_id,
            position=self.participant.position,
            minutes=self.minutes,
            on_pitch_interval=self.participant.interval,
            goals_non_penalty=self.goals_non_penalty,
            goals_penalty=self.goals_penalty,
            eligible_assists=self.eligible_assists,
            goals_conceded_while_eligible=self.goals_conceded_while_eligible,
            saves=self.saves,
            penalty_saves=self.penalty_saves,
            penalty_misses=self.penalty_misses,
            yellow_cards=self.yellow_cards,
            red_cards=self.red_cards,
            own_goals=self.own_goals,
            defensive_actions=DefensiveActions.model_validate(self.defensive),
            bps=BpsEvents.model_validate(self.bps),
            dismissed=self.red_cards > 0,
            team_goals_after_dismissal=self.team_goals_after_dismissal,
            auxiliary_source_tag=auxiliary_source_tag,
        )


def _event_probability(rate_per90: float, minutes: int) -> float:
    return 1.0 - exp(-rate_per90 * minutes / 90.0)


def _poisson(rng: NamedRandom, rate_per90: float, minutes: int) -> int:
    return int(rng.poisson(rate_per90 * minutes / 90.0))


def _eligible(
    accumulators: dict[str, _Accumulator], team_id: str, minute: float
) -> tuple[_Accumulator, ...]:
    return tuple(
        sorted(
            (
                accumulator
                for accumulator in accumulators.values()
                if accumulator.participant.team_id == team_id and accumulator.on_pitch(minute)
            ),
            key=lambda item: item.participant.player_id,
        )
    )


def _choose_accumulator(
    candidates: tuple[_Accumulator, ...],
    weight: Callable[[_Accumulator], float],
    rng: NamedRandom,
    *,
    code: str,
) -> _Accumulator:
    eligible = tuple(candidate for candidate in candidates if weight(candidate) > 0.0)
    if not eligible:
        raise FplPointsError(code, "no eligible player has positive allocation share")
    return _sample_weighted(eligible, tuple(weight(item) for item in eligible), rng)


def _resolve_penalty_taker(
    candidates: tuple[_Accumulator, ...],
    hierarchy: tuple[PenaltyTakerHierarchyEntry, ...],
    exhaustion_policy: PenaltyHierarchyExhaustionPolicy,
    rng: NamedRandom,
    degradation: list[str],
) -> _Accumulator:
    """Resolve published ordinal role evidence before the governed donor fallback."""

    team_id = candidates[0].participant.team_id if candidates else None
    team_hierarchy = tuple(item for item in hierarchy if item.team_id == team_id)
    order_by_player = {item.player_id: item.order for item in team_hierarchy}
    current = tuple(item for item in candidates if item.participant.player_id in order_by_player)
    if current:
        return min(
            current,
            key=lambda item: (
                order_by_player[item.participant.player_id],
                item.participant.player_id,
            ),
        )
    historical = tuple(item for item in candidates if item.profile.penalty_taker_share > 0.0)
    if historical:
        selected = _sample_weighted(
            historical,
            tuple(item.profile.penalty_taker_share for item in historical),
            rng,
        )
        degradation.append("HISTORICAL_PENALTY_ROLE_FALLBACK_USED")
        return selected
    if (
        team_hierarchy
        and exhaustion_policy
        is PenaltyHierarchyExhaustionPolicy.PRIVATE_CURRENT_PENALTY_ROLE_GOAL_SHARE_PROXY_V1
    ):
        selected = _choose_accumulator(
            candidates,
            lambda item: item.profile.goal_share,
            rng,
            code="NO_ELIGIBLE_PENALTY_TAKER",
        )
        degradation.append(PENALTY_GOAL_SHARE_PROXY_WARNING)
        return selected
    raise FplPointsError(
        "NO_ELIGIBLE_PENALTY_TAKER",
        "no eligible player has positive allocation share",
    )


def _sample_goal_mechanism(config: EventAllocationConfig, rng: NamedRandom) -> GoalMechanism:
    draw = float(rng.random())
    cursor = config.own_goal_probability
    if draw < cursor:
        return GoalMechanism.OPPONENT_OWN_GOAL
    cursor += config.penalty_goal_probability
    if draw < cursor:
        return GoalMechanism.PENALTY
    cursor += config.direct_free_kick_goal_probability
    if draw < cursor:
        return GoalMechanism.DIRECT_FREE_KICK
    cursor += config.set_piece_goal_probability
    if draw < cursor:
        return GoalMechanism.SET_PIECE
    return GoalMechanism.OPEN_PLAY


def _allocate_legacy_assist(
    *,
    scorer: _Accumulator,
    candidates: tuple[_Accumulator, ...],
    config: EventAllocationConfig,
    rng: NamedRandom,
) -> tuple[_Accumulator | None, AssistClassification, bool]:
    if float(rng.random()) >= config.assistable_probability:
        return None, AssistClassification.DEFINITE_NO_ASSIST, False
    ambiguous = float(rng.random()) < config.ambiguous_assist_probability
    classification = (
        AssistClassification.AMBIGUOUS_ASSIST if ambiguous else AssistClassification.DEFINITE_ASSIST
    )
    if ambiguous and float(rng.random()) >= config.ambiguous_assist_eligible_probability:
        return None, classification, False
    eligible = tuple(candidate for candidate in candidates if candidate is not scorer)
    eligible = tuple(candidate for candidate in eligible if candidate.profile.assist_share > 0.0)
    if not eligible:
        return None, classification, False
    assister = _sample_weighted(
        eligible,
        tuple(candidate.profile.assist_share for candidate in eligible),
        rng,
    )
    return assister, classification, True


def _allocate_versioned_assist(
    *,
    scorer: _Accumulator | None,
    candidates: tuple[_Accumulator, ...],
    mechanism: GoalMechanism,
    config: EventAllocationConfig,
    rng: NamedRandom,
    classifier: Callable[[AssistDecisionContext], AssistClassification | None],
) -> tuple[_Accumulator | None, AssistClassification, bool, AssistDecisionContext | None]:
    """Sample model facts, then let the compiled rules decide exact eligibility."""

    if float(rng.random()) >= config.assistable_probability:
        return None, AssistClassification.DEFINITE_NO_ASSIST, False, None
    eligible = tuple(candidate for candidate in candidates if candidate.profile.assist_share > 0.0)
    if not eligible:
        return None, AssistClassification.DEFINITE_NO_ASSIST, False, None
    candidate = _sample_weighted(
        eligible,
        tuple(item.profile.assist_share for item in eligible),
        rng,
    )
    goal_kind, action, route = {
        GoalMechanism.PENALTY: (
            AssistGoalKind.DIRECT_PENALTY,
            AssistAction.FOUL_WON,
            AssistSetPieceRoute.FOUL_WON,
        ),
        GoalMechanism.DIRECT_FREE_KICK: (
            AssistGoalKind.DIRECT_FREE_KICK,
            AssistAction.FOUL_WON,
            AssistSetPieceRoute.FOUL_WON,
        ),
        GoalMechanism.OPPONENT_OWN_GOAL: (
            AssistGoalKind.OWN_GOAL,
            AssistAction.FORCED_OWN_GOAL_ACTION,
            AssistSetPieceRoute.NONE,
        ),
    }.get(
        mechanism,
        (AssistGoalKind.OPEN_PLAY, AssistAction.PASS, AssistSetPieceRoute.NONE),
    )
    context = AssistDecisionContext(
        goal_kind=goal_kind,
        action=action,
        set_piece_route=route,
        candidate_is_scorer=candidate is scorer,
    )
    classification = classifier(context)
    if classification is None or classification is AssistClassification.AMBIGUOUS_ASSIST:
        raise FplPointsError(
            "RULESET_ASSIST_AMBIGUOUS",
            "schema-v1.1 exact scoring requires a definite compiled assist decision",
        )
    awarded = classification is AssistClassification.DEFINITE_ASSIST
    return candidate if awarded else None, classification, awarded, context


def _initialize_accumulators(
    participation: ParticipationScenario,
    profiles: tuple[PlayerAllocationProfile, ...],
    *,
    root_seed: int,
    scenario_index: int,
) -> dict[str, _Accumulator]:
    profile_map = {profile.player_id: profile for profile in profiles}
    accumulators: dict[str, _Accumulator] = {}
    for participant in sorted(participation.participants, key=lambda item: item.player_id):
        profile = profile_map[participant.player_id]
        effective_end = (
            participant.interval.end_minute if participant.interval is not None else None
        )
        accumulator = _Accumulator(
            participant=participant,
            profile=profile,
            minutes=participant.official_minutes,
            effective_end=effective_end,
        )
        if participant.official_minutes > 0 and participant.interval is not None:
            rng = rng_for(root_seed, "discipline", scenario_index, participant.player_id)
            if float(rng.random()) < _event_probability(
                profile.yellow_cards_per90, participant.official_minutes
            ):
                accumulator.yellow_cards = 1
            if float(rng.random()) < _event_probability(
                profile.red_cards_per90, participant.official_minutes
            ):
                accumulator.red_cards = 1
                accumulator.dismissed_at = participant.interval.end_minute
        accumulators[participant.player_id] = accumulator
    return accumulators


def _allocate_goals(
    *,
    cell: ScorelineCell,
    participation: ParticipationScenario,
    config: EventAllocationConfig,
    accumulators: dict[str, _Accumulator],
    penalty_taker_hierarchy: tuple[PenaltyTakerHierarchyEntry, ...],
    penalty_hierarchy_exhaustion_policy: PenaltyHierarchyExhaustionPolicy,
    degradation: list[str],
    root_seed: int,
    scenario_index: int,
    assist_classifier: Callable[[AssistDecisionContext], AssistClassification | None] | None,
) -> list[GoalEvent]:
    goal_specs = [participation.home_team_id] * cell.home_goals + [
        participation.away_team_id
    ] * cell.away_goals
    times_rng = rng_for(root_seed, "goal-times", scenario_index)
    times = sorted(
        times_rng.uniform(config.goal_time_lower, config.goal_time_upper) for _ in goal_specs
    )
    ordering_rng = rng_for(root_seed, "goal-team-order", scenario_index)
    ordering_rng.shuffle(goal_specs)
    events: list[GoalEvent] = []
    for sequence, (scoring_team, minute) in enumerate(zip(goal_specs, times, strict=True), start=1):
        conceding_team = (
            participation.away_team_id
            if scoring_team == participation.home_team_id
            else participation.home_team_id
        )
        rng = rng_for(root_seed, "goal", scenario_index, sequence)
        mechanism = _sample_goal_mechanism(config, rng)
        scorer: _Accumulator | None = None
        own_goal_player: _Accumulator | None = None
        assister: _Accumulator | None = None
        classification = AssistClassification.DEFINITE_NO_ASSIST
        assist_awarded = False
        assist_context: AssistDecisionContext | None = None
        scoring_candidates = _eligible(accumulators, scoring_team, minute)
        if mechanism is GoalMechanism.OPPONENT_OWN_GOAL:
            own_candidates = _eligible(accumulators, conceding_team, minute)
            eligible_own = tuple(
                item for item in own_candidates if item.profile.own_goal_share > 0.0
            )
            if eligible_own:
                own_goal_player = _sample_weighted(
                    eligible_own,
                    tuple(item.profile.own_goal_share for item in eligible_own),
                    rng,
                )
                own_goal_player.own_goals += 1
            else:
                raise FplPointsError(
                    "NO_ELIGIBLE_OWN_GOAL_PLAYER",
                    "sampled own goal has no eligible governed own-goal share",
                )
        if mechanism is not GoalMechanism.OPPONENT_OWN_GOAL:
            scorer = (
                _resolve_penalty_taker(
                    scoring_candidates,
                    penalty_taker_hierarchy,
                    penalty_hierarchy_exhaustion_policy,
                    rng,
                    degradation,
                )
                if mechanism is GoalMechanism.PENALTY
                else _choose_accumulator(
                    scoring_candidates,
                    lambda item: item.profile.goal_share,
                    rng,
                    code="NO_ELIGIBLE_SCORER",
                )
            )
            if mechanism is GoalMechanism.PENALTY:
                scorer.goals_penalty += 1
            else:
                scorer.goals_non_penalty += 1
            scorer.bps["shots_on_target"] += 1
            if assist_classifier is None and mechanism in {
                GoalMechanism.OPEN_PLAY,
                GoalMechanism.SET_PIECE,
            }:
                assister, classification, assist_awarded = _allocate_legacy_assist(
                    scorer=scorer,
                    candidates=scoring_candidates,
                    config=config,
                    rng=rng,
                )
                if assister is not None:
                    assister.eligible_assists += 1
                    if classification is AssistClassification.DEFINITE_ASSIST:
                        assist_context = AssistDecisionContext(
                            goal_kind=AssistGoalKind.OPEN_PLAY,
                            action=AssistAction.PASS,
                        )
        if assist_classifier is not None:
            assister, classification, assist_awarded, assist_context = _allocate_versioned_assist(
                scorer=scorer,
                candidates=scoring_candidates,
                mechanism=mechanism,
                config=config,
                rng=rng,
                classifier=assist_classifier,
            )
            if assister is not None:
                assister.eligible_assists += 1
        events.append(
            GoalEvent(
                goal_id=stable_identifier("goal", root_seed, scenario_index, sequence),
                minute=minute,
                scoring_team_id=scoring_team,
                conceding_team_id=conceding_team,
                mechanism=mechanism,
                scorer_player_id=scorer.participant.player_id if scorer is not None else None,
                own_goal_player_id=(
                    own_goal_player.participant.player_id if own_goal_player is not None else None
                ),
                assister_player_id=(
                    assister.participant.player_id if assister is not None else None
                ),
                assist_classification=classification,
                assist_awarded=assist_awarded,
                assist_context=assist_context,
            )
        )
    return sorted(events, key=lambda event: (event.minute, event.goal_id))


def _mark_match_winning_goal(
    events: list[GoalEvent],
    accumulators: dict[str, _Accumulator],
    cell: ScorelineCell,
    participation: ParticipationScenario,
) -> None:
    if cell.home_goals == cell.away_goals:
        return
    winner = (
        participation.home_team_id
        if cell.home_goals > cell.away_goals
        else participation.away_team_id
    )
    loser_goals = min(cell.home_goals, cell.away_goals)
    winner_goals = [event for event in events if event.scoring_team_id == winner]
    decisive = winner_goals[loser_goals]
    if decisive.scorer_player_id is not None:
        accumulators[decisive.scorer_player_id].bps["match_winning_goals"] += 1


def _assign_conceded(events: list[GoalEvent], accumulators: dict[str, _Accumulator]) -> None:
    for event in events:
        for accumulator in accumulators.values():
            if accumulator.participant.team_id != event.conceding_team_id:
                continue
            if accumulator.on_pitch(event.minute):
                accumulator.goals_conceded_while_eligible += 1
            elif accumulator.dismissed_at is not None and event.minute >= accumulator.dismissed_at:
                accumulator.team_goals_after_dismissal += 1


def _generate_auxiliary_events(
    *,
    participation: ParticipationScenario,
    config: EventAllocationConfig,
    accumulators: dict[str, _Accumulator],
    root_seed: int,
    scenario_index: int,
) -> None:
    for player_id in sorted(accumulators):
        accumulator = accumulators[player_id]
        minutes = accumulator.minutes
        if minutes <= 0:
            continue
        profile = accumulator.profile
        rng = rng_for(root_seed, "auxiliary", scenario_index, player_id)
        accumulator.defensive["clearances"] = _poisson(rng, profile.clearances_per90, minutes)
        accumulator.defensive["blocks"] = _poisson(rng, profile.blocks_per90, minutes)
        accumulator.defensive["interceptions"] = _poisson(rng, profile.interceptions_per90, minutes)
        accumulator.defensive["tackles"] = _poisson(rng, profile.tackles_per90, minutes)
        accumulator.defensive["ball_recoveries"] = _poisson(
            rng, profile.ball_recoveries_per90, minutes
        )
        if config.bps_completeness_mode is BpsCompletenessMode.EVENT_LINKED_ONLY:
            continue
        rates = profile.bps_auxiliary
        accumulator.bps["big_chances_created"] = _poisson(
            rng, rates.big_chances_created_per90, minutes
        )
        accumulator.bps["big_chances_missed"] = _poisson(
            rng, rates.big_chances_missed_per90, minutes
        )
        accumulator.bps["errors_leading_attempt"] = _poisson(
            rng, rates.errors_leading_attempt_per90, minutes
        )
        accumulator.bps["errors_leading_goal"] = _poisson(
            rng, rates.errors_leading_goal_per90, minutes
        )
        accumulator.bps["fouls_conceded"] = _poisson(rng, rates.fouls_conceded_per90, minutes)
        accumulator.bps["fouls_won"] = _poisson(rng, rates.fouls_won_per90, minutes)
        accumulator.bps["goal_line_clearances"] = _poisson(
            rng, rates.goal_line_clearances_per90, minutes
        )
        accumulator.bps["key_passes"] = _poisson(rng, rates.key_passes_per90, minutes)
        accumulator.bps["offsides"] = _poisson(rng, rates.offsides_per90, minutes)
        attempts = _poisson(rng, rates.pass_attempts_per90, minutes)
        accumulator.bps["pass_attempts"] = attempts
        accumulator.bps["passes_completed"] = int(
            rng.binomial(attempts, rates.pass_completion_probability)
        )
        accumulator.bps["recoveries"] = _poisson(rng, rates.recoveries_per90, minutes)
        accumulator.bps["shots_off_target"] = _poisson(rng, rates.shots_off_target_per90, minutes)
        accumulator.bps["successful_dribbles"] = _poisson(
            rng, rates.successful_dribbles_per90, minutes
        )
        accumulator.bps["successful_open_play_crosses"] = _poisson(
            rng, rates.successful_open_play_crosses_per90, minutes
        )
        # Tackles already feed the defensive-event vector. The temporary baseline deliberately
        # leaves the distinct BPS successful-tackle category at zero to prevent double counting.
        accumulator.bps["successful_tackles"] = 0
        accumulator.bps["times_tackled"] = _poisson(rng, rates.times_tackled_per90, minutes)


def _generate_goalkeeper_saves(
    *,
    participation: ParticipationScenario,
    config: EventAllocationConfig,
    accumulators: dict[str, _Accumulator],
    root_seed: int,
    scenario_index: int,
    degradation: list[str],
) -> list[GoalkeeperSaveEvent]:
    """Sample GK-prior saves and create one compatible timed on-target shot per save."""

    events: list[GoalkeeperSaveEvent] = []
    goalkeepers = tuple(
        accumulator
        for accumulator in sorted(
            accumulators.values(), key=lambda item: item.participant.player_id
        )
        if accumulator.participant.position is PlayerPosition.GK and accumulator.minutes > 0
    )
    for goalkeeper in goalkeepers:
        interval = goalkeeper.participant.interval
        assert interval is not None
        count_rng = rng_for(
            root_seed,
            "goalkeeper-save-count",
            scenario_index,
            goalkeeper.participant.player_id,
        )
        save_count = _poisson(
            count_rng, goalkeeper.profile.goalkeeper_saves_per90, goalkeeper.minutes
        )
        attacking_team = (
            participation.away_team_id
            if goalkeeper.participant.team_id == participation.home_team_id
            else participation.home_team_id
        )
        for sequence in range(1, save_count + 1):
            rng = rng_for(
                root_seed,
                "goalkeeper-save",
                scenario_index,
                goalkeeper.participant.player_id,
                sequence,
            )
            minute = float(rng.uniform(interval.start_minute, interval.end_minute))
            candidates = _eligible(accumulators, attacking_team, minute)
            weighted = tuple(
                candidate
                for candidate in candidates
                if candidate.profile.bps_auxiliary.shots_on_target_non_goal_per90 > 0.0
            )
            if weighted:
                shooter = _sample_weighted(
                    weighted,
                    tuple(
                        candidate.profile.bps_auxiliary.shots_on_target_non_goal_per90
                        for candidate in weighted
                    ),
                    rng,
                )
            elif config.source_tag == "TEST_SYNTHETIC":
                shooter = _choose_accumulator(
                    candidates,
                    lambda item: item.profile.goal_share,
                    rng,
                    code="NO_ELIGIBLE_ON_TARGET_SHOOTER",
                )
                degradation.append("TEST_SAVE_SHOOTER_GOAL_SHARE_PROXY")
            else:
                raise FplPointsError(
                    "NO_ELIGIBLE_ON_TARGET_SHOOTER",
                    "sampled goalkeeper save has no compatible governed shooter share",
                )
            goalkeeper.saves += 1
            if float(rng.random()) < goalkeeper.profile.saves_inside_box_fraction:
                goalkeeper.bps["saves_inside_box"] += 1
            else:
                goalkeeper.bps["saves_outside_box"] += 1
            shooter.bps["shots_on_target"] += 1
            events.append(
                GoalkeeperSaveEvent(
                    save_id=stable_identifier(
                        "save",
                        root_seed,
                        scenario_index,
                        goalkeeper.participant.player_id,
                        sequence,
                    ),
                    minute=minute,
                    attacking_team_id=attacking_team,
                    defending_team_id=goalkeeper.participant.team_id,
                    goalkeeper_player_id=goalkeeper.participant.player_id,
                    shooter_player_id=shooter.participant.player_id,
                )
            )
    return sorted(events, key=lambda event: (event.minute, event.save_id))


def _scored_penalty_events(events: list[GoalEvent]) -> list[PenaltyEvent]:
    return [
        PenaltyEvent(
            penalty_id=stable_identifier("penalty-goal", 0, event.goal_id),
            minute=event.minute,
            attacking_team_id=event.scoring_team_id,
            defending_team_id=event.conceding_team_id,
            taker_player_id=event.scorer_player_id,
            outcome=PenaltyOutcome.GOAL,
            goalkeeper_player_id=None,
            goal_id=event.goal_id,
        )
        for event in events
        if event.mechanism is GoalMechanism.PENALTY and event.scorer_player_id is not None
    ]


def _generate_extra_penalty(
    *,
    participation: ParticipationScenario,
    config: EventAllocationConfig,
    accumulators: dict[str, _Accumulator],
    penalty_taker_hierarchy: tuple[PenaltyTakerHierarchyEntry, ...],
    penalty_hierarchy_exhaustion_policy: PenaltyHierarchyExhaustionPolicy,
    degradation: list[str],
    root_seed: int,
    scenario_index: int,
) -> tuple[PenaltyEvent | None, GoalkeeperSaveEvent | None]:
    rng = rng_for(root_seed, "extra-penalty", scenario_index)
    if float(rng.random()) >= config.extra_penalty_attempt_probability:
        return None, None
    minute = float(rng.uniform(config.goal_time_lower, config.goal_time_upper))
    attacking_team = (
        participation.home_team_id if float(rng.random()) < 0.5 else participation.away_team_id
    )
    defending_team = (
        participation.away_team_id
        if attacking_team == participation.home_team_id
        else participation.home_team_id
    )
    takers = _eligible(accumulators, attacking_team, minute)
    keepers = tuple(
        item
        for item in _eligible(accumulators, defending_team, minute)
        if item.participant.position.value == "GK"
    )
    if not takers or not keepers:
        raise FplPointsError(
            "NO_ELIGIBLE_PENALTY_PARTICIPANT",
            "sampled penalty lacks an on-pitch taker or defending goalkeeper",
        )
    taker = _resolve_penalty_taker(
        takers,
        penalty_taker_hierarchy,
        penalty_hierarchy_exhaustion_policy,
        rng,
        degradation,
    )
    keeper = (
        keepers[0]
        if len(keepers) == 1
        else _sample_weighted(keepers, tuple(1.0 for _ in keepers), rng)
    )
    taker.penalty_misses += 1
    penalty_id = stable_identifier("extra-penalty", root_seed, scenario_index)
    if float(rng.random()) < config.extra_penalty_save_probability:
        keeper.penalty_saves += 1
        keeper.saves += 1
        keeper.bps["saves_inside_box"] += 1
        keeper.bps["big_chance_saves"] += 1
        taker.bps["shots_on_target"] += 1
        penalty = PenaltyEvent(
            penalty_id=penalty_id,
            minute=minute,
            attacking_team_id=attacking_team,
            defending_team_id=defending_team,
            taker_player_id=taker.participant.player_id,
            outcome=PenaltyOutcome.SAVED,
            goalkeeper_player_id=keeper.participant.player_id,
            goal_id=None,
        )
        save = GoalkeeperSaveEvent(
            save_id=stable_identifier("penalty-save", 0, penalty_id),
            minute=minute,
            attacking_team_id=attacking_team,
            defending_team_id=defending_team,
            goalkeeper_player_id=keeper.participant.player_id,
            shooter_player_id=taker.participant.player_id,
            penalty_id=penalty_id,
        )
        return penalty, save
    return (
        PenaltyEvent(
            penalty_id=penalty_id,
            minute=minute,
            attacking_team_id=attacking_team,
            defending_team_id=defending_team,
            taker_player_id=taker.participant.player_id,
            outcome=PenaltyOutcome.MISSED,
            goalkeeper_player_id=None,
            goal_id=None,
        ),
        None,
    )


def allocate_fixture_events(
    *,
    cell: ScorelineCell,
    participation: ParticipationScenario,
    profiles: tuple[PlayerAllocationProfile, ...],
    config: EventAllocationConfig,
    ruleset: RulesetIdentity,
    projection_mode: ProjectionMode,
    root_seed: int,
    scenario_index: int,
    penalty_taker_hierarchy: tuple[PenaltyTakerHierarchyEntry, ...] = (),
    penalty_hierarchy_exhaustion_policy: PenaltyHierarchyExhaustionPolicy = (
        PenaltyHierarchyExhaustionPolicy.BLOCK
    ),
    assist_classifier: Callable[[AssistDecisionContext], AssistClassification | None] | None = None,
) -> tuple[FixtureEventScenario, tuple[str, ...]]:
    """Allocate one coherent exact event vector conditional on score and minutes."""

    for team_id in (participation.home_team_id, participation.away_team_id):
        validate_goal_share_simplex(profiles, team_id)
        validate_assist_share_constraints(profiles, team_id)
    accumulators = _initialize_accumulators(
        participation, profiles, root_seed=root_seed, scenario_index=scenario_index
    )
    degradation: list[str] = [config.source_tag]
    if config.bps_completeness_mode is not BpsCompletenessMode.EVENT_LINKED_ONLY:
        degradation.extend([config.auxiliary_source_tag, "BPS_AUXILIARY_BASELINE_INCOMPLETE"])
    degradation.extend(
        [
            "GOALKEEPER_SAVES_CONDITIONAL_ON_GK_RATE",
            "SAVED_SHOTS_EVENT_LINKED_TO_ON_PITCH_ATTACKER",
        ]
    )
    if projection_mode is not ProjectionMode.PRODUCTION or ruleset.status != "ACTIVE":
        degradation.append("TARGET_RULESET_NOT_ACTIVE_CONFIDENCE_E")
    events = _allocate_goals(
        cell=cell,
        participation=participation,
        config=config,
        accumulators=accumulators,
        penalty_taker_hierarchy=penalty_taker_hierarchy,
        penalty_hierarchy_exhaustion_policy=penalty_hierarchy_exhaustion_policy,
        degradation=degradation,
        root_seed=root_seed,
        scenario_index=scenario_index,
        assist_classifier=assist_classifier,
    )
    _mark_match_winning_goal(events, accumulators, cell, participation)
    _assign_conceded(events, accumulators)
    _generate_auxiliary_events(
        participation=participation,
        config=config,
        accumulators=accumulators,
        root_seed=root_seed,
        scenario_index=scenario_index,
    )
    save_events = _generate_goalkeeper_saves(
        participation=participation,
        config=config,
        accumulators=accumulators,
        root_seed=root_seed,
        scenario_index=scenario_index,
        degradation=degradation,
    )
    penalty_events = _scored_penalty_events(events)
    extra_penalty, extra_save = _generate_extra_penalty(
        participation=participation,
        config=config,
        accumulators=accumulators,
        penalty_taker_hierarchy=penalty_taker_hierarchy,
        penalty_hierarchy_exhaustion_policy=penalty_hierarchy_exhaustion_policy,
        degradation=degradation,
        root_seed=root_seed,
        scenario_index=scenario_index,
    )
    if extra_penalty is not None:
        penalty_events.append(extra_penalty)
    if extra_save is not None:
        save_events.append(extra_save)
    players = tuple(
        accumulators[player_id].to_model(config.auxiliary_source_tag)
        for player_id in sorted(accumulators)
    )
    event_scenario = FixtureEventScenario(
        fixture_id=participation.fixture_id,
        gameweek_id=participation.gameweek_id,
        home_team_id=participation.home_team_id,
        away_team_id=participation.away_team_id,
        home_goals=cell.home_goals,
        away_goals=cell.away_goals,
        participant_universe_complete=True,
        players=players,
        goals=tuple(events),
        penalties=tuple(sorted(penalty_events, key=lambda event: (event.minute, event.penalty_id))),
        goalkeeper_saves=tuple(
            sorted(save_events, key=lambda event: (event.minute, event.save_id))
        ),
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.ruleset_version,
        ruleset_hash=ruleset.ruleset_hash,
    )
    return event_scenario, tuple(sorted(set(degradation)))
