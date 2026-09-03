from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import PrivateFixtureScorePrior, seal_fixture_score_prior
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.rolling_models import (
    PrivateRollingFixtureInput,
    PrivateRollingGameweekInput,
    PrivateV1RollingExecutionInput,
    seal_rolling_execution_input,
    seal_rolling_fixture_input,
    seal_rolling_gameweek_input,
)

_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def _construct(value, **updates):
    payload = {name: getattr(value, name) for name in type(value).model_fields}
    payload.update(updates)
    return type(value).model_construct(**payload)


def _fixture(minutes, *, gameweek: int, market_mode: str = "SCORE_PRIOR_ONLY"):
    fixture_id = UUID(minutes.fixture_id)
    home_id = UUID(minutes.home_team_id)
    away_id = UUID(minutes.away_team_id)
    prior = seal_fixture_score_prior(
        PrivateFixtureScorePrior.model_construct(
            source_class="REPOSITORY_OWNED_SYNTHETIC",
            fixture_id=fixture_id,
            competition_id=UUID("30000000-0000-7000-8000-000000000001"),
            home_team_id=home_id,
            away_team_id=away_id,
            as_of=_CUTOFF,
            score_prior_request=ScorePriorRequest(
                home_goal_rate=Decimal("1.5"), away_goal_rate=Decimal("1.2")
            ),
            current_bundle=None,
            semantic_sha256="0" * 64,
        )
    )
    return seal_rolling_fixture_input(
        PrivateRollingFixtureInput.model_construct(
            official_fpl_fixture_id=100 + gameweek,
            official_fpl_fixture_lookup_sha256=canonical_sha256({"gw": gameweek}),
            canonical_fixture_id=fixture_id,
            home_official_fpl_team_id=1,
            away_official_fpl_team_id=2,
            home_canonical_team_id=home_id,
            away_canonical_team_id=away_id,
            kickoff_at=_CUTOFF + timedelta(days=gameweek),
            information_cutoff=_CUTOFF,
            market_mode=market_mode,
            market_constraints=(),
            blocked_reason=None,
            score_prior=prior,
            stage7=minutes,
            warnings=(),
            semantic_sha256="0" * 64,
        )
    )


def test_future_fixture_prior_only_mode_is_explicit_and_hash_bound(
    repository_root, tmp_path
) -> None:
    from tests.unit.private_v1.e2e_test_support import build_execution_input

    current = build_execution_input(repository_root, tmp_path / "current")
    minutes = current.manual_minutes[0]
    fixture = _fixture(minutes, gameweek=2)

    assert fixture.market_mode == "SCORE_PRIOR_ONLY"
    assert fixture.market_constraints == ()
    payload = fixture.model_dump(mode="python")
    payload["market_mode"] = "MARKET_BACKED"
    with pytest.raises(ValidationError):
        PrivateRollingFixtureInput.model_validate(payload)


def test_rolling_execution_requires_exactly_three_consecutive_gameweeks(
    repository_root, tmp_path
) -> None:
    from tests.unit.private_v1.e2e_test_support import build_execution_input

    current = build_execution_input(repository_root, tmp_path / "current")
    minutes = current.manual_minutes[0]
    future = tuple(
        seal_rolling_gameweek_input(
            PrivateRollingGameweekInput.model_construct(
                gameweek=gameweek,
                fixtures=(_fixture(minutes, gameweek=gameweek),),
                semantic_sha256="0" * 64,
            )
        )
        for gameweek in (2, 4)
    )
    provisional = PrivateV1RollingExecutionInput.model_construct(
        horizon_gameweeks=(1, 2, 4),
        current_execution=current,
        future_gameweeks=future,
        terminal_value_mode="THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON",
        terminal_policy_sha256="0" * 64,
        future_price_mode="FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1",
        scenario_tree_mode="DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1",
        search_scope_mode="PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1",
        transfer_count_scope_source=("CURRENT_FT_COMPILED_RULES_AND_TICKET_BOUNDED_SEARCH_POLICY"),
        maximum_transfers_per_deadline=current.candidate_action_policy.maximum_transfers,
        chip_mode="NO_CHIP_EXPLICIT",
        semantic_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="consecutive"):
        seal_rolling_execution_input(provisional)


def test_future_blocked_market_mode_fails_closed_before_projection(
    repository_root, tmp_path
) -> None:
    from tests.unit.private_v1.e2e_test_support import build_rolling_execution_input

    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")
    first_gameweek, second_gameweek = execution.future_gameweeks
    first_fixture, *remaining = first_gameweek.fixtures
    blocked = seal_rolling_fixture_input(
        _construct(
            first_fixture,
            market_mode="BLOCKED",
            blocked_reason="ACCEPTED_FUTURE_SOURCE_UNAVAILABLE",
            semantic_sha256="0" * 64,
        )
    )
    changed_gameweek = seal_rolling_gameweek_input(
        _construct(
            first_gameweek,
            fixtures=(blocked, *remaining),
            semantic_sha256="0" * 64,
        )
    )
    changed = seal_rolling_execution_input(
        _construct(
            execution,
            future_gameweeks=(changed_gameweek, second_gameweek),
            semantic_sha256="0" * 64,
        )
    )

    with pytest.raises(PrivateV1Error) as caught:
        PrivateV1RollingRecommendationService().run(changed)
    assert caught.value.code == "FUTURE_FIXTURE_INPUT_BLOCKED"


def test_future_cutoff_mutation_and_terminal_policy_mutation_fail_closed(
    repository_root, tmp_path
) -> None:
    from tests.unit.private_v1.e2e_test_support import build_rolling_execution_input

    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")
    fixture = execution.future_gameweeks[0].fixtures[0]
    with pytest.raises(ValueError, match="identity or cutoff differs"):
        seal_rolling_fixture_input(
            _construct(
                fixture,
                information_cutoff=fixture.information_cutoff + timedelta(seconds=1),
                semantic_sha256="0" * 64,
            )
        )
    changed = seal_rolling_execution_input(
        _construct(
            execution,
            terminal_policy_sha256="f" * 64,
            semantic_sha256="0" * 64,
        )
    )
    with pytest.raises(PrivateV1Error) as caught:
        PrivateV1RollingRecommendationService().run(changed)
    assert caught.value.code == "ROLLING_TERMINAL_POLICY_INVALID"
