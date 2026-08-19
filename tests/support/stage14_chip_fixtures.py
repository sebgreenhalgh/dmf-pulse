from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ChipDefinition,
    ChipEffect,
    InventoryGrant,
    semantic_sha256,
)
from dmf_pulse.chips.inventory import ChipInventory, build_chip_inventory
from dmf_pulse.chips.schedule_models import (
    ChipScheduleOpportunity,
    ChipScheduleRequest,
    OpportunityLineage,
    OpportunitySourceKind,
    ScheduleObjectiveConfig,
    ScheduleScenarioIdentity,
    ScheduleScenarioValue,
    scenario_set_hash,
    seal_opportunity,
    seal_schedule_request,
)
from dmf_pulse.chips.service import seal_chip_service_request
from dmf_pulse.chips.service_models import ChipServiceRequest
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import (
    DatasetMode,
    FeatureRecord,
    ObservationKind,
    ObservationRole,
    OperationalUsability,
)
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.prices.models import ConfidenceGrade

NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)
RULESET_HASH = "1" * 64
SOURCE_HASH = "2" * 64
CONFIG_HASH = "3" * 64
MANAGER_HASH = "4" * 64
PRICE_HASH = "5" * 64


def stage12_feature_records(
    *,
    now: datetime,
    include_price: bool,
    gameweek: int = 1,
) -> tuple[FeatureRecord, ...]:
    observed = now - timedelta(minutes=5)

    def record(
        record_id: str,
        kind: ObservationKind,
        *,
        role: ObservationRole = ObservationRole.FEATURE,
        values: dict[str, object] | None = None,
    ) -> FeatureRecord:
        return FeatureRecord(
            record_id=record_id,
            entity_id="manager-synthetic",
            target_id=f"GW{gameweek}",
            gameweek=gameweek,
            dataset_mode=DatasetMode.LIVE_OBSERVED,
            operational_usability=OperationalUsability.LIVE_OPERATIONAL,
            role=role,
            kind=kind,
            source_timestamp=observed,
            received_at=observed,
            mapped_at=observed,
            usable_at=observed,
            valid_from=observed,
            current_vintage=False,
            feature_intended=True,
            values=values or {"status": "FROZEN"},
            source_snapshot_id=f"snapshot:{record_id}",
            mapping_version_id="mapping:v1",
        )

    records = [
        record("fixture-assignment", ObservationKind.FIXTURE_ASSIGNMENT),
        record("injury-evidence", ObservationKind.OTHER, values={"category": "INJURY"}),
        record("lineup-evidence", ObservationKind.LINEUP),
        record(
            "manager-state",
            ObservationKind.MANAGER_STATE,
            role=ObservationRole.MANAGER_STATE,
        ),
        record("points-scenarios", ObservationKind.PULSE_PROJECTION),
    ]
    if include_price:
        records.append(record("price-scenarios", ObservationKind.PRICE))
    return tuple(sorted(records, key=lambda item: item.record_id))


def chip_definition(
    key: str,
    *,
    start: int = 1,
    end: int = 5,
    copies: int = 1,
    duration: int = 1,
) -> ChipDefinition:
    return ChipDefinition(
        chip_key=key,
        definition_version=f"SYNTHETIC:{key}:V1",
        grants=(
            InventoryGrant(
                grant_id="window",
                copies=copies,
                acquired_gameweek=start,
                activation_start_gameweek=start,
                activation_end_gameweek=end,
                expires_after_gameweek=end,
            ),
        ),
        duration_gameweeks=duration,
        concurrency_group="FPL_CHIP",
        activation_route=ActivationRoute.PICK_TEAM_SAVE,
        cancellable_before_lock=True,
        effects=(
            ChipEffect(
                surface="SCORING",
                operation="ADD_POINTS",
                parameters={"points": 1},
            ),
        ),
    )


def synthetic_bundle(
    keys: Iterable[str] = ("TRIPLE_CAPTAIN",),
    *,
    activation_end_gameweek: int = 5,
):
    return compile_synthetic_bundle(
        ruleset_id="SYNTHETIC-CHIP-RULESET",
        ruleset_version="1.0",
        ruleset_hash=RULESET_HASH,
        concurrency_limit=1,
        definitions=tuple(chip_definition(key, end=activation_end_gameweek) for key in keys),
    )


def scenario_universe() -> tuple[ScheduleScenarioIdentity, ...]:
    return (
        ScheduleScenarioIdentity(scenario_id="S1", outcome_draw_id="D1", weight=0.5),
        ScheduleScenarioIdentity(scenario_id="S2", outcome_draw_id="D2", weight=0.5),
    )


