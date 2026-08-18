"""Immutable captaincy and Triple Captain contracts for Stage 14.

Every result is evaluated on a common coherent scenario set and carries the
rules, chip-definition and inventory identities needed for reproducibility.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictStr, model_validator

from dmf_pulse.chips.definitions import (
    FrozenModel,
    NonNegativeInt,
    PositiveInt,
    Sha256,
    semantic_sha256,
)

from dmf_pulse.optimisation.manager_state import ManagerState

FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Probability = Annotated[StrictFloat, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
CaptainResolution = Literal["CAPTAIN", "VICE_CAPTAIN", "NEITHER"]


class ScenarioPolicyValue(FrozenModel):
    """Common-scenario comparison between two frozen root policies."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    no_chip_points: FiniteFloat
    chip_points: FiniteFloat
    gross_increment: FiniteFloat
    policy_increment: FiniteFloat

    @model_validator(mode="after")
    def current_increment_is_coherent(self) -> ScenarioPolicyValue:
        if abs(self.gross_increment - (self.chip_points - self.no_chip_points)) > 1e-9:
            raise ValueError("gross scenario increment must be chip minus no-chip points")
        return self


class CaptainScenarioScore(FrozenModel):
    """One exact common-scenario captain/vice resolution."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    manager_points: FiniteFloat
    effective_captain_id: StrictStr | None
    effective_captain_raw_points: FiniteFloat
    captain_resolution: CaptainResolution

    @model_validator(mode="after")
    def effective_captain_matches_resolution(self) -> CaptainScenarioScore:
        if self.captain_resolution == "NEITHER" and self.effective_captain_id is not None:
            raise ValueError("NEITHER captain resolution cannot identify an effective captain")
        if self.captain_resolution != "NEITHER" and self.effective_captain_id is None:
            raise ValueError("captain or vice resolution requires an effective captain")
        return self


class CaptainViceDecision(FrozenModel):
    """Joint captain/vice optimum under one declared multiplier."""

    captain: StrictStr = Field(min_length=1)
    vice_captain: StrictStr = Field(min_length=1)
    captain_multiplier: PositiveInt
    expected_manager_points: FiniteFloat
    expected_effective_captain_raw_points: FiniteFloat
    vice_fallback_probability: Probability
    vice_fallback_incremental_points: FiniteFloat
    captain_and_vice_failure_probability: Probability
    evaluated_pairs: PositiveInt
    scenario_scores: tuple[CaptainScenarioScore, ...]
    decision_hash: Sha256

    @model_validator(mode="after")
    def pair_and_scenarios_are_coherent(self) -> CaptainViceDecision:
        if self.captain == self.vice_captain:
            raise ValueError("captain and vice-captain must differ")
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_scores
        )
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("captain scenario identities must be non-empty and unique")
        if abs(sum(item.weight for item in self.scenario_scores) - 1.0) > 1e-9:
            raise ValueError("captain scenario weights must sum to one")
        expected_manager = sum(
            item.weight * item.manager_points for item in self.scenario_scores
        )
        expected_raw = sum(
            item.weight * item.effective_captain_raw_points
            for item in self.scenario_scores
        )
        vice_probability = sum(
            item.weight
            for item in self.scenario_scores
            if item.captain_resolution == "VICE_CAPTAIN"
        )
        vice_incremental = sum(
            item.weight
            * (self.captain_multiplier - 1)
            * item.effective_captain_raw_points
            for item in self.scenario_scores
            if item.captain_resolution == "VICE_CAPTAIN"
        )
        neither_probability = sum(
            item.weight
            for item in self.scenario_scores
            if item.captain_resolution == "NEITHER"
        )
        checks = (
            (self.expected_manager_points, expected_manager, "expected manager points"),
            (
                self.expected_effective_captain_raw_points,
                expected_raw,
                "expected effective-captain raw points",
            ),
            (self.vice_fallback_probability, vice_probability, "vice fallback probability"),
            (
                self.vice_fallback_incremental_points,
                vice_incremental,
                "vice fallback incremental points",
            ),
            (
                self.captain_and_vice_failure_probability,
                neither_probability,
                "captain-and-vice failure probability",
            ),
        )
        for observed, expected, name in checks:
            if abs(observed - expected) > 1e-9:
                raise ValueError(f"{name} differs from scenario values")
        payload = self.model_dump(mode="json", exclude={"decision_hash"})
        if semantic_sha256(payload) != self.decision_hash:
            raise ValueError("captain/vice decision hash mismatch")
        return self


class TripleCaptainEvaluation(FrozenModel):
    """Optimised Triple Captain policy versus the optimised no-chip comparator."""

    chip_key: Literal["TRIPLE_CAPTAIN"] = "TRIPLE_CAPTAIN"
    rule_multiplier: PositiveInt
    ordinary: CaptainViceDecision
    triple_captain: CaptainViceDecision
    scenario_values: tuple[ScenarioPolicyValue, ...]
    gross_current_gain: FiniteFloat
    chip_consumed: Literal[True]
    zero_extra_score: StrictBool
    token_id: StrictStr = Field(min_length=1)
    inventory_before_hash: Sha256
    inventory_after_activation_hash: Sha256
    scenario_set_hash: Sha256
    ruleset_id: StrictStr = Field(min_length=1)
    ruleset_version: StrictStr = Field(min_length=1)
    ruleset_hash: Sha256
    chip_definition_hash: Sha256
    evaluation_hash: Sha256

    @model_validator(mode="after")
    def multiplier_and_gain_are_coherent(self) -> TripleCaptainEvaluation:
        if self.rule_multiplier <= self.ordinary.captain_multiplier:
            raise ValueError("Triple Captain multiplier must exceed the ordinary multiplier")
        if self.triple_captain.captain_multiplier != self.rule_multiplier:
            raise ValueError("Triple Captain decision uses the wrong multiplier")
        ordinary_ids = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.ordinary.scenario_scores
        )
        triple_ids = tuple(
            (item.scenario_id, item.outcome_draw_id)
            for item in self.triple_captain.scenario_scores
        )
        value_ids = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_values
        )
        if ordinary_ids != triple_ids or ordinary_ids != value_ids:
            raise ValueError("Triple Captain policies must use the same ordered scenario set")
        expected = (
            self.triple_captain.expected_manager_points
            - self.ordinary.expected_manager_points
        )
        weighted_increment = sum(
            item.weight * item.gross_increment for item in self.scenario_values
        )
        if abs(expected - self.gross_current_gain) > 1e-9:
            raise ValueError(
                "Triple Captain gross gain must compare optimised common-scenario policies"
            )
        if abs(weighted_increment - self.gross_current_gain) > 1e-9:
            raise ValueError("Triple Captain scenario increments do not reconcile")
        if self.zero_extra_score != (abs(self.gross_current_gain) <= 1e-12):
            raise ValueError("zero-extra flag differs from gross current gain")
        if self.inventory_before_hash == self.inventory_after_activation_hash:
            raise ValueError("consuming Triple Captain must change projected inventory state")
        payload = self.model_dump(mode="json", exclude={"evaluation_hash"})
        if semantic_sha256(payload) != self.evaluation_hash:
            raise ValueError("Triple Captain evaluation hash mismatch")
        return self


NonNegativeFloat = Annotated[StrictFloat, Field(ge=0.0, allow_inf_nan=False)]


class BenchBoostCostProfile(FrozenModel):
    """Explicit preparation and post-use costs before chip continuation value."""

    plan_id: StrictStr = Field(min_length=1)
    is_natural: StrictBool
    preparation_transfer_count: NonNegativeInt = 0
    preparation_hit_cost_points: NonNegativeFloat = 0.0
    budget_shift_cost_points: NonNegativeFloat = 0.0
    future_starting_xi_cost_points: NonNegativeFloat = 0.0
    post_boost_unwind_cost_points: NonNegativeFloat = 0.0
    price_route_cost_points: NonNegativeFloat = 0.0

    @property
    def total_cost_points(self) -> float:
        """Return the transparent sum of declared policy costs."""

        return float(
            self.preparation_hit_cost_points
            + self.budget_shift_cost_points
            + self.future_starting_xi_cost_points
            + self.post_boost_unwind_cost_points
            + self.price_route_cost_points
        )


class BenchBoostScenarioValue(FrozenModel):
    """Scenario-level Bench Boost result after ordinary autosub overlap."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    normal_points: FiniteFloat
    bench_boost_points: FiniteFloat
    gross_increment: FiniteFloat
    bench_appeared_ids: tuple[StrictStr, ...]
    normal_autosub_overlap_ids: tuple[StrictStr, ...]
    bench_raw_points: FiniteFloat
    autosub_overlap_points: FiniteFloat

    @model_validator(mode="after")
    def scenario_arithmetic_is_coherent(self) -> BenchBoostScenarioValue:
        if abs(self.gross_increment - (self.bench_boost_points - self.normal_points)) > 1e-9:
            raise ValueError("Bench Boost gross increment must compare common-scenario policies")
        if len(self.bench_appeared_ids) != len(set(self.bench_appeared_ids)):
            raise ValueError("appearing bench player IDs must be unique")
        if len(self.normal_autosub_overlap_ids) != len(set(self.normal_autosub_overlap_ids)):
            raise ValueError("autosub-overlap player IDs must be unique")
        if not set(self.normal_autosub_overlap_ids) <= set(self.bench_appeared_ids):
            raise ValueError("autosub overlap must be a subset of appearing bench players")
        return self


