from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.manager_state import OwnershipSpell
from dmf_pulse.optimisation.multi_gameweek_models import SellingPriceRule
from dmf_pulse.prices.artifacts import seal_observation
from dmf_pulse.prices.classifier import fit_competing_logit
from dmf_pulse.prices.configuration import PriceConfig, load_price_config
from dmf_pulse.prices.latent_pressure import initial_latent_pressure
from dmf_pulse.prices.models import (
    ChipContaminationState,
    EarlyTransferAction,
    EarlyTransferAlternative,
    FeatureValue,
    ObservationKind,
    PriceEvent,
    PriceFeatureVector,
    PriceObservation,
    PriceProjection,
    PriceStatus,
    PriceTrainingExample,
    TransferFlowContext,
    UtilityComponents,
)
from dmf_pulse.prices.service import predict_price

BASE = datetime(2026, 8, 1, 12, tzinfo=UTC)
ZERO = "0" * 64


@lru_cache
def config() -> PriceConfig:
    return load_price_config()


def observation(
    observation_id: str,
    *,
    hour: int,
    price: int = 75,
    gameweek: int = 1,
    transfers_in_total: int = 1000,
    transfers_out_total: int = 500,
    transfers_in_event: int | None = None,
    transfers_out_event: int | None = None,
    ownership: str = "10.0",
    received_delay: int = 0,
    usable_delay: int | None = None,
    status: PriceStatus = PriceStatus.AVAILABLE,
    kind: ObservationKind = ObservationKind.ORDINARY,
    supersedes: str | None = None,
    dataset_mode: DatasetMode = DatasetMode.RECONSTRUCTED,
) -> PriceObservation:
    observed_at = BASE + timedelta(hours=hour)
    received_at = observed_at + timedelta(hours=received_delay)
    usable_at = received_at + timedelta(hours=usable_delay or 0)
    value = PriceObservation(
        observation_id=observation_id,
        player_id="player-1",
        season="2026-27",
        gameweek=gameweek,
        source_snapshot_id=f"snapshot-{observation_id}",
        observed_at=observed_at,
        received_at=received_at,
        usable_at=usable_at,
        current_price_units=price,
        ownership_percent=Decimal(ownership),
        transfers_in_total=transfers_in_total,
        transfers_out_total=transfers_out_total,
        transfers_in_event=(
            transfers_in_total if transfers_in_event is None else transfers_in_event
        ),
        transfers_out_event=(
            transfers_out_total if transfers_out_event is None else transfers_out_event
        ),
        player_status=status,
        status_observed_at=observed_at,
        source="synthetic-test",
        rights_profile_id="SYNTHETIC-TEST-ONLY",
        dataset_mode=dataset_mode,
        payload_hash=semantic_sha256({"synthetic_payload_id": observation_id}),
        semantic_hash=ZERO,
        observation_kind=kind,
        supersedes_observation_id=supersedes,
    )
    return seal_observation(value)


def flow_context(**updates: object) -> TransferFlowContext:
    payload: dict[str, object] = {
        "active_manager_count": 10_000_000,
        "global_transfer_activity": 1_000_000,
        "previous_event": PriceEvent.NO_CHANGE,
        "hours_since_last_rise": "48",
        "hours_since_last_fall": "72",
        "hours_since_any_change": "48",
        "net_since_deadline": 400,
        "net_since_last_rise": 500,
        "net_since_last_fall": 900,
        "net_since_any_change": 500,
        "hours_since_deadline": "24",
        "hours_to_next_deadline": "96",
        "player_match_complete": True,
        "chip_contamination": ChipContaminationState.LOW,
        "chip_contamination_confidence": "0.9",
    }
    payload.update(updates)
    return TransferFlowContext.model_validate(payload)


def vector(
    vector_id: str,
    *,
    at: datetime = BASE,
    sign: int = 0,
) -> PriceFeatureVector:
    values = tuple(
        FeatureValue(
            name=name,
            value=Decimal(sign) * Decimal(index + 1) / Decimal(100),
        )
        for index, name in enumerate(config().competing_logit.feature_names)
    )
    return PriceFeatureVector(
        vector_id=vector_id,
        player_id="player-1",
        information_cutoff=at,
        values=values,
    )


@lru_cache
def fitted_model():
    events = (
        PriceEvent.FALL,
        PriceEvent.NO_CHANGE,
        PriceEvent.RISE,
        PriceEvent.FALL,
        PriceEvent.NO_CHANGE,
        PriceEvent.RISE,
    )
    examples = tuple(
        PriceTrainingExample(
            example_id=f"example-{index}",
            feature_vector=vector(
                f"training-vector-{index}",
                at=BASE - timedelta(days=10 - index),
                sign=(-1 if event is PriceEvent.FALL else 1 if event is PriceEvent.RISE else 0),
            ),
            event=event,
            label_available_at=BASE - timedelta(days=10 - index, hours=-1),
            dataset_mode=DatasetMode.RECONSTRUCTED,
        )
        for index, event in enumerate(events)
    )
    return fit_competing_logit(
        examples,
        training_cutoff=BASE - timedelta(days=3),
        config=config(),
    )


@lru_cache
def projection() -> PriceProjection:
    state = initial_latent_pressure(
        state_id="state-1",
        player_id="player-1",
        as_of=BASE,
        config=config(),
    )
    return predict_price(
        player_id="player-1",
        current_price_units=75,
        feature_vector=vector("projection-vector"),
        model=fitted_model(),
        pressure_state=state,
        source_observation_ids=("observation-1",),
        source_semantic_hashes=(ZERO,),
        ruleset_id="synthetic-rules",
        ruleset_hash=ZERO,
        dataset_mode=DatasetMode.RECONSTRUCTED,
        config=config(),
    )


def spell(*, purchase: int = 50, current: int = 55, spell_id: str = "spell-1") -> OwnershipSpell:
    return OwnershipSpell(
        spell_id=spell_id,
        player_id="player-1",
        club_id="club-1",
        position=PlayerPosition.MID,
        purchase_price_tenths=purchase,
        current_price_tenths=current,
        started_gameweek=1,
        started_at_node_id="root",
    )


def selling_rule() -> SellingPriceRule:
    return SellingPriceRule(
        rule_id="synthetic-half-profit",
        retained_profit_numerator=1,
        retained_profit_denominator=2,
    )


def alternative(
    action: EarlyTransferAction,
    utility: str,
    *,
    route_id: str | None = None,
    information_value: str = "0",
    free_transfer_value: str = "0",
    hit: str = "0",
) -> EarlyTransferAlternative:
    return EarlyTransferAlternative(
        action=action,
        route_id=route_id or action.value.lower(),
        components=UtilityComponents(
            football_expected_value=Decimal(utility),
            affordability_route_value=Decimal(0),
            price_scenario_value=Decimal(0),
            outgoing_selling_value_risk=Decimal(0),
            free_transfer_value=Decimal(free_transfer_value),
            future_recourse_value=Decimal(0),
            information_value=Decimal(information_value),
            transfer_hit_cost=Decimal(hit),
            injury_rotation_cost=Decimal(0),
            reversal_cost=Decimal(0),
            lost_purchase_position_cost=Decimal(0),
            execution_risk_cost=Decimal(0),
        ),
    )
