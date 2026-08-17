"""Rules-owned transfer-state view for OPT-011 multi-Gameweek optimisation.

The optimiser consumes this immutable, typed projection of a compiled schema-v1.1
ruleset.  Season constants remain in governed rules artifacts rather than solver code.
"""

from __future__ import annotations

from typing import Any

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.multi_gameweek_models import (
    FreeTransferEventRule,
    SellingPriceRule,
    TransferRules,
)
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
    RulesetStatus,
)
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

_ACCOUNTING_ORDER = (
    "SELL_OUTGOING_AT_SELLING_PRICE",
    "BUY_INCOMING_AT_CURRENT_PRICE",
    "CONSUME_FREE_TRANSFERS",
    "APPLY_TRANSFER_HITS",
    "EARN_NEXT_DEADLINE_TRANSFER",
    "CAP_FREE_TRANSFERS",
)


def _plain(value: Any, path: str) -> Any:
    if isinstance(value, dict) and value.get("verification_status") in {
        "UNKNOWN",
        "CONFLICTED",
    }:
        raise RulesValidationError(
            "RULESET_VALUE_UNRESOLVED", f"required value is unresolved: {path}"
        )
    if isinstance(value, dict) and set(value) >= {"value", "verification_status"}:
        resolved = value.get("value")
        if resolved is None:
            raise RulesValidationError(
                "RULESET_VALUE_UNRESOLVED", f"required value is unresolved: {path}"
            )
        return resolved
    return value


def _mapping(rules: dict[str, Any], path: str) -> dict[str, Any]:
    value: Any = rules
    for token in path.strip("/").split("/"):
        if not isinstance(value, dict) or token not in value:
            raise RulesValidationError(
                "RULESET_VALUE_MISSING", f"required value is absent: /rules/{path}"
            )
        value = value[token]
    value = _plain(value, f"/rules/{path}")
    if not isinstance(value, dict):
        raise RulesValidationError(
            "RULESET_VALUE_INVALID", f"required mapping is invalid: /rules/{path}"
        )
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    value = _plain(value, path)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RulesValidationError("RULESET_VALUE_INVALID", f"required integer is invalid: {path}")
    return int(value)


def _literal(value: Any, expected: object, path: str) -> None:
    value = _plain(value, path)
    if value != expected:
        raise RulesValidationError(
            "RULESET_VALUE_INVALID",
            f"required controlled value is invalid: {path}; expected {expected!r}",
        )


def _validate_production_capability(
    compiled: CompiledRuleset,
    capability: CapabilityArtifact | None,
) -> CapabilityArtifact:
    if (
        compiled.status is not RulesetStatus.ACTIVE
        or not compiled.production_eligible
        or capability is None
        or capability.capability is not RuleCapability.FULL_SEASON
    ):
        raise RulesValidationError(
            "TRANSFER_STATE_CAPABILITY_UNAVAILABLE",
            "production transfer optimisation requires an active source-backed "
            "FULL_SEASON capability artifact",
        )
    expected = compile_capability_artifact(compiled, RuleCapability.FULL_SEASON)
    if (
        capability.model_dump(mode="json") != expected.model_dump(mode="json")
        or not expected.source_backed
        or not expected.production_eligible
        or expected.blockers
    ):
        raise RulesValidationError(
            "TRANSFER_STATE_CAPABILITY_UNAVAILABLE",
            "FULL_SEASON capability does not match the compiled ruleset",
        )
    return expected


