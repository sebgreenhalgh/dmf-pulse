from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext
from uuid import UUID

import pytest

import dmf_pulse.markets.consensus as consensus_module
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets import (
    MarketOutcome,
    MarketState,
    NormalisationMethod,
    build_market_consensus,
    load_market_normalisation_policy,
    normalise_complete_market,
    raw_implied_probability,
)
from dmf_pulse.markets.consensus import (
    NoEligibleMarketError,
    _confidence_grade,
    _group_observations,
    evaluate_market_consensus,
)
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketObservation,
)
from dmf_pulse.markets.normalisation import (
    MarketNormalisationError,
    PowerNormalisationError,
    _build_operator_result,
    _compute_market,
    _operator_input_signature,
    _ordered_quotes,
    _power_vector,
    _source_build_sha256,
    code_identity,
)

pytestmark = pytest.mark.unit

FIXTURE_ID = UUID("00000000-0000-7000-8000-000000000101")
PROVIDER_ID = UUID("00000000-0000-7000-8000-000000000901")
AS_OF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)


def _quotes(
    operator_number: int,
    operator_key: str,
    odds: tuple[str, str, str],
    *,
    age_seconds: int,
    snapshot_number: int | None = None,
    state: MarketState = MarketState.COMPLETE,
) -> tuple[ExclusiveOutcomeQuote, ...]:
    observed = AS_OF - timedelta(seconds=age_seconds)
    received = max(observed, datetime(2026, 8, 20, 12, 0, 5, tzinfo=UTC))
    usable = max(received, datetime(2026, 8, 20, 12, 0, 10, tzinfo=UTC))
    snapshot = snapshot_number if snapshot_number is not None else operator_number
    return tuple(
        ExclusiveOutcomeQuote(
            fixture_id=FIXTURE_ID,
            market_id=UUID(f"00000000-0000-7000-8000-{operator_number:012d}"),
            selection_id=UUID(f"00000000-0000-7000-8100-{operator_number * 10 + index:012d}"),
            operator_id=UUID(f"00000000-0000-7000-8200-{operator_number:012d}"),
            outcome=outcome,
            decimal_odds=odds[index],
            observed_at=observed,
            received_at=received,
            usable_at=usable,
            source_snapshot_id=UUID(f"00000000-0000-7000-8300-{snapshot:012d}"),
            market_state=state,
            contract_version="the-odds-api-v4-reference-v1",
            book_observation_id=UUID(f"00000000-0000-7000-8350-{snapshot:012d}"),
            odds_observation_id=UUID(f"00000000-0000-7000-8400-{snapshot * 10 + index:012d}"),
            provider_id=PROVIDER_ID,
            operator_key=operator_key,
        )
        for index, outcome in enumerate(MarketOutcome)
    )


def _semantic_operator(result: object) -> dict[str, object]:
    dumped = result.model_dump(mode="json")  # type: ignore[attr-defined]
    return {
        "operator_key": dumped["operator_key"],
        "raw_booksum": dumped["raw_booksum"],
        "overround": dumped["overround"],
        "power_exponent": dumped["power_exponent"],
        "outcomes": dumped["outcomes"],
    }


def test_power_normalisation_matches_frozen_happy_operator() -> None:
    result = normalise_complete_market(
        _quotes(1, "book_alpha", ("1.80", "3.60", "4.20"), age_seconds=360),
        NormalisationMethod.POWER,
        load_market_normalisation_policy(),
    )
    assert _semantic_operator(result) == {
        "operator_key": "book_alpha",
        "raw_booksum": "1.071428571429",
        "overround": "0.071428571429",
        "power_exponent": "1.072594229814",
        "outcomes": [
            {
                "outcome": "HOME",
                "decimal_odds": "1.80",
                "raw_implied_probability": "0.555555555556",
                "proportional_probability": "0.518518518519",
                "market_probability": "0.532348683014",
            },
            {
                "outcome": "DRAW",
                "decimal_odds": "3.60",
                "raw_implied_probability": "0.277777777778",
                "proportional_probability": "0.259259259259",
                "market_probability": "0.253112240216",
            },
            {
                "outcome": "AWAY",
                "decimal_odds": "4.20",
                "raw_implied_probability": "0.238095238095",
                "proportional_probability": "0.222222222222",
                "market_probability": "0.214539076770",
            },
        ],
    }


