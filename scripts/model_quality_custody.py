"""Opt-in MQ003 orchestration of existing qualified forecast/label custody.

No prediction is reconstructed from a warehouse view, missing fields invented,
registry changed or database opened at import. Callers supply complete original
PlayerForecast artifacts and an already registered deadline population. Actual
source/intent and server-clock authority stay in the existing research ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.player_lab.contracts import FinalPlayerOutcome, PlayerForecast
from dmf_pulse.player_lab.real import (
    RealDeadlineRegistration,
    RealPlayerProtocol,
    RealPointFreeze,
    adapt_qualified_full_forecast,
)
from dmf_pulse.player_lab.real_rights import (
    require_real_outcome,
    require_real_population,
    require_real_sources,
)
from dmf_pulse.player_lab.store import PostgresResearchLedger

CONTRACT_VERSION = "MQ003_EXISTING_LEDGER_COMPLETE_POPULATION_V1"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CaptureReceipt:
    contract_version: str
    kind: str
    protocol_sha256: str
    population_registration_sha256: str
    original_artifact_sha256s: tuple[str, ...]
    ledger_artifact_sha256s: tuple[str, ...]


class IncompleteCaptureError(Exception):
    """Some earlier calls committed; the attempted cell needs ledger reconciliation."""

    def __init__(
        self,
        completed_sha256s: tuple[str, ...],
        attempted_id: str,
        model_id: str | None = None,
        *,
        exception_family: str | None = None,
        interrupted: bool = False,
    ):
        super().__init__("MQ003_CAPTURE_INCOMPLETE_RECONCILE_LEDGER")
        self.completed_sha256s = completed_sha256s
        self.attempted_id = attempted_id
        self.attempted_model_id = model_id
        self.attempted_outcome = "UNKNOWN_RECONCILE_EXISTING_LEDGER"
        self.exception_family = exception_family
        self.interrupted = interrupted


def freeze_full_population(
    ledger: PostgresResearchLedger,
    protocol: RealPlayerProtocol,
    registration: RealDeadlineRegistration,
    originals: tuple[PlayerForecast, ...],
) -> CaptureReceipt:
    """Validate ALL expected original model/player cells before the first write.

    Existing per-forecast transactions remain authoritative; this is not an
    atomic batch. A failed/uncertain call raises with completed hashes and its
    attempted cell. Never retry blindly, backdate, delete or call partial PASS.
    """
    from dmf_pulse.player_lab.real_store import _require_intent

    now = _now()
    protocol = RealPlayerProtocol.model_validate_json(protocol.model_dump_json())
    registration = RealDeadlineRegistration.model_validate_json(registration.model_dump_json())
    require_real_sources(protocol.sources, now=now)
    _require_intent(protocol, now)
    population = registration.population
    require_real_population(
        population.catalogue_source,
        canonical_sha256(population.model_dump(mode="json")),
        now=now,
    )
    if (
        protocol.evaluation_classification != "PREREGISTERED_PROSPECTIVE"
        or registration.custody != "DATABASE_PREDEADLINE"
        or registration.protocol_sha256 != protocol.semantic_sha256
        or population.gameweek not in protocol.gameweeks
        or population.targets[0].season != protocol.season
        or not protocol.registered_at <= registration.registered_at <= now < population.deadline_at
    ):
        raise ValueError("MQ003_NATIVE_PREREGISTERED_PREDEADLINE_BINDING_REQUIRED")
    originals = tuple(PlayerForecast.model_validate_json(x.model_dump_json()) for x in originals)
    expected = {
        (key.target_id(), model) for key in population.targets for model in protocol.model_ids
    }
    cells = tuple((value.key.target_id(), value.model_id) for value in originals)
    if len(cells) != len(set(cells)) or set(cells) != expected:
        raise ValueError("MQ003_COMPLETE_UNIQUE_ORIGINAL_POPULATION_REQUIRED")
    bindings = {row.model_id: row for row in protocol.model_bindings}
    adapted = []
    for value in sorted(originals, key=lambda x: (x.key.target_id(), x.model_id)):
        binding = bindings[value.model_id]
        if (
            value.dataset_mode != "PROSPECTIVE_REAL"
            or value.deadline_at != population.deadline_at
            or value.generated_at > now
            or value.code_sha != binding.code_sha
            or value.model_version_ids != binding.model_version_ids
            or value.ruleset_sha256 != binding.ruleset_sha256
        ):
            raise ValueError("MQ003_ORIGINAL_TIME_MODEL_RULES_BINDING_REQUIRED")
        adapted.append(
            adapt_qualified_full_forecast(
                value, information_grade=protocol.information_grade, now=now
            )
        )
    completed = []
    for value in adapted:
        try:
            frozen = ledger.freeze_real_forecast(
                protocol.semantic_sha256, registration.semantic_sha256, value
            )
            frozen = RealPointFreeze.model_validate_json(frozen.model_dump_json())
            if (
                frozen.forecast != value
                or frozen.population_registration_sha256 != registration.semantic_sha256
                or frozen.custody != "DATABASE_PREDEADLINE"
            ):
                raise ValueError("MQ003_LEDGER_RESPONSE_BINDING_INVALID")
        except BaseException as error:
            raise IncompleteCaptureError(
                tuple(completed),
                value.key.target_id(),
                value.model_id,
                exception_family=type(error).__name__,
                interrupted=isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)),
            ) from None
        completed.append(frozen.semantic_sha256)
    return CaptureReceipt(
        CONTRACT_VERSION,
        "COMPLETE_ORIGINAL_FORECAST_POPULATION",
        protocol.semantic_sha256,
        registration.semantic_sha256,
        tuple(x.original_full_forecast.semantic_sha256 for x in adapted),
        tuple(completed),
    )


def main() -> None:
    """Report current package qualification counts without ledger/provider access."""
    import argparse
    import json

    from dmf_pulse.player_lab.real_rights import real_source_registry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", action="store_true")
    args = parser.parse_args()
    if not args.readiness:
        parser.error("explicit read-only --readiness required")
    registry = real_source_registry()
    blocked = not registry.sources or not registry.accepted_protocol_intents
    print(
        json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "status": "BLOCKED_REAL_AUTHORITY_NOT_INSTALLED"
                if blocked
                else "EXACT_PROTOCOL_POPULATION_FORECAST_CHECKS_STILL_REQUIRED",
                "package_qualified_source_count": len(registry.sources),
                "package_accepted_intent_count": len(registry.accepted_protocol_intents),
                "database_or_provider_access": False,
                "matched_finalized_pairs": "NOT_QUERIED",
                "predictive_skill_or_promotion_claim": False,
            },
            sort_keys=True,
        )
    )
    raise SystemExit(2 if blocked else 1)


def append_finalized_population(
    ledger: PostgresResearchLedger,
    registration: RealDeadlineRegistration,
    labels: tuple[FinalPlayerOutcome, ...],
) -> CaptureReceipt:
    """Append one explicit qualified final revision per expected target; never fill gaps."""
    now = _now()
    registration = RealDeadlineRegistration.model_validate_json(registration.model_dump_json())
    labels = tuple(FinalPlayerOutcome.model_validate_json(x.model_dump_json()) for x in labels)
    expected = {key.target_id() for key in registration.population.targets}
    actual = tuple(label.key.target_id() for label in labels)
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("MQ003_COMPLETE_UNIQUE_FINAL_LABEL_POPULATION_REQUIRED")
    for label in labels:
        require_real_outcome(label, now=now)
        if label.usable_at > now or label.finalized_at > now:
            raise ValueError("MQ003_LABEL_NOT_AVAILABLE_OR_FINALIZED")
    ordered = sorted(labels, key=lambda x: x.key.target_id())
    completed = []
    for label in ordered:
        try:
            digest = ledger.append_real_label(label)
            if digest != label.semantic_sha256:
                raise ValueError("MQ003_LABEL_LEDGER_RESPONSE_BINDING_INVALID")
        except BaseException as error:
            raise IncompleteCaptureError(
                tuple(completed),
                label.key.target_id(),
                exception_family=type(error).__name__,
                interrupted=isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)),
            ) from None
        completed.append(digest)
    return CaptureReceipt(
        CONTRACT_VERSION,
        "COMPLETE_EXPLICIT_FINAL_LABEL_POPULATION",
        registration.protocol_sha256,
        registration.semantic_sha256,
        tuple(x.semantic_sha256 for x in ordered),
        tuple(completed),
    )


if __name__ == "__main__":
    main()
