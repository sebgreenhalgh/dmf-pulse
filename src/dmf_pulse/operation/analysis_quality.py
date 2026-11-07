"""Pure diagnostics of retained derived forecasts; never reconstruct missing evidence."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from math import fsum
from typing import Literal

from dmf_pulse.operation.analysis_models import AnalysisSnapshot, ProvenanceClass
from dmf_pulse.private_v1.models import PrivateV1Decision
from dmf_pulse.private_v1.presentation import PresentationModel

type ZeroStatus = Literal[
    "MISSING_POINTS",
    "NONZERO_POINTS",
    "ZERO_POINTS_MINUTES_UNKNOWN",
    "ZERO_POINTS_POSITIVE_MINUTES",
    "ZERO_POINTS_ZERO_MINUTES_CAUSE_UNAVAILABLE",
    "ZERO_POINTS_ZERO_MINUTES_PMF_CONFIRMED",
]


class PlayerQuality(PresentationModel):
    official_id: int
    player_id: str | None
    zero_status: ZeroStatus
    p_zero_minutes: str | None
    minutes_confidence_reasons: tuple[str, ...] | None
    issues: tuple[str, ...]


class TeamAccounting(PresentationModel):
    status: Literal["MARGINAL_ACCOUNTING_ONLY", "INCOMPLETE_MARGINALS", "ROLLING_UNAVAILABLE"]
    starting_xi_expected_points: Decimal | None = None
    captain_standalone_expected_points: Decimal | None = None
    xi_plus_standalone_captain: Decimal | None = None
    retained_before_hit: Decimal | None = None
    hit_points: int | None = None
    retained_after_hit: Decimal | None = None
    unattributed_difference: Decimal | None = None
    # Marginals cannot identify these joint scenario expectations.
    autosub_expected_points: None = None
    vice_contingency_expected_points: None = None
    captain_only_counterfactual: None = None


class ForecastQuality(PresentationModel):
    schema_version: Literal["analysis-quality-v1"] = "analysis-quality-v1"
    metric_version: Literal["retained-derived-diagnostics-v1"] = "retained-derived-diagnostics-v1"
    run_id: str
    snapshot_sha256: str
    provenance_class: ProvenanceClass
    permission_origin: Literal["OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED", "OWNED_FIXTURE"]
    rights: Literal["PRIVATE_DERIVED_ONLY_NO_RAW_NO_PUBLIC_SHARING_NO_REPLAY"]
    validation: Literal["UNVALIDATED"] = "UNVALIDATED"
    player_count: int
    missing_points_count: int
    fallback_count: int
    confidence_counts: dict[str, int]
    zero_status_counts: dict[str, int]
    p10_zero_count: int
    p10_missing_count: int
    maximum_retained_mean_se: float | None
    retained_scenario_count: int | None
    monte_carlo_policy: None = None
    predictive_performance: None = None
    issues: tuple[str, ...]
    team: TeamAccounting
    players: tuple[PlayerQuality, ...]
    limitations: tuple[str, ...] = (
        "NO_OUTCOMES_OR_PREDICTIVE_SKILL_EVALUATION",
        "MARGINAL_RESIDUAL_IS_NOT_AUTOSUB_OR_CAPTAIN_ATTRIBUTION",
        "ZERO_MINUTES_DOES_NOT_PROVE_UNAVAILABILITY",
        "POINTS_P10_ZERO_DOES_NOT_IDENTIFY_NONAPPEARANCE_PROBABILITY",
        "RETAINED_MONTE_CARLO_PASS_IS_NOT_A_PRECISION_CERTIFICATE",
        "CURRENT_TEAM_CATALOGUE_IS_NOT_MATCH_TIME_MEMBERSHIP_EVIDENCE",
    )


def _number(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _team(snapshot: AnalysisSnapshot) -> TeamAccounting:
    decision = snapshot.view.team.decision
    if not isinstance(decision, PrivateV1Decision):
        return TeamAccounting(status="ROLLING_UNAVAILABLE")
    comparison = decision.paired_comparison
    by_id = {row.catalogue.player_id: row.expected_points for row in snapshot.view.players}
    ids = (*decision.tactics.starting_xi, decision.tactics.captain)
    mapped = [
        row.catalogue.player_id
        for row in snapshot.view.players
        if row.catalogue.player_id is not None
    ]
    if len(mapped) != len(set(mapped)) or any(by_id.get(player) is None for player in ids):
        return TeamAccounting(
            status="INCOMPLETE_MARGINALS",
            retained_before_hit=comparison.recommended_expected_points_before_hit,
            hit_points=comparison.transfer_hit_points,
            retained_after_hit=comparison.recommended_expected_points_after_hit,
        )
    values = tuple(Decimal(str(by_id[player])) for player in ids)
    xi = sum(values[:-1], Decimal(0))
    naive = xi + values[-1]
    return TeamAccounting(
        status="MARGINAL_ACCOUNTING_ONLY",
        starting_xi_expected_points=xi,
        captain_standalone_expected_points=values[-1],
        xi_plus_standalone_captain=naive,
        unattributed_difference=comparison.recommended_expected_points_before_hit - naive,
        retained_before_hit=comparison.recommended_expected_points_before_hit,
        hit_points=comparison.transfer_hit_points,
        retained_after_hit=comparison.recommended_expected_points_after_hit,
    )


def diagnose_forecast(snapshot: AnalysisSnapshot) -> ForecastQuality:
    """Inspect one immutable typed snapshot without a provider, store or model call."""
    snapshot = AnalysisSnapshot.model_validate_json(snapshot.model_dump_json())
    view = snapshot.view
    issues: set[str] = set()
    mapped = [
        row.catalogue.player_id for row in view.players if row.catalogue.player_id is not None
    ]
    if len(mapped) != len(set(mapped)):
        issues.add("DUPLICATE_CANONICAL_PLAYER_ID")
    if len(view.players) != view.catalogue_count:
        issues.add("CATALOGUE_COUNT_MISMATCH")
    presentation = snapshot.presentation
    if presentation is None:
        issues.add("FIXTURE_AND_GAMEWEEK_DETAILS_NOT_RETAINED")
    players = []
    for row in sorted(view.players, key=lambda value: value.catalogue.official_id):
        row_issues: set[str] = set()
        minutes = _number(row.expected_minutes)
        for label, value, upper in (
            ("EXPECTED_MINUTES", row.expected_minutes, Decimal(90)),
            ("P_START", row.p_start, Decimal(1)),
            ("P_60_PLUS", row.p_60_plus, Decimal(1)),
        ):
            numeric = _number(value)
            if value is not None and (numeric is None or not Decimal(0) <= numeric <= upper):
                row_issues.add(f"{label}_INVALID")
        fixture_minutes = (
            []
            if presentation is None
            else [
                fixture.minutes[row.catalogue.player_id]
                for fixture in presentation.fixtures
                if fixture.gameweek == view.gameweeks[0]
                and row.catalogue.player_id in fixture.minutes
            ]
        )
        single = fixture_minutes[0] if len(fixture_minutes) == 1 else None
        if single is not None and (
            single.player_id != row.catalogue.player_id or single.position != row.catalogue.position
        ):
            row_issues.add("FIXTURE_PLAYER_IDENTITY_MISMATCH")
        if (
            single is not None
            and minutes is not None
            and minutes != Decimal(single.expected_minutes)
        ):
            row_issues.add("RETAINED_MINUTES_MISMATCH")
        if row.expected_points not in {None, 0} and minutes == 0:
            row_issues.add("NONZERO_POINTS_WITH_ZERO_EXPECTED_MINUTES")
        for uncertainty_label, uncertainty_value in (
            ("MEAN_SE", row.monte_carlo_mean_se),
            ("STANDARD_DEVIATION", row.points_standard_deviation),
        ):
            if uncertainty_value is not None and uncertainty_value < 0:
                row_issues.add(f"{uncertainty_label}_NEGATIVE")
        if (
            row.points_p10 is not None
            and row.points_p90 is not None
            and (
                row.points_p10 > row.points_p90
                or (
                    row.median_points is not None
                    and not row.points_p10 <= row.median_points <= row.points_p90
                )
            )
        ):
            row_issues.add("QUANTILES_NOT_MONOTONE")
        status: ZeroStatus
        if row.expected_points is None:
            status = "MISSING_POINTS"
        elif row.expected_points != 0:
            status = "NONZERO_POINTS"
        elif minutes is None:
            status = "ZERO_POINTS_MINUTES_UNKNOWN"
        elif minutes > 0:
            status = "ZERO_POINTS_POSITIVE_MINUTES"
        elif single is not None and Decimal(single.p_zero_minutes) == 1:
            status = "ZERO_POINTS_ZERO_MINUTES_PMF_CONFIRMED"
        else:
            status = "ZERO_POINTS_ZERO_MINUTES_CAUSE_UNAVAILABLE"
        players.append(
            PlayerQuality(
                official_id=row.catalogue.official_id,
                player_id=row.catalogue.player_id,
                zero_status=status,
                p_zero_minutes=None if single is None else single.p_zero_minutes,
                minutes_confidence_reasons=None if single is None else single.confidence_reasons,
                issues=tuple(sorted(row_issues)),
            )
        )
    if presentation is not None:
        if len({g.gameweek for g in presentation.gameweeks}) != len(presentation.gameweeks):
            issues.add("DUPLICATE_GAMEWEEK_IDENTITY")
        if len({f.official_fixture_id for f in presentation.fixtures}) != len(
            presentation.fixtures
        ):
            issues.add("DUPLICATE_FIXTURE_IDENTITY")
        for gameweek in presentation.gameweeks:
            for summary in gameweek.summaries.values():
                if any(not 0 <= probability <= 1 for probability in summary.pmf.values()):
                    issues.add("POINTS_PMF_MASS_INVALID")
                if abs(fsum(summary.pmf.values()) - 1) > 1e-9:
                    issues.add("POINTS_PMF_NOT_NORMALIZED")
                if (
                    abs(fsum(k * p for k, p in summary.pmf.items()) - summary.expected_points)
                    > 1e-9
                ):
                    issues.add("POINTS_PMF_MEAN_MISMATCH")
    errors = [
        row.monte_carlo_mean_se for row in view.players if row.monte_carlo_mean_se is not None
    ]
    decision = view.team.decision
    return ForecastQuality(
        run_id=snapshot.run_id,
        snapshot_sha256=snapshot.semantic_sha256,
        provenance_class=snapshot.provenance_class,
        permission_origin=snapshot.permission_origin,
        rights=snapshot.rights,
        player_count=len(players),
        missing_points_count=sum(row.expected_points is None for row in view.players),
        fallback_count=sum(row.fallback for row in view.players),
        confidence_counts=dict(
            sorted(Counter(row.confidence or "UNAVAILABLE" for row in view.players).items())
        ),
        zero_status_counts=dict(sorted(Counter(row.zero_status for row in players).items())),
        p10_zero_count=sum(row.points_p10 == 0 for row in view.players),
        p10_missing_count=sum(row.points_p10 is None for row in view.players),
        maximum_retained_mean_se=max(errors) if errors else None,
        retained_scenario_count=decision.scenario_count
        if isinstance(decision, PrivateV1Decision)
        else None,
        issues=tuple(sorted(issues)),
        team=_team(snapshot),
        players=tuple(players),
    )
