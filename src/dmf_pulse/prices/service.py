"""Stage-13 application service shared by library and CLI entry points."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import StrictBool, StrictInt, StrictStr, TypeAdapter

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
from dmf_pulse.prices.errors import PriceLeakageError
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

_STRICT_BOOL = TypeAdapter(StrictBool)
_STRICT_INT = TypeAdapter(StrictInt)
_STRICT_STR = TypeAdapter(StrictStr)
_STRICT_STR_TUPLE = TypeAdapter(tuple[StrictStr, ...])


def _strict_int(payload: dict[str, Any], key: str) -> int:
    return _STRICT_INT.validate_python(payload[key])


def _strict_str(payload: dict[str, Any], key: str) -> str:
    return _STRICT_STR.validate_python(payload[key])


def _strict_datetime(payload: dict[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(_strict_str(payload, key).replace("Z", "+00:00"))


def _strict_decimal(payload: dict[str, Any], key: str, default: Decimal) -> Decimal:
    value = payload.get(key, default)
    if isinstance(value, (bool, float)):
        raise ValueError(f"{key} binary floats/booleans are prohibited")
    return Decimal(value)


def _canonical_source_lineage(
    observation_ids: tuple[str, ...],
    semantic_hashes: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not observation_ids or len(observation_ids) != len(semantic_hashes):
        raise ValueError("projection requires one semantic hash per source observation")
    pairs = tuple(zip(observation_ids, semantic_hashes, strict=True))
    if len({observation_id for observation_id, _ in pairs}) != len(pairs):
        raise ValueError("projection source observation IDs must be unique")
    canonical = tuple(sorted(pairs, key=lambda item: item[0]))
    return (
        tuple(observation_id for observation_id, _ in canonical),
        tuple(semantic_hash for _, semantic_hash in canonical),
    )


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
    verify_sealed(model, "artifact_sha256")
    cutoff = feature_vector.information_cutoff
    if model.training_cutoff > cutoff:
        raise PriceLeakageError(
            "PRICE_MODEL_FUTURE_TRAINING_BLOCKED",
            "model training cutoff follows the prediction information cutoff",
        )
    if model.configuration_sha256 != price_config_sha256(config):
        raise ValueError("model artifact configuration hash differs from the active price policy")
    if (
        model.model_version != config.competing_logit.model_version
        or model.feature_schema_version != config.competing_logit.feature_schema_version
        or model.feature_names != config.competing_logit.feature_names
    ):
        raise ValueError("model artifact identity/schema differs from the active price policy")
    if pressure_state.state_version != config.recurrent_pressure.state_version:
        raise ValueError("latent pressure state version differs from the active price policy")
    if calibration is not None:
        if calibration.training_cutoff > cutoff:
            raise PriceLeakageError(
                "PRICE_CALIBRATION_FUTURE_TRAINING_BLOCKED",
                "calibration training cutoff follows the prediction information cutoff",
            )
        if (
            calibration.calibration_version != config.competing_logit.calibration_version
            or calibration.probability_epsilon
            != config.competing_logit.calibration_probability_epsilon
        ):
            raise ValueError("calibration artifact identity differs from the active price policy")
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
    canonical_source_ids, canonical_source_hashes = _canonical_source_lineage(
        source_observation_ids,
        source_semantic_hashes,
    )
    paths = simulate_price_paths(
        current_price_units=current_price_units,
        state=pressure_state,
        baseline=p1,
        config=config,
        model_lineage=model_lineage,
    )
    h24, h72, h7d = paths.horizons
    lineage = ProjectionLineage(
        source_observation_ids=canonical_source_ids,
        source_semantic_hashes=canonical_source_hashes,
        model_version_ids=model_lineage,
        calibration_version_ids=(
            (calibration.calibration_version,) if calibration is not None else ()
        ),
        model_artifact_sha256=model.artifact_sha256,
        calibration_artifact_sha256=(
            calibration.artifact_sha256 if calibration is not None else None
        ),
        price_path_distribution_sha256=paths.distribution_sha256,
        configuration_sha256=price_config_sha256(config),
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
            player_id=_strict_str(payload, "player_id"),
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
            player_id=_strict_str(payload, "player_id"),
            cutoff=_strict_datetime(payload, "information_cutoff"),
            dataset_mode=DatasetMode(payload["dataset_mode"]),
            context=TransferFlowContext.model_validate(payload["context"]),
            config=self.config,
            strict_temporal=_STRICT_BOOL.validate_python(payload.get("strict_temporal", True)),
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
            training_cutoff=_strict_datetime(payload, "training_cutoff"),
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
            player_id=_strict_str(payload, "player_id"),
            current_price_units=_strict_int(payload, "current_price_units"),
            feature_vector=PriceFeatureVector.model_validate(payload["feature_vector"]),
            model=CompetingLogitArtifact.model_validate(payload["model"]),
            pressure_state=LatentPressureState.model_validate(payload["pressure_state"]),
            source_observation_ids=_STRICT_STR_TUPLE.validate_python(
                payload["source_observation_ids"]
            ),
            source_semantic_hashes=_STRICT_STR_TUPLE.validate_python(
                payload["source_semantic_hashes"]
            ),
            ruleset_id=_strict_str(payload, "ruleset_id"),
            ruleset_hash=_strict_str(payload, "ruleset_hash"),
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
            current_price_units=_strict_int(payload, "current_price_units"),
            state=LatentPressureState.model_validate(payload["pressure_state"]),
            baseline=PriceProbabilityVector.model_validate(payload["baseline"]),
            config=self.config,
            model_lineage=_STRICT_STR_TUPLE.validate_python(payload["model_lineage"]),
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
            player_id=_strict_str(payload, "player_id"),
            horizon=_strict_str(payload, "horizon"),
            market_price_pmf=PricePmf.model_validate(payload["market_price_pmf"]),
            maximum_support=_STRICT_INT.validate_python(
                payload.get("maximum_support", self.config.price_paths.maximum_optimiser_support)
            ),
            ownership_spell=(
                OwnershipSpell.model_validate(spell_payload) if spell_payload is not None else None
            ),
            selling_price_rule=(
                SellingPriceRule.model_validate(rule_payload) if rule_payload is not None else None
            ),
            route_budget_units=(
                _strict_int(payload, "route_budget_units")
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
            evaluation_cutoff=_strict_datetime(payload, "evaluation_cutoff"),
            alert_probability=_strict_decimal(
                payload,
                "alert_probability",
                self.config.evaluation.alert_probability,
            ),
            probability_epsilon=self.config.evaluation.probability_epsilon,
        )

    def validate(self) -> PriceValidationReport:
        return PriceValidationReport(
            configuration_id=self.config.configuration_id,
            configuration_sha256=price_config_sha256(self.config),
            configuration_role=self.config.configuration_role,
            parameter_status=self.config.parameter_status,
            evidence_status=self.config.evidence_status,
            implemented_models=(
                ModelFamily.P0_NO_CHANGE,
                ModelFamily.P1_REGULARIZED_COMPETING_LOGIT,
                ModelFamily.P2_RECURRENT_LATENT_PRESSURE,
            ),
            challenger_status=gbdt_challenger_status(self.config),
            activation_statuses=self.config.activation.production_statuses,
        )
