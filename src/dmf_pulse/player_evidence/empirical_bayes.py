"""Deterministic Gamma-Poisson partial pooling for approved player-event fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import pow
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.models import (
    CaptureAccessMode,
    CurrentPlayer,
    CurrentPlayerCatalogue,
    EmpiricalBayesParameters,
    HistoryPastSeason,
    PlayerHistoryEvidence,
    PlayerPosterior,
    PlayerPosteriorArtifact,
    PosteriorRate,
    RolePooledPrior,
    TacticalRole,
)
from dmf_pulse.player_evidence.role_priors import (
    RolePriorCandidateArtifact,
    role_priors_from_candidate,
)


def resolve_role_prior(
    player: CurrentPlayer,
    tactical_role: TacticalRole,
    priors: Sequence[RolePooledPrior],
) -> RolePooledPrior:
    """Resolve explicit role, position, then generic priors without guessing roles."""

    candidates = (
        (player.position, tactical_role) if tactical_role is not TacticalRole.UNKNOWN else None,
        (player.position, None),
        (None, None),
    )
    for key in candidates:
        if key is None:
            continue
        matches = [prior for prior in priors if (prior.position, prior.tactical_role) == key]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise IngestionError("PRIOR_AMBIGUOUS", "role-prior group is ambiguous")
    raise IngestionError("PRIOR_MISSING", "no role, position, or generic prior is available")


def _weighted_history(
    seasons: Sequence[HistoryPastSeason], *, parameters: EmpiricalBayesParameters
) -> tuple[float, dict[str, float]]:
    if not seasons:
        return 0.0, {name: 0.0 for name in ("goals", "assists", "yellow", "red", "saves")}
    current_start = 2026
    exposure = 0.0
    totals = {name: 0.0 for name in ("goals", "assists", "yellow", "red", "saves")}
    for season in seasons:
        end_year = int(season.season[:4]) + 1
        age = max(0, current_start - end_year)
        weight = pow(0.5, age / parameters.recency_half_life_seasons)
        exposure += weight * season.minutes / 90.0
        totals["goals"] += weight * season.goals
        totals["assists"] += weight * season.assists
        totals["yellow"] += weight * season.yellow_cards
        totals["red"] += weight * season.red_cards
        totals["saves"] += weight * season.saves
    return exposure, totals


def gamma_poisson_posterior(
    *, prior_mean_per90: float, kappa: float, exposure_full_matches: float, events: float
) -> PosteriorRate:
    """Return the analytical Gamma-Poisson posterior mean and variance."""

    if prior_mean_per90 < 0.0 or kappa <= 0.0 or exposure_full_matches < 0.0 or events < 0.0:
        raise IngestionError("EB_INPUT_INVALID", "Gamma-Poisson inputs must be non-negative")
    alpha = prior_mean_per90 * kappa + events
    beta = kappa + exposure_full_matches
    return PosteriorRate(mean_per90=alpha / beta, variance_per90=alpha / (beta * beta))


def _posterior_player(
    *,
    player: CurrentPlayer,
    history: PlayerHistoryEvidence | None,
    prior: RolePooledPrior,
    parameters: EmpiricalBayesParameters,
    source_locator: str,
    source_observed_at: datetime,
    usable_at: datetime,
    schema_fingerprint: str,
    source_hash: str | None,
    rights_profile_id: str,
) -> PlayerPosterior:
    seasons = history.seasons if history is not None else ()
    exposure, totals = _weighted_history(seasons, parameters=parameters)
    return PlayerPosterior(
        player_id=player.player_id,
        source_player_id=player.source_player_id,
        history_seasons_included=tuple(season.season for season in seasons),
        goal_rate=gamma_poisson_posterior(
            prior_mean_per90=prior.goal_rate_per90,
            kappa=parameters.goal_kappa_full_match_equivalents,
            exposure_full_matches=exposure,
            events=totals["goals"],
        ),
        assist_rate=gamma_poisson_posterior(
            prior_mean_per90=prior.assist_rate_per90,
            kappa=parameters.assist_kappa_full_match_equivalents,
            exposure_full_matches=exposure,
            events=totals["assists"],
        ),
        yellow_rate=gamma_poisson_posterior(
            prior_mean_per90=prior.yellow_rate_per90,
            kappa=parameters.yellow_kappa_full_match_equivalents,
            exposure_full_matches=exposure,
            events=totals["yellow"],
        ),
        red_rate=gamma_poisson_posterior(
            prior_mean_per90=prior.red_rate_per90,
            kappa=parameters.red_kappa_full_match_equivalents,
            exposure_full_matches=exposure,
            events=totals["red"],
        ),
        save_rate=gamma_poisson_posterior(
            prior_mean_per90=prior.save_rate_per90,
            kappa=parameters.save_kappa_full_match_equivalents,
            exposure_full_matches=exposure,
            events=totals["saves"],
        ),
        posterior_effective_minutes=exposure * 90.0,
        shrinkage_group_id=prior.shrinkage_group_id,
        prior_version=prior.prior_version,
        source_locator=source_locator,
        source_observed_at=source_observed_at,
        usable_at=usable_at,
        schema_fingerprint=schema_fingerprint,
        source_hash=source_hash,
        rights_profile_id=rights_profile_id,
        access_mode=CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT,
    )


def compile_posterior_artifact(
    *,
    catalogue: CurrentPlayerCatalogue,
    histories: Sequence[PlayerHistoryEvidence],
    role_priors: Sequence[RolePooledPrior] | RolePriorCandidateArtifact,
    tactical_roles: Mapping[UUID, TacticalRole],
    parameters: EmpiricalBayesParameters,
    information_cutoff: datetime,
    source_observed_at: datetime,
    usable_at: datetime,
    produced_at: datetime,
    source_locator: str,
    schema_fingerprint: str,
    rights_profile_id: str,
    source_hash: str | None = None,
    source_hashes: Mapping[UUID, str | None] | None = None,
    source_observed_ats: Mapping[UUID, datetime] | None = None,
) -> PlayerPosteriorArtifact:
    """Compile only posterior parameters from transient history interpretations.

    The function deliberately has no path, byte-string, logging, or persistence
    argument.  Callers cannot use it to retain raw FPL history rows.
    """

    resolved_role_priors = (
        role_priors_from_candidate(role_priors)
        if isinstance(role_priors, RolePriorCandidateArtifact)
        else role_priors
    )
    for label, value in (
        ("information_cutoff", information_cutoff),
        ("source_observed_at", source_observed_at),
        ("usable_at", usable_at),
        ("produced_at", produced_at),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise IngestionError("TEMPORAL_INVALID", f"{label} must be timezone-aware")
    cutoff = information_cutoff.astimezone(UTC)
    observed = source_observed_at.astimezone(UTC)
    usable = usable_at.astimezone(UTC)
    if observed > usable or usable > cutoff or produced_at.astimezone(UTC) < usable:
        raise IngestionError("POST_CUTOFF", "posterior temporal order is invalid")

    history_by_player = {history.player_id: history for history in histories}
    if len(history_by_player) != len(histories):
        raise IngestionError("IDENTITY_CONFLICT", "duplicate player history evidence")
    catalogue_by_player = {player.player_id: player for player in catalogue.players}
    if any(
        history.player_id not in catalogue_by_player
        or history.source_player_id != catalogue_by_player[history.player_id].source_player_id
        for history in histories
    ):
        raise IngestionError("IDENTITY_CONFLICT", "history identity is not in current catalogue")
    if any(
        season.season >= catalogue.season_code
        for history in histories
        for season in history.seasons
    ):
        raise IngestionError(
            "HISTORY_CURRENT_SEASON_FORBIDDEN",
            "posterior compilation accepts completed historical seasons only",
        )
    if source_hash is not None and source_hashes is not None:
        raise IngestionError(
            "SOURCE_HASH_AMBIGUOUS", "provide a global source hash or per-player source hashes"
        )
    allowed_ids = set(catalogue_by_player)
    if source_hashes is not None and set(source_hashes) - allowed_ids:
        raise IngestionError(
            "IDENTITY_CONFLICT", "source hashes include an unknown catalogue player"
        )
    if source_observed_ats is not None:
        if set(source_observed_ats) != set(history_by_player):
            raise IngestionError(
                "IDENTITY_CONFLICT",
                "successful receipt times must map one-to-one to captured histories",
            )
        for receipt in source_observed_ats.values():
            if receipt.tzinfo is None or receipt.utcoffset() is None:
                raise IngestionError(
                    "TEMPORAL_INVALID", "successful receipt time must be timezone-aware"
                )
            if receipt.astimezone(UTC) > usable:
                raise IngestionError(
                    "POST_CUTOFF", "successful receipt is after posterior usability"
                )

    players = []
    for player in catalogue.players:
        prior = resolve_role_prior(
            player,
            tactical_roles.get(player.player_id, TacticalRole.UNKNOWN),
            resolved_role_priors,
        )
        players.append(
            _posterior_player(
                player=player,
                history=history_by_player.get(player.player_id),
                prior=prior,
                parameters=parameters,
                source_locator=source_locator,
                source_observed_at=(
                    source_observed_ats[player.player_id].astimezone(UTC)
                    if source_observed_ats is not None and player.player_id in history_by_player
                    else observed
                ),
                usable_at=usable,
                schema_fingerprint=schema_fingerprint,
                source_hash=(
                    source_hashes.get(player.player_id)
                    if source_hashes is not None
                    else source_hash
                ),
                rights_profile_id=rights_profile_id,
            )
        )
    ordered = tuple(sorted(players, key=lambda item: str(item.player_id)))
    provisional = PlayerPosteriorArtifact.model_construct(
        information_cutoff=cutoff,
        produced_at=produced_at.astimezone(UTC),
        parameters=parameters,
        players=ordered,
        artifact_sha256="0" * 64,
    )
    return PlayerPosteriorArtifact(
        information_cutoff=cutoff,
        produced_at=produced_at.astimezone(UTC),
        parameters=parameters,
        players=ordered,
        artifact_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"artifact_sha256"})
        ),
    )
