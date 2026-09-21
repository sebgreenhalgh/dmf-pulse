"""Fixed reconstructed OOT reproduction; no selection, live-vintage or activation claim."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, time
from importlib.resources import files
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.team_strength_adapter import _rates
from dmf_pulse.football_events.team_strength_model import (
    Number,
    entrants,
    fit_team_strength,
    historical_cohort,
    memberships,
    number,
)
from dmf_pulse.football_events.team_strength_numerics import Observation, fit_strength
from dmf_pulse.football_events.team_strength_store import persist_team_strength
from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_reconstructed_corpus
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FixtureRegistry,
    FrozenEvidence,
    ParsedSnapshot,
    SealedEvidence,
    SourceResource,
    StrengthEvidenceError,
    authenticate,
    build_dataset,
    seal,
)

METRICS = (
    "exact_log_loss",
    "hda_log_loss",
    "hda_brier",
    "clean_sheet_brier",
    "btts_brier",
    "totals_brier",
    "home_mae",
    "away_mae",
    "total_mae",
    "goal_rps",
    "omitted_tail",
)
SUPPORT_MAX = 36
REPRODUCTION_TOLERANCE = 0.000002  # predeclared in checkpoint .02, not fitted to new results
GOLDEN_SEMANTIC_SHA256 = "c32233b55d0242fa9abc74d9823235dcf8a93b16845eff80617f646166a7d1ad"
GOLDEN_METRIC_TOLERANCE = 1e-9


def prediction_metrics(row: Observation, home_rate: float, away_rate: float) -> dict[str, float]:
    if any(not math.isfinite(rate) or not 0 < rate <= 8 for rate in (home_rate, away_rate)):
        raise StrengthEvidenceError("replay rates must lie in (0, 8]")
    if max(row.home_goals, row.away_goals) > SUPPORT_MAX:
        raise StrengthEvidenceError("realized score is outside the identical research support")
    marginals = []
    for rate in (home_rate, away_rate):
        pmf = [math.exp(-rate)]
        for k in range(1, SUPPORT_MAX + 1):
            pmf.append(pmf[-1] * rate / k)
        marginals.append(pmf)
    raw = tuple(tuple(h * a for a in marginals[1]) for h in marginals[0])
    mass = math.fsum(value for line in raw for value in line)
    omitted = max(0.0, 1.0 - mass)
    if omitted > 1e-12:
        raise StrengthEvidenceError("research score support has material omitted mass")
    matrix = tuple(tuple(value / mass for value in line) for line in raw)
    hg, ag = row.home_goals, row.away_goals
    hda = (
        math.fsum(matrix[h][a] for h in range(37) for a in range(h)),
        math.fsum(matrix[h][h] for h in range(37)),
        math.fsum(matrix[h][a] for h in range(37) for a in range(h + 1, 37)),
    )
    outcome = 0 if hg > ag else 1 if hg == ag else 2
    hp = tuple(math.fsum(line) for line in matrix)
    ap = tuple(math.fsum(matrix[h][a] for h in range(37)) for a in range(37))
    clean = ((ap[0] - float(ag == 0)) ** 2 + (hp[0] - float(hg == 0)) ** 2) / 2
    btts = math.fsum(matrix[h][a] for h in range(1, 37) for a in range(1, 37))
    totals = (
        math.fsum(
            (
                math.fsum(matrix[h][a] for h in range(37) for a in range(37) if h + a > threshold)
                - float(hg + ag > threshold)
            )
            ** 2
            for threshold in (1, 2, 3)
        )
        / 3
    )
    rps = (
        math.fsum(
            (math.fsum(pmf[: k + 1]) - float(k >= observed)) ** 2
            for pmf, observed in ((hp, hg), (ap, ag))
            for k in range(36)
        )
        / 2
    )
    return {
        "exact_log_loss": -math.log(max(matrix[hg][ag], 1e-300)),
        "hda_log_loss": -math.log(max(hda[outcome], 1e-300)),
        "hda_brier": math.fsum(
            (probability - float(i == outcome)) ** 2 for i, probability in enumerate(hda)
        ),
        "clean_sheet_brier": clean,
        "btts_brier": (btts - float(hg > 0 and ag > 0)) ** 2,
        "totals_brier": totals,
        "home_mae": abs(home_rate - hg),
        "away_mae": abs(away_rate - ag),
        "total_mae": abs(home_rate + away_rate - hg - ag),
        "goal_rps": rps,
        "omitted_tail": omitted,
    }


class ReplayMetrics(FrozenEvidence):
    exact_log_loss: Number = Field(ge=0)
    hda_log_loss: Number = Field(ge=0)
    hda_brier: Number = Field(ge=0, le=2)
    clean_sheet_brier: Number = Field(ge=0, le=1)
    btts_brier: Number = Field(ge=0, le=1)
    totals_brier: Number = Field(ge=0, le=1)
    home_mae: Number = Field(ge=0)
    away_mae: Number = Field(ge=0)
    total_mae: Number = Field(ge=0)
    goal_rps: Number = Field(ge=0)
    omitted_tail: Number = Field(ge=0)


def aggregate(rows: tuple[dict[str, float], ...]) -> ReplayMetrics:
    if not rows or any(set(row) != set(METRICS) for row in rows):
        raise StrengthEvidenceError("replay metric population is empty or incomplete")
    return ReplayMetrics(
        **{key: number(math.fsum(row[key] for row in rows) / len(rows)) for key in METRICS}
    )


class ReplayVariant(FrozenEvidence):
    regime: Literal[
        "ORIGINAL_RESEARCH_DATE_BEFORE_ORIGIN_METRICS_ONLY", "GOVERNED_D_PLUS_2_RECONSTRUCTED"
    ]
    fixtures: Literal[380] = 380
    origins: Literal[38] = 38
    metrics: ReplayMetrics
    candidate_minus_baseline_exact_log_loss: Number
    maximum_gradient_infinity: Number = Field(ge=0)
    maximum_iterations: int = Field(ge=1, le=100)
    population_sha256s: tuple[SHA, ...] = Field(min_length=38, max_length=38)
    model_state_sha256s: tuple[SHA, ...]
    parameters_retained: bool

    @model_validator(mode="after")
    def check_regime(self) -> Self:
        if float(self.maximum_gradient_infinity) > 1e-8:
            raise ValueError("replay includes an unconverged fit")
        if self.regime == "ORIGINAL_RESEARCH_DATE_BEFORE_ORIGIN_METRICS_ONLY":
            if self.model_state_sha256s or self.parameters_retained:
                raise ValueError("legacy reproduction cannot emit governed model artifacts")
        elif len(self.model_state_sha256s) != 38:
            raise ValueError("governed replay requires all 38 authenticated model states")
        return self


class TeamStrengthReplayReportV1(SealedEvidence):
    schema_version: Literal["team-strength-replay-v1"] = "team-strength-replay-v1"
    classification: Literal["RECONSTRUCTED"] = "RECONSTRUCTED"
    historical_live_availability_claimed: Literal[False] = False
    production_active: Literal[False] = False
    current_2026_27_used_for_selection: Literal[False] = False
    holdout: Literal["2025/26"] = "2025/26"
    baseline_seasons: tuple[Literal["2022/23", "2023/24", "2024/25"], ...] = (
        "2022/23",
        "2023/24",
        "2024/25",
    )
    selected_policy: Literal["FIXED_365_DAY_12_ATTACK_12_DEFENCE_HISTORICAL_ENTRANT_COHORT"] = (
        "FIXED_365_DAY_12_ATTACK_12_DEFENCE_HISTORICAL_ENTRANT_COHORT"
    )
    governance_sha256: Literal[
        "e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"
    ] = "e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"
    identity_registry_sha256: Literal[
        "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    ] = "55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef"
    fixture_registry_sha256: SHA
    source_resources: tuple[SourceResource, ...]
    score_support: Literal["IDENTICAL_NORMALIZED_0_THROUGH_36_BOTH_MODELS"] = (
        "IDENTICAL_NORMALIZED_0_THROUGH_36_BOTH_MODELS"
    )
    prediction_rate_boundary: Literal["UNROUNDED_BINARY64_RESEARCH_METRICS"] = (
        "UNROUNDED_BINARY64_RESEARCH_METRICS"
    )
    baseline: ReplayMetrics
    research_reproduction: ReplayVariant
    governed_d_plus_2: ReplayVariant
    differing_training_origins: tuple[int, ...]
    reproduction_tolerance: Literal["0.000002"] = "0.000002"

    @model_validator(mode="after")
    def check_comparison(self) -> Self:
        if self.baseline_seasons != ("2022/23", "2023/24", "2024/25"):
            raise ValueError("replay baseline seasons must be the ordered prior three seasons")
        if (
            self.research_reproduction.regime != "ORIGINAL_RESEARCH_DATE_BEFORE_ORIGIN_METRICS_ONLY"
            or self.governed_d_plus_2.regime != "GOVERNED_D_PLUS_2_RECONSTRUCTED"
        ):
            raise ValueError("replay comparison fields must bind their mandated regimes")
        for variant in (self.research_reproduction, self.governed_d_plus_2):
            expected = float(variant.metrics.exact_log_loss) - float(self.baseline.exact_log_loss)
            if abs(float(variant.candidate_minus_baseline_exact_log_loss) - expected) > 1e-12:
                raise ValueError("replay delta contradicts its candidate and baseline metrics")
        return self


def _all_observations(sources: tuple[ParsedSnapshot, ...]) -> tuple[Observation, ...]:
    result = []
    for source in sources:
        for row in source.matches:
            if row.finality != "FULL_TIME" or row.home_goals is None or row.away_goals is None:
                raise StrengthEvidenceError(
                    "locked replay requires complete recognized full-time results"
                )
            result.append(
                Observation(
                    row.fixture.fixture_id,
                    row.fixture.season,
                    row.source_match_date,
                    row.fixture.home_team_id,
                    row.fixture.away_team_id,
                    row.home_goals,
                    row.away_goals,
                )
            )
    return tuple(sorted(result, key=lambda row: row.fixture_id))


def _replay(
    fixtures: FixtureRegistry,
    sources: tuple[ParsedSnapshot, ...],
    *,
    progress: Callable[[int], None] | None = None,
    private_artifact_root: Path | None = None,
) -> TeamStrengthReplayReportV1:
    if tuple(source.lineage.resource.season for source in sources) != tuple(
        sorted(s for s in memberships() if s <= "2025/26")
    ):
        raise StrengthEvidenceError(
            "replay historical source scope must be exactly 2010/11 through 2025/26"
        )
    observations = _all_observations(sources)
    lookup = {row.fixture_id: row for row in observations}
    holdout = tuple(row for row in sources[-1].matches)
    if len(holdout) != 380 or {row.source_round for row in holdout} != set(range(1, 39)):
        raise StrengthEvidenceError("locked holdout must contain 380 fixtures in 38 origins")
    prior_seasons = {"2022/23", "2023/24", "2024/25"}
    baseline_rows = tuple(row for row in observations if row.season in prior_seasons)
    if len(baseline_rows) != 1140:
        raise StrengthEvidenceError("time-valid baseline requires three complete prior seasons")
    baseline_rates = (
        math.fsum(row.home_goals for row in baseline_rows) / 1140,
        math.fsum(row.away_goals for row in baseline_rows) / 1140,
    )
    baseline = aggregate(
        tuple(
            prediction_metrics(lookup[row.fixture.fixture_id], *baseline_rates) for row in holdout
        )
    )
    membership = memberships()
    cohort = historical_cohort(
        observations,
        forecast_season="2025/26",
        cutoff=datetime.combine(min(row.source_match_date for row in holdout), time(), UTC),
    )
    current_entrants = entrants("2025/26", membership)
    centres = {
        team: (float(cohort.attack_centre), float(cohort.defence_centre))
        for team in current_entrants
    }
    legacy_metrics, governed_metrics = [], []
    legacy_hashes, dataset_hashes, state_hashes = [], [], []
    legacy_gradients, governed_gradients, legacy_iterations, governed_iterations = [], [], [], []
    differences = []
    for round_number in range(1, 39):
        matches = tuple(row for row in holdout if row.source_round == round_number)
        if len(matches) != 10:
            raise StrengthEvidenceError("research origin does not contain ten fixtures")
        origin = datetime.combine(min(row.source_match_date for row in matches), time(), UTC)
        legacy_rows = tuple(row for row in observations if row.played_on < origin.date())
        if any(row.played_on >= origin.date() for row in baseline_rows):
            raise StrengthEvidenceError("baseline contains post-origin evidence")
        teams = tuple(
            sorted(
                {team for row in legacy_rows for team in (row.home, row.away)}
                | membership["2025/26"]
            )
        )
        legacy = fit_strength(
            legacy_rows, teams=teams, cutoff=origin, centres=centres, cold_entrants=current_entrants
        )
        legacy_hashes.append(canonical_sha256([str(row.fixture_id) for row in legacy_rows]))
        legacy_gradients.append(legacy.gradient_infinity)
        legacy_iterations.append(legacy.iterations)
        index = {team: i for i, team in enumerate(legacy.teams)}
        dataset = build_dataset(
            sources=sources,
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
            information_cutoff=max(source.lineage.usable_at for source in sources),
            training_cutoff=origin,
            forecast_season="2025/26",
            mode="RECONSTRUCTED",
        )
        if {row.fixture_id for row in legacy_rows} != {
            row.observation.fixture.fixture_id for row in dataset.matches
        }:
            differences.append(round_number)
        artifact = fit_team_strength(dataset)
        dataset_hashes.append(dataset.semantic_sha256)
        state_hashes.append(artifact.model.semantic_sha256)
        governed_gradients.append(float(artifact.model.numerics.gradient_infinity))
        governed_iterations.append(artifact.model.numerics.iterations)
        if private_artifact_root is not None:
            persist_team_strength(artifact, artifact_root=private_artifact_root)
        for row in matches:
            observation = lookup[row.fixture.fixture_id]
            h, a = index[observation.home], index[observation.away]
            rates = (
                math.exp(legacy.beta[0] + legacy.beta[1] + legacy.attack[h] - legacy.defence[a]),
                math.exp(legacy.beta[0] + legacy.attack[a] - legacy.defence[h]),
            )
            legacy_metrics.append(prediction_metrics(observation, *rates))
            governed_metrics.append(prediction_metrics(observation, *_rates(artifact, row.fixture)))
        if progress is not None:
            progress(round_number)
    legacy_mean, governed_mean = (
        aggregate(tuple(legacy_metrics)),
        aggregate(tuple(governed_metrics)),
    )
    return seal(
        TeamStrengthReplayReportV1,
        fixture_registry_sha256=fixtures.semantic_sha256,
        source_resources=tuple(source.lineage.resource for source in sources),
        baseline=baseline,
        research_reproduction=ReplayVariant(
            regime="ORIGINAL_RESEARCH_DATE_BEFORE_ORIGIN_METRICS_ONLY",
            metrics=legacy_mean,
            candidate_minus_baseline_exact_log_loss=number(
                float(legacy_mean.exact_log_loss) - float(baseline.exact_log_loss)
            ),
            maximum_gradient_infinity=number(max(legacy_gradients)),
            maximum_iterations=max(legacy_iterations),
            population_sha256s=tuple(legacy_hashes),
            model_state_sha256s=(),
            parameters_retained=False,
        ),
        governed_d_plus_2=ReplayVariant(
            regime="GOVERNED_D_PLUS_2_RECONSTRUCTED",
            metrics=governed_mean,
            candidate_minus_baseline_exact_log_loss=number(
                float(governed_mean.exact_log_loss) - float(baseline.exact_log_loss)
            ),
            maximum_gradient_infinity=number(max(governed_gradients)),
            maximum_iterations=max(governed_iterations),
            population_sha256s=tuple(dataset_hashes),
            model_state_sha256s=tuple(state_hashes),
            parameters_retained=private_artifact_root is not None,
        ),
        differing_training_origins=tuple(differences),
    )


def verify_research_reproduction(report: TeamStrengthReplayReportV1) -> None:
    report = authenticate(report)
    reproduction = report.research_reproduction
    values = (
        float(report.baseline.exact_log_loss),
        float(reproduction.metrics.exact_log_loss),
        float(reproduction.candidate_minus_baseline_exact_log_loss),
    )
    if any(
        abs(value - target) > REPRODUCTION_TOLERANCE
        for value, target in zip(values, (2.951989, 2.887816, -0.064172), strict=True)
    ):
        raise StrengthEvidenceError(
            "locked historical research reproduction differs materially; acceptance blocked"
        )
    if report.governed_d_plus_2.metrics.exact_log_loss >= report.baseline.exact_log_loss:
        raise StrengthEvidenceError(
            "governed candidate does not improve the locked reconstructed baseline"
        )
    if report.differing_training_origins != (34,):
        raise StrengthEvidenceError(
            "legacy/D+2 population difference differs from the preimplementation audit"
        )


def load_replay_golden() -> TeamStrengthReplayReportV1:
    body = (
        files("dmf_pulse.evaluation.resources").joinpath("team_strength_golden.json").read_bytes()
    )
    return authenticate(
        TeamStrengthReplayReportV1.model_validate_json(body), GOLDEN_SEMANTIC_SHA256
    )


def verify_replay_golden(report: TeamStrengthReplayReportV1) -> None:
    verify_research_reproduction(report)
    golden = load_replay_golden()
    for name in (
        "source_resources",
        "fixture_registry_sha256",
        "governance_sha256",
        "identity_registry_sha256",
        "holdout",
        "baseline_seasons",
        "selected_policy",
        "differing_training_origins",
    ):
        if getattr(report, name) != getattr(golden, name):
            raise StrengthEvidenceError("replay source or policy differs from the sealed golden")
    for actual, expected in (
        (report.baseline, golden.baseline),
        (report.research_reproduction.metrics, golden.research_reproduction.metrics),
        (report.governed_d_plus_2.metrics, golden.governed_d_plus_2.metrics),
    ):
        if any(
            abs(float(getattr(actual, key)) - float(getattr(expected, key)))
            > GOLDEN_METRIC_TOLERANCE
            for key in METRICS
        ):
            raise StrengthEvidenceError(
                "replay metric differs from the explicit golden; acceptance blocked"
            )


def run_reconstructed_replay(
    corpus_root: Path,
    *,
    progress: Callable[[int], None] | None = None,
    private_artifact_root: Path | None = None,
) -> TeamStrengthReplayReportV1:
    fixtures, sources = load_reconstructed_corpus(corpus_root)
    report = _replay(
        fixtures, sources, progress=progress, private_artifact_root=private_artifact_root
    )
    verify_replay_golden(report)
    return report