def build_multi_gameweek_transfer_rules(
    compiled: CompiledRuleset,
    *,
    projection_mode: ProjectionMode,
    capability: CapabilityArtifact | None = None,
) -> TransferRules:
    """Resolve exact price, squad and transfer transitions from compiled rules."""

    if compiled.schema_version != "1.1":
        raise RulesValidationError(
            "TRANSFER_STATE_SCHEMA_UNSUPPORTED",
            "multi-Gameweek transfer optimisation requires compiled schema 1.1",
        )
    production_capability: CapabilityArtifact | None = None
    if projection_mode is ProjectionMode.PRODUCTION:
        production_capability = _validate_production_capability(compiled, capability)
    elif compiled.status not in {
        RulesetStatus.REFERENCE_ONLY,
        RulesetStatus.VERIFIED,
        RulesetStatus.ACTIVE,
    }:
        raise RulesValidationError(
            "TRANSFER_STATE_CAPABILITY_UNAVAILABLE",
            "test/replay transfer optimisation requires a complete reference or verified ruleset",
        )

    tactical = build_one_gameweek_rules_view(
        compiled,
        projection_mode=projection_mode,
        capability=(capability if projection_mode is ProjectionMode.PRODUCTION else None),
    )
    transfers = _mapping(compiled.rules, "transfers/transition")
    prices = _mapping(compiled.rules, "prices")
    selling = _mapping(compiled.rules, "prices/selling_price")
    above = _plain(selling.get("above_purchase"), "/rules/prices/selling_price/above_purchase")
    below = _plain(
        selling.get("at_or_below_purchase"),
        "/rules/prices/selling_price/at_or_below_purchase",
    )
    if not isinstance(above, dict) or not isinstance(below, dict):
        raise RulesValidationError(
            "RULESET_VALUE_INVALID", "selling-price branches must be mappings"
        )

    _literal(prices.get("price_unit"), "TENTHS_OF_MILLION_GBP", "/rules/prices/price_unit")
    _literal(prices.get("integer_only"), True, "/rules/prices/integer_only")
    _literal(
        prices.get("initial_purchase_price_basis"),
        "CURRENT_PLAYER_PRICE_AT_INITIAL_SELECTION",
        "/rules/prices/initial_purchase_price_basis",
    )
    _literal(
        prices.get("current_purchase_price_basis"),
        "PRICE_PAID_FOR_CURRENT_OWNERSHIP",
        "/rules/prices/current_purchase_price_basis",
    )
    _literal(
        above.get("condition"),
        "CURRENT_ABOVE_PURCHASE",
        "/rules/prices/selling_price/above_purchase/condition",
    )
    _literal(
        above.get("formula"),
        "PURCHASE_PLUS_FLOOR_HALF_PROFIT",
        "/rules/prices/selling_price/above_purchase/formula",
    )
    _literal(
        below.get("condition"),
        "CURRENT_AT_OR_BELOW_PURCHASE",
        "/rules/prices/selling_price/at_or_below_purchase/condition",
    )
    _literal(
        below.get("formula"),
        "CURRENT_PRICE",
        "/rules/prices/selling_price/at_or_below_purchase/formula",
    )
    _literal(
        transfers.get("outgoing_and_incoming_same_position"),
        True,
        "/rules/transfers/transition/outgoing_and_incoming_same_position",
    )
    _literal(
        transfers.get("club_quota_repair_required"),
        True,
        "/rules/transfers/transition/club_quota_repair_required",
    )
    order = _plain(
        transfers.get("transfer_accounting_order"),
        "/rules/transfers/transition/transfer_accounting_order",
    )
    if not isinstance(order, list | tuple) or tuple(order) != _ACCOUNTING_ORDER:
        raise RulesValidationError(
            "RULESET_VALUE_INVALID",
            "transfer accounting order is unsupported or incomplete",
        )

    free_transfer_cap = _integer(
        transfers.get("free_transfer_cap"),
        "/rules/transfers/transition/free_transfer_cap",
        minimum=1,
    )
    earned = _integer(
        transfers.get("earned_per_deadline"),
        "/rules/transfers/transition/earned_per_deadline",
    )
    hit_points = _integer(
        transfers.get("hit_points"),
        "/rules/transfers/transition/hit_points",
        minimum=-1000,
    )
    if hit_points >= 0:
        raise RulesValidationError(
            "RULESET_VALUE_INVALID",
            "configured transfer hit_points must be a negative scoring adjustment",
        )
    preseason_unlimited = _plain(
        transfers.get("preseason_unlimited"),
        "/rules/transfers/transition/preseason_unlimited",
    )
    if not isinstance(preseason_unlimited, bool):
        raise RulesValidationError("RULESET_VALUE_INVALID", "preseason_unlimited must be boolean")

    events: dict[str, FreeTransferEventRule] = {
        "NORMAL": FreeTransferEventRule(
            earn_for_next_deadline=earned,
            carry_unused=True,
            cap_after=free_transfer_cap,
        )
    }
    if preseason_unlimited:
        events["PRESEASON"] = FreeTransferEventRule(
            unlimited_transfers_without_hits=True,
            reset_before=0,
            earn_for_next_deadline=earned,
            carry_unused=False,
            cap_after=free_transfer_cap,
        )

    if tactical.max_players_per_club is None:
        raise RulesValidationError(
            "RULESET_VALUE_MISSING",
            "multi-Gameweek transfer rules require a configured club maximum",
        )

    return TransferRules(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        projection_mode=projection_mode,
        capability=(
            RuleCapability.FULL_SEASON.value
            if production_capability is not None
            else "REFERENCE_ONLY"
        ),
        capability_hash=(
            production_capability.capability_hash if production_capability is not None else None
        ),
        squad_size=tactical.squad_size,
        position_squad_quota=tactical.position_squad_quota,
        max_players_per_club=tactical.max_players_per_club,
        maximum_free_transfers=free_transfer_cap,
        hit_cost_per_paid_transfer=abs(hit_points),
        max_transfers_per_deadline=tactical.squad_size,
        selling_price_rule=SellingPriceRule(
            rule_id="PURCHASE_PLUS_FLOOR_HALF_PROFIT_OR_CURRENT_LOSS",
            retained_profit_numerator=1,
            retained_profit_denominator=2,
        ),
        event_rules=events,
    )