class BenchBoostRouteEvaluation(FrozenModel):
    """One natural or engineered Bench Boost preparation route."""

    plan_id: StrictStr = Field(min_length=1)
    is_natural: StrictBool
    normal_tactic_signature: Sha256
    bench_boost_tactic_signature: Sha256
    expected_normal_points: FiniteFloat
    expected_bench_boost_points: FiniteFloat
    gross_current_gain: FiniteFloat
    costs: BenchBoostCostProfile
    net_pre_continuation_value: FiniteFloat
    evaluated_tactics: PositiveInt
    scenario_values: tuple[BenchBoostScenarioValue, ...]
    route_hash: Sha256

    @model_validator(mode="after")
    def route_arithmetic_is_coherent(self) -> BenchBoostRouteEvaluation:
        if self.plan_id != self.costs.plan_id or self.is_natural != self.costs.is_natural:
            raise ValueError("Bench Boost route identity must match its cost profile")
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_values
        )
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("Bench Boost scenario identities must be non-empty and unique")
        if abs(sum(item.weight for item in self.scenario_values) - 1.0) > 1e-9:
            raise ValueError("Bench Boost scenario weights must sum to one")
        expected_normal = sum(
            item.weight * item.normal_points for item in self.scenario_values
        )
        expected_boost = sum(
            item.weight * item.bench_boost_points for item in self.scenario_values
        )
        if abs(expected_normal - self.expected_normal_points) > 1e-9:
            raise ValueError("Bench Boost expected normal points do not reconcile")
        if abs(expected_boost - self.expected_bench_boost_points) > 1e-9:
            raise ValueError("Bench Boost expected chip points do not reconcile")
        if abs(self.gross_current_gain - (expected_boost - expected_normal)) > 1e-9:
            raise ValueError("Bench Boost gross current gain does not reconcile")
        expected_net = self.gross_current_gain - self.costs.total_cost_points
        if abs(self.net_pre_continuation_value - expected_net) > 1e-9:
            raise ValueError("Bench Boost net pre-continuation value does not reconcile")
        payload = self.model_dump(mode="json", exclude={"route_hash"})
        if semantic_sha256(payload) != self.route_hash:
            raise ValueError("Bench Boost route hash mismatch")
        return self


