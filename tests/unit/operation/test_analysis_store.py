"""Rights-safe immutable analytical history, SQL isolation and crash recovery."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.dashboard.synthetic import DEMO_TIME, run_synthetic_recommendation
from dmf_pulse.dashboard.views import desk_view
from dmf_pulse.operation.analysis_models import AnalysisSnapshot
from dmf_pulse.operation.analysis_store import AnalysisStore
from dmf_pulse.private_v1.progress import NullProgress


@pytest.fixture(scope="module")
def owned_snapshot():
    result = run_synthetic_recommendation(1, NullProgress())
    view = desk_view(
        result,
        job_id="owned-first",
        mode="SYNTHETIC_DEMONSTRATION",
        generated_at=DEMO_TIME,
        expires_at=DEMO_TIME + timedelta(minutes=15),
    )
    return AnalysisSnapshot(
        run_id=view.job_id,
        provenance_class="OWNED_SYNTHETIC",
        permission_origin="OWNED_FIXTURE",
        source_commit="1" * 40,
        implementation_sha="2" * 40,
        policy_sha256="3" * 64,
        wheel_sha256="4" * 64,
        recorded_at=DEMO_TIME,
        view=view,
        presentation=result.presentation,
    )


@pytest.fixture
def store(tmp_path):
    value = AnalysisStore(tmp_path / "analysis" / "warehouse.sqlite")
    value.initialize()
    return value


def publish(store, snapshot, canonical="a" * 64):
    digest = store.stage(snapshot)
    store.confirm(snapshot.run_id, digest, canonical, at=DEMO_TIME)
    return digest


def test_stage_not_visible_until_durable_canonical_confirmation(store, owned_snapshot):
    digest = store.stage(owned_snapshot)
    assert store.snapshot() is None
    assert store.query("select count(*) as n from runs") == [{"n": 0}]
    reopened = AnalysisStore(store.path)
    reopened.initialize()
    assert reopened.stage(owned_snapshot) == digest
    reopened.confirm(owned_snapshot.run_id, digest, "a" * 64, at=DEMO_TIME)
    reopened.confirm(owned_snapshot.run_id, digest, "a" * 64, at=datetime.now(UTC))
    assert reopened.snapshot() == owned_snapshot
    assert len(reopened.history()) == 1


def test_all_derived_outputs_and_unavailable_reason_survive_json_sql(store, owned_snapshot):
    publish(store, owned_snapshot)
    loaded = AnalysisSnapshot.model_validate_json(store.export_json())
    assert loaded == owned_snapshot
    assert store.query("select count(*) as n from player_forecasts")[0]["n"] == len(
        owned_snapshot.view.players
    )
    assert store.query("select count(*) as n from manager_squad") == [{"n": 15}]
    assert store.query("select count(*) as n from fixture_projections")[0]["n"] == len(
        owned_snapshot.presentation.fixtures
    )
    assert store.query("select count(*) as n from transfer_plans")[0]["n"] == len(
        owned_snapshot.view.team.decision.transfer_frontier.points
    )
    assert store.query("select captaincy_explanation,validation from runs") == [
        {
            "captaincy_explanation": "UNAVAILABLE_IN_RETAINED_ENGINE_OUTPUT",
            "validation": "UNVALIDATED",
        }
    ]
    assert json.loads(
        store.query("select manager_decision_json from runs")[0]["manager_decision_json"]
    ) == owned_snapshot.view.team.model_dump(mode="json")


@pytest.mark.parametrize(
    "sql",
    [
        "delete from snapshots",
        "update snapshots set digest='x'",
        "drop table snapshots",
        "insert into failed_attempts values ('a','b','c')",
        "pragma journal_mode=wal",
        "attach database ':memory:' as other",
        "select load_extension('bad')",
        "select 1; delete from snapshots",
        "vacuum",
        "begin immediate",
    ],
)
def test_query_never_writes_attaches_or_loads_extensions(store, owned_snapshot, sql):
    publish(store, owned_snapshot)
    before = store.path.read_bytes()
    with pytest.raises(sqlite3.Error):
        store.query(sql)
    assert store.path.read_bytes() == before


def test_immutability_and_conflicting_publication_refused(store, owned_snapshot):
    digest = publish(store, owned_snapshot)
    with pytest.raises(ValueError, match="RUN_ID_CONFLICT"):
        store.stage(owned_snapshot.model_copy(update={"wheel_sha256": "5" * 64}))
    with pytest.raises(ValueError, match="PUBLICATION_CONFLICT"):
        store.confirm(owned_snapshot.run_id, digest, "b" * 64, at=DEMO_TIME)
    with sqlite3.connect(store.path) as connection:
        for table in ("snapshots", "publications", "failed_attempts"):
            if table == "failed_attempts":
                connection.execute("insert into failed_attempts values ('owned','now','BLOCKED')")
            for verb in (f"delete from {table}", f"update {table} set rowid=rowid"):
                with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
                    connection.execute(verb)
    assert store.snapshot() == owned_snapshot


def test_concurrent_idempotent_inserts_have_one_complete_snapshot(store, owned_snapshot):
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert len(set(executor.map(lambda _: publish(store, owned_snapshot), range(12)))) == 1
    assert store.query("select count(*) as n from snapshots") == [{"n": 1}]
    assert store.snapshot() == owned_snapshot


def test_restarts_select_older_run_and_no_partial_latest_pointer(store, owned_snapshot):
    publish(store, owned_snapshot)
    second_view = owned_snapshot.view.model_copy(
        update={"job_id": "second", "generated_at": DEMO_TIME + timedelta(days=1)}
    )
    second = owned_snapshot.model_copy(update={"run_id": "second", "view": second_view})
    store.stage(second)
    assert AnalysisStore(store.path).snapshot() == owned_snapshot
    publish(store, second, "b" * 64)
    assert AnalysisStore(store.path).snapshot() == second
    assert AnalysisStore(store.path).snapshot(owned_snapshot.run_id) == owned_snapshot
    assert (
        store.query("select count(*) as n from run_player_changes")[0]["n"]
        == len(owned_snapshot.view.players) * 2
    )


def test_failure_never_replaces_latest_and_error_text_is_closed(store, owned_snapshot):
    publish(store, owned_snapshot)
    store.failure("owned-failure", "RAW_SECRET_SENTINEL", at=DEMO_TIME)
    assert store.snapshot() == owned_snapshot
    assert "RAW_SECRET_SENTINEL" not in store.path.read_bytes().decode("latin1")
    assert store.query("select error_code from failed_attempts") == [
        {"error_code": "CURRENT_TYPED_FAILURE_UNRECOGNIZED"}
    ]


def test_readonly_cli_reads_without_launch_or_credentials(store, owned_snapshot, monkeypatch):
    from dmf_pulse.credentials.service import CredentialService

    monkeypatch.setattr(CredentialService, "resolve", lambda *_: pytest.fail("credential read"))
    monkeypatch.setattr(CredentialService, "status", lambda *_: pytest.fail("credential metadata"))
    publish(store, owned_snapshot)
    before = store.path.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "analysis",
            "query",
            "select count(*) as n from player_forecasts",
            "--database",
            str(store.path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["n"] == len(owned_snapshot.view.players)
    result = CliRunner().invoke(app, ["analysis", "export", "--database", str(store.path)])
    assert result.exit_code == 0
    assert AnalysisSnapshot.model_validate_json(result.output) == owned_snapshot
    assert store.path.read_bytes() == before


def test_unknown_schema_and_tampering_fail_closed(tmp_path, owned_snapshot):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("pragma user_version=99")
    with pytest.raises(ValueError, match="SCHEMA_VERSION_UNSUPPORTED"):
        AnalysisStore(path).initialize()
    path = tmp_path / "tamper.sqlite"
    value = AnalysisStore(path)
    value.initialize()
    publish(value, owned_snapshot)
    with sqlite3.connect(path) as connection:
        connection.execute("drop trigger snapshots_UPDATE")
        connection.execute("update snapshots set digest=?", ("f" * 64,))
        connection.execute("drop trigger publications_UPDATE")
        connection.execute("update publications set digest=?", ("f" * 64,))
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        value.snapshot()


def test_migration_failure_rolls_back_ddl_and_restarts_cleanly(tmp_path, monkeypatch):
    from dmf_pulse.operation import analysis_store

    path = tmp_path / "interrupted" / "derived.sqlite"
    store = AnalysisStore(path)
    original = analysis_store._SCHEMA
    monkeypatch.setattr(analysis_store, "_SCHEMA", original + "\nINVALID OWNED MIGRATION;\n")
    with pytest.raises(sqlite3.Error):
        store.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("pragma user_version").fetchone()[0] == 0
        assert connection.execute("select count(*) from sqlite_master").fetchone()[0] == 0
    monkeypatch.setattr(analysis_store, "_SCHEMA", original)
    store.initialize()
    assert store.snapshot() is None


def test_query_bounds_and_utc_confirmation_are_explicit(store, owned_snapshot):
    digest = publish(store, owned_snapshot)
    with pytest.raises(ValueError, match="ROW_LIMIT"):
        store.query("select * from player_forecasts", limit=1)
    with pytest.raises(ValueError, match="BOUND_EXCEEDED"):
        store.query("select 1", limit=0)
    with pytest.raises(ValueError, match="UTC_REQUIRED"):
        store.confirm(owned_snapshot.run_id, digest, "a" * 64, at=datetime(2026, 11, 4))
    assert store.snapshot() == owned_snapshot


def test_failed_attempt_preserves_closed_quota_receipt_without_changing_latest(
    store, owned_snapshot
):
    from dmf_pulse.operation.models import ChargedQuotaStatus

    publish(store, owned_snapshot)
    quota = ChargedQuotaStatus(
        remaining_credits=498,
        used_credits=2,
        last_request_cost=2,
        received_at=DEMO_TIME,
        provider_status=200,
        consistent_with_ledger=True,
        receipt_sha256="b" * 64,
    )
    store.failure(
        "owned-failed",
        "CURRENT_SNAPSHOT_INVALID",
        at=DEMO_TIME,
        quota=quota,
        provenance="OWNED_SYNTHETIC",
    )
    store.failure(
        "owned-failed",
        "CURRENT_SNAPSHOT_INVALID",
        at=DEMO_TIME + timedelta(seconds=1),
        quota=quota,
        provenance="OWNED_SYNTHETIC",
    )
    record = json.loads(store.query("select derived_json from failure_evidence")[0]["derived_json"])
    assert record["provenance_class"] == "OWNED_SYNTHETIC"
    assert record["quota"] == quota.model_dump(mode="json")
    assert store.snapshot() == owned_snapshot
    with pytest.raises(ValueError, match="FAILED_ATTEMPT_CONFLICT"):
        store.failure("owned-failed", "DIFFERENT_RAW_INPUT", at=DEMO_TIME)


def test_readonly_queries_bound_output_before_materializing_every_row(store):
    with pytest.raises(ValueError, match="OUTPUT_LIMIT"):
        store.query(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<20) SELECT printf('%0*d',1000000,x) AS large_value FROM n"
        )
    with pytest.raises(ValueError, match="BINARY_OUTPUT_REJECTED"):
        store.query("SELECT randomblob(10) AS owned_blob")
    with pytest.raises(sqlite3.DataError):
        store.query("SELECT randomblob(40000000) AS oversized_owned_blob")


def test_full_snapshot_capacity_is_separate_from_history_and_query_output_bounds(
    store, owned_snapshot
):
    # Reproduce the measured full native result's size without repeating its
    # expensive 760-player simulation. This is an explicitly owned derived note.
    large_view = owned_snapshot.view.model_copy(
        update={
            "restrictions": (*owned_snapshot.view.restrictions, "OWNED_NOTE_" + "x" * 17_500_000)
        }
    )
    large = owned_snapshot.model_copy(update={"view": large_view})
    publish(store, large)
    assert store.snapshot() == large
    history = store.history()
    assert history[0]["run_id"] == large.run_id
    assert len(json.dumps(history)) < 4096
    assert AnalysisSnapshot.model_validate_json(store.export_json()) == large
    with pytest.raises(ValueError, match="OUTPUT_LIMIT"):
        store.query("SELECT payload FROM snapshots")
    before = store.path.read_bytes()
    too_large = large.model_copy(
        update={"view": large_view.model_copy(update={"restrictions": ("x" * 33_554_432,)})}
    )
    with pytest.raises(ValueError, match="SNAPSHOT_TOO_LARGE"):
        store.stage(too_large)
    assert store.path.read_bytes() == before
