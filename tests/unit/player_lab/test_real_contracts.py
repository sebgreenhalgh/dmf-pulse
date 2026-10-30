"""Real branches use owned invented engineering inputs, never actual performance."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.operation.models import OperationError
from dmf_pulse.player_lab import real_rights as rights
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.real import RealDeadlineRegistration, RealPointFreeze, real_coverage
from dmf_pulse.player_lab.store import PostgresResearchLedger
from tests.unit.player_lab.real_support import AT, owned_case, owned_full, reseal

pytestmark = pytest.mark.unit


def test_full_adapter_preserves_original_without_inventing_missing_features(monkeypatch):
    from dmf_pulse.player_lab.real import adapt_qualified_full_forecast

    _, _, forecasts, _, registry = owned_case()
    monkeypatch.setattr(rights, "real_source_registry", lambda: registry)
    original = owned_full(forecasts[0])
    adapted = adapt_qualified_full_forecast(original, information_grade="RAW_OBSERVED", now=AT)
    assert adapted.original_full_forecast == original
    assert adapted.stage12.point_forecast == original.mean
    assert adapted.stage12.pmf == {str(key): value for key, value in original.pmf.items()}
    assert adapted.expected_minutes == 60 and adapted.stage12.dataset_mode.value == "RAW_OBSERVED"
    assert original.semantic_sha256 == adapted.original_full_forecast.semantic_sha256


def test_real_registry_empty_and_rights_fail_before_engine():
    protocol, populations, forecasts, labels, _ = owned_case()
    assert not rights.real_source_registry().sources
    ledger = PostgresResearchLedger(lambda: pytest.fail("unqualified database access"))
    calls = (
        lambda: ledger.register_real_protocol(protocol),
        lambda: ledger.register_real_population(protocol.semantic_sha256, populations[0]),
        lambda: ledger.freeze_real_forecast(protocol.semantic_sha256, "a" * 64, forecasts[0]),
        lambda: ledger.append_real_label(labels[0]),
        lambda: ledger.evaluate_real(
            protocol.semantic_sha256,
            "owned-point",
            expected_sources=protocol.sources,
            label_sha256s=tuple(row.semantic_sha256 for row in labels),
        ),
    )
    for call in calls:
        with pytest.raises(OperationError, match="SOURCE_NOT_QUALIFIED"):
            call()


@pytest.mark.parametrize(
    "changes",
    [
        {"registered_at": AT + timedelta(days=30)},
        {"source_manifest_sha256": "a" * 64},
        {"benchmark_definitions_sha256": "a" * 64},
        {"inner_gameweeks": (10,), "holdout_gameweeks": (9,)},
        {"gameweeks": (10, 9)},
    ],
)
def test_prospective_protocol_rejects_late_or_changed_bindings(changes):
    protocol, *_ = owned_case(prospective=True)
    with pytest.raises(ValidationError):
        reseal(protocol, **changes)


def test_point_only_preserves_absence_and_rejects_inner_seal_repair():
    _, _, forecasts, *_ = owned_case()
    point = forecasts[0]
    assert (
        not point.stage12.pmf
        and point.original_full_forecast is None
        and point.expected_minutes is None
    )
    with pytest.raises(EvaluationError, match="does not match"):
        reseal(point, stage12=point.stage12.model_copy(update={"forecast_sha256": "a" * 64}))


def test_retention_and_duplicate_authority_denied(monkeypatch):
    _, _, _, labels, registry = owned_case()
    monkeypatch.setattr(rights, "real_source_registry", lambda: registry)
    rights.require_real_outcome(labels[0], now=AT)
    altered = reseal(
        labels[0],
        total_points=3,
        components={**labels[0].components, next(iter(labels[0].components)): 3},
    )
    with pytest.raises(OperationError, match="VALUES_NOT_QUALIFIED"):
        rights.require_real_outcome(altered, now=AT)
    row = registry.sources[0]
    profile = row.profile.model_copy(update={"retention_seconds": 0})
    from dmf_pulse.player_lab.rights import profile_identity

    source = row.source.model_copy(update={"profile_sha256": profile_identity(profile)})
    replacement = row.model_copy(update={"profile": profile, "source": source})
    monkeypatch.setattr(
        rights,
        "real_source_registry",
        lambda: registry.model_copy(update={"sources": (replacement,)}),
    )
    with pytest.raises(OperationError, match="IMMUTABLE_RETENTION"):
        rights.require_real_sources((source,), now=AT)
    with pytest.raises(ValidationError):
        type(registry)(sources=(row, row))


def test_coverage_counts_all_targets_and_unregistered_deadlines():
    protocol, populations, forecasts, *_ = owned_case()
    registrations = tuple(
        seal(
            RealDeadlineRegistration.model_construct(
                protocol_sha256=protocol.semantic_sha256,
                population=pop,
                registered_at=AT,
                original_population_frozen_at=pop.deadline_at - timedelta(hours=2),
                custody="QUALIFIED_EXTERNAL_HISTORICAL_IMPORT",
                external_custody_sha256="a" * 64,
                semantic_sha256="0" * 64,
            )
        )
        for pop in populations
    )
    frozen = tuple(
        seal(
            RealPointFreeze.model_construct(
                forecast=point,
                population_registration_sha256=registrations[
                    point.key.gameweek - 9
                ].semantic_sha256,
                recorded_at=AT,
                original_frozen_at=point.generated_at + timedelta(seconds=1),
                custody="QUALIFIED_EXTERNAL_HISTORICAL_IMPORT",
                external_custody_sha256="b" * 64,
                semantic_sha256="0" * 64,
            )
        )
        for point in forecasts
    )
    assert real_coverage(protocol, registrations, frozen).complete
    incomplete = real_coverage(protocol, registrations, frozen[:-1])
    assert (
        incomplete.expected_cells == 4
        and len(incomplete.missing_cells) == 1
        and not incomplete.complete
    )
    unknown = real_coverage(protocol, registrations[:1], frozen[:2])
    assert unknown.expected_cells is None and unknown.unregistered_gameweeks == (10,)