def schedule_opportunity(
    inventory: ChipInventory,
    *,
    token_id: str,
    gameweek: int,
    values: tuple[float, float],
    now: datetime,
    opportunity_id: str | None = None,
    continuation: tuple[float, float] = (0.0, 0.0),
    policy_cost: tuple[float, float] = (0.0, 0.0),
    usable_at: datetime | None = None,
    source_kind: OpportunitySourceKind = OpportunitySourceKind.FORECAST,
) -> ChipScheduleOpportunity:
    scenarios = scenario_universe()
    scenario_hash = scenario_set_hash(scenarios)
    token = inventory.token(token_id)
    scenario_values = tuple(
        ScheduleScenarioValue(
            scenario_id=scenario.scenario_id,
            outcome_draw_id=scenario.outcome_draw_id,
            weight=scenario.weight,
            gross_current_gain=values[index],
            continuation_value=continuation[index],
            policy_cost=policy_cost[index],
            net_policy_value=(values[index] + continuation[index] - policy_cost[index]),
        )
        for index, scenario in enumerate(scenarios)
    )
    identifier = opportunity_id or f"{token.chip_key.lower()}-{gameweek}"
    value = ChipScheduleOpportunity(
        opportunity_id=identifier,
        candidate_history_key=f"history:{identifier}",
        token_id=token.token_id,
        chip_key=token.chip_key,
        activation_gameweek=gameweek,
        duration_gameweeks=token.duration_gameweeks,
        scenario_values=scenario_values,
        expected_gross_current_gain=sum(
            item.weight * item.gross_current_gain for item in scenario_values
        ),
        expected_continuation_value=sum(
            item.weight * item.continuation_value for item in scenario_values
        ),
        expected_policy_cost=sum(item.weight * item.policy_cost for item in scenario_values),
        expected_net_policy_value=sum(
            item.weight * item.net_policy_value for item in scenario_values
        ),
        expected_cash_like_value=0.0,
        expected_terminal_state_value=0.0,
        optimistic_upper_bound=max(item.net_policy_value for item in scenario_values),
        lineage=OpportunityLineage(
            forecast_origin=now,
            information_cutoff=now,
            usable_at=usable_at or now,
            decision_cutoff=now + timedelta(days=max(1, gameweek) * 7),
            source_kind=source_kind,
            source_artifact_hash=SOURCE_HASH,
            scenario_set_hash=scenario_hash,
            model_version="SYNTHETIC-OPPORTUNITY-V1",
            configuration_hash=CONFIG_HASH,
            code_commit="eea9591282c2147ad674b35e7c8e2c328a20c68a",
        ),
        opportunity_hash="0" * 64,
    )
    return seal_opportunity(value)


def service_request(
    *,
    keys: tuple[str, ...] = ("TRIPLE_CAPTAIN",),
    inventory: ChipInventory | None = None,
    gameweek: int = 1,
    current_values: dict[str, tuple[float, float]] | None = None,
    future_values: dict[str, tuple[float, float]] | None = None,
    now: datetime = NOW,
    price_statuses: tuple[PriceActivationStatus, ...] = (),
    confidence: ConfidenceGrade = ConfidenceGrade.B,
    activation_end_gameweek: int = 5,
) -> ChipServiceRequest:
    bundle = synthetic_bundle(
        keys,
        activation_end_gameweek=activation_end_gameweek,
    )
    current_inventory = inventory or build_chip_inventory(bundle, current_gameweek=gameweek)
    if current_inventory.bundle_hash != bundle.bundle_hash:
        # Replay callers pass an inventory minted from an equivalent bundle.  Keep
        # the exact bundle object associated with that inventory by rebuilding no
        # semantic state; hashes are the authority.
        raise ValueError("fixture inventory bundle differs from requested keys")
    if current_values is None:
        current_values = {key: (4.0, 3.0) for key in keys}
    if future_values is None:
        future_values = {key: (2.0, 2.0) for key in keys}
    opportunities: list[ChipScheduleOpportunity] = []
    for token in current_inventory.tokens:
        if token.chip_key not in current_values:
            continue
        opportunities.append(
            schedule_opportunity(
                current_inventory,
                token_id=token.token_id,
                gameweek=gameweek,
                values=current_values[token.chip_key],
                now=now,
                opportunity_id=f"{token.chip_key.lower()}-{gameweek}-current",
            )
        )
        if gameweek < token.activation_end_gameweek:
            opportunities.append(
                schedule_opportunity(
                    current_inventory,
                    token_id=token.token_id,
                    gameweek=gameweek + 1,
                    values=future_values[token.chip_key],
                    now=now,
                    opportunity_id=f"{token.chip_key.lower()}-{gameweek + 1}-future",
                )
            )
    scenarios = scenario_universe()
    objective = ScheduleObjectiveConfig(config_version="SYNTHETIC-SCHEDULE-V1")
    schedule = seal_schedule_request(
        ChipScheduleRequest(
            request_id=f"schedule-gw{gameweek}",
            inventory=current_inventory,
            horizon_start_gameweek=gameweek,
            horizon_end_gameweek=min(activation_end_gameweek, gameweek + 1),
            information_cutoff=now,
            scenario_universe=scenarios,
            scenario_set_hash=scenario_set_hash(scenarios),
            opportunities=tuple(
                sorted(
                    opportunities,
                    key=lambda item: (
                        item.activation_gameweek,
                        item.chip_key,
                        item.token_id,
                        item.opportunity_id,
                    ),
                )
            ),
            objective=objective,
            request_hash="0" * 64,
        )
    )
    request = ChipServiceRequest(
        request_id=f"service-gw{gameweek}",
        decision_id=f"chip-decision-gw{gameweek}",
        manager_state_id="manager-synthetic",
        manager_state_hash=MANAGER_HASH,
        forecast_origin=now,
        information_cutoff=now,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        feature_records=(
            records := stage12_feature_records(
                now=now,
                include_price=bool(price_statuses),
                gameweek=gameweek,
            )
        ),
        leakage_report=scan_for_leakage(
            records,
            forecast_origin=now,
            dataset_mode=DatasetMode.LIVE_OBSERVED,
        ),
        chip_bundle=bundle,
        inventory=current_inventory,
        schedule_request=schedule,
        confidence=confidence,
        price_input_hash=PRICE_HASH if price_statuses else None,
        price_activation_statuses=tuple(sorted(price_statuses, key=lambda item: item.value)),
        continuation_model_version="SYNTHETIC-CONTINUATION-V1",
        continuation_configuration_hash=semantic_sha256(objective),
        code_commit="eea9591282c2147ad674b35e7c8e2c328a20c68a",
        random_seed=42,
        service_request_hash="0" * 64,
    )
    return seal_chip_service_request(request)


def write_service_request(path: Path, request: ChipServiceRequest) -> None:
    path.write_text(
        request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