class WildcardBenchBoostSynergy(FrozenModel):
    """Measured route difference; positive synergy is never assumed."""

    standalone_route_hash: Sha256
    wildcard_prepared_route_hash: Sha256
    measured_synergy: FiniteFloat
    positive: StrictBool
    synergy_hash: Sha256

    @model_validator(mode="after")
    def sign_and_hash_are_coherent(self) -> WildcardBenchBoostSynergy:
        if self.positive != (self.measured_synergy > 0.0):
            raise ValueError("Wildcard-Bench Boost synergy sign is inconsistent")
        payload = self.model_dump(mode="json", exclude={"synergy_hash"})
        if semantic_sha256(payload) != self.synergy_hash:
            raise ValueError("Wildcard-Bench Boost synergy hash mismatch")
        return self


class BenchBoostEvaluation(FrozenModel):
    """Bench Boost evaluation with explicit current and preparation value."""

    chip_key: Literal["BENCH_BOOST"] = "BENCH_BOOST"
    standalone_route: BenchBoostRouteEvaluation
    wildcard_prepared_route: BenchBoostRouteEvaluation | None
    wildcard_synergy: WildcardBenchBoostSynergy | None
    chip_consumed: Literal[True]
    continuation_value_included: Literal[False]
    token_id: StrictStr = Field(min_length=1)
    inventory_before_hash: Sha256
    inventory_after_activation_hash: Sha256
    scenario_set_hash: Sha256
    ruleset_id: StrictStr = Field(min_length=1)
    ruleset_version: StrictStr = Field(min_length=1)
    ruleset_hash: Sha256
    chip_definition_hash: Sha256
    evaluation_hash: Sha256

    @model_validator(mode="after")
    def route_and_lineage_are_coherent(self) -> BenchBoostEvaluation:
        if (self.wildcard_prepared_route is None) != (self.wildcard_synergy is None):
            raise ValueError("Wildcard-Bench Boost route and synergy must be supplied together")
        if self.wildcard_prepared_route is not None and self.wildcard_synergy is not None:
            expected = (
                self.wildcard_prepared_route.net_pre_continuation_value
                - self.standalone_route.net_pre_continuation_value
            )
            if abs(expected - self.wildcard_synergy.measured_synergy) > 1e-9:
                raise ValueError("Wildcard-Bench Boost measured synergy does not reconcile")
            if self.wildcard_synergy.standalone_route_hash != self.standalone_route.route_hash:
                raise ValueError("Wildcard-Bench Boost standalone route hash differs")
            if (
                self.wildcard_synergy.wildcard_prepared_route_hash
                != self.wildcard_prepared_route.route_hash
            ):
                raise ValueError("Wildcard-Bench Boost prepared route hash differs")
        if self.inventory_before_hash == self.inventory_after_activation_hash:
            raise ValueError("consuming Bench Boost must change projected inventory state")
        payload = self.model_dump(mode="json", exclude={"evaluation_hash"})
        if semantic_sha256(payload) != self.evaluation_hash:
            raise ValueError("Bench Boost evaluation hash mismatch")
        return self

