"""Temporal identity, provenance, and missingness integration proofs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    entity_alias,
    external_identifier,
    fixture,
    fixture_observation,
    player,
    player_observation,
    player_season,
    player_team_membership,
    semantic_observation_claim,
    source_bundle,
    source_snapshot,
    team,
    team_observation,
)
from dmf_pulse.ingestion.fixtures import ApprovedFixture
from dmf_pulse.ingestion.fpl import service as service_module
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    DEFAULT_CAPTURED_AT,
    FplImportRequest,
    FplIngestionService,
    FplOperationOutcome,
    FplReplayRequest,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _count(session: Session, table: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _happy(repository_root: Path) -> FplReplayRequest:
    return FplReplayRequest(
        fixture_set=repository_root / "fixtures/fpl/FPL-004",
        scenario="happy_path",
        database_url_ref=DATABASE_REF,
    )


def _modified_import(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    bootstrap_change: object | None = None,
    fixtures_change: object | None = None,
    captured_at: datetime = DEFAULT_CAPTURED_AT + timedelta(minutes=10),
) -> FplOperationOutcome:
    source_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = json.loads((source_root / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures = json.loads((source_root / "fixtures.json").read_text(encoding="utf-8"))
    if callable(bootstrap_change):
        bootstrap_change(bootstrap)
    if callable(fixtures_change):
        fixtures_change(fixtures)
    bootstrap_path = tmp_path / "generated-bootstrap.json"
    fixtures_path = tmp_path / "generated-fixtures.json"
    bootstrap_path.write_text(
        json.dumps(bootstrap, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    fixtures_path.write_text(
        json.dumps(fixtures, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    def approve(path: Path, *, profile_id: str) -> ApprovedFixture:
        assert profile_id == "synthetic_test_v1"
        body = path.read_bytes()
        return ApprovedFixture(
            path=path.resolve(),
            relative_path=f"fixtures/fpl/FPL-004/generated/{path.name}",
            sha256=hashlib.sha256(body).hexdigest(),
        )

    monkeypatch.setattr(service_module, "approve_synthetic_fixture", approve)
    return FplIngestionService(repository_root=repository_root).import_pair(
        FplImportRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixtures_path,
            competition_key="SYNTHETIC_PL",
            season_code="2026/27",
            captured_at=captured_at,
            information_cutoff=captured_at + timedelta(minutes=30),
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )


def test_fixture_identifier_cannot_change_immutable_competitors(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    first = service.replay(_happy(repository_root))
    assert first.result.source_bundle is not None

    def swap_fixture_teams(values: list[dict[str, object]]) -> None:
        values[0]["team_h"], values[0]["team_a"] = (
            values[0]["team_a"],
            values[0]["team_h"],
        )

    blocked = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        fixtures_change=swap_fixture_teams,
    )
    assert blocked.exit_code == 2
    assert blocked.result.status == "QUARANTINED"
    assert blocked.result.canonical_effects["error_code"] == "MAPPING_CONFLICT"
    with postgres_session_factory() as session:
        assert _count(session, fixture) == 1
        assert _count(session, fixture_observation) == 1
        assert _count(session, source_bundle) == 1


def test_player_transfer_and_rename_append_temporal_history_without_identity_change(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    first = service.replay(_happy(repository_root))
    assert first.result.source_bundle is not None

    def transfer_and_rename(value: dict[str, object]) -> None:
        element = value["elements"][0]  # type: ignore[index]
        element["team"] = 2
        element["web_name"] = "A. Keeper Renamed"

    changed = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        bootstrap_change=transfer_and_rename,
    )
    assert changed.exit_code == 0
    with postgres_session_factory() as session:
        assert _count(session, player) == 4
        assert _count(session, player_season) == 4
        player_id = session.scalar(
            select(external_identifier.c.canonical_entity_id).where(
                external_identifier.c.identifier_namespace == "fpl.element.id",
                external_identifier.c.external_id_text == "11",
                func.upper_inf(external_identifier.c.system_during),
            )
        )
        assert player_id is not None
        memberships = session.execute(
            select(
                player_team_membership.c.membership_id,
                player_team_membership.c.team_id,
                player_team_membership.c.system_during,
                player_team_membership.c.superseded_by_membership_id,
            )
            .where(player_team_membership.c.player_id == player_id)
            .order_by(func.lower(player_team_membership.c.system_during))
        ).all()
        assert len(memberships) == 2
        assert memberships[0].superseded_by_membership_id == memberships[1].membership_id
        assert memberships[0].system_during.upper is not None
        assert memberships[1].system_during.upper is None
        aliases = session.execute(
            select(
                entity_alias.c.alias_id,
                entity_alias.c.raw_text,
                entity_alias.c.system_during,
                entity_alias.c.superseded_by_alias_id,
            )
            .where(entity_alias.c.canonical_entity_id == player_id)
            .order_by(func.lower(entity_alias.c.system_during))
        ).all()
        assert tuple(alias.raw_text for alias in aliases) == (
            "A. Keeper",
            "A. Keeper Renamed",
        )
        assert aliases[0].superseded_by_alias_id == aliases[1].alias_id
        assert aliases[0].system_during.upper is not None
        assert aliases[1].system_during.upper is None
        player_fpl_season_id = session.scalar(
            select(player_season.c.player_fpl_season_id).where(
                player_season.c.player_id == player_id
            )
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(player_observation)
                .where(player_observation.c.player_fpl_season_id == player_fpl_season_id)
            )
            == 2
        )


def test_stable_provider_codes_reuse_entities_when_primary_ids_change(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    service.replay(_happy(repository_root))

    def replace_primary_ids(value: dict[str, object]) -> None:
        value["teams"][0]["id"] = 101  # type: ignore[index]
        for element in value["elements"]:  # type: ignore[union-attr]
            if element["team"] == 1:
                element["team"] = 101
        value["elements"][0]["id"] = 111  # type: ignore[index]

    def replace_fixture_ids(values: list[dict[str, object]]) -> None:
        values[0]["id"] = 1101
        values[0]["team_h"] = 101

    changed = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        bootstrap_change=replace_primary_ids,
        fixtures_change=replace_fixture_ids,
    )
    assert changed.exit_code == 0
    with postgres_session_factory() as session:
        assert _count(session, team) == 2
        assert _count(session, player) == 4
        assert _count(session, fixture) == 1
        for namespace, old_id, new_id in (
            ("fpl.team.id", "1", "101"),
            ("fpl.element.id", "11", "111"),
            ("fpl.fixture.id", "101", "1101"),
        ):
            canonical_ids = set(
                session.scalars(
                    select(external_identifier.c.canonical_entity_id).where(
                        external_identifier.c.identifier_namespace == namespace,
                        external_identifier.c.external_id_text.in_((old_id, new_id)),
                        func.upper_inf(external_identifier.c.system_during),
                    )
                )
            )
            assert len(canonical_ids) == 1


def test_absent_and_explicit_null_persist_distinct_missingness_semantics(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    service.replay(_happy(repository_root))

    def publish_null(value: dict[str, object]) -> None:
        value["teams"][0]["draw"] = None  # type: ignore[index]

    changed = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        bootstrap_change=publish_null,
    )
    assert changed.exit_code == 0
    with postgres_session_factory() as session:
        rows = session.execute(
            select(team_observation.c.draw, team_observation.c.missingness)
            .where(team_observation.c.display_name == "Alpha Athletic")
            .order_by(team_observation.c.observed_at)
        ).all()
        assert len(rows) == 2
        assert rows[0].draw is None and rows[0].missingness["draw"] == "NOT_PUBLISHED"
        assert rows[1].draw is None and "draw" not in rows[1].missingness


def test_equal_time_conflicting_observation_is_quarantined_as_semantic_contradiction(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    service.replay(_happy(repository_root))

    def change_price(value: dict[str, object]) -> None:
        value["elements"][0]["now_cost"] = 56  # type: ignore[index]

    blocked = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        bootstrap_change=change_price,
        captured_at=DEFAULT_CAPTURED_AT,
    )
    assert blocked.exit_code == 2
    assert blocked.result.status == "QUARANTINED"
    assert blocked.result.canonical_effects["error_code"] == "SEMANTIC_CONTRADICTION"
    with postgres_session_factory() as session:
        assert _count(session, player_observation) == 4
        assert _count(session, source_bundle) == 1


def test_equal_time_conflict_considers_deduplicated_observation_lineage(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    service.replay(_happy(repository_root))
    captured_at = DEFAULT_CAPTURED_AT + timedelta(minutes=10)

    unchanged = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        captured_at=captured_at,
    )
    assert unchanged.exit_code == 0

    def change_price(value: dict[str, object]) -> None:
        value["elements"][0]["now_cost"] = 56  # type: ignore[index]

    blocked = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        bootstrap_change=change_price,
        captured_at=captured_at,
    )
    assert blocked.exit_code == 2
    assert blocked.result.status == "QUARANTINED"
    assert blocked.result.canonical_effects["error_code"] == "SEMANTIC_CONTRADICTION"
    with postgres_session_factory() as session:
        assert _count(session, player_observation) == 4
        assert _count(session, source_bundle) == 2


def test_observation_contradiction_rolls_back_mixed_canonical_promotion(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    service = FplIngestionService(repository_root=repository_root)
    initial = service.replay(_happy(repository_root))
    assert initial.result.source_bundle is not None

    def add_player_and_conflict_on_price(value: dict[str, object]) -> None:
        elements = cast(list[dict[str, object]], value["elements"])
        elements[0]["now_cost"] = 56
        new_player = dict(elements[0])
        new_player.update(
            {
                "code": 20999,
                "first_name": "Synthetic",
                "id": 99,
                "second_name": "Rollback",
                "web_name": "S. Rollback",
            }
        )
        elements.append(new_player)

    blocked = _modified_import(
        repository_root,
        tmp_path,
        monkeypatch,
        bootstrap_change=add_player_and_conflict_on_price,
        captured_at=DEFAULT_CAPTURED_AT,
    )
    assert blocked.exit_code == 2
    assert blocked.result.status == "QUARANTINED"
    assert blocked.result.canonical_effects["error_code"] == "SEMANTIC_CONTRADICTION"
    with postgres_session_factory() as session:
        assert _count(session, player) == 4
        assert _count(session, player_season) == 4
        assert _count(session, player_observation) == 4
        assert _count(session, semantic_observation_claim) == 9
        assert _count(session, source_bundle) == 1


def test_every_published_source_link_points_to_usable_snapshot(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    outcome = FplIngestionService(repository_root=repository_root).replay(_happy(repository_root))
    assert outcome.result.source_bundle is not None
    with postgres_session_factory() as session:
        nonusable_links = session.scalar(
            text(
                """
                SELECT count(*)
                FROM (
                  SELECT source_snapshot_id FROM fpl.team_observation
                  UNION ALL SELECT source_snapshot_id FROM fpl.player_observation
                  UNION ALL SELECT source_snapshot_id FROM fpl.gameweek_observation
                  UNION ALL SELECT source_snapshot_id FROM fpl.fixture_observation
                  UNION ALL SELECT evidence_source_snapshot_id FROM core.external_identifier
                  UNION ALL SELECT source_snapshot_id FROM core.entity_alias
                  UNION ALL SELECT source_snapshot_id FROM football.player_team_membership
                  UNION ALL SELECT source_snapshot_id FROM football.fixture_revision
                  UNION ALL SELECT source_snapshot_id FROM football.fixture_gameweek_assignment
                ) AS linked
                JOIN provenance.source_snapshot_lifecycle AS lifecycle
                  ON lifecycle.source_snapshot_id = linked.source_snapshot_id
                WHERE lifecycle.current_state <> 'USABLE'
                """
            )
        )
        assert nonusable_links == 0
        assert _count(session, source_snapshot) == 2
