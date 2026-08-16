from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.legality import validate_squad_legality
from dmf_pulse.optimisation.models import CandidateSquad
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import players, synthetic_ruleset


def test_legality_rejects_duplicate_squad_player() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    player_map = {player.player_id: player for player in players()}
    report = validate_squad_legality(
        CandidateSquad.model_construct(player_ids=tuple(["p00"] * 15)), player_map, view
    )
    assert not report.legal
    assert any(issue.code == "DUPLICATE_PLAYER" for issue in report.issues)
