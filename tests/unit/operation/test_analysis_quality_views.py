"""Transactional derived-view expansion preserves v1 historical bytes and semantics."""

import json
import sqlite3
from contextlib import closing

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation import analysis_store
from dmf_pulse.operation.analysis_store import AnalysisStore
from tests.unit.operation.test_analysis_quality import snapshot as snapshot


def as_v1(store):
    with closing(sqlite3.connect(store.path)) as db, db:
        for name in (
            "player_component_metrics_v2",
            "player_fixture_metrics_v2",
            "player_gameweek_metrics_v2",
        ):
            db.execute(f"DROP VIEW {name}")
        db.execute("PRAGMA user_version=1")


def test_v1_read_and_atomic_idempotent_v2_migration_preserve_all_original_records(
    snapshot, tmp_path
):
    store = AnalysisStore(tmp_path / "copy" / "warehouse.sqlite")
    store.initialize()
    digest = store.stage(snapshot)
    store.confirm(snapshot.run_id, digest, "a" * 64, at=snapshot.recorded_at)
    as_v1(store)
    before = store.path.read_bytes()
    payload = store.export_json()
    v1_rows = store.query("SELECT * FROM player_forecasts")
    assert store.snapshot() == snapshot
    assert store.path.read_bytes() == before
    store.initialize()
    assert store.export_json() == payload
    assert store.query("SELECT * FROM player_forecasts") == v1_rows
    assert store.snapshot().semantic_sha256 == digest
    first_migration = store.path.read_bytes()
    store.initialize()
    assert store.path.read_bytes() == first_migration
    with closing(sqlite3.connect(store.path)) as db, db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
            db.execute("UPDATE snapshots SET digest=digest")


def test_metrics_join_exact_player_fixture_gameweek_components_and_preserve_nulls(
    snapshot, tmp_path
):
    store = AnalysisStore(tmp_path / "metrics" / "warehouse.sqlite")
    store.initialize()
    digest = store.stage(snapshot)
    store.confirm(snapshot.run_id, digest, "b" * 64, at=snapshot.recorded_at)
    gameweeks = store.query(
        "SELECT official_id,player_id,gameweek,expected_points,snapshot_sha256 FROM player_gameweek_metrics_v2"
    )
    assert len(gameweeks) == sum(len(g.summaries) for g in snapshot.presentation.gameweeks)
    catalogue = {p.player_id: p for p in snapshot.presentation.catalogue}
    for row in gameweeks:
        assert row["official_id"] == catalogue[row["player_id"]].official_id
        assert row["snapshot_sha256"] == digest
    components = store.query(
        "SELECT metric_scope,player_id,gameweek,SUM(expected_points) AS total FROM player_component_metrics_v2 WHERE metric_scope='GAMEWEEK' GROUP BY metric_scope,player_id,gameweek"
    )
    means = {(r["player_id"], r["gameweek"]): r["expected_points"] for r in gameweeks}
    assert len(components) == len(gameweeks)
    for row in components:
        assert row["total"] == pytest.approx(means[row["player_id"], row["gameweek"]], abs=1e-10)
    fixtures = store.query(
        "SELECT official_fixture_id,player_id,p_start,p_zero_minutes,minute_pmf_json FROM player_fixture_metrics_v2"
    )
    assert len(fixtures) == sum(len(f.summaries) for f in snapshot.presentation.fixtures)
    for row in fixtures:
        original = next(
            f
            for f in snapshot.presentation.fixtures
            if f.official_fixture_id == row["official_fixture_id"]
        )
        assert row["p_start"] == original.minutes[row["player_id"]].p_start
        assert row["p_zero_minutes"] == original.minutes[row["player_id"]].p_zero_minutes
        assert row["minute_pmf_json"] is not None


def test_historical_absence_creates_no_fake_detail_rows_or_zeroes(snapshot, tmp_path):
    store = AnalysisStore(tmp_path / "old" / "warehouse.sqlite")
    store.initialize()
    old = snapshot.model_copy(update={"presentation": None})
    digest = store.stage(old)
    store.confirm(old.run_id, digest, "c" * 64, at=old.recorded_at)
    for view in (
        "player_gameweek_metrics_v2",
        "player_fixture_metrics_v2",
        "player_component_metrics_v2",
    ):
        assert store.query(f"SELECT * FROM {view}") == []
    assert len(store.query("SELECT * FROM player_forecasts")) == len(snapshot.view.players)


