"""Stage-13 application service shared by library and CLI entry points."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from dmf_pulse.evaluation.artifacts import semantic_sha256, verify_sealed
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.optimisation.manager_state import OwnershipSpell
from dmf_pulse.optimisation.multi_gameweek_models import SellingPriceRule
from dmf_pulse.prices.artifacts import persist_price_artifact, seal_projection
from dmf_pulse.prices.benchmarks import gbdt_challenger_status
from dmf_pulse.prices.calibration import apply_price_calibration
from dmf_pulse.prices.classifier import fit_competing_logit, predict_competing_logit
from dmf_pulse.prices.configuration import PriceConfig, load_price_config, price_config_sha256
from dmf_pulse.prices.early_transfer import evaluate_act_now_vs_wait
from dmf_pulse.prices.evaluation import evaluate_price_forecasts
from dmf_pulse.prices.models import (
    ArtifactReceipt,
    CompetingLogitArtifact,
    ConfidenceGrade,
    EarlyTransferAlternative,
    EarlyTransferDecision,
    LatentPressureState,
    ModelDisagreementStatus,
    ModelFamily,
    PriceCalibrationArtifact,
    PriceEvaluationReport,
    PriceEvaluationRow,
    PriceFeatureVector,
    PriceObservation,
    PricePathDistribution,
    PricePmf,
    PriceProbabilityVector,
    PriceProjection,
    PriceScenarioSet,
    PriceTrainingExample,
    PriceUpdateCycle,
    PriceUpdateWindow,
    PriceValidationReport,
    ProjectionLineage,
    TransferFlowContext,
    TransferFlowFeatures,
)
from dmf_pulse.prices.price_paths import simulate_price_paths
from dmf_pulse.prices.recurrent_hazard import predict_recurrent_hazard, threshold_distance
from dmf_pulse.prices.selling_value import (
    build_optimiser_price_scenarios,
    selling_value_distribution,
)
from dmf_pulse.prices.transfer_flows import build_transfer_flow_features
from dmf_pulse.prices.update_cycles import build_price_update_cycles


def _confidence(state: LatentPressureState, *, config: PriceConfig) -> ConfidenceGrade:
    proposed = (
        ConfidenceGrade.C
        if state.uncertainty <= config.activation.confidence_c_max_uncertainty
        else ConfidenceGrade.D
    )
    order = {
        ConfidenceGrade.A: 0,
        ConfidenceGrade.B: 1,
        ConfidenceGrade.C: 2,
        ConfidenceGrade.D: 3,
        ConfidenceGrade.E: 4,
    }
    return (
        proposed
        if order[proposed] >= order[config.activation.maximum_confidence]
        else config.activation.maximum_confidence
    )


def predict_price(
    *,
    player_id: str,
    current_price_units: int,
    feature_vector: PriceFeatureVector,
    model: CompetingLogitArtifact,
    pressure_state: LatentPressureState,
    source_observation_ids: tuple[str, ...],
    source_semantic_hashes: tuple[str, ...],
    ruleset_id: str,
    ruleset_hash: str,
    dataset_mode: DatasetMode,
    config: PriceConfig,
    calibration: PriceCalibrationArtifact | None = None,
) -> PriceProjection:
    """Produce one recurrent, PMF-backed projection with fail-closed activation lineage."""

    if feature_vector.player_id != player_id or pressure_state.player_id != player_id:
        raise ValueError("projection player identity differs across model inputs")
    if feature_vector.information_cutoff != pressure_state.as_of:
        raise ValueError("feature and recurrent-state cutoffs differ")
    p1 = predict_competing_logit(model, feature_vector)
    if calibration is not None:
        verify_sealed(calibration, "artifact_sha256")
        p1 = apply_price_calibration(p1, calibration)
    p2 = predict_recurrent_hazard(pressure_state, config=config, baseline=p1)
    maximum_difference = max(
        abs(p1.probability_fall - p2.probability_fall),
        abs(p1.probability_no_change - p2.probability_no_change),
        abs(p1.probability_rise - p2.probability_rise),
    )
    disagreement = (
        ModelDisagreementStatus.MATERIAL_DISAGREEMENT
        if maximum_difference > config.competing_logit.disagreement_threshold
        else ModelDisagreementStatus.AGREEMENT
    )
    model_lineage = tuple(sorted({model.model_version, pressure_state.state_version}))
    paths = simulate_price_paths(
        current_price_units=current_price_units,
        state=pressure_state,
        baseline=p1,
        config=config,
        model_lineage=model_lineage,
    )
    h24, h72, h7d = paths.horizons
    lineage = ProjectionLineage(
        source_observation_ids=tuple(sorted(set(source_observation_ids))),
        source_semantic_hashes=tuple(sorted(set(source_semantic_hashes))),
        model_version_ids=model_lineage,
        calibration_version_ids=(
            (calibration.calibration_version,) if calibration is not None else ()
        ),
        ruleset_id=ruleset_id,
        ruleset_hash=ruleset_hash,
        dataset_mode=dataset_mode,
        information_cutoff=feature_vector.information_cutoff,
    )
    identity = semantic_sha256(
        {
            "player_id": player_id,
            "current_price_units": current_price_units,
            "feature_vector": feature_vector.model_dump(mode="json"),
            "model_sha256": model.artifact_sha256,
            "calibration_sha256": calibration.artifact_sha256 if calibration else None,
            "pressure_state": pressure_state.model_dump(mode="json"),
            "path_sha256": paths.distribution_sha256,
            "lineage": lineage.model_dump(mode="json"),
        }
    )
    value = PriceProjection(
        projection_id=f"price-projection-{identity[:24]}",
        player_id=player_id,
        current_price_units=current_price_units,
        probability_rise_next_update=p2.probability_rise,
        probability_fall_next_update=p2.probability_fall,
        probability_no_change_next_update=p2.probability_no_change,
        expected_price_24h=h24.expected_price_units,
        expected_price_72h=h72.expected_price_units,
        expected_price_7d=h7d.expected_price_units,
        price_pmf_24h=h24.price_pmf,
        price_pmf_72h=h72.price_pmf,
        price_pmf_7d=h7d.price_pmf,
        probability_any_rise_24h=h24.probability_any_rise,
        probability_any_rise_72h=h72.probability_any_rise,
        probability_any_rise_7d=h7d.probability_any_rise,
        probability_any_fall_24h=h24.probability_any_fall,
        probability_any_fall_72h=h72.probability_any_fall,
        probability_any_fall_7d=h7d.probability_any_fall,
        probability_multiple_rises_gameweek=paths.probability_multiple_rises_gameweek,
        probability_multiple_falls_gameweek=paths.probability_multiple_falls_gameweek,
        confidence=_confidence(pressure_state, config=config),
        model_disagreement_status=disagreement,
        activation_statuses=config.activation.production_statuses,
        threshold_distance=threshold_distance(pressure_state, config=config),
        lineage=lineage,
        projection_sha256="0" * 64,
    )
    return seal_projection(value)


class PriceService:
    """Validate JSON-shaped requests and execute the same pure Stage-13 functions as the CLI."""

    def __init__(self, config: PriceConfig | None = None) -> None:
        self.config = config or load_price_config()

    def build_update_cycles(self, payload: dict[str, Any]) -> tuple[PriceUpdateCycle, ...]:
        observations = TypeAdapter(tuple[PriceObservation, ...]).validate_python(
            payload["observations"]
        )
        windows = TypeAdapter(tuple[PriceUpdateWindow, ...]).validate_python(payload["windows"])
        return build_price_update_cycles(
            observations,
            windows,
            player_id=str(payload["player_id"]),
            dataset_mode=DatasetMode(payload["dataset_mode"]),
            maximum_label_interval=timedelta(
                minutes=self.config.update_cycles.maximum_label_interval_minutes
            ),
        )

    def build_features(self, payload: dict[str, Any]) -> TransferFlowFeatures:
        observations = TypeAdapter(tuple[PriceObservation, ...]).validate_python(
            payload["observations"]
        )
        return build_transfer_flow_features(
            observations,
            player_id=str(payload["player_id"]),
            cutoff=datetime.fromisoformat(
                str(payload["information_cutoff"]).replace("Z", "+00:00")
            ),
            dataset_mode=DatasetMode(payload["dataset_mode"]),
            context=TransferFlowContext.model_validate(payload["context"]),
            config=self.config,
            strict_temporal=bool(payload.get("strict_temporal", True)),
        )

    def train_baseline(
        self,
        payload: dict[str, Any],
        *,
        artifact_root: Path | None = None,
    ) -> CompetingLogitArtifact | ArtifactReceipt:
        examples = TypeAdapter(tuple[PriceTrainingExample, ...]).validate_python(
            payload["examples"]
        )
        artifact = fit_competing_logit(
            examples,
            training_cutoff=datetime.fromisoformat(
                str(payload["training_cutoff"]).replace("Z", "+00:00")
            ),
            config=self.config,
        )
        if artifact_root is None:
            return artifact
        return persist_price_artifact(
            artifact,
            hash_field="artifact_sha256",
            artifact_root=artifact_root,
            category="models",
            identity=artifact.model_id,
        )

    def predict(self, payload: dict[str, Any]) -> PriceProjection:
        calibration_payload = payload.get("calibration")
        return predict_price(
            player_id=str(payload["player_id"]),
            current_price_units=int(payload["current_price_units"]),
            feature_vector=PriceFeatureVector.model_validate(payload["feature_vector"]),
            model=CompetingLogitArtifact.model_validate(payload["model"]),
            pressure_state=LatentPressureState.model_validate(payload["pressure_state"]),
            source_observation_ids=tuple(payload["source_observation_ids"]),
            source_semantic_hashes=tuple(payload["source_semantic_hashes"]),
            ruleset_id=str(payload["ruleset_id"]),
            ruleset_hash=str(payload["ruleset_hash"]),
            dataset_mode=DatasetMode(payload["dataset_mode"]),
            config=self.config,
            calibration=(
                PriceCalibrationArtifact.model_validate(calibration_payload)
                if calibration_payload is not None
                else None
            ),
        )

    def simulate(self, payload: dict[str, Any]) -> PricePathDistribution:
        return simulate_price_paths(
            current_price_units=int(payload["current_price_units"]),
            state=LatentPressureState.model_validate(payload["pressure_state"]),
            baseline=PriceProbabilityVector.model_validate(payload["baseline"]),
            config=self.config,
            model_lineage=tuple(payload["model_lineage"]),
        )

    def selling_value(self, payload: dict[str, Any]) -> PricePmf:
        return selling_value_distribution(
            OwnershipSpell.model_validate(payload["ownership_spell"]),
            PricePmf.model_validate(payload["market_price_pmf"]),
            rule=SellingPriceRule.model_validate(payload["selling_price_rule"]),
        )

    def price_scenarios(self, payload: dict[str, Any]) -> PriceScenarioSet:
        spell_payload = payload.get("ownership_spell")
        rule_payload = payload.get("selling_price_rule")
        return build_optimiser_price_scenarios(
            player_id=str(payload["player_id"]),
            horizon=str(payload["horizon"]),
            market_price_pmf=PricePmf.model_validate(payload["market_price_pmf"]),
            maximum_support=int(
                payload.get("maximum_support", self.config.price_paths.maximum_optimiser_support)
            ),
            ownership_spell=(
                OwnershipSpell.model_validate(spell_payload) if spell_payload is not None else None
            ),
            selling_price_rule=(
                SellingPriceRule.model_validate(rule_payload) if rule_payload is not None else None
            ),
            route_budget_units=(
                int(payload["route_budget_units"])
                if payload.get("route_budget_units") is not None
                else None
            ),
        )

    def act_or_wait(self, payload: dict[str, Any]) -> EarlyTransferDecision:
        alternatives = TypeAdapter(tuple[EarlyTransferAlternative, ...]).validate_python(
            payload["alternatives"]
        )
        return evaluate_act_now_vs_wait(
            alternatives,
            projection=PriceProjection.model_validate(payload["projection"]),
            dataset_mode=DatasetMode(payload["dataset_mode"]),
            config=self.config,
        )

    def evaluate(self, payload: dict[str, Any]) -> PriceEvaluationReport:
        rows = TypeAdapter(tuple[PriceEvaluationRow, ...]).validate_python(payload["rows"])
        return evaluate_price_forecasts(
            rows,
            evaluation_cutoff=datetime.fromisoformat(
                str(payload["evaluation_cutoff"]).replace("Z", "+00:00")
            ),
            alert_probability=Decimal(
                str(payload.get("alert_probability", self.config.evaluation.alert_probability))
            ),
            probability_epsilon=self.config.evaluation.probability_epsilon,
        )

    def validate(self) -> PriceValidationReport:
        return PriceValidationReport(
            configuration_id=self.config.configuration_id,
            configuration_sha256=price_config_sha256(self.config),
            implemented_models=(
                ModelFamily.P0_NO_CHANGE,
                ModelFamily.P1_REGULARIZED_COMPETING_LOGIT,
                ModelFamily.P2_RECURRENT_LATENT_PRESSURE,
            ),
            challenger_status=gbdt_challenger_status(self.config),
            activation_statuses=self.config.activation.production_statuses,
        )