PolicyRole = Literal[
    "NORMAL_TRANSFER",
    "FREE_HIT_TEMPORARY",
    "WILDCARD_IMMEDIATE",
    "WILDCARD_DELAYED",
    "FREE_HIT_BRIDGE",
    "HOLD",
]


class PolicyScenarioScore(FrozenModel):
    """One common-scenario manager score for a frozen root policy."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    manager_points: FiniteFloat


class PolicyCostProfile(FrozenModel):
    """Transparent non-score costs attached to a permanent or temporary route."""

    permanent_squad_damage_points: NonNegativeFloat = 0.0
    route_flexibility_cost_points: NonNegativeFloat = 0.0
    purchase_price_spell_damage_points: NonNegativeFloat = 0.0
    information_delay_cost_points: NonNegativeFloat = 0.0
    affordability_route_cost_points: NonNegativeFloat = 0.0

    @property
    def total_cost_points(self) -> float:
        return float(
            self.permanent_squad_damage_points
            + self.route_flexibility_cost_points
            + self.purchase_price_spell_damage_points
            + self.information_delay_cost_points
            + self.affordability_route_cost_points
        )


class ChipPolicyCandidate(FrozenModel):
    """Immutable Stage-11/Stage-10 root-policy snapshot used by chip comparators."""

    policy_id: StrictStr = Field(min_length=1)
    policy_role: PolicyRole
    state_before_sha256: Sha256
    state_after_sha256: Sha256
    transition_event: StrictStr = Field(min_length=1)
    squad_ids: tuple[StrictStr, ...]
    bank_tenths: NonNegativeInt
    active_purchase_spell_ids: tuple[StrictStr, ...]
    free_transfers_after: NonNegativeInt
    transfer_count: NonNegativeInt
    transfer_hit_points: NonNegativeFloat
    tactical_plan_sha256: Sha256
    scenario_scores: tuple[PolicyScenarioScore, ...]
    expected_current_points: FiniteFloat
    costs: PolicyCostProfile = PolicyCostProfile()
    continuation_value: FiniteFloat = 0.0
    candidate_hash: Sha256

    @model_validator(mode="after")
    def candidate_reconciles(self) -> ChipPolicyCandidate:
        if self.squad_ids != tuple(sorted(self.squad_ids)):
            raise ValueError("chip-policy squad IDs must be sorted")
        if not self.squad_ids or len(self.squad_ids) != len(set(self.squad_ids)):
            raise ValueError("chip-policy squad IDs must be non-empty and unique")
        if self.active_purchase_spell_ids != tuple(sorted(self.active_purchase_spell_ids)):
            raise ValueError("chip-policy purchase-spell IDs must be sorted")
        if len(self.active_purchase_spell_ids) != len(set(self.active_purchase_spell_ids)):
            raise ValueError("chip-policy purchase-spell IDs must be unique")
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_scores
        )
        if not identities or identities != tuple(sorted(identities)):
            raise ValueError("chip-policy scenario identities must be non-empty and sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("chip-policy scenario identities must be unique")
        if abs(sum(item.weight for item in self.scenario_scores) - 1.0) > 1e-9:
            raise ValueError("chip-policy scenario weights must sum to one")
        expected = sum(item.weight * item.manager_points for item in self.scenario_scores)
        if abs(expected - self.expected_current_points) > 1e-9:
            raise ValueError("chip-policy expected current points do not reconcile")
        payload = self.model_dump(mode="json", exclude={"candidate_hash"})
        if semantic_sha256(payload) != self.candidate_hash:
            raise ValueError("chip-policy candidate hash mismatch")
        return self

    @property
    def net_pre_continuation_value(self) -> float:
        return float(
            self.expected_current_points - self.transfer_hit_points - self.costs.total_cost_points
        )

    @property
    def policy_value(self) -> float:
        return float(self.net_pre_continuation_value + self.continuation_value)


class FreeHitScenarioValue(FrozenModel):
    """Common-scenario Free Hit score relative to the best normal policy."""

    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    normal_points: FiniteFloat
    free_hit_points: FiniteFloat
    gross_current_increment: FiniteFloat

    @model_validator(mode="after")
    def scenario_reconciles(self) -> FreeHitScenarioValue:
        if abs(self.gross_current_increment - (self.free_hit_points - self.normal_points)) > 1e-9:
            raise ValueError("Free Hit scenario increment must compare common-scenario scores")
        return self


class FreeHitEvaluation(FrozenModel):
    """Best temporary Free Hit route versus the best legal normal transfer route."""

    chip_key: Literal["FREE_HIT"] = "FREE_HIT"
    normal_policy: ChipPolicyCandidate
    free_hit_policy: ChipPolicyCandidate
    scenario_values: tuple[FreeHitScenarioValue, ...]
    gross_current_gain: FiniteFloat
    transfer_hits_avoided: FiniteFloat
    permanent_squad_damage_avoided: FiniteFloat
    route_flexibility_preserved: FiniteFloat
    purchase_price_spell_value_preserved: FiniteFloat
    net_pre_continuation_value: FiniteFloat
    continuation_value_difference: FiniteFloat
    net_policy_value: FiniteFloat
    exercise_advantage: FiniteFloat
    use_now: StrictBool
    permanent_squad_restored: Literal[True]
    permanent_bank_restored: Literal[True]
    purchase_prices_restored: Literal[True]
    temporary_purchases_excluded_from_permanent_cohorts: Literal[True]
    restored_state: ManagerState
    token_id: StrictStr = Field(min_length=1)
    inventory_before_hash: Sha256
    inventory_after_activation_hash: Sha256
    scenario_set_hash: Sha256
    ruleset_id: StrictStr = Field(min_length=1)
    ruleset_version: StrictStr = Field(min_length=1)
    ruleset_hash: Sha256
    chip_definition_hash: Sha256
    evaluation_hash: Sha256

    @model_validator(mode="after")
    def evaluation_reconciles(self) -> FreeHitEvaluation:
        if self.normal_policy.policy_role != "NORMAL_TRANSFER":
            raise ValueError("Free Hit comparator requires a normal transfer policy")
        if self.free_hit_policy.policy_role != "FREE_HIT_TEMPORARY":
            raise ValueError("Free Hit route must be marked temporary")
        normal_ids = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.normal_policy.scenario_scores
        )
        free_hit_ids = tuple(
            (item.scenario_id, item.outcome_draw_id)
            for item in self.free_hit_policy.scenario_scores
        )
        value_ids = tuple((item.scenario_id, item.outcome_draw_id) for item in self.scenario_values)
        if normal_ids != free_hit_ids or normal_ids != value_ids:
            raise ValueError("Free Hit policies must use the same ordered scenario set")
        weighted = sum(item.weight * item.gross_current_increment for item in self.scenario_values)
        if abs(weighted - self.gross_current_gain) > 1e-9:
            raise ValueError("Free Hit gross current gain does not reconcile")
        expected_pre = (
            self.gross_current_gain
            + self.transfer_hits_avoided
            + self.permanent_squad_damage_avoided
            + self.route_flexibility_preserved
            + self.purchase_price_spell_value_preserved
        )
        if abs(expected_pre - self.net_pre_continuation_value) > 1e-9:
            raise ValueError("Free Hit pre-continuation value does not reconcile")
        if (
            abs(
                self.net_pre_continuation_value
                + self.continuation_value_difference
                - self.net_policy_value
            )
            > 1e-9
        ):
            raise ValueError("Free Hit net policy value does not reconcile")
        if abs(self.exercise_advantage - self.net_policy_value) > 1e-9:
            raise ValueError("Free Hit exercise advantage must equal use-now versus hold value")
        if self.use_now != (self.exercise_advantage > 0.0):
            raise ValueError("Free Hit use-now decision differs from exercise advantage")
        if self.inventory_before_hash == self.inventory_after_activation_hash:
            raise ValueError("Free Hit activation must change projected inventory")
        payload = self.model_dump(mode="json", exclude={"evaluation_hash"})
        if semantic_sha256(payload) != self.evaluation_hash:
            raise ValueError("Free Hit evaluation hash mismatch")
        return self
