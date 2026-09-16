"""Pure three-world R9B compiler. Never imported by the recommendation path."""

from __future__ import annotations

from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import (
    CHANNELS,
    Channel,
    CurrentPlayerAllocationShadow,
    CurrentPlayerAllocationShadowWorld,
    CurrentPlayerPosteriorArtifact,
    CurrentPlayerPosteriorEntry,
    CurrentPlayerPosteriorRate,
    HistoricalRateResource,
    HistoricalRateRow,
    RateStatus,
    gamma_poisson_update,
    seal,
    shadow_profile,
)
from dmf_pulse.fpl_points.models import PlayerAllocationProfile
from dmf_pulse.fpl_points.player_prior import (
    CurrentGwPlayerPriorBinding,
    CurrentGwStalePriorCarryForwardPolicy,
    GovernedPlayerPrior,
    build_current_gw_player_prior_binding,
)
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from dmf_pulse.ingestion.fpl.current_player_history import (
    CurrentPlayerHistoryCoverage,
    CurrentPlayerHistoryEntry,
    CurrentPlayerHistoryEvidence,
    _field_coverage,
    _quality,
    _reconciliation,
)

_STAT_BY_CHANNEL = {
    "assist": "assists",
    "yellow": "yellow_cards",
    "red": "red_cards",
    "save": "saves",
    "total_goal_diagnostic": "goals_scored",
}


def validate_current_evidence(
    history: CurrentPlayerHistoryEvidence,
    fpl: CurrentFplInputBundle,
    binding: CurrentGwPlayerPriorBinding,
) -> None:
    """Check relationships beyond independent object seals, without raw bodies or I/O."""
    cutoff = fpl.provenance.information_cutoff
    window = tuple(
        sorted(
            e.provider_event_id
            for e in fpl.events
            if e.provider_event_id < fpl.target_gameweek
            and e.finished is True
            and e.data_checked is True
        )
    )[-12:]
    if (
        history.target_gameweek != fpl.target_gameweek
        or history.information_cutoff != cutoff
        or history.coverage.observed_gameweeks != window
    ):
        raise ValueError("history window/cutoff differs from acquired finalized FPL window")
    current = {p.provider_element_id: p for p in fpl.players}
    mappings = {e.source_player_id: e for e in binding.entries}
    if (
        len(current) != len(fpl.players)
        or set(current) != set(mappings)
        or tuple(e.official_fpl_element_id for e in history.entries) != tuple(sorted(current))
    ):
        raise ValueError("current catalogue/history/binding coverage differs or duplicates")
    events = {e.provider_event_id: e for e in fpl.events}
    if len(events) != len(fpl.events):
        raise ValueError("duplicate current Gameweek")
    lineage: dict[int, tuple[str, str]] = {}
    for entry in history.entries:
        player = current[entry.official_fpl_element_id]
        mapping = mappings[entry.official_fpl_element_id]
        if (
            entry.current_player_identity_sha256 != player.identity.canonical_lookup_sha256
            or entry.canonical_player_id not in (None, UUID(mapping.current_player_id))
        ):
            raise ValueError("current history identity mismatch")
        for row in entry.observations:
            if (
                row.gameweek not in window
                or row.information_cutoff != cutoff
                or row.source_gameweek_identity_sha256
                != events[row.gameweek].identity.canonical_lookup_sha256
                or events[row.gameweek].deadline_at > cutoff
            ):
                raise ValueError("history observation source window/cutoff mismatch")
            source = (row.source_body_sha256, row.source_semantic_sha256)
            if lineage.setdefault(row.gameweek, source) != source:
                raise ValueError("one source Gameweek has conflicting digests")
        minutes = _reconciliation(entry.observations, window, "minutes", player.season_minutes)
        starts = _reconciliation(entry.observations, window, "starts", player.season_starts)
        if (
            entry.reconciliation_minutes != minutes
            or entry.reconciliation_starts != starts
            or entry.quality != _quality(entry.observations, window, minutes, starts)
        ):
            raise ValueError("history reconciliation/quality differs from source facts")
        if "FAILED" in (minutes, starts):
            raise ValueError("bootstrap exposure reconciliation failed; shadow blocked")
    entries = history.entries
    coverage = CurrentPlayerHistoryCoverage(
        observed_gameweeks=window,
        earliest_observed_gameweek=window[0] if window else None,
        latest_observed_gameweek=window[-1] if window else None,
        gameweek_count=len(window),
        current_player_count=len(entries),
        players_with_any_history=sum(bool(e.observations) for e in entries),
        players_with_zero_history=sum(not e.observations for e in entries),
        historical_row_count=sum(len(e.observations) for e in entries),
        field_coverage=_field_coverage(entries),
        full_minutes_reconciliation_count=sum(e.reconciliation_minutes == "MATCH" for e in entries),
        full_starts_reconciliation_count=sum(e.reconciliation_starts == "MATCH" for e in entries),
        failed_minutes_reconciliation_count=0,
        failed_starts_reconciliation_count=0,
    )
    if coverage != history.coverage:
        raise ValueError("history coverage does not agree with observations")


