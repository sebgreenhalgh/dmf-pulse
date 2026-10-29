"""Cutoff-safe descriptive starts/minutes features, independent of prediction models."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal

from dmf_pulse.player_evidence.contracts import (
    EvidenceError,
    EvidenceFeatureSet,
    EvidenceFixture,
    EvidenceSource,
    FeatureRequest,
    IdentityMapping,
    MinuteDistribution,
    Participation,
    ParticipationDataset,
    PlayerFeatures,
    PlayerScope,
    Ratio,
    Reason,
    Role,
    RosterMembership,
    SelectedEvidence,
    Timed,
)
from dmf_pulse.player_evidence.qualification import authenticate_source, decode_dataset


def _mapping(
    dataset: ParticipationDataset,
    kind: Literal["PLAYER", "TEAM"],
    provider_id: str,
    fixture: EvidenceFixture,
    cutoff: datetime,
) -> IdentityMapping | None:
    candidates = [
        item
        for item in dataset.mappings
        if item.kind == kind
        and item.provider_id == provider_id
        and item.season == fixture.season
        and item.effective_from <= fixture.kickoff_at < item.effective_until
        and item.usable_at <= cutoff
    ]
    if len(candidates) > 1:
        raise EvidenceError("CANONICAL_IDENTITY_AMBIGUOUS")
    return candidates[0] if candidates else None


def _ratio(numerator: int, denominator: int) -> Ratio:
    return Ratio(
        numerator=numerator,
        denominator=denominator,
        value=Decimal(numerator) / Decimal(denominator) if denominator else None,
    )


def _distribution(values: list[int]) -> MinuteDistribution:
    return MinuteDistribution(
        sample_count=len(values), counts=dict(sorted(Counter(values).items()))
    )


def _latest_observation(
    dataset: ParticipationDataset,
    membership: RosterMembership,
    cutoff: datetime,
) -> Participation | None:
    eligible = [
        item
        for item in dataset.observations
        if item.season == membership.season
        and item.provider_fixture_id == membership.provider_fixture_id
        and item.provider_player_id == membership.provider_player_id
        and item.usable_at <= cutoff
    ]
    return max(eligible, key=lambda item: item.revision) if eligible else None


def _player_features(
    dataset: ParticipationDataset, request: FeatureRequest, scope: PlayerScope
) -> PlayerFeatures:
    opportunities: list[tuple[EvidenceFixture, RosterMembership, IdentityMapping]] = []
    missing: Counter[Reason] = Counter()
    fixtures = {
        (item.season, item.provider_fixture_id): item
        for item in dataset.fixtures
        if item.season == request.season
        and item.usable_at <= request.cutoff
        and item.finished_at <= request.cutoff
    }
    for membership in dataset.memberships:
        fixture = fixtures.get((membership.season, membership.provider_fixture_id))
        if fixture is None or membership.usable_at > request.cutoff:
            continue
        player_mapping = _mapping(
            dataset, "PLAYER", membership.provider_player_id, fixture, request.cutoff
        )
        if player_mapping is None or player_mapping.canonical_id != scope.player_id:
            continue
        if fixture.kickoff_at < request.history_start:
            missing["OUTSIDE_WINDOW"] += 1
        else:
            opportunities.append((fixture, membership, player_mapping))
    opportunities.sort(key=lambda item: (item[0].kickoff_at, str(item[0].fixture_id)))
    if len(opportunities) > request.maximum_fixtures:
        missing["OUTSIDE_WINDOW"] += len(opportunities) - request.maximum_fixtures
        opportunities = opportunities[-request.maximum_fixtures :]
    if not opportunities:
        missing["NO_ELIGIBLE_HISTORY"] += 1
    role_counts: dict[Role, int] = dict.fromkeys(("START", "BENCH", "OUT", "UNKNOWN"), 0)
    minutes: list[int] = []
    starter_minutes: list[int] = []
    bench_minutes: list[int] = []
    selected: list[SelectedEvidence] = []
    latest: datetime | None = None
    for fixture, membership, player_mapping in opportunities:
        if fixture.status != "FINAL":
            missing["FIXTURE_NOT_FINAL"] += 1
            continue
        team_mapping = _mapping(
            dataset, "TEAM", membership.provider_team_id, fixture, request.cutoff
        )
        if team_mapping is None:
            missing["MAPPING_UNRESOLVED"] += 1
            continue
        if team_mapping.canonical_id != scope.team_id:
            missing["OTHER_TEAM"] += 1
            continue
        if membership.status != "VERIFIED_ELIGIBLE":
            missing["ROSTER_NOT_PROVEN"] += 1
            continue
        observation = _latest_observation(dataset, membership, request.cutoff)
        if observation is None:
            missing["NOT_REPORTED"] += 1
            continue
        if observation.provider_team_id != membership.provider_team_id:
            raise EvidenceError("PARTICIPATION_MEMBERSHIP_TEAM_DISAGREEMENT")
        role_counts[observation.role] += 1
        if observation.role == "UNKNOWN":
            missing["ROLE_UNKNOWN"] += 1
        if observation.minutes is None:
            missing["MINUTES_UNKNOWN"] += 1
        elif observation.minute_convention != "REGULATION_0_90":
            missing["UNSUPPORTED_MINUTE_CONVENTION"] += 1
        else:
            minutes.append(observation.minutes)
            if observation.role == "START":
                starter_minutes.append(observation.minutes)
            elif observation.role == "BENCH":
                bench_minutes.append(observation.minutes)
        latest = max(latest, observation.usable_at) if latest else observation.usable_at
        selected.append(
            SelectedEvidence(
                fixture_id=fixture.fixture_id,
                participation_sha256=observation.semantic_sha256,
                revision=observation.revision,
                identity_mapping_sha256s=tuple(
                    sorted((player_mapping.semantic_sha256, team_mapping.semantic_sha256))
                ),
                membership_sha256=membership.semantic_sha256,
            )
        )
    return PlayerFeatures(
        player_id=scope.player_id,
        team_id=scope.team_id,
        opportunity_count=len(opportunities),
        selected_count=len(selected),
        coverage_status=(
            "NO_ELIGIBLE_HISTORY" if not opportunities else "PARTIAL" if missing else "COMPLETE"
        ),
        role_counts=role_counts,
        start_rate=_ratio(role_counts["START"], len(selected) - role_counts["UNKNOWN"]),
        mean_minutes=_ratio(sum(minutes), len(minutes)),
        sixty_plus_rate=_ratio(sum(value >= 60 for value in minutes), len(minutes)),
        all_minutes=_distribution(minutes),
        starter_minutes=_distribution(starter_minutes),
        bench_minutes=_distribution(bench_minutes),
        latest_observation_age_seconds=(
            int((request.cutoff - latest).total_seconds()) if latest is not None else None
        ),
        missingness=dict(sorted(missing.items())),
        selected=tuple(selected),
    )


def build_features(
    body: bytes, *, source: EvidenceSource, request: FeatureRequest
) -> EvidenceFeatureSet:
    """Authenticate exact owned bytes, resolve vintage identities, and describe evidence.

    No network, persistence, training, production model or Stage-7 export is performed.
    Unknown roles are never inferred from positive minutes. Every mean/rate carries
    its own denominator; empirical support is not a predictive uncertainty claim.
    """
    authenticate_source(body, source)
    request = FeatureRequest.model_validate_json(request.model_dump_json())
    dataset = decode_dataset(body)
    if dataset.source_id != source.source_id or dataset.mode != source.mode:
        raise EvidenceError("SOURCE_DATASET_IDENTITY_DISAGREEMENT")
    # Fixed arithmetic policy makes the feature identity independent of caller context.
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        result = EvidenceFeatureSet(
            source=source,
            request=request,
            players=tuple(_player_features(dataset, request, item) for item in request.players),
            unattributed_player_membership_count=_unresolved_player_mapping_count(
                dataset, request.cutoff, request.season
            ),
        )
    return result


def _unresolved_player_mapping_count(
    dataset: ParticipationDataset, cutoff: datetime, season: str
) -> int:
    """Unassignable eligible roster rows cannot be attributed using future mappings."""
    checked = Timed(observed_at=cutoff, usable_at=cutoff).usable_at
    fixtures = {(item.season, item.provider_fixture_id): item for item in dataset.fixtures}
    count = 0
    for membership in dataset.memberships:
        fixture = fixtures[(membership.season, membership.provider_fixture_id)]
        if (
            fixture.season == season
            and fixture.usable_at <= checked
            and membership.usable_at <= checked
            and _mapping(dataset, "PLAYER", membership.provider_player_id, fixture, checked) is None
        ):
            count += 1
    return count
