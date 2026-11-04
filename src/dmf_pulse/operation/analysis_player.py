"""Historical detail from retained typed outputs, without reconstructing a run."""

from dmf_pulse.dashboard.views import PlayerDetail
from dmf_pulse.operation.analysis_models import AnalysisSnapshot
from dmf_pulse.private_v1.models import PrivateV1Decision


def saved_player(snapshot: AnalysisSnapshot, official_id: int) -> PlayerDetail:
    presentation = snapshot.presentation
    if presentation is None:
        raise ValueError("FIXTURE_DISTRIBUTIONS_NOT_RETAINED_IN_ORIGINAL_SNAPSHOT")
    player = next(row for row in presentation.catalogue if row.official_id == official_id)
    summaries = {
        row.gameweek: row.summaries[player.player_id]
        for row in presentation.gameweeks
        if player.player_id in row.summaries
    }
    decision = snapshot.view.team.decision
    squad = (
        decision.resulting_squad
        if isinstance(decision, PrivateV1Decision)
        else decision.do_now.squad_after
    )
    return PlayerDetail(
        job_id=snapshot.run_id,
        catalogue=player,
        gameweeks=summaries,
        fixtures=tuple(
            row.model_copy(
                update={
                    "summaries": {player.player_id: row.summaries[player.player_id]},
                    "minutes": {player.player_id: row.minutes[player.player_id]}
                    if player.player_id in row.minutes
                    else {},
                }
            )
            for row in presentation.fixtures
            if player.player_id in row.summaries
        ),
        warnings=tuple(sorted(set(decision.warnings))),
        role="UNAVAILABLE"
        if not summaries
        else "RECOMMENDED_SQUAD"
        if player.player_id in squad
        else "CURRENT_SQUAD"
        if player.player_id in presentation.current_squad
        else "PROJECTED",
        frontier_transfer_counts=tuple(
            row.transfer_count
            for row in decision.transfer_frontier.points
            if any(
                player.player_id in {move.player_in_id, move.player_out_id}
                for move in row.transfers
            )
        )
        if decision.transfer_frontier is not None
        else (),
    )
