"""Immutable captaincy and Triple Captain contracts for Stage 14.

Every result is evaluated on a common coherent scenario set and carries the
rules, chip-definition and inventory identities needed for reproducibility.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictStr, model_validator

from dmf_pulse.chips.definitions import FrozenModel, PositiveInt, Sha256, semantic_sha256

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