def test_public_residual_tie_breaks_to_home() -> None:
    result = normalise_complete_market(
        _quotes(2, "balanced_book", ("2.70", "3.20", "2.70"), age_seconds=1),
        NormalisationMethod.POWER,
        load_market_normalisation_policy(),
    )
    assert [row.proportional_probability for row in result.outcomes] == [
        Decimal("0.351648351649"),
        Decimal("0.296703296703"),
        Decimal("0.351648351648"),
    ]
    assert sum(row.market_probability for row in result.outcomes) == Decimal(1)


def test_valid_extreme_odds_may_publish_zero_q12_raw_values() -> None:
    result = normalise_complete_market(
        _quotes(
            22,
            "extreme_book",
            ("10000000000000", "10000000000000", "10000000000000"),
            age_seconds=1,
        ),
        NormalisationMethod.POWER,
        load_market_normalisation_policy(),
    )

    assert result.raw_booksum == Decimal("0.000000000000")
    assert result.overround == Decimal("-1.000000000000")
    assert [item.raw_implied_probability for item in result.outcomes] == [Decimal(0)] * 3
    assert sum(item.market_probability for item in result.outcomes) == Decimal(1)


def test_raw_implied_probability_rejects_non_decimal_and_invalid_domain() -> None:
    assert raw_implied_probability(Decimal("4")) == Decimal("0.25")
    for value in (Decimal("1"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(MarketNormalisationError):
            raw_implied_probability(value)
    with pytest.raises(MarketNormalisationError):
        raw_implied_probability(2.0)  # type: ignore[arg-type]


def test_normalisation_does_not_mutate_global_decimal_context() -> None:
    original = getcontext().copy()
    normalise_complete_market(
        _quotes(3, "book", ("1.55", "3.20", "5.10"), age_seconds=1),
        NormalisationMethod.POWER,
        load_market_normalisation_policy(),
    )
    current = getcontext()
    assert (
        current.prec,
        current.rounding,
        current.Emin,
        current.Emax,
        current.flags,
        current.traps,
    ) == (
        original.prec,
        original.rounding,
        original.Emin,
        original.Emax,
        original.flags,
        original.traps,
    )


def test_happy_consensus_matches_frozen_uncertainty_and_confidence() -> None:
    observations = (
        *_quotes(1, "book_alpha", ("1.80", "3.60", "4.20"), age_seconds=360),
        *_quotes(2, "book_beta", ("1.85", "3.50", "4.10"), age_seconds=420),
    )
    result = build_market_consensus(
        observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert [row.consensus_probability for row in result.outcomes] == [
        Decimal("0.524978633868"),
        Decimal("0.257342673557"),
        Decimal("0.217678692575"),
    ]
    assert result.operator_disagreement == Decimal("0.014740098291")
    assert result.method_disagreement == Decimal("0.013830164495")
    assert result.confidence_grade == "B"
    assert result.freshness.minimum_age_seconds == 360
    assert result.freshness.maximum_age_seconds == 420


def test_stale_and_incomplete_books_are_excluded_without_fill() -> None:
    stale = _quotes(2, "book_beta", ("1.85", "3.50", "4.10"), age_seconds=1801)
    incomplete = _quotes(
        3,
        "book_incomplete",
        ("2.00", "3.00", "4.00"),
        age_seconds=1,
        state=MarketState.INCOMPLETE,
    )[:2]
    evaluation = evaluate_market_consensus(
        (
            *_quotes(1, "book_alpha", ("1.80", "3.60", "4.20"), age_seconds=360),
            *stale,
            *incomplete,
        ),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert evaluation.consensus is not None
    assert evaluation.consensus.confidence_grade == "C"
    assert [(item.operator_key, item.reason.value) for item in evaluation.exclusions] == [
        ("book_beta", "STALE"),
        ("book_incomplete", "INCOMPLETE"),
    ]


def test_freshness_boundary_uses_exact_time_before_reporting_whole_seconds() -> None:
    exact = _quotes(20, "exact_boundary", ("1.80", "3.60", "4.20"), age_seconds=1800)
    exact_evaluation = evaluate_market_consensus(
        exact,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert exact_evaluation.consensus is not None
    assert exact_evaluation.consensus.freshness.maximum_age_seconds == 1800

    just_stale = tuple(
        quote.model_copy(update={"observed_at": AS_OF - timedelta(seconds=1800, microseconds=1)})
        for quote in exact
    )
    stale_evaluation = evaluate_market_consensus(
        just_stale,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert stale_evaluation.consensus is None
    assert [(item.operator_key, item.reason.value) for item in stale_evaluation.exclusions] == [
        ("exact_boundary", "STALE")
    ]


def test_mathematical_kernel_failures_are_typed_and_fallback_is_narrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(PowerNormalisationError, match="invalid total") as invalid_total:
        _power_vector((Decimal(0), Decimal(0), Decimal(0)))
    assert invalid_total.value.code == "POWER_TOTAL_INVALID"
    with pytest.raises(PowerNormalisationError, match="finite and positive") as invalid_vector:
        _power_vector((Decimal(0), Decimal("0.5"), Decimal("0.5")))
    assert invalid_vector.value.code == "POWER_VECTOR_INVALID"
    with pytest.raises(PowerNormalisationError, match="failed numerically") as decimal_failure:
        _power_vector((Decimal("-0.1"), Decimal("0.5"), Decimal("0.7")))
    assert decimal_failure.value.code == "POWER_DECIMAL_FAILURE"
    with pytest.raises(PowerNormalisationError, match="exceeds 1024") as bracket_failure:
        _power_vector((Decimal("0.9999"), Decimal("0.9999"), Decimal("0.9999")))
    assert bracket_failure.value.code == "POWER_BRACKET_EXCEEDED"

    monkeypatch.setattr(
        "dmf_pulse.markets.normalisation.raw_implied_probability",
        lambda _value: Decimal(0),
    )
    with pytest.raises(MarketNormalisationError, match="booksum"):
        _compute_market(
            (Decimal(2), Decimal(3), Decimal(4)),
            NormalisationMethod.PROPORTIONAL,
        )

    monkeypatch.setattr(
        "dmf_pulse.markets.normalisation.raw_implied_probability",
        lambda _value: Decimal("0.5"),
    )
    monkeypatch.setattr(
        "dmf_pulse.markets.normalisation._power_vector",
        lambda _raw: (_ for _ in ()).throw(ValueError("not a numerical failure")),
    )
    with pytest.raises(ValueError, match="not a numerical failure"):
        _compute_market(
            (Decimal(2), Decimal(3), Decimal(4)),
            NormalisationMethod.POWER,
        )


def test_complete_book_validation_covers_every_structural_boundary() -> None:
    quotes = _quotes(9, "book", ("1.80", "3.60", "4.20"), age_seconds=1)
    with pytest.raises(MarketNormalisationError, match="exactly three"):
        _ordered_quotes(quotes[:2])
    with pytest.raises(MarketNormalisationError, match="duplicate outcome"):
        _ordered_quotes((quotes[0], quotes[0], quotes[2]))
    invalid_outcome = quotes[2].model_copy(update={"outcome": "OTHER"})
    with pytest.raises(MarketNormalisationError, match="HOME, DRAW, and AWAY"):
        _ordered_quotes((quotes[0], quotes[1], invalid_outcome))  # type: ignore[arg-type]
    other_fixture = quotes[2].model_copy(update={"fixture_id": UUID(int=999)})
    with pytest.raises(MarketNormalisationError, match="one complete operator market"):
        _ordered_quotes((quotes[0], quotes[1], other_fixture))
    other_book = quotes[2].model_copy(update={"book_observation_id": UUID(int=998)})
    with pytest.raises(MarketNormalisationError, match="one complete operator market"):
        _ordered_quotes((quotes[0], quotes[1], other_book))
    other_timestamp = quotes[2].model_copy(
        update={"observed_at": quotes[2].observed_at - timedelta(microseconds=1)}
    )
    with pytest.raises(MarketNormalisationError, match="one complete operator market"):
        _ordered_quotes((quotes[0], quotes[1], other_timestamp))
    duplicate_selection = quotes[2].model_copy(update={"selection_id": quotes[0].selection_id})
    with pytest.raises(MarketNormalisationError, match="one complete operator market"):
        _ordered_quotes((quotes[0], quotes[1], duplicate_selection))


def test_operator_result_hash_binds_public_identity_and_temporal_fields() -> None:
    policy = load_market_normalisation_policy()
    ordered = _ordered_quotes(_quotes(21, "bound_book", ("1.80", "3.60", "4.20"), age_seconds=1))
    computed = _compute_market(
        (ordered[0].decimal_odds, ordered[1].decimal_odds, ordered[2].decimal_odds),
        NormalisationMethod.POWER,
    )
    original = _build_operator_result(
        ordered,
        computed,
        method=NormalisationMethod.POWER,
        policy=policy,
        result_as_of=AS_OF,
        mapping_cutoff=AS_OF,
    )
    changed_quotes = tuple(
        quote.model_copy(
            update={
                "observed_at": quote.observed_at - timedelta(microseconds=1),
                "provider_id": UUID(int=999),
            }
        )
        for quote in ordered
    )
    changed = _build_operator_result(
        _ordered_quotes(changed_quotes),
        computed,
        method=NormalisationMethod.POWER,
        policy=policy,
        result_as_of=AS_OF,
        mapping_cutoff=AS_OF,
    )

    assert changed.input_signature_sha256 == original.input_signature_sha256
    assert changed.result_sha256 != original.result_sha256


def test_consensus_rejects_unenriched_observations_and_naive_cutoffs() -> None:
    quote = _quotes(10, "book", ("1.80", "3.60", "4.20"), age_seconds=1)[0]
    plain = MarketObservation.model_validate(
        {name: getattr(quote, name) for name in MarketObservation.model_fields}
    )
    with pytest.raises(MarketNormalisationError, match="canonical observation IDs"):
        _group_observations((plain,))
    with pytest.raises(MarketNormalisationError, match="as_of must be timezone-aware"):
        evaluate_market_consensus(
            (),
            as_of=AS_OF.replace(tzinfo=None),
            mapping_cutoff=AS_OF,
            policy=load_market_normalisation_policy(),
        )
    with pytest.raises(MarketNormalisationError, match="mapping_cutoff must be timezone-aware"):
        evaluate_market_consensus(
            (),
            as_of=AS_OF,
            mapping_cutoff=AS_OF.replace(tzinfo=None),
            policy=load_market_normalisation_policy(),
        )
    mixed_fixture = tuple(
        quote.model_copy(update={"fixture_id": UUID(int=999)})
        for quote in _quotes(11, "other", ("1.80", "3.60", "4.20"), age_seconds=1)
    )
    with pytest.raises(MarketNormalisationError, match="multiple fixtures"):
        evaluate_market_consensus(
            (*_quotes(10, "book", ("1.80", "3.60", "4.20"), age_seconds=1), *mixed_fixture),
            as_of=AS_OF,
            mapping_cutoff=AS_OF,
            policy=load_market_normalisation_policy(),
        )


def test_consensus_records_preselection_failures_and_ignores_superseded_books() -> None:
    mixed = list(_quotes(11, "mixed", ("1.80", "3.60", "4.20"), age_seconds=1))
    mixed[2] = mixed[2].model_copy(update={"market_state": MarketState.SUSPENDED})
    incomplete = _quotes(12, "short", ("1.80", "3.60", "4.20"), age_seconds=1)[:2]
    future = _quotes(13, "future", ("1.80", "3.60", "4.20"), age_seconds=-1)
    unavailable = _quotes(
        14,
        "unavailable",
        ("1.80", "3.60", "4.20"),
        age_seconds=1,
        state=MarketState.UNAVAILABLE,
    )
    selected = _quotes(
        15,
        "selected",
        ("1.80", "3.60", "4.20"),
        age_seconds=1,
        snapshot_number=150,
    )
    duplicate = tuple(
        quote.model_copy(update={"provider_id": UUID(int=12345)})
        for quote in _quotes(
            15,
            "duplicate",
            ("1.85", "3.50", "4.10"),
            age_seconds=2,
            snapshot_number=151,
        )
    )
    same_provider_duplicate = _quotes(
        15,
        "same_provider_duplicate",
        ("1.90", "3.40", "4.00"),
        age_seconds=3,
        snapshot_number=152,
    )
    evaluation = evaluate_market_consensus(
        (
            *mixed,
            *incomplete,
            *future,
            *unavailable,
            *selected,
            *duplicate,
            *same_provider_duplicate,
        ),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert evaluation.consensus is not None
    assert {item.reason.value for item in evaluation.exclusions} == {
        "QUALITY_BLOCKED",
        "INCOMPLETE",
        "FUTURE_OBSERVATION",
        "UNAVAILABLE",
    }
    assert "BOOK_EXCLUDED_DUPLICATE_OPERATOR" not in evaluation.warnings


def test_consensus_equal_time_book_selection_is_quote_order_independent() -> None:
    first_book = tuple(
        quote.model_copy(update={"source_snapshot_id": UUID(int=snapshot_id)})
        for quote, snapshot_id in zip(
            _quotes(
                16,
                "same_operator",
                ("1.80", "3.60", "4.20"),
                age_seconds=1,
                snapshot_number=160,
            ),
            (90, 1, 2),
            strict=True,
        )
    )
    second_book = tuple(
        quote.model_copy(update={"source_snapshot_id": UUID(int=snapshot_id)})
        for quote, snapshot_id in zip(
            _quotes(
                16,
                "same_operator",
                ("1.90", "3.40", "4.00"),
                age_seconds=1,
                snapshot_number=161,
            ),
            (50, 51, 52),
            strict=True,
        )
    )
    policy = load_market_normalisation_policy()

    ordered = evaluate_market_consensus(
        (*first_book, *second_book),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )
    permuted = evaluate_market_consensus(
        (*reversed(first_book), *second_book),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )

    assert ordered.consensus is not None
    assert permuted.consensus is not None
    assert ordered.consensus.result_sha256 == permuted.consensus.result_sha256
    assert ordered.consensus.operator_markets[0].source_observation_ids == tuple(
        quote.odds_observation_id for quote in second_book
    )


def test_no_eligible_market_and_all_confidence_grades_are_typed() -> None:
    policy = load_market_normalisation_policy()
    evaluation = evaluate_market_consensus(
        (),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=load_market_normalisation_policy(),
    )
    assert evaluation.consensus is None
    with pytest.raises(NoEligibleMarketError) as caught:
        build_market_consensus(
            (),
            as_of=AS_OF,
            mapping_cutoff=AS_OF,
            policy=load_market_normalisation_policy(),
        )
    assert caught.value.exclusions == ()
    assert caught.value.warnings == ()
    assert (
        _confidence_grade(
            operator_count=3,
            maximum_age_seconds=600,
            disagreement=Decimal("0.02"),
            fallback_used=False,
            policy=policy,
        )
        == "A"
    )
    assert (
        _confidence_grade(
            operator_count=2,
            maximum_age_seconds=1800,
            disagreement=Decimal("0.05"),
            fallback_used=False,
            policy=policy,
        )
        == "B"
    )
    assert (
        _confidence_grade(
            operator_count=1,
            maximum_age_seconds=1800,
            disagreement=Decimal("0.10"),
            fallback_used=True,
            policy=policy,
        )
        == "C"
    )
    assert (
        _confidence_grade(
            operator_count=1,
            maximum_age_seconds=1801,
            disagreement=Decimal("0.11"),
            fallback_used=True,
            policy=policy,
        )
        == "D"
    )
    with pytest.raises(MarketNormalisationError, match="rejects an eligible market"):
        _confidence_grade(
            operator_count=0,
            maximum_age_seconds=0,
            disagreement=Decimal(0),
            fallback_used=False,
            policy=policy,
        )


def test_confidence_rejects_gate_policy_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = load_market_normalisation_policy()
    gate_policy = consensus_module.load_confidence_gate_policy()
    monkeypatch.setattr(
        consensus_module,
        "load_confidence_gate_policy",
        lambda: gate_policy.model_copy(update={"normalisation_policy_sha256": "0" * 64}),
    )

    with pytest.raises(MarketNormalisationError, match="identity is inconsistent"):
        _confidence_grade(
            operator_count=3,
            maximum_age_seconds=100,
            disagreement=Decimal("0.01"),
            fallback_used=False,
            policy=policy,
        )


def test_confidence_rejects_copied_policy_drift_and_blocking_warnings_cap_grade() -> None:
    policy = load_market_normalisation_policy()
    stricter_b = policy.confidence.B.model_copy(update={"minimum_operators": 3})
    modified = policy.model_copy(
        update={"confidence": policy.confidence.model_copy(update={"B": stricter_b})}
    )
    with pytest.raises(IngestionError) as copied_policy:
        _confidence_grade(
            operator_count=2,
            maximum_age_seconds=600,
            disagreement=Decimal("0.01"),
            fallback_used=False,
            policy=modified,
        )
    assert copied_policy.value.code == "POLICY_INVALID"

    excluded = _quotes(
        33,
        "excluded",
        ("1.80", "3.60", "4.20"),
        age_seconds=100,
        state=MarketState.INCOMPLETE,
    )[:2]
    with_exclusion = evaluate_market_consensus(
        (
            *(
                quote
                for operator in range(30, 33)
                for quote in _quotes(
                    operator,
                    f"book_{operator}",
                    ("1.80", "3.60", "4.20"),
                    age_seconds=100,
                )
            ),
            *excluded,
        ),
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )
    assert with_exclusion.consensus is not None
    assert with_exclusion.consensus.confidence_grade == "C"
    assert with_exclusion.exclusions

    clean_observations = tuple(
        quote
        for operator in range(30, 33)
        for quote in _quotes(
            operator,
            f"book_{operator}",
            ("1.80", "3.60", "4.20"),
            age_seconds=100,
        )
    )
    clean = evaluate_market_consensus(
        clean_observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )
    evaluation = evaluate_market_consensus(
        clean_observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
        initial_warnings=("DUPLICATE_OUTCOME_DEDUPED",),
    )
    with_initial_exclusion = evaluate_market_consensus(
        clean_observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
        initial_exclusions=(
            ExcludedBook(operator_key="excluded", reason=ExclusionReason.QUALITY_BLOCKED),
        ),
    )
    assert clean.consensus is not None
    assert evaluation.consensus is not None
    assert with_initial_exclusion.consensus is not None
    assert evaluation.consensus.confidence_grade == "B"
    assert with_initial_exclusion.consensus.confidence_grade == "C"
    assert evaluation.warnings == ("DUPLICATE_OUTCOME_DEDUPED",)
    assert clean.consensus.input_signature_sha256 != evaluation.consensus.input_signature_sha256
    assert clean.consensus.result_sha256 != evaluation.consensus.result_sha256
    assert (
        clean.consensus.input_signature_sha256
        != with_initial_exclusion.consensus.input_signature_sha256
    )
    assert clean.consensus.result_sha256 != with_initial_exclusion.consensus.result_sha256
    assert (
        _confidence_grade(
            operator_count=3,
            maximum_age_seconds=100,
            disagreement=Decimal("0.01"),
            fallback_used=False,
            policy=policy,
            has_warning=True,
            has_blocking_warning=True,
        )
        == "C"
    )


def test_operator_signature_binds_mapping_cutoff_and_exact_source_build(tmp_path) -> None:
    quotes = _ordered_quotes(_quotes(20, "book", ("1.80", "3.60", "4.20"), age_seconds=1))
    policy = load_market_normalisation_policy()
    first = _operator_input_signature(
        quotes,
        as_of=AS_OF.isoformat(),
        mapping_cutoff=AS_OF.isoformat(),
        method=NormalisationMethod.POWER,
        policy=policy,
    )
    second = _operator_input_signature(
        quotes,
        as_of=AS_OF.isoformat(),
        mapping_cutoff=(AS_OF - timedelta(seconds=1)).isoformat(),
        method=NormalisationMethod.POWER,
        policy=policy,
    )
    assert first != second

    package = tmp_path / "package"
    package.mkdir()
    source = package / "module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    before = _source_build_sha256(package)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    assert _source_build_sha256(package) != before
    identity = code_identity()
    prefix, digest = identity.rsplit(":", 1)
    assert prefix == "dmf-pulse-0.2.0:source-sha256"
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_consensus_signature_binds_mapping_cutoff() -> None:
    observations = (
        *_quotes(40, "book_alpha", ("1.80", "3.60", "4.20"), age_seconds=100),
        *_quotes(41, "book_beta", ("1.85", "3.50", "4.10"), age_seconds=100),
    )
    policy = load_market_normalisation_policy()
    first = build_market_consensus(
        observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF,
        policy=policy,
    )
    second = build_market_consensus(
        observations,
        as_of=AS_OF,
        mapping_cutoff=AS_OF - timedelta(seconds=1),
        policy=policy,
    )

    assert first.input_signature_sha256 != second.input_signature_sha256
    assert first.result_sha256 != second.result_sha256
    assert [item.input_signature_sha256 for item in first.operator_markets] != [
        item.input_signature_sha256 for item in second.operator_markets
    ]
    assert first.outcomes == second.outcomes


def test_code_identity_is_not_evaluated_during_fresh_module_import() -> None:
    script = """
from pathlib import Path

def forbidden(*_args, **_kwargs):
    raise AssertionError('source inventory was read during import')

Path.rglob = forbidden
import dmf_pulse.markets.normalisation
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
