"""Automatic, transient private-V1 inputs derived from one direct current snapshot."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid5

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import (
    CurrentModelFixtureMinutesInput,
    build_current_model_fixture_minutes,
)
from dmf_pulse.availability.models import format_utc
from dmf_pulse.availability.pipeline import fit_projection_artifact, predict_minutes_baseline
from dmf_pulse.availability.projection import MinutesPredictionResult
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplFixture
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateBundle
from dmf_pulse.markets.current import CurrentMarketCanonicalIdentityView
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCanonicalPlayerIdentity,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCanonicalTeamIdentity,
    PrivateCurrentOwnership,
    PrivateCurrentOwnershipMember,
    seal_candidate_action_policy,
    seal_canonical_player_identity_map,
    seal_current_ownership,
)
from dmf_pulse.private_v1.progress import NullProgress, ProgressSink

_NAMESPACE = UUID("15b4fe6e-0149-54bb-a936-af6fccf69e89")


def _team_uuid(identity_sha256: str) -> UUID:
    return uuid5(_NAMESPACE, "one-command:team:" + identity_sha256)


def _player_uuid(identity_sha256: str) -> UUID:
    return uuid5(_NAMESPACE, "one-command:player:" + identity_sha256)


def _fixture_uuid(identity_sha256: str) -> UUID:
    return uuid5(_NAMESPACE, "one-command:history-fixture:" + identity_sha256)


def build_automatic_player_identity_map(
    snapshot: DirectFplSnapshot,
    manager: CurrentManagerStateBundle,
) -> PrivateCanonicalPlayerIdentityMap:
    """Map the exact legal action/manager universe to run-stable transient UUIDs."""

    squad = {item.official_fpl_element_id for item in manager.squad}
    players = tuple(
        item
        for item in snapshot.fpl_input.players
        if item.removed is not True or item.provider_element_id in squad
    )
    if any(item.can_select is None or item.removed is None for item in players):
        raise IngestionError(
            "CANDIDATE_ELIGIBILITY_UNRESOLVED",
            "official FPL did not expose complete player selection eligibility",
        )
    team_by_id = {item.provider_team_id: item for item in snapshot.fpl_input.teams}
    mapped_team_ids = {int(item.team_identity.external_id_text) for item in players}
    teams = tuple(
        PrivateCanonicalTeamIdentity(
            official_fpl_team_id=team_id,
            canonical_team_id=_team_uuid(team_by_id[team_id].identity.canonical_lookup_sha256),
        )
        for team_id in sorted(mapped_team_ids)
    )
    mapped_players = tuple(
        PrivateCanonicalPlayerIdentity(
            official_fpl_element_id=item.provider_element_id,
            official_fpl_team_id=int(item.team_identity.external_id_text),
            canonical_player_id=_player_uuid(item.identity.canonical_lookup_sha256),
        )
        for item in sorted(players, key=lambda value: value.provider_element_id)
    )
    return seal_canonical_player_identity_map(
        PrivateCanonicalPlayerIdentityMap.model_construct(
            source_class="OPERATOR_INITIATED_DETERMINISTIC",
            resolved_at=snapshot.captured_at,
            information_cutoff=snapshot.fpl_input.provenance.information_cutoff,
            teams=teams,
            players=mapped_players,
            semantic_sha256="0" * 64,
        )
    )


def build_automatic_ownership(
    snapshot: DirectFplSnapshot,
    manager: CurrentManagerStateBundle,
) -> PrivateCurrentOwnership:
    """Reconstruct unique acquisition GWs from public transfer history and current auth state."""

    current_ids = {item.official_fpl_element_id for item in manager.squad}
    public_ids = (
        set()
        if snapshot.latest_public_picks is None
        else {item.element for item in snapshot.latest_public_picks.picks}
    )
    latest_incoming: dict[int, int] = {}
    for transfer in snapshot.transfers:
        if transfer.event > snapshot.target_gameweek:
            raise IngestionError(
                "OWNERSHIP_HISTORY_UNRESOLVED", "official FPL transfer is after the target GW"
            )
        latest_incoming[transfer.element_in] = max(
            transfer.event, latest_incoming.get(transfer.element_in, 0)
        )
    members: list[PrivateCurrentOwnershipMember] = []
    for element_id in sorted(current_ids):
        acquired = latest_incoming.get(element_id)
        if acquired is None and public_ids and element_id not in public_ids:
            acquired = snapshot.target_gameweek
        if acquired is None:
            acquired = snapshot.entry.started_event
        if acquired > snapshot.target_gameweek:
            raise IngestionError(
                "OWNERSHIP_HISTORY_UNRESOLVED", "current player acquisition GW is ambiguous"
            )
        members.append(
            PrivateCurrentOwnershipMember(
                official_fpl_element_id=element_id, acquired_gameweek=acquired
            )
        )
    return seal_current_ownership(
        PrivateCurrentOwnership.model_construct(
            source_class="PROVIDER_OBSERVED_RECONSTRUCTED",
            attestation_status="PROVIDER_OBSERVED",
            provider_verification="PROVIDER_VERIFIED",
            target_gameweek=snapshot.target_gameweek,
            declared_at=snapshot.captured_at,
            attested_at=snapshot.captured_at,
            information_cutoff=snapshot.fpl_input.provenance.information_cutoff,
            members=tuple(members),
            semantic_sha256="0" * 64,
        )
    )


def build_full_candidate_policy(
    snapshot: DirectFplSnapshot,
    manager: CurrentManagerStateBundle,
) -> PrivateCandidateActionPolicy:
    squad = {item.official_fpl_element_id for item in manager.squad}
    incoming = tuple(
        sorted(
            item.provider_element_id
            for item in snapshot.fpl_input.players
            if item.provider_element_id not in squad
            and item.can_select is True
            and item.removed is not True
        )
    )
    if len(incoming) > 1000:
        raise IngestionError(
            "CANDIDATE_UNIVERSE_UNBOUNDED",
            "official FPL selectable player universe exceeds the private exact-search bound",
        )
    return seal_candidate_action_policy(
        PrivateCandidateActionPolicy.model_construct(
            allowed_transfer_in_element_ids=incoming,
            maximum_transfers=1 if incoming else 0,
            rationale=(
                "Complete official-FPL selectable non-squad universe at the transient cutoff; "
                "no heuristic shortlist; the accepted private-V1 action tree is bounded to one "
                "current-GW transfer."
            ),
            semantic_sha256="0" * 64,
        )
    )


def _read_resource(relative: str) -> object:
    resource = files("dmf_pulse.availability.resources").joinpath(relative)
    return json.loads(resource.read_text(encoding="utf-8"))


def _current_history(
    snapshot: DirectFplSnapshot,
    identity_map: PrivateCanonicalPlayerIdentityMap,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    fpl = snapshot.fpl_input
    player_map = {item.official_fpl_element_id: item for item in identity_map.players}
    team_map = {item.official_fpl_team_id: item for item in identity_map.teams}
    catalogue = {
        item.provider_element_id: item
        for item in fpl.players
        if item.provider_element_id in player_map
    }
    events = {item.provider_event_id: item for item in fpl.events}
    fixtures_by_gw: dict[int, list[Any]] = {}
    for fixture in fpl.fixtures:
        if fixture.event_identity is None:
            continue
        gameweek = int(fixture.event_identity.external_id_text)
        if gameweek in snapshot.live_by_gameweek:
            fixtures_by_gw.setdefault(gameweek, []).append(fixture)
    team_fixture: dict[tuple[int, int], CurrentFplFixture] = {}
    ambiguous_team_gws: set[tuple[int, int]] = set()
    for gameweek, fixtures in fixtures_by_gw.items():
        for fixture in fixtures:
            for team_identity in (fixture.home_team_identity, fixture.away_team_identity):
                key = (gameweek, int(team_identity.external_id_text))
                if key in team_fixture:
                    ambiguous_team_gws.add(key)
                team_fixture[key] = fixture
    rows: list[dict[str, Any]] = []
    for gameweek, live in sorted(snapshot.live_by_gameweek.items()):
        event = events.get(gameweek)
        if event is None:
            raise IngestionError("MAPPING_CONFLICT", "live GW is absent from current events")
        for observation in live.elements:
            player = catalogue.get(observation.id)
            if player is None:
                continue
            team_id = int(player.team_identity.external_id_text)
            if (gameweek, team_id) in ambiguous_team_gws:
                continue
            observed_fixture = team_fixture.get((gameweek, team_id))
            minutes = observation.stats.minutes
            starts = observation.stats.starts
            if (
                observed_fixture is None
                or minutes is None
                or starts is None
                or starts not in {0, 1}
            ):
                continue
            role = "START" if starts == 1 else "BENCH" if minutes > 0 else "OUT"
            if role == "START" and minutes == 0:
                continue
            canonical_player = player_map[player.provider_element_id].canonical_player_id
            canonical_team = team_map[team_id].canonical_team_id
            fixture_id = _fixture_uuid(observed_fixture.identity.canonical_lookup_sha256)
            manager_id = uuid5(_NAMESPACE, f"one-command:manager-regime:{team_id}")
            rows.append(
                {
                    "evidence_type": "COMPETITIVE",
                    "example_id": str(
                        uuid5(
                            _NAMESPACE,
                            f"one-command:history:{gameweek}:{player.provider_element_id}",
                        )
                    ),
                    "feature_cutoff": format_utc(event.deadline_at),
                    "fixture_id": str(fixture_id),
                    "fixture_key": f"official-fpl-{observed_fixture.provider_fixture_id}",
                    "label_usable_at": format_utc(snapshot.captured_at),
                    "manager_regime_id": str(manager_id),
                    "minutes_label": min(minutes, 90),
                    "player_id": str(canonical_player),
                    "player_key": f"fpl-{player.provider_element_id}",
                    "position": player.position.value,
                    "role_label": role,
                    "sequence_index": gameweek,
                    "split": "TRAIN",
                    "team_id": str(canonical_team),
                    "team_key": f"fpl-team-{team_id}",
                }
            )
    rosters: dict[str, list[dict[str, object]]] = {}
    for player in sorted(catalogue.values(), key=lambda value: value.provider_element_id):
        team_id = int(player.team_identity.external_id_text)
        rosters.setdefault(f"fpl-team-{team_id}", []).append(
            {
                "player_id": str(player_map[player.provider_element_id].canonical_player_id),
                "player_key": f"fpl-{player.provider_element_id}",
                "position": player.position.value,
                "team_id": str(team_map[team_id].canonical_team_id),
                "team_key": f"fpl-team-{team_id}",
            }
        )
    warnings = {
        "CURRENT_FPL_LIVE_STATS_TRANSIENT_PROVIDER_OBSERVED",
        "CURRENT_TEAM_ASSOCIATION_USED_FOR_RETRIEVED_HISTORY",
        "MANAGER_REGIME_NOT_PROVIDER_EXPOSED_BASELINE_ASSUMPTION",
    }
    if ambiguous_team_gws:
        warnings.add("DOUBLE_GAMEWEEK_AGGREGATES_EXCLUDED_FROM_PLAYER_HISTORY")
    if not rows:
        warnings.add("NO_USABLE_CURRENT_SEASON_PLAYER_HISTORY_GLOBAL_PRIORS_ONLY")
    return {
        "schema_version": "minutes-history-v1",
        "rows": sorted(
            rows, key=lambda item: (int(item["sequence_index"]), str(item["player_id"]))
        ),
        "rosters": rosters,
    }, tuple(sorted(warnings))


def build_automatic_model_minutes(
    snapshot: DirectFplSnapshot,
    identity_map: PrivateCanonicalPlayerIdentityMap,
    market_view: CurrentMarketCanonicalIdentityView,
    *,
    progress: ProgressSink | None = None,
) -> tuple[CurrentModelFixtureMinutesInput, ...]:
    """Run the accepted model family over current transient rosters and observed live facts."""

    active_progress = progress or NullProgress()
    training = _read_resource("MIN-007/training_dataset.json")
    policy = _read_resource("MIN-007G/minutes_baseline_policy.json")
    artifact = fit_projection_artifact(training, policy=policy)
    history, warnings = _current_history(snapshot, identity_map)
    history_sha256 = canonical_sha256(history)
    team_map = {item.official_fpl_team_id: item for item in identity_map.teams}
    players = {item.provider_element_id: item for item in snapshot.fpl_input.players}
    mapped_players = {item.official_fpl_element_id: item for item in identity_map.players}
    target_fixtures = {
        item.provider_fixture_id: item
        for item in snapshot.fpl_input.fixtures
        if item.event_identity == snapshot.fpl_input.target_event.identity
    }
    outputs: list[CurrentModelFixtureMinutesInput] = []
    fixture_count = len(market_view.fixtures)
    for fixture_index, canonical_fixture in enumerate(market_view.fixtures, start=1):
        fixture = target_fixtures.get(canonical_fixture.official_fpl_fixture_id)
        if fixture is None:
            raise IngestionError("MAPPING_CONFLICT", "market fixture is absent from current FPL")
        home_id = int(fixture.home_team_identity.external_id_text)
        away_id = int(fixture.away_team_identity.external_id_text)

        def context(team_id: int, *, fixture_id: UUID) -> dict[str, object]:
            team_key = f"fpl-team-{team_id}"
            team_rows = [item for item in history["rows"] if item["team_key"] == team_key]
            overrides: dict[str, dict[str, bool]] = {}
            for element_id in mapped_players:
                player = players[element_id]
                if int(player.team_identity.external_id_text) != team_id:
                    continue
                hard = player.removed is True or player.status == "u"
                if hard:
                    overrides[f"fpl-{element_id}"] = {"hard_ineligible": True}
            return {
                "schema_version": "minutes-prediction-context-v1",
                "scenario": "private-one-command-current",
                "fixture_id": str(fixture_id),
                "team_key": team_key,
                "team_id": str(team_map[team_id].canonical_team_id),
                "as_of": format_utc(snapshot.captured_at),
                "cutoff_sequence_index": snapshot.target_gameweek,
                "manager_regime_id": str(
                    uuid5(_NAMESPACE, f"one-command:manager-regime:{team_id}")
                ),
                "bench_size": 9,
                "bench_goalkeeper_slots": 1,
                "current_manager_team_lineups": len(
                    {str(item["fixture_id"]) for item in team_rows}
                ),
                "target_league_team_lineups": len({str(item["fixture_id"]) for item in team_rows}),
                "promoted_team": False,
                "new_manager": False,
                "player_overrides": overrides,
            }

        home_context = context(home_id, fixture_id=canonical_fixture.canonical_fixture_id)
        away_context = context(away_id, fixture_id=canonical_fixture.canonical_fixture_id)

        def predict(prediction_context: dict[str, object]) -> MinutesPredictionResult:
            try:
                result = predict_minutes_baseline(
                    history,
                    artifact,
                    context=prediction_context,
                    policy=policy,
                )
            except ValueError as exc:
                raise IngestionError(
                    "CURRENT_MINUTES_MODEL_BLOCKED",
                    "accepted current minutes model could not project",
                ) from exc
            if result.status != "PROJECTED" or result.projection is None:
                raise IngestionError(
                    result.error_code or "CURRENT_MINUTES_MODEL_BLOCKED",
                    "accepted current minutes predictor returned a blocked result",
                )
            return result

        progress_prefix = f"Stage 7 fixture {fixture_index}/{fixture_count}"
        with active_progress.stage(
            started=None,
            completed=f"{progress_prefix} ready",
            failed=f"{progress_prefix}",
        ):
            with active_progress.stage(
                started=f"{progress_prefix}: predicting home team...",
                completed=f"{progress_prefix}: home prediction ready",
                failed=f"{progress_prefix} home team prediction",
            ):
                home = predict(home_context)
            with active_progress.stage(
                started=f"{progress_prefix}: predicting away team...",
                completed=f"{progress_prefix}: away prediction ready",
                failed=f"{progress_prefix} away team prediction",
            ):
                away = predict(away_context)
            with active_progress.stage(
                started=f"{progress_prefix}: reconciling team scenarios...",
                completed=None,
                failed=f"{progress_prefix} scenario adaptation",
            ):
                try:
                    outputs.append(
                        build_current_model_fixture_minutes(
                            home,
                            away,
                            information_cutoff=snapshot.fpl_input.provenance.information_cutoff,
                            observed_history_sha256=history_sha256,
                            warnings=warnings,
                        )
                    )
                except (KeyError, ValueError) as exc:
                    raise IngestionError(
                        "CURRENT_STAGE7_SCENARIO_ROSTER_INVALID",
                        "current Stage-7 scenario adaptation or reconciliation failed",
                    ) from exc
    return tuple(sorted(outputs, key=lambda item: item.fixture_id))


__all__ = [
    "build_automatic_model_minutes",
    "build_automatic_ownership",
    "build_automatic_player_identity_map",
    "build_full_candidate_policy",
]
