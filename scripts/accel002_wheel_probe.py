"""Installed-wheel acceptance using owned inputs and the actual application stack."""

from __future__ import annotations

import json
import socket
from datetime import timedelta
from decimal import Decimal


def main() -> None:
    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.dashboard.runtime import DeskRuntime
    from dmf_pulse.dashboard.synthetic import DEMO_TIME, run_synthetic_recommendation
    from dmf_pulse.dashboard.views import desk_view, player_detail
    from dmf_pulse.player_lab.demo import synthetic_evaluation
    from dmf_pulse.private_v1.progress import NullProgress

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("installed synthetic acceptance attempted network access")

    # This process does no HTTP or PostgreSQL IO; every provider-shaped input is
    # repository-owned. Guard both connection and DNS APIs before model execution.
    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    socket.create_connection = forbidden
    socket.getaddrinfo = forbidden
    result = run_synthetic_recommendation(1, NullProgress())
    view = desk_view(
        result,
        job_id="INSTALLED_WHEEL_SYNTHETIC",
        mode="SYNTHETIC_DEMONSTRATION",
        generated_at=DEMO_TIME,
        expires_at=DEMO_TIME + timedelta(minutes=10),
    )
    assert (view.catalogue_count, view.projected_count, view.blocked_count) == (121, 120, 1)
    assert len(view.team.current_squad) == 15
    assert len(view.team.decision.tactics.starting_xi) == 11
    assert result.presentation is not None
    for row in view.players:
        if row.catalogue.player_id is None:
            assert row.expected_points is None
            continue
        original = result.presentation.gameweeks[0].summaries[row.catalogue.player_id]
        assert row.expected_points == original.expected_points
        detail = player_detail(result, view.job_id, row.catalogue.official_id)
        assert detail.gameweeks[view.gameweeks[0]] == original
        assert (
            abs(
                sum(c.expected_points for c in original.component_breakdown.values())
                - original.expected_points
            )
            < 1e-10
        )
    lab = synthetic_evaluation()
    assert lab.scorecard.point_metrics.mae == Decimal(2)
    runtime = DeskRuntime()
    app = create_app(runtime=runtime, pairing_code="synthetic-wheel-only", port=8765)
    assert app.docs_url is None and app.openapi_url is None
    assert runtime.refresh(1).error_code == "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"
    runtime.close()
    print(
        json.dumps(
            {
                "status": "PASS",
                "classification": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
                "provider_calls": 0,
                "catalogue": view.catalogue_count,
                "projected": view.projected_count,
                "blocked": view.blocked_count,
                "all_stage9_summaries_equal": True,
                "evaluation_pairs": len(lab.labels),
                "live_refresh": "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