def posterior_rate(
    channel: Channel,
    historical: HistoricalRateRow,
    current: CurrentPlayerHistoryEntry,
    *,
    is_goalkeeper: bool,
) -> CurrentPlayerPosteriorRate:
    prior_channel = "goal" if channel == "total_goal_diagnostic" else channel
    mean = float(getattr(historical, f"{prior_channel}_mean_per90"))
    variance = float(getattr(historical, f"{prior_channel}_variance_per90"))
    rows = current.observations
    stat = _STAT_BY_CHANNEL[channel]
    available = tuple(
        row for row in rows if getattr(row, stat) is not None and row.minutes is not None
    )
    discipline = channel in ("yellow", "red")
    excluded = tuple(row for row in available if discipline and row.minutes == 0)
    included = tuple(row for row in available if not discipline or row.minutes != 0)
    minutes = sum(row.minutes or 0 for row in included)
    # This zero is the sum of *known* counts, not imputation for missing rows.
    events = sum(int(getattr(row, stat)) for row in included) if available else None
    if not discipline and any(row.minutes == 0 and getattr(row, stat) > 0 for row in available):
        raise ValueError("positive goals/assists/saves with zero exposure")
    status: RateStatus
    if channel == "save" and not is_goalkeeper:
        if (mean, variance) != (0.0, 0.0) or any(
            row.saves is not None and row.saves != 0 for row in rows
        ):
            raise ValueError("non-GK saves violate structural zero")
        status = "STRUCTURAL_NON_GK_ZERO"
    elif not rows:
        status = "CURRENT_HISTORY_UNAVAILABLE"
    elif len(available) != len(rows):
        status = "CURRENT_HISTORY_FIELD_PARTIAL_NO_UPDATE"
    elif mean <= 0 or variance <= 0:
        status = "HISTORICAL_RATE_DEGENERATE_NO_UPDATE"
    elif minutes == 0:
        status = "NO_CURRENT_EXPOSURE"
    else:
        status = "UPDATED"
    post = (
        gamma_poisson_update(mean, variance, events, minutes)
        if status == "UPDATED" and events is not None
        else (mean, variance)
    )
    return CurrentPlayerPosteriorRate(
        channel=channel,
        status=status,
        historical_mean_per90=mean,
        historical_variance_per90=variance,
        posterior_mean_per90=post[0],
        posterior_variance_per90=post[1],
        observed_rows=len(available),
        applicable_rows=len(rows),
        included_minutes=minutes,
        included_events=events,
        zero_exposure_discipline_excluded_rows=len(excluded),
        zero_exposure_discipline_excluded_events=sum(int(getattr(row, stat)) for row in excluded),
    )


