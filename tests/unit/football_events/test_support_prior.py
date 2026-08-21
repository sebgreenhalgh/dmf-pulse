"""Offline contracts for the unaccepted GW1 Stage-8 support-prior candidate."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.football_events.support_prior import (
    SEASON_SOURCES,
    SupportPriorError,
    build_candidate_artifact,
    build_support_prior_worlds,
    calibrate_openfootball_support_prior,
    diagnose_market_dominance,
    parse_openfootball_completed_fixtures,
    stage8_support_diagnostics,
    validate_candidate_artifact,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)
RETRIEVED = "2026-08-20T12:00:00Z"
PRODUCED = "2026-08-20T12:01:00Z"
CODE_COMMIT = "1" * 40
SOURCE_TOTALS = (
    (575, 496),
    (621, 463),
    (684, 562),
    (575, 540),
    (580, 465),
)


def _goals(total: int, count: int = 380) -> tuple[int, ...]:
    base, remainder = divmod(total, count)
    return tuple(base + (1 if index < remainder else 0) for index in range(count))


def _source_root(tmp_path: Path, *, match_count: int = 380) -> Path:
    root = tmp_path / "openfootball-england"
    for source, (home_total, away_total) in zip(SEASON_SOURCES, SOURCE_TOTALS, strict=True):
        home_goals = _goals(home_total)
        away_goals = _goals(away_total)
        path = root / source.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            f"  Home {index:03d} v Away {index:03d}  {home_goals[index]}-{away_goals[index]}"
            for index in range(match_count)
        ]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    return root


def _constraint(
    *,
    constraint_id: str,
    event: ScoreEvent,
    family: MarketFamily,
    target: str,
    line: str | None = None,
) -> MarketConstraint:
    body: dict[str, object] = {
        "confidence_grade": "B",
        "constraint_id": constraint_id,
        "event": event,
        "family": family,
        "target_probability": Decimal(target),
        "uncertainty": Decimal("0.010000000000"),
        "usable_at": AS_OF,
        "weight": Decimal("0.750000000000"),
    }
    if line is not None:
        body["line"] = Decimal(line)
    return MarketConstraint.model_validate(body)


def _constraint_sets() -> tuple[MarketConstraintSet, MarketConstraintSet, MarketConstraintSet]:
    h2h = MarketConstraintSet.model_validate(
        {
            "as_of": AS_OF,
            "constraints": (
                _constraint(
                    constraint_id="synthetic-home",
                    event=ScoreEvent.HOME_WIN,
                    family=MarketFamily.ONE_X_TWO,
                    target="0.460000000000",
                ),
                _constraint(
                    constraint_id="synthetic-draw",
                    event=ScoreEvent.DRAW,
                    family=MarketFamily.ONE_X_TWO,
                    target="0.280000000000",
                ),
                _constraint(
                    constraint_id="synthetic-away",
                    event=ScoreEvent.AWAY_WIN,
                    family=MarketFamily.ONE_X_TWO,
                    target="0.260000000000",
                ),
            ),
        }
    )
    totals = (
        _constraint(
            constraint_id="synthetic-over-2.5",
            event=ScoreEvent.TOTAL_OVER,
            family=MarketFamily.TOTALS,
            target="0.600000000000",
            line="2.5",
        ),
        _constraint(
            constraint_id="synthetic-under-2.5",
            event=ScoreEvent.TOTAL_UNDER,
            family=MarketFamily.TOTALS,
            target="0.400000000000",
            line="2.5",
        ),
    )
    complete = MarketConstraintSet.model_validate(
        {"as_of": AS_OF, "constraints": (*h2h.constraints, *totals)}
    )
    no_market = MarketConstraintSet.model_validate({"as_of": AS_OF, "constraints": ()})
    return complete, h2h, no_market


def test_parser_accepts_both_pinned_football_text_layouts() -> None:
    fixtures = parse_openfootball_completed_fixtures(
        "  20:00  Brentford FC  2-0 (1-0)  Arsenal FC\n  Liverpool FC v Everton FC  1-1 (0-1)\n"
    )

    assert [
        (item.home_team, item.away_team, item.home_goals, item.away_goals) for item in fixtures
    ] == [
        ("Brentford FC", "Arsenal FC", 2, 0),
        ("Liverpool FC", "Everton FC", 1, 1),
    ]


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("Home FC v Away FC  1-x", "MALFORMED_SCORE"),
        ("Home FC v Away FC  -1-0", "NEGATIVE_SCORE"),
    ],
)
def test_parser_rejects_malformed_or_negative_scores(source: str, code: str) -> None:
    with pytest.raises(SupportPriorError) as error:
        parse_openfootball_completed_fixtures(source)

    assert error.value.code == code


def test_calibration_rejects_missing_completed_match_coverage(tmp_path: Path) -> None:
    root = _source_root(tmp_path, match_count=379)

    with pytest.raises(SupportPriorError) as error:
        calibrate_openfootball_support_prior(root)

    assert error.value.code == "INCOMPLETE_SEASON"


def test_calibration_rejects_duplicate_fixture(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    path = root / SEASON_SOURCES[0].relative_path
    rows = path.read_text(encoding="utf-8").splitlines()
    rows[-1] = rows[0]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(SupportPriorError) as error:
        calibrate_openfootball_support_prior(root)

    assert error.value.code == "DUPLICATE_FIXTURE"


def test_five_by_380_calibration_reproduces_expected_lambdas_deterministically(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path)
    first = calibrate_openfootball_support_prior(root)
    second = calibrate_openfootball_support_prior(root)

    assert first == second
    assert first.match_count == 1900
    assert [
        (item.match_count, item.home_goal_total, item.away_goal_total) for item in first.seasons
    ] == [(380, home, away) for home, away in SOURCE_TOTALS]
    assert first.central_home_goal_rate == Decimal("1.5840940818")
    assert first.central_away_goal_rate == Decimal("1.3253421983")


def test_candidate_artifact_is_hash_bound_unaccepted_and_revalidates(tmp_path: Path) -> None:
    calibration = calibrate_openfootball_support_prior(_source_root(tmp_path))
    artifact = build_candidate_artifact(
        calibration,
        policy=load_score_baseline_policy(),
        source_retrieved_at=RETRIEVED,
        produced_at=PRODUCED,
        information_cutoff=RETRIEVED,
        code_commit=CODE_COMMIT,
    )

    validate_candidate_artifact(artifact)
    assert artifact["status"] == "CANDIDATE_NOT_ACCEPTED"
    assert artifact["human_acceptance"] == {
        "accepted": False,
        "accepted_at": None,
        "decision_reference": None,
        "reviewer": None,
    }
    assert (
        artifact["artifact_sha256"]
        == build_candidate_artifact(
            calibration,
            policy=load_score_baseline_policy(),
            source_retrieved_at=RETRIEVED,
            produced_at=PRODUCED,
            information_cutoff=RETRIEVED,
            code_commit=CODE_COMMIT,
        )["artifact_sha256"]
    )

    tampered = dict(artifact)
    tampered["derived_home_goal_rate"] = "1.0000000000"
    with pytest.raises(SupportPriorError) as error:
        validate_candidate_artifact(tampered)
    assert error.value.code == "ARTIFACT_CALCULATION"


def test_sensitivity_worlds_are_complete_hashed_and_explicit(tmp_path: Path) -> None:
    calibration = calibrate_openfootball_support_prior(_source_root(tmp_path))
    worlds = build_support_prior_worlds(calibration, model_sha256="2" * 64)

    assert len(worlds) == 18
    assert len({item.world_sha256 for item in worlds}) == 18
    complete = [item for item in worlds if item.availability == "H2H_TOTALS"]
    h2h_only = [item for item in worlds if item.availability == "H2H_ONLY"]
    assert {(item.home_multiplier, item.away_multiplier) for item in complete} == {
        (home, away)
        for home in (Decimal("0.85"), Decimal("1.00"), Decimal("1.15"))
        for away in (Decimal("0.85"), Decimal("1.00"), Decimal("1.15"))
    }
    assert {(item.home_multiplier, item.away_multiplier) for item in h2h_only} == {
        (home, away)
        for home in (Decimal("0.75"), Decimal("1.00"), Decimal("1.25"))
        for away in (Decimal("0.75"), Decimal("1.00"), Decimal("1.25"))
    }


def test_stage8_compatibility_uses_existing_score_prior_request_and_adaptive_tail(
    tmp_path: Path,
) -> None:
    calibration = calibrate_openfootball_support_prior(_source_root(tmp_path))
    request = calibration.score_prior_request()
    diagnostics = stage8_support_diagnostics(calibration, policy=load_score_baseline_policy())

    assert request.model_family == "INDEPENDENT_POISSON_V1"
    assert request.home_goal_rate > 0 and request.away_goal_rate > 0
    assert diagnostics["finite_strictly_positive_support"] is True
    assert Decimal(diagnostics["omitted_tail_mass"]) <= Decimal(diagnostics["tail_tolerance"])
    assert diagnostics["home_max"] >= 6 and diagnostics["away_max"] >= 6


def test_market_dominance_diagnostics_keep_complete_markets_less_prior_sensitive(
    tmp_path: Path,
) -> None:
    calibration = calibrate_openfootball_support_prior(_source_root(tmp_path))
    complete, h2h_only, no_market = _constraint_sets()
    report = diagnose_market_dominance(
        calibration,
        complete_constraints=complete,
        h2h_only_constraints=h2h_only,
        no_market_constraints=no_market,
        policy=load_score_baseline_policy(),
    )

    assert len(report["complete_h2h_totals"]) == 9
    assert len(report["h2h_only"]) == 9
    assert report["no_market"]["projection_status"] == "PRIOR_ONLY"
    assert report["no_market"]["prior_to_posterior_total_variation"] == "0.000000000000"
    complete_spread = Decimal(report["complete_h2h_totals_prior_world_output_spread"]["over_2_5"])
    h2h_only_spread = Decimal(report["h2h_only_prior_world_output_spread"]["over_2_5"])
    assert complete_spread < h2h_only_spread
    assert "confidence_grade" not in report
    assert report["thresholds"] == "CANDIDATE_DIAGNOSTIC_ONLY_NO_PRODUCTION_THRESHOLD"


def test_numerical_fallback_is_explicit_and_does_not_add_a_confidence_grade(tmp_path: Path) -> None:
    calibration = calibrate_openfootball_support_prior(_source_root(tmp_path))
    complete, h2h_only, no_market = _constraint_sets()
    report = diagnose_market_dominance(
        calibration,
        complete_constraints=complete,
        h2h_only_constraints=h2h_only,
        no_market_constraints=no_market,
        policy=load_score_baseline_policy(),
        max_iterations=1,
    )

    statuses = {
        item["projection_status"] for item in [*report["complete_h2h_totals"], *report["h2h_only"]]
    }
    fallback_codes = {
        item["solver_error_code"] for item in [*report["complete_h2h_totals"], *report["h2h_only"]]
    }
    assert statuses == {"DEGRADED"}
    assert fallback_codes == {"PROJECTION_DID_NOT_CONVERGE"}
    assert all("confidence_grade" not in item for item in report["complete_h2h_totals"])