def test_migration_failure_rolls_back_every_new_view_and_version(snapshot, tmp_path, monkeypatch):
    store = AnalysisStore(tmp_path / "failed" / "warehouse.sqlite")
    store.initialize()
    as_v1(store)
    before = store.path.read_bytes()
    monkeypatch.setattr(
        analysis_store,
        "_QUALITY_VIEWS",
        analysis_store._QUALITY_VIEWS + "CREATE VIEW invalid AS SELECT (;",
    )
    with pytest.raises(sqlite3.Error):
        store.initialize()
    assert store.path.read_bytes() == before
    with closing(sqlite3.connect(store.path)) as db, db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_v2'").fetchall() == []


@pytest.mark.parametrize(
    "kind",
    ["canonical_player", "gameweek", "fixture", "fixture_key", "minutes_key", "team", "position"],
)
def test_ambiguous_metric_grains_never_enter_new_warehouse_rows(snapshot, tmp_path, kind):
    altered = snapshot
    if kind == "canonical_player":
        first, second, *rest = snapshot.view.players
        second = second.model_copy(
            update={
                "catalogue": second.catalogue.model_copy(
                    update={"player_id": first.catalogue.player_id}
                )
            }
        )
        altered = snapshot.model_copy(
            update={
                "presentation": None,
                "view": snapshot.view.model_copy(update={"players": (first, second, *rest)}),
            }
        )
    else:
        presentation = snapshot.presentation
        first = presentation.fixtures[0]
        if kind == "gameweek":
            presentation = presentation.model_copy(
                update={"gameweeks": (*presentation.gameweeks, presentation.gameweeks[0])}
            )
        elif kind == "fixture":
            presentation = presentation.model_copy(
                update={"fixtures": (*presentation.fixtures, first)}
            )
        elif kind == "team":
            first = first.model_copy(
                update={"home": "Owned Other Home", "away": "Owned Other Away"}
            )
            presentation = presentation.model_copy(
                update={"fixtures": (first, *presentation.fixtures[1:])}
            )
        elif kind == "position":
            key, value = next(iter(first.minutes.items()))
            alternate = "FWD" if value.position != "FWD" else "GK"
            body = value.model_dump(mode="json") | {"position": alternate}
            body["projection_sha256"] = canonical_sha256(
                {k: v for k, v in body.items() if k != "projection_sha256"}
            )
            changed = type(value).model_validate_json(json.dumps(body))
            first = first.model_copy(update={"minutes": first.minutes | {key: changed}})
            presentation = presentation.model_copy(
                update={"fixtures": (first, *presentation.fixtures[1:])}
            )
        else:
            field = "summaries" if kind == "fixture_key" else "minutes"
            values = getattr(first, field)
            key, value = next(iter(values.items()))
            mismatch = {"unknown": value} | {k: v for k, v in values.items() if k != key}
            first = first.model_copy(update={field: mismatch})
            presentation = presentation.model_copy(
                update={"fixtures": (first, *presentation.fixtures[1:])}
            )
        altered = snapshot.model_copy(update={"presentation": presentation})
    store = AnalysisStore(tmp_path / kind / "warehouse.sqlite")
    store.initialize()
    with pytest.raises(ValueError, match="METRIC_IDENTITY_AMBIGUOUS"):
        store.stage(altered)
    assert store.query("SELECT * FROM snapshots") == []


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("defect", ["digest", "identity"])
def test_v1_migration_refuses_corruption_and_ambiguous_historical_grains_without_changes(
    snapshot, tmp_path, confirmed, defect
):
    store = AnalysisStore(tmp_path / "refused" / "warehouse.sqlite")
    store.initialize()
    as_v1(store)
    old = snapshot.model_copy(update={"presentation": None})
    if defect == "identity":
        first, second, *rest = old.view.players
        second = second.model_copy(
            update={
                "catalogue": second.catalogue.model_copy(
                    update={"player_id": first.catalogue.player_id}
                )
            }
        )
        old = old.model_copy(
            update={"view": old.view.model_copy(update={"players": (first, second, *rest)})}
        )
    digest = "f" * 64 if defect == "digest" else old.semantic_sha256
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute(
            "INSERT INTO snapshots VALUES(?,?,?)", (old.run_id, digest, old.model_dump_json())
        )
        if confirmed:
            db.execute(
                "INSERT INTO publications VALUES(?,?,?,?)",
                (old.run_id, digest, "c" * 64, old.recorded_at.isoformat()),
            )
    before = store.path.read_bytes()
    error = "DIGEST_MISMATCH" if defect == "digest" else "METRIC_IDENTITY_AMBIGUOUS"
    with pytest.raises(ValueError, match=error):
        store.initialize()
    assert store.path.read_bytes() == before
    with closing(sqlite3.connect(store.path)) as db, db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_v2'").fetchall() == []