def compile_current_player_shadow(
    *,
    history: CurrentPlayerHistoryEvidence,
    current_fpl: CurrentFplInputBundle,
    binding: CurrentGwPlayerPriorBinding,
    policy: CurrentGwStalePriorCarryForwardPolicy,
    prior: GovernedPlayerPrior,
    historical: HistoricalRateResource,
) -> CurrentPlayerAllocationShadow:
    """Pure compiler; all evidence/resources are explicit inputs, all output is transient.

    Missing event rows never contribute zero. Fully published available rows may update
    a new player's rate even when season-total reconciliation is not applicable.
    """
    history = CurrentPlayerHistoryEvidence.model_validate(history.model_dump(mode="python"))
    current_fpl = CurrentFplInputBundle.model_validate(current_fpl.model_dump(mode="python"))
    binding = CurrentGwPlayerPriorBinding.model_validate(binding.model_dump(mode="python"))
    policy = CurrentGwStalePriorCarryForwardPolicy.model_validate(policy.model_dump(mode="python"))
    prior = GovernedPlayerPrior.model_validate(prior.model_dump(mode="python"))
    historical = HistoricalRateResource.model_validate(historical.model_dump(mode="python"))
    expected = build_current_gw_player_prior_binding(
        prior,
        current_fpl,
        policy,
        canonical_player_ids_by_source_id={
            e.source_player_id: e.current_player_id for e in binding.entries
        },
        canonical_team_ids_by_source_id={
            e.source_team_id: e.current_team_id for e in binding.entries
        },
    )
    if expected != binding:
        raise ValueError("current prior binding differs from governed source mapping")
    validate_current_evidence(history, current_fpl, binding)
    if (
        prior.artifact.posterior_artifact_sha256
        != historical.central_source_posterior_artifact_sha256
    ):
        raise ValueError("stale allocation and historical rate resource lineage differ")
    mappings = tuple(sorted(binding.entries, key=lambda e: e.source_player_id))
    evidence = {e.official_fpl_element_id: e for e in history.entries}
    donors = {p.player_id: p for p in prior.artifact.profiles}
    stale_profiles = tuple(
        PlayerAllocationProfile.model_validate(
            donors[e.donor_player_id].model_dump(mode="python")
            | {"player_id": e.current_player_id, "team_id": e.current_team_id}
        )
        for e in mappings
    )
    worlds: list[CurrentPlayerAllocationShadowWorld] = []
    for historical_world in historical.worlds:
        rates = {r.source_official_fpl_player_id: r for r in historical_world.rates}
        entries: list[CurrentPlayerPosteriorEntry] = []
        for mapping in mappings:
            row = rates.get(mapping.donor_source_player_id)
            if row is None:
                raise ValueError("governed donor missing from historical rate resource")
            current = evidence[mapping.source_player_id]
            entries.append(
                seal(
                    CurrentPlayerPosteriorEntry.model_construct(
                        binding=mapping,
                        current_history_entry_sha256=current.semantic_sha256,
                        observed_minutes=sum(
                            r.minutes for r in current.observations if r.minutes is not None
                        ),
                        rates=tuple(
                            posterior_rate(
                                channel, row, current, is_goalkeeper=mapping.position.value == "GK"
                            )
                            for channel in CHANNELS
                        ),
                        semantic_sha256="0" * 64,
                    )
                )
            )
        posterior = seal(
            CurrentPlayerPosteriorArtifact.model_construct(
                sensitivity_world=historical_world.sensitivity_world,
                information_cutoff=history.information_cutoff,
                target_gameweek=history.target_gameweek,
                confidence=(
                    "CURRENT_HISTORY_PRESENT_SHADOW_NOT_ACCEPTED"
                    if history.coverage.players_with_any_history
                    else "CURRENT_HISTORY_UNAVAILABLE_SHADOW_NOT_ACCEPTED"
                ),
                source_gameweeks=history.coverage.observed_gameweeks,
                historical_resource_sha256=historical.semantic_sha256,
                source_posterior_sha256=historical_world.source_posterior_artifact_sha256,
                current_history_sha256=history.semantic_sha256,
                current_binding_sha256=binding.semantic_sha256,
                current_catalogue_sha256=canonical_sha256(
                    [
                        p.model_dump(mode="json")
                        for p in sorted(current_fpl.players, key=lambda p: p.provider_element_id)
                    ]
                ),
                entries=tuple(entries),
                semantic_sha256="0" * 64,
            )
        )
        worlds.append(
            seal(
                CurrentPlayerAllocationShadowWorld.model_construct(
                    posterior=posterior,
                    stale_profiles=stale_profiles,
                    profiles=tuple(
                        shadow_profile(stale, entry)
                        for stale, entry in zip(stale_profiles, entries, strict=True)
                    ),
                    semantic_sha256="0" * 64,
                )
            )
        )
    return seal(
        CurrentPlayerAllocationShadow.model_construct(
            worlds=tuple(worlds), semantic_sha256="0" * 64
        )
    )
