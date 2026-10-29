"""Reproducible complete owned-evidence path; no real historical values."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from dmf_pulse.player_evidence.contracts import EvidenceFeatureSet, FeatureRequest, PlayerScope
from dmf_pulse.player_evidence.features import build_features
from dmf_pulse.player_evidence.qualification import owned_body, owned_source


def owned_request(cutoff: datetime | None = None) -> FeatureRequest:
    team = uuid5(NAMESPACE_URL, "dmf-owned-accel003:team-b")
    return FeatureRequest(
        season="2026/27",
        players=tuple(
            sorted(
                (
                    PlayerScope(
                        player_id=uuid5(NAMESPACE_URL, f"dmf-owned-accel003:player-p{index}"),
                        team_id=team,
                    )
                    for index in range(1, 7)
                ),
                key=lambda item: str(item.player_id),
            )
        ),
        cutoff=cutoff if cutoff is not None else datetime(2026, 9, 30, 12, tzinfo=UTC),
        history_start=datetime(2026, 9, 1, tzinfo=UTC),
        target_kickoff=datetime(2026, 11, 1, 12, tzinfo=UTC),
        maximum_fixtures=20,
    )


def owned_demo(cutoff: datetime | None = None) -> EvidenceFeatureSet:
    """Authenticate, join and describe the exact packaged owned participation fixture."""
    return build_features(body=owned_body(), source=owned_source(), request=owned_request(cutoff))
