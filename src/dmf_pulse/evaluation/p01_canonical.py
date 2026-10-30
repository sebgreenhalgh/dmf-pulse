"""P01-only nongenerative canonical admission; no acquisition or model generation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.p01_frozen_view import P01FrozenScoringView, _read_pinned_representation
from dmf_pulse.evaluation.team_strength_prospective import (
    PublicProspectiveScoreV1,
    score_public_fixture_labels,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MAX_BYTES,
    FixtureRegistration,
    FrozenEvidence,
    ParsedSnapshot,
    SealedEvidence,
    SourceLineage,
    StrengthEvidenceError,
    authenticate,
    parse_snapshot,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    POLICY_REPOSITORY_PATH,
    POLICY_RESOURCE,
    _resource_bytes,
    eligibility_not_before,
)

FORECAST_SHA: Final = "96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"
FORECAST_BYTE_SHA: Final = "e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee"
FORECAST_BYTES = 38_208_223
FIXTURE_SHA: Final = "de447eb368a807d4edf701a75c094a8b3f4925aa3e87cbff9b9f4fadd63eba18"
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Ref = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
IDENTITY_RESOURCE = "p01_original_identity.json"
IDENTITY_BYTE_SHA = "e4035f285d8dd574808fa2084420b51936e3e1e27f43f8dbb5f7e275dbd60cb4"
CRITICAL_COMPONENTS = frozenset(
    {
        "evaluation/p01_canonical.py",
        "evaluation/p01_frozen_view.py",
        "evaluation/team_strength_prospective.py",
        "ingestion/openfootball/team_strength_data.py",
        "ingestion/openfootball/team_strength_governance.py",
        POLICY_RESOURCE,
        "evaluation/resources/" + IDENTITY_RESOURCE,
    }
)


class OriginalFixtureIdentity(FrozenEvidence):
    fixture: FixtureRegistration
    scheduled_date: date
    products: tuple[str, ...]


class OriginalP01Identity(FrozenEvidence):
    schema_version: Literal["p01-original-frozen-identity-v1"]
    forecast_sha256: Sha
    forecast_byte_sha256: Sha
    forecast_bytes: int
    forecast_origin: datetime
    frozen_at: datetime
    dataset_mode: Literal["LIVE_OBSERVED"]
    model_sha256: Sha
    source_lineage_sha256: Sha
    training_dataset_sha256: Sha
    fixture_registry_sha256: Sha
    draw_policy_sha256: Sha
    fixtures: tuple[OriginalFixtureIdentity, ...] = Field(min_length=10, max_length=10)
    actual_outcome_labels_read: Literal[False]
    model_fit_or_draw_or_freeze_calls: Literal[0]


def original_identity() -> OriginalP01Identity:
    body = files("dmf_pulse.evaluation.resources").joinpath(IDENTITY_RESOURCE).read_bytes()
    if hashlib.sha256(body).hexdigest() != IDENTITY_BYTE_SHA:
        raise StrengthEvidenceError("P01_ORIGINAL_IDENTITY_RESOURCE_CHANGED")
    return OriginalP01Identity.model_validate_json(body)


class CanonicalCodeBinding(SealedEvidence):
    schema_version: Literal["p01-canonical-code-binding-v1"] = "p01-canonical-code-binding-v1"
    state: Literal["PROPOSED_UNACCEPTED"] = "PROPOSED_UNACCEPTED"
    forecast_sha256: Literal["96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"] = (
        FORECAST_SHA
    )
    forecast_byte_sha256: Literal[
        "e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee"
    ] = FORECAST_BYTE_SHA
    fixture_registry_sha256: Literal[
        "de447eb368a807d4edf701a75c094a8b3f4925aa3e87cbff9b9f4fadd63eba18"
    ] = FIXTURE_SHA
    original_code_commit: Literal["3815152e978dd55e1dc1f115055050d4ed6b1735"] = (
        "3815152e978dd55e1dc1f115055050d4ed6b1735"
    )
    historical_original_protocol_sha256: Literal[
        "93b9c2e8a0b0f6c00e1299cb410784daabf1eb04efa01baaab5f10d85d10e029"
    ] = "93b9c2e8a0b0f6c00e1299cb410784daabf1eb04efa01baaab5f10d85d10e029"
    components: tuple[tuple[str, Sha], ...] = Field(min_length=6)
    governance_history: tuple[tuple[str, Sha], ...] = Field(min_length=3)
    outcome_route: Literal["QUALIFIED_CANONICAL_OPENFOOTBALL_ONLY"] = (
        "QUALIFIED_CANONICAL_OPENFOOTBALL_ONLY"
    )
    source_policy_change: Literal["POST_ORIGIN_CODE_ADMISSION_AMENDMENT_DISCLOSED"] = (
        "POST_ORIGIN_CODE_ADMISSION_AMENDMENT_DISCLOSED"
    )
    evaluation: Literal["DESCRIPTIVE_TEN_FIXTURES_NO_TUNING_NO_PROMOTION"] = (
        "DESCRIPTIVE_TEN_FIXTURES_NO_TUNING_NO_PROMOTION"
    )
    acquisition_authorized: Literal[False] = False
    fallback_attempts_authorized: Literal[False] = False

    @model_validator(mode="after")
    def complete_components(self) -> Self:
        paths = tuple(path for path, _ in self.components)
        if paths != tuple(sorted(set(paths))) or not set(paths) >= CRITICAL_COMPONENTS:
            raise ValueError("complete canonical code closure required")
        if tuple(path for path, _ in self.governance_history) != (
            "MODEL_GOVERNANCE_AT_P01_ORIGIN",
            "A02_POST_ORIGIN_SOURCE_AMENDMENT_HISTORY_ONLY",
            "A02_PERMANENT_CONSUMPTION",
            "A03_ONE_SHOT_HISTORICAL_AUTHORITY",
        ):
            raise ValueError("original and post-origin governance history required")
        return self


class AcceptedCanonicalBinding(FrozenEvidence):
    code_binding_sha256: Sha
    owner_decision_ref: Ref
    independent_review_sha256: Sha
    accepted_at: datetime


class QualifiedCanonicalOutcome(FrozenEvidence):
    lineage: SourceLineage
    qualification_decision_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
    qualification_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_evidence_sha256: Sha
    parsed_snapshot_sha256: Sha
    qualified_at: datetime
    purpose: Literal["P01_CANONICAL_DESCRIPTIVE_SCORING_ONLY"] = (
        "P01_CANONICAL_DESCRIPTIVE_SCORING_ONLY"
    )

    @model_validator(mode="after")
    def completed_qualification(self) -> Self:
        if self.qualified_at < self.lineage.usable_at:
            raise ValueError("qualification predates available source evidence")
        return self


class CanonicalAcceptances(FrozenEvidence):
    schema_version: Literal["p01-canonical-acceptances-v1"] = "p01-canonical-acceptances-v1"
    accepted_code_bindings: tuple[AcceptedCanonicalBinding, ...] = ()
    qualified_outcomes: tuple[QualifiedCanonicalOutcome, ...] = ()

    @model_validator(mode="after")
    def unique_accepted_identities(self) -> Self:
        bindings = [row.code_binding_sha256 for row in self.accepted_code_bindings]
        outcomes = [row.lineage.resource.content_sha256 for row in self.qualified_outcomes]
        if len(bindings) != len(set(bindings)) or len(outcomes) != len(set(outcomes)):
            raise ValueError("canonical authority identity is ambiguous")
        return self


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate canonical authority field")
        result[key] = value
    return result


def _acceptances_or_none() -> CanonicalAcceptances | None:
    """No caller path, status flag or resealed proposal can accept this binding."""
    try:
        body = (
            files("dmf_pulse.evaluation.resources")
            .joinpath("p01_canonical_acceptances.json")
            .read_bytes()
        )
        if len(body) > 131072:
            raise ValueError("canonical authority exceeds bound")
        value = json.loads(body, object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "accepted_code_bindings",
            "qualified_outcomes",
        }:
            raise ValueError("canonical authority schema differs")
        return CanonicalAcceptances.model_validate_json(json.dumps(value, allow_nan=False))
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def installed_canonical_acceptances() -> CanonicalAcceptances:
    result = _acceptances_or_none()
    if result is None:
        raise StrengthEvidenceError("P01_CANONICAL_AUTHORITY_INVALID")
    return result


def propose_canonical_binding() -> CanonicalCodeBinding:
    original_identity()
    root = Path(str(files("dmf_pulse")))
    paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    components = (
        ("evaluation/resources/" + IDENTITY_RESOURCE, IDENTITY_BYTE_SHA),
        *((path, hashlib.sha256(root.joinpath(path).read_bytes()).hexdigest()) for path in paths),
        (
            POLICY_RESOURCE,
            hashlib.sha256(
                _resource_bytes(POLICY_RESOURCE, POLICY_REPOSITORY_PATH, None)
            ).hexdigest(),
        ),
        (
            "ingestion/resources/openfootball_historical_team_identity.json",
            hashlib.sha256(
                _resource_bytes(
                    "ingestion/resources/openfootball_historical_team_identity.json",
                    "config/providers/openfootball_historical_team_identity.json",
                    None,
                )
            ).hexdigest(),
        ),
        (
            "ingestion/resources/openfootball_profiles.json",
            hashlib.sha256(
                _resource_bytes(
                    "ingestion/resources/openfootball_profiles.json",
                    "config/rights/openfootball_profiles.json",
                    None,
                )
            ).hexdigest(),
        ),
    )
    history = tuple(
        (ref, hashlib.sha256(_resource_bytes(resource, repository_path, None)).hexdigest())
        for ref, resource, repository_path in (
            ("MODEL_GOVERNANCE_AT_P01_ORIGIN", POLICY_RESOURCE, POLICY_REPOSITORY_PATH),
            (
                "A02_POST_ORIGIN_SOURCE_AMENDMENT_HISTORY_ONLY",
                "evaluation/resources/evaluation/team_strength_p01_fallback_a02.json",
                "config/evaluation/team_strength_p01_fallback_a02.json",
            ),
            (
                "A02_PERMANENT_CONSUMPTION",
                "evaluation/resources/evaluation/team_strength_p01_a02_consumption.json",
                "config/evaluation/team_strength_p01_a02_consumption.json",
            ),
            (
                "A03_ONE_SHOT_HISTORICAL_AUTHORITY",
                "evaluation/resources/evaluation/team_strength_p01_fallback_a03.json",
                "config/evaluation/team_strength_p01_fallback_a03.json",
            ),
        )
    )
    return seal(
        CanonicalCodeBinding,
        components=tuple(sorted(components)),
        governance_history=history,
    )


def _regular_or_none(
    path: Path, limit: int, *, allowed_sizes: frozenset[int] | None = None
) -> bytes | None:
    try:
        raw_path = str(path)
        if (
            raw_path.startswith(("\\\\", "//"))
            or "://" in raw_path
            or any(
                part.lower() in {".env", ".aws", ".ssh", "credentials", "secrets"}
                or "credential" in part.lower()
                or "secret" in part.lower()
                or part.lower().startswith(".env.")
                for part in path.parts
            )
        ):
            return None
        for item in (path, *path.parents):
            metadata = item.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                return None
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size > limit
                or path.is_symlink()
                or (allowed_sizes is not None and before.st_size not in allowed_sizes)
            ):
                return None
            body = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if len(body) != before.st_size or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            return None
        return body
    except (OSError, ValueError):
        return None


def _authenticate_original_p01(path: Path) -> P01FrozenScoringView:
    raw = _regular_or_none(path, FORECAST_BYTES, allowed_sizes=frozenset({FORECAST_BYTES}))
    if raw is None or len(raw) != FORECAST_BYTES:
        raise StrengthEvidenceError("P01_FORECAST_BOUNDED_REGULAR_FILE_REQUIRED")
    view = _read_pinned_representation(
        raw, expected_byte_sha256=FORECAST_BYTE_SHA, expected_semantic_sha256=FORECAST_SHA
    )
    identity = original_identity()
    if (
        view.fixture_registry.semantic_sha256 != FIXTURE_SHA
        or view.artifact.model.semantic_sha256 != identity.model_sha256
        or view.training_dataset.semantic_sha256 != identity.training_dataset_sha256
        or view.public_schedule.lineage.semantic_sha256 != identity.source_lineage_sha256
        or view.draw_set.draw_policy_sha256 != identity.draw_policy_sha256
        or view.forecast_origin != identity.forecast_origin
        or view.frozen_at != identity.frozen_at
        or tuple(
            (row.fixture, row.scheduled_date, tuple(item.product for item in row.distributions))
            for row in view.forecasts
        )
        != tuple((row.fixture, row.scheduled_date, row.products) for row in identity.fixtures)
    ):
        raise StrengthEvidenceError("P01_ORIGINAL_COHORT_CHANGED")
    return view


def _original_p01_scope(path: Path) -> P01FrozenScoringView | str:
    try:
        return _authenticate_original_p01(path)
    except StrengthEvidenceError as error:
        code = str(error)
        return code if code in _PUBLIC_CODES else "P01_ORIGINAL_FORECAST_INVALID"
    except (ValueError, OSError, TypeError):
        return "P01_ORIGINAL_FORECAST_INVALID"


def authenticate_original_p01(path: Path) -> P01FrozenScoringView:
    result = _original_p01_scope(path)
    if isinstance(result, str):
        raise StrengthEvidenceError(result)
    return result


class CanonicalFinalLabel(FrozenEvidence):
    fixture_id: UUID
    originally_scheduled_date: date
    actually_played_date: date
    home_goals: int = Field(ge=0, le=36)
    away_goals: int = Field(ge=0, le=36)
    outcome_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def admit_canonical_labels(
    forecast: P01FrozenScoringView, outcomes: ParsedSnapshot, *, as_of: datetime
) -> tuple[CanonicalFinalLabel, ...]:
    """Admission only. All ten are checked before the first metric is calculated."""
    if type(forecast) is not P01FrozenScoringView:
        raise StrengthEvidenceError("P01_NONGENERATIVE_TYPED_VIEW_REQUIRED")
    forecast = authenticate(P01FrozenScoringView.model_validate_json(forecast.model_dump_json()))
    as_of = FrozenEvidence.utc_datetimes(as_of)
    outcomes = authenticate(outcomes)
    if not forecast.frozen_at < outcomes.lineage.usable_at <= as_of:
        raise StrengthEvidenceError("P01_OUTCOME_TEMPORAL_ADMISSION_FAILED")
    if outcomes.fixture_registry_sha256 != forecast.fixture_registry.semantic_sha256:
        raise StrengthEvidenceError("P01_OUTCOME_COHORT_MISMATCH")
    observed = {row.fixture.fixture_id: row for row in outcomes.matches}
    if len(observed) != len(outcomes.matches) or len(forecast.forecasts) != 10:
        raise StrengthEvidenceError("P01_EXACT_TEN_UNIQUE_FIXTURES_REQUIRED")
    labels = []
    for prediction in forecast.forecasts:
        row = observed.get(prediction.fixture.fixture_id)
        if (
            row is None
            or row.fixture != prediction.fixture
            or row.finality != "FULL_TIME"
            or type(row.home_goals) is not int
            or type(row.away_goals) is not int
        ):
            raise StrengthEvidenceError("P01_COMPLETE_EXACT_FINALS_REQUIRED")
        if (
            row.source_match_date <= forecast.frozen_at.date()
            or eligibility_not_before(row.source_match_date) > as_of
            or outcomes.lineage.received_at.date() < row.source_match_date
            or not 0 <= row.home_goals <= 36
            or not 0 <= row.away_goals <= 36
        ):
            raise StrengthEvidenceError("P01_FINAL_LABEL_ADMISSION_FAILED")
        labels.append(
            CanonicalFinalLabel(
                fixture_id=row.fixture.fixture_id,
                originally_scheduled_date=prediction.scheduled_date,
                actually_played_date=row.source_match_date,
                home_goals=row.home_goals,
                away_goals=row.away_goals,
                outcome_row_sha256=row.source_row_sha256,
            )
        )
    if len({row.fixture_id for row in labels}) != 10:
        raise StrengthEvidenceError("P01_EXACT_TEN_UNIQUE_FIXTURES_REQUIRED")
    return tuple(labels)


class CanonicalP01Score(SealedEvidence):
    schema_version: Literal["p01-nongenerative-canonical-score-v1"] = (
        "p01-nongenerative-canonical-score-v1"
    )
    code_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_qualification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualified_outcome: QualifiedCanonicalOutcome
    accepted_binding: AcceptedCanonicalBinding
    acceptance_registry_sha256: Sha
    outcome_provenance: Literal["OPENFOOTBALL_QUALIFIED_CANONICAL"] = (
        "OPENFOOTBALL_QUALIFIED_CANONICAL"
    )
    policy_history: Literal["POST_ORIGIN_NONGENERATIVE_ADMISSION_AMENDMENT"] = (
        "POST_ORIGIN_NONGENERATIVE_ADMISSION_AMENDMENT"
    )
    labels: tuple[CanonicalFinalLabel, ...] = Field(min_length=10, max_length=10)
    score: PublicProspectiveScoreV1
    fixture_outcome_count: Literal[10] = 10
    confirmatory_promotion_evidence: Literal[False] = False
    model_tuning_authorized: Literal[False] = False

    @model_validator(mode="after")
    def exact_score_population(self) -> Self:
        ids = tuple(row.fixture_id for row in self.labels)
        identity = original_identity()
        products = (
            "LEAGUE_BASELINE",
            "PLUG_IN_TEAM_STRENGTH_SHADOW",
            "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW",
        )
        if (
            ids != tuple(sorted(set(ids)))
            or ids != tuple(row.fixture.fixture_id for row in identity.fixtures)
            or self.score.forecast_sha256 != FORECAST_SHA
            or self.score.dataset_mode != "LIVE_OBSERVED"
            or tuple((fixture, product) for fixture, product, _ in self.score.scores)
            != tuple((fixture, product) for fixture in ids for product in products)
            or any(len(metrics) != 49 for _, _, metrics in self.score.scores)
        ):
            raise ValueError(
                "canonical score must retain ten exact fixtures and thirty complete products"
            )
        if self.score.draw_policy_sha256 != identity.draw_policy_sha256:
            raise ValueError("original draw policy differs")
        by_id = {row.fixture_id: row for row in self.labels}
        scheduled = {row.fixture.fixture_id: row.scheduled_date for row in identity.fixtures}
        if (
            self.accepted_binding.code_binding_sha256 != self.code_binding_sha256
            or self.accepted_binding.accepted_at > self.score.scored_at
            or any(
                row.originally_scheduled_date != scheduled[row.fixture_id]
                or row.actually_played_date <= identity.frozen_at.date()
                or eligibility_not_before(row.actually_played_date) > self.score.scored_at
                for row in self.labels
            )
        ):
            raise ValueError("canonical acceptance or label chronology differs")
        if (
            self.outcome_qualification_sha256
            != canonical_sha256(self.qualified_outcome.model_dump(mode="json"))
            or self.qualified_outcome.code_binding_sha256 != self.code_binding_sha256
            or self.qualified_outcome.qualified_at > self.score.scored_at
            or self.score.outcome_snapshot_sha256 != self.qualified_outcome.parsed_snapshot_sha256
            or any(
                self.qualified_outcome.lineage.received_at.date() < row.actually_played_date
                for row in self.labels
            )
        ):
            raise ValueError("qualified outcome provenance differs")
        for fixture, _, pairs in self.score.scores:
            metrics, label = dict(pairs), by_id[fixture]
            hg, ag = label.home_goals, label.away_goals
            outcomes = {
                "home_win": hg > ag,
                "draw": hg == ag,
                "away_win": hg < ag,
                "home_clean_sheet": ag == 0,
                "away_clean_sheet": hg == 0,
                **{f"total_over_{line}.5": hg + ag > line for line in range(6)},
            }
            if any(
                metrics[event + "_outcome"] != int(actual) for event, actual in outcomes.items()
            ):
                raise ValueError("score indicators differ from admitted final labels")
        return self


def _score_original_p01(
    forecast_path: Path, outcome_path: Path, *, as_of: datetime
) -> CanonicalP01Score:
    as_of = FrozenEvidence.utc_datetimes(as_of)
    binding = propose_canonical_binding()
    registry = installed_canonical_acceptances()
    accepted = [
        row
        for row in registry.accepted_code_bindings
        if row.code_binding_sha256 == binding.semantic_sha256 and row.accepted_at <= as_of
    ]
    if len(accepted) != 1:
        raise StrengthEvidenceError("P01_CANONICAL_CODE_BINDING_NOT_ACCEPTED")
    candidates = [
        row
        for row in registry.qualified_outcomes
        if row.code_binding_sha256 == binding.semantic_sha256 and row.qualified_at <= as_of
    ]
    if not candidates:
        raise StrengthEvidenceError("P01_QUALIFIED_CANONICAL_OUTCOME_REQUIRED")
    raw = _regular_or_none(
        outcome_path,
        MAX_BYTES,
        allowed_sizes=frozenset(row.lineage.resource.byte_length for row in candidates),
    )
    if raw is None:
        raise StrengthEvidenceError("P01_QUALIFIED_OUTCOME_BYTES_REQUIRED")
    digest = hashlib.sha256(raw).hexdigest()
    rows = [
        row
        for row in registry.qualified_outcomes
        if row.lineage.resource.content_sha256 == digest
        and row.code_binding_sha256 == binding.semantic_sha256
    ]
    if len(rows) != 1:
        raise StrengthEvidenceError("P01_QUALIFIED_CANONICAL_OUTCOME_REQUIRED")
    qualified = rows[0]
    if qualified.qualified_at > as_of or as_of > datetime.now(UTC):
        raise StrengthEvidenceError("P01_CANONICAL_DECISION_TIME_INVALID")
    forecast = authenticate_original_p01(forecast_path)
    # Reparse the original provider bytes, including Git blob, CC0, names, season
    # and orientation checks. A caller's parsed snapshot cannot substitute.
    outcomes = parse_snapshot(
        raw,
        lineage=qualified.lineage,
        fixtures=forecast.fixture_registry,
        expected_fixture_registry_sha256=FIXTURE_SHA,
    )
    if outcomes.semantic_sha256 != qualified.parsed_snapshot_sha256:
        raise StrengthEvidenceError("P01_QUALIFIED_OUTCOME_SNAPSHOT_MISMATCH")
    labels = admit_canonical_labels(forecast, outcomes, as_of=as_of)
    by_id = {row.fixture_id: row for row in labels}
    scores = tuple(
        row
        for prediction in forecast.forecasts
        for row in score_public_fixture_labels(
            prediction,
            hg=by_id[prediction.fixture.fixture_id].home_goals,
            ag=by_id[prediction.fixture.fixture_id].away_goals,
        )
    )
    score = seal(
        PublicProspectiveScoreV1,
        forecast_sha256=forecast.semantic_sha256,
        outcome_snapshot_sha256=outcomes.semantic_sha256,
        scored_at=as_of,
        dataset_mode=forecast.dataset_mode,
        draw_policy_sha256=forecast.draw_set.draw_policy_sha256,
        scores=scores,
    )
    final_raw = _regular_or_none(
        forecast_path, FORECAST_BYTES, allowed_sizes=frozenset({FORECAST_BYTES})
    )
    if (
        final_raw is None
        or hashlib.sha256(final_raw).hexdigest() != FORECAST_BYTE_SHA
        or propose_canonical_binding() != binding
        or installed_canonical_acceptances() != registry
    ):
        raise StrengthEvidenceError("P01_IMMUTABLE_INPUT_CHANGED_DURING_SCORING")
    return seal(
        CanonicalP01Score,
        code_binding_sha256=binding.semantic_sha256,
        outcome_qualification_sha256=canonical_sha256(qualified.model_dump(mode="json")),
        qualified_outcome=qualified,
        labels=labels,
        score=score,
        accepted_binding=accepted[0],
        acceptance_registry_sha256=canonical_sha256(registry.model_dump(mode="json")),
    )


_PUBLIC_CODES = frozenset(
    {
        "P01_CANONICAL_CODE_BINDING_NOT_ACCEPTED",
        "P01_QUALIFIED_OUTCOME_BYTES_REQUIRED",
        "P01_QUALIFIED_CANONICAL_OUTCOME_REQUIRED",
        "P01_CANONICAL_DECISION_TIME_INVALID",
        "P01_FORECAST_BOUNDED_REGULAR_FILE_REQUIRED",
        "P01_FORECAST_BYTE_IDENTITY_MISMATCH",
        "P01_CANONICAL_AUTHORITY_INVALID",
        "P01_ORIGINAL_COHORT_CHANGED",
        "P01_OUTCOME_TEMPORAL_ADMISSION_FAILED",
        "P01_OUTCOME_COHORT_MISMATCH",
        "P01_EXACT_TEN_UNIQUE_FIXTURES_REQUIRED",
        "P01_COMPLETE_EXACT_FINALS_REQUIRED",
        "P01_FINAL_LABEL_ADMISSION_FAILED",
    }
)


def _score_scope(
    forecast_path: Path, outcome_path: Path, as_of: datetime
) -> CanonicalP01Score | str:
    try:
        return _score_original_p01(forecast_path, outcome_path, as_of=as_of)
    except StrengthEvidenceError as error:
        code = str(error)
        return code if code in _PUBLIC_CODES else "P01_CANONICAL_ADMISSION_INVALID"
    except (ValueError, OSError, TypeError):
        return "P01_CANONICAL_ADMISSION_INVALID"


def score_original_p01(
    forecast_path: Path, outcome_path: Path, *, as_of: datetime
) -> CanonicalP01Score:
    """Discard raw source/parser exception frames before any public refusal."""
    result = _score_scope(forecast_path, outcome_path, as_of)
    if isinstance(result, str):
        raise StrengthEvidenceError(result)
    return result


def _write_artifact_or_none(
    path: Path, value: CanonicalCodeBinding | CanonicalP01Score
) -> str | None:
    from dmf_pulse.assurance.canonical import canonical_json_bytes

    try:
        if path.is_symlink():
            return None
        if type(value) not in {CanonicalCodeBinding, CanonicalP01Score}:
            return None
        value = authenticate(value)
        body = canonical_json_bytes(value.model_dump(mode="json")) + b"\n"
        with path.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(body).hexdigest()
    except (OSError, ValueError):
        return None


def write_canonical_artifact(path: Path, value: CanonicalCodeBinding | CanonicalP01Score) -> str:
    result = _write_artifact_or_none(path, value)
    if result is None:
        raise StrengthEvidenceError("P01_CANONICAL_ARTIFACT_WRITE_FAILED")
    return result
