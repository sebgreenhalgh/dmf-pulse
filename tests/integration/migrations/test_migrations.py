"""Alembic reversibility and exact PostgreSQL catalog acceptance."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Table, delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import (
    canonical_entity,
    data_provider,
    data_quality_issue,
    external_identifier,
    fixture,
    market_consensus_outcome,
    market_consensus_result,
    market_normalisation_book_source,
    market_normalisation_exclusion,
    market_normalisation_policy,
    market_normalisation_run,
    market_normalisation_source,
    market_normalisation_warning,
    metadata,
    normalised_operator_market,
    normalised_operator_market_source,
    normalised_operator_outcome,
    odds_mapping_dependency,
    odds_observation,
    odds_publication_attestation,
    odds_publication_batch,
    operator_fixture_market,
    operator_market_observation,
    provider_market_representation,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.database.doctor import build_database_doctor
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.migrate import (
    alembic_config,
    downgrade_database,
    head_revision,
    upgrade_database,
)
from dmf_pulse.database.schema import inspect_schema
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.service import DEFAULT_CUTOFF, OddsIngestionService, OddsReplayRequest

pytestmark = pytest.mark.migration
EXPECTED_SCHEMA_SHA256 = "9d15f10b4129f3846a22875c1482001e3975dead606848119fb440cbfc9796c3"
NORMALISATION_AS_OF = datetime(2026, 8, 20, 12, 5, tzinfo=UTC)
NRM006_TABLES = {
    "betting.market_consensus_outcome",
    "betting.market_consensus_result",
    "betting.market_normalisation_book_source",
    "betting.market_normalisation_exclusion",
    "betting.market_normalisation_policy",
    "betting.market_normalisation_run",
    "betting.market_normalisation_source",
    "betting.market_normalisation_warning",
    "betting.normalised_operator_market",
    "betting.normalised_operator_market_source",
    "betting.normalised_operator_outcome",
    "betting.odds_mapping_dependency",
    "betting.odds_publication_attestation",
    "betting.odds_publication_batch",
}


def _catalog_names(manifest: object) -> tuple[set[str], set[str]]:
    schemas = manifest.schemas  # type: ignore[attr-defined]
    tables = {f"{schema}.{table}" for schema, value in schemas.items() for table in value["tables"]}
    views = {f"{schema}.{view}" for schema, value in schemas.items() for view in value["views"]}
    return tables, views


def test_catalog_matches_expected_schema_and_is_deterministic(
    postgres_engine: Engine, repository_root: Path, postgres_url: str
) -> None:
    expected = json.loads(
        (repository_root / "fixtures/data_model/DAT-003/expected_schema.json").read_text(
            encoding="utf-8"
        )
    )
    with postgres_engine.connect() as connection:
        first = inspect_schema(connection)
        second = inspect_schema(connection)
    tables, views = _catalog_names(first)
    assert tables >= set(expected["tables"])
    assert views >= set(expected["views"])
    assert {
        "fpl.current_fixture_observation",
        "fpl.current_gameweek_observation",
        "fpl.current_player_observation",
        "fpl.current_team_observation",
        "provenance.available_raw_storage_object",
        "provenance.source_snapshot_lifecycle",
    } <= views
    assert set(first.extensions) == set(expected["extensions"])
    assert first.schema_sha256 == second.schema_sha256
    assert first.schema_sha256 == EXPECTED_SCHEMA_SHA256
    assert first.alembic_revision == head_revision() == "20260807_0006"

    function_names = {
        f"{schema}.{function['name']}"
        for schema, value in first.schemas.items()
        for function in value["functions"]
    }
    assert function_names == {
        "betting.guard_book_completeness",
        "betting.guard_consensus_vector",
        "betting.guard_normalisation_book_source_fixture",
        "betting.guard_normalisation_run_graph",
        "betting.guard_normalisation_run_open",
        "betting.guard_normalisation_source_fixture",
        "betting.guard_normalisation_vectors",
        "betting.guard_normalised_operator_source",
        "betting.guard_normalised_operator_source_count",
        "betting.guard_odds_mapping_dependency",
        "betting.guard_odds_observation_coherence",
        "betting.guard_odds_publication_attestation",
        "betting.guard_odds_publication_batch",
        "betting.guard_odds_quality_subject",
        "betting.guard_operator_book_observation",
        "betting.guard_provider_market_representation",
        "betting.guard_quota_provider",
        "betting.reject_immutable_change",
        "betting.require_odds_mapping_dependency",
        "core.guard_canonical_successor",
        "core.guard_temporal_version",
        "core.is_canonical_tstzrange",
        "football.reject_immutable_availability_change",
        "football.validate_lineup_scenario",
        "football.validate_minute_pmf",
        "football.validate_player_minutes_projection",
        "football.validate_prediction_complete",
        "football.round_half_even_6",
        "provenance.guard_processing_event",
        "provenance.guard_fpl_observation_source_usable",
        "provenance.guard_raw_storage_rights",
        "provenance.guard_source_bundle_publication",
        "provenance.guard_source_snapshot_envelope",
        "provenance.lock_bundle_quality_subject",
        "provenance.reject_immutable_change",
        "provenance.validate_dataset_complete",
        "provenance.validate_model_dataset_complete",
    }
    trigger_names = {
        trigger["name"] for value in first.schemas.values() for trigger in value["triggers"]
    }
    assert trigger_names == {
        "trg_betting_operator_immutable",
        "trg_canonical_entity_successor",
        "trg_data_quality_bundle_lock",
        "trg_data_quality_odds_guard",
        "trg_entity_alias_temporal",
        "trg_external_identifier_temporal",
        "trg_fixture_gameweek_assignment_temporal",
        "trg_fixture_observation_immutable",
        "trg_fixture_observation_source_usable",
        "trg_fixture_revision_temporal",
        "trg_gameweek_observation_immutable",
        "trg_gameweek_observation_source_usable",
        "trg_market_definition_immutable",
        "trg_market_consensus_outcome_immutable",
        "trg_market_consensus_outcome_run_open",
        "trg_market_consensus_parent_vector",
        "trg_market_consensus_result_immutable",
        "trg_market_consensus_result_run_open",
        "trg_market_consensus_run_graph",
        "trg_market_consensus_vector",
        "trg_market_normalisation_exclusion_immutable",
        "trg_market_normalisation_exclusion_run_graph",
        "trg_market_normalisation_book_source_fixture",
        "trg_market_normalisation_book_source_immutable",
        "trg_market_normalisation_book_source_run_open",
        "trg_market_normalisation_policy_immutable",
        "trg_market_normalisation_run_graph",
        "trg_market_normalisation_run_immutable",
        "trg_market_normalisation_source_fixture",
        "trg_market_normalisation_source_immutable",
        "trg_market_normalisation_source_run_open",
        "trg_market_normalisation_warning_immutable",
        "trg_market_normalisation_warning_run_graph",
        "trg_market_normalisation_warning_run_open",
        "trg_market_normalisation_exclusion_run_open",
        "trg_market_selection_immutable",
        "trg_normalised_operator_market_immutable",
        "trg_normalised_operator_market_run_open",
        "trg_normalised_operator_market_source_immutable",
        "trg_normalised_operator_market_source_run_open",
        "trg_normalised_operator_parent_source_count",
        "trg_normalised_operator_parent_vector",
        "trg_normalised_operator_outcome_immutable",
        "trg_normalised_operator_outcome_run_open",
        "trg_normalised_operator_outcome_source_count",
        "trg_normalised_operator_run_graph",
        "trg_normalised_operator_source_count",
        "trg_normalised_operator_source_guard",
        "trg_normalised_operator_vector",
        "trg_odds_mapping_dependency_guard",
        "trg_odds_mapping_dependency_immutable",
        "trg_odds_observation_coherence",
        "trg_odds_observation_completeness",
        "trg_odds_observation_immutable",
        "trg_odds_publication_attestation_guard",
        "trg_odds_publication_attestation_immutable",
        "trg_odds_publication_batch_guard",
        "trg_odds_publication_batch_immutable",
        "trg_operator_book_completeness",
        "trg_operator_book_mapping_dependency",
        "trg_operator_book_observation_guard",
        "trg_operator_fixture_market_immutable",
        "trg_operator_market_observation_immutable",
        "trg_player_observation_immutable",
        "trg_player_observation_source_usable",
        "trg_player_season_immutable",
        "trg_player_team_membership_temporal",
        "trg_provider_market_representation_guard",
        "trg_provider_market_representation_immutable",
        "trg_provider_quota_observation_guard",
        "trg_provider_quota_observation_immutable",
        "trg_raw_blob_deletion_immutable",
        "trg_raw_blob_immutable",
        "trg_raw_storage_deletion_immutable",
        "trg_raw_storage_object_immutable",
        "trg_raw_storage_rights",
        "trg_rights_decision_immutable",
        "trg_rights_profile_immutable",
        "trg_ruleset_activation_immutable",
        "trg_ruleset_artifact_immutable",
        "trg_semantic_effect_source_immutable",
        "trg_semantic_observation_claim_immutable",
        "trg_settlement_profile_immutable",
        "trg_source_bundle_immutable",
        "trg_source_bundle_member_immutable",
        "trg_source_bundle_member_publication_guard",
        "trg_source_bundle_publication_guard",
        "trg_source_mapping_candidate_immutable",
        "trg_source_processing_event_guard",
        "trg_source_snapshot_envelope",
        "trg_source_snapshot_immutable",
        "trg_team_observation_immutable",
        "trg_team_observation_source_usable",
        "trg_min007f_immutable_0",
        "trg_min007f_immutable_1",
        "trg_min007f_immutable_2",
        "trg_min007f_immutable_3",
        "trg_min007f_immutable_4",
        "trg_min007f_immutable_5",
        "trg_min007f_immutable_6",
        "trg_min007f_immutable_7",
        "trg_min007f_immutable_8",
        "trg_min007f_immutable_9",
        "trg_min007f_immutable_10",
        "trg_min007f_immutable_11",
        "trg_min007f_scenario_parent",
        "trg_min007f_scenario_member",
        "trg_min007f_dataset_complete",
        "trg_min007f_model_dataset_complete",
        "trg_min007f_prediction_complete",
    }
    trigger_definitions = {
        trigger["name"]: trigger["definition"]
        for value in first.schemas.values()
        for trigger in value["triggers"]
    }
    for trigger_name in (
        "trg_market_consensus_parent_vector",
        "trg_market_consensus_run_graph",
        "trg_market_normalisation_exclusion_run_graph",
        "trg_market_normalisation_run_graph",
        "trg_market_normalisation_warning_run_graph",
        "trg_normalised_operator_parent_source_count",
        "trg_normalised_operator_parent_vector",
        "trg_normalised_operator_outcome_source_count",
        "trg_normalised_operator_run_graph",
        "trg_normalised_operator_source_count",
        "trg_operator_book_mapping_dependency",
    ):
        assert "DEFERRABLE INITIALLY DEFERRED" in trigger_definitions[trigger_name]
    exclusions = [
        constraint
        for value in first.schemas.values()
        for table in value["tables"].values()
        for constraint in table["constraints"]
        if constraint["kind"] == "EXCLUSION"
    ]
    assert len(exclusions) == 5
    assert all(item["deferrable"] is True for item in exclusions)
    assert all(item["initially_deferred"] is False for item in exclusions)

    for table in metadata.sorted_tables:
        schema_name = table.schema or "public"
        declared = first.schemas[schema_name]["tables"][table.name]
        assert {column["name"] for column in declared["columns"]} == {
            column.name for column in table.columns
        }
        if table.fullname not in NRM006_TABLES:
            assert {
                constraint["name"]
                for constraint in declared["constraints"]
                if constraint["kind"] not in {"n", "t"}
            } == {constraint.name for constraint in table.constraints}
        assert {index.name for index in table.indexes} <= {
            index["name"] for index in declared["indexes"]
        }

    doctor = build_database_doctor(postgres_engine, postgres_url)
    assert doctor.status == "HEALTHY"
    assert doctor.postgres.major == 18
    assert set(doctor.capabilities) == set(expected["required_capabilities"])
    assert all(doctor.capabilities.values())


def test_single_linear_revision_and_secret_free_offline_sql(postgres_url: str) -> None:
    revisions = list(ScriptDirectory.from_config(alembic_config()).walk_revisions())
    assert [(revision.revision, revision.down_revision) for revision in revisions] == [
        ("20260807_0006", "20260803_0005"),
        ("20260803_0005", "20260725_0004"),
        ("20260725_0004", "20260725_0003"),
        ("20260725_0003", "20260724_0002"),
        ("20260724_0002", "20260723_0001"),
        ("20260723_0001", None),
    ]
    output = io.StringIO()
    with redirect_stdout(output):
        command.upgrade(alembic_config(postgres_url), "head", sql=True)
    sql = output.getvalue()
    assert "CREATE SCHEMA core" in sql
    assert "CREATE TABLE football.player_team_membership" in sql
    assert all(value not in sql for value in ("changeme", "dmf_test_password"))
    assert "postgresql+psycopg" not in sql


def test_alembic_metadata_drift_check_is_clean(postgres_url: str) -> None:
    command.check(alembic_config(postgres_url))


def _replay_happy_path(repository_root: Path) -> None:
    replay = OddsIngestionService(repository_root=repository_root).replay(
        OddsReplayRequest(
            fixture_set=repository_root / "fixtures/odds/ODD-005",
            scenario="happy_path",
            information_cutoff=DEFAULT_CUTOFF,
            database_url_ref=DATABASE_REF,
        )
    )
    assert replay.exit_code == 0


def _quality_issue_values(source_snapshot_id: object, *, issue_type: str) -> dict[str, object]:
    return {
        "source_snapshot_id": source_snapshot_id,
        "issue_type": issue_type,
        "severity": "P1",
        "status": "OPEN",
        "detected_at": NORMALISATION_AS_OF,
        "decision_impact": "block normalisation until resolved",
        "details": {"synthetic_test": True},
        "subject_scope": "SOURCE_SNAPSHOT",
        "stage": "NORMALISATION",
        "message": "synthetic post-publication blocking issue",
    }


def test_publication_first_allows_later_blocking_quality_knowledge(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay_happy_path(repository_root)
    with postgres_session_factory.begin() as session:
        snapshot_id = session.scalar(
            select(operator_market_observation.c.source_snapshot_id).limit(1)
        )
        assert snapshot_id is not None
        issue_id = session.execute(
            insert(data_quality_issue)
            .values(**_quality_issue_values(snapshot_id, issue_type="POST_PUBLICATION_P1"))
            .returning(data_quality_issue.c.data_quality_issue_id)
        ).scalar_one()
    with postgres_session_factory.begin() as session:
        session.execute(
            update(data_quality_issue)
            .where(data_quality_issue.c.data_quality_issue_id == issue_id)
            .values(status="RESOLVED", resolved_at=NORMALISATION_AS_OF + timedelta(seconds=1))
        )
    with postgres_session_factory() as session:
        assert (
            session.scalar(
                select(data_quality_issue.c.status).where(
                    data_quality_issue.c.data_quality_issue_id == issue_id
                )
            )
            == "RESOLVED"
        )


@pytest.mark.parametrize(
    "subject_scope",
    ("SOURCE_SNAPSHOT", "INGESTION_RUN", "CANONICAL_ENTITY"),
)
def test_blocking_quality_subject_locks_derived_odds_snapshots(
    repository_root: Path,
    postgres_engine: Engine,
    subject_scope: str,
) -> None:
    _replay_happy_path(repository_root)
    with postgres_engine.connect() as connection:
        subject = (
            connection.execute(
                select(
                    source_snapshot.c.source_snapshot_id,
                    source_snapshot.c.ingestion_run_id,
                    operator_fixture_market.c.fixture_id,
                )
                .join(
                    operator_market_observation,
                    operator_market_observation.c.source_snapshot_id
                    == source_snapshot.c.source_snapshot_id,
                )
                .join(
                    operator_fixture_market,
                    operator_fixture_market.c.market_id == operator_market_observation.c.market_id,
                )
                .limit(1)
            )
            .mappings()
            .one()
        )
    values = _quality_issue_values(
        subject["source_snapshot_id"], issue_type=f"{subject_scope}_LOCK_P1"
    )
    if subject_scope == "INGESTION_RUN":
        values["source_snapshot_id"] = None
        values["ingestion_run_id"] = subject["ingestion_run_id"]
        values["subject_scope"] = subject_scope
    elif subject_scope == "CANONICAL_ENTITY":
        values["source_snapshot_id"] = None
        values["canonical_entity_id"] = subject["fixture_id"]
        values["subject_scope"] = subject_scope

    with postgres_engine.connect() as lock_holder:
        transaction = lock_holder.begin()
        lock_holder.execute(insert(data_quality_issue).values(**values))
        with postgres_engine.connect() as contender:
            acquired = contender.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": f"bundle-quality:{subject['source_snapshot_id']}"},
            )
            assert acquired is False
        transaction.rollback()


def test_blocking_quality_first_prevents_later_book_publication(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay_happy_path(repository_root)
    with postgres_session_factory() as session:
        book = dict(session.execute(select(operator_market_observation).limit(1)).mappings().one())

    with (
        pytest.raises(DBAPIError, match="ODDS_PUBLICATION_BLOCKED"),
        postgres_session_factory.begin() as session,
    ):
        for table_name, trigger_name in (
            ("odds_observation", "trg_odds_observation_immutable"),
            ("odds_mapping_dependency", "trg_odds_mapping_dependency_immutable"),
            ("operator_market_observation", "trg_operator_market_observation_immutable"),
        ):
            session.execute(
                text(f"ALTER TABLE betting.{table_name} DISABLE TRIGGER {trigger_name}")
            )
        session.execute(
            delete(odds_observation).where(
                odds_observation.c.book_observation_id == book["book_observation_id"]
            )
        )
        session.execute(
            delete(odds_mapping_dependency).where(
                odds_mapping_dependency.c.provider_market_representation_id
                == book["provider_market_representation_id"],
                odds_mapping_dependency.c.publication_batch_id == book["publication_batch_id"],
            )
        )
        session.execute(
            delete(operator_market_observation).where(
                operator_market_observation.c.book_observation_id == book["book_observation_id"]
            )
        )
        for table_name, trigger_name in (
            ("odds_observation", "trg_odds_observation_immutable"),
            ("odds_mapping_dependency", "trg_odds_mapping_dependency_immutable"),
            ("operator_market_observation", "trg_operator_market_observation_immutable"),
        ):
            session.execute(text(f"ALTER TABLE betting.{table_name} ENABLE TRIGGER {trigger_name}"))
        session.execute(
            insert(data_quality_issue).values(
                **_quality_issue_values(book["source_snapshot_id"], issue_type="PRE_PUBLICATION_P1")
            )
        )
        replacement = {key: value for key, value in book.items() if key != "created_at"}
        session.execute(insert(operator_market_observation).values(**replacement))


def test_mapping_dependencies_are_activation_scoped_guarded_and_immutable(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay_happy_path(repository_root)
    with postgres_session_factory() as session:
        dependencies = [
            dict(row) for row in session.execute(select(odds_mapping_dependency)).mappings()
        ]
        book_scopes = set(
            session.execute(
                select(
                    operator_market_observation.c.provider_market_representation_id,
                    operator_market_observation.c.publication_batch_id,
                )
            ).all()
        )
    assert len(dependencies) == 2
    assert {
        (
            row["provider_market_representation_id"],
            row["publication_batch_id"],
        )
        for row in dependencies
    } == book_scopes
    assert all(
        len(str(row["dependency_sha256"])) == 64
        and set(str(row["dependency_sha256"])) <= set("0123456789abcdef")
        for row in dependencies
    )
    for row in dependencies:
        expected_commence_time = row["expected_commence_time"]
        assert isinstance(expected_commence_time, datetime)
        assert row["dependency_sha256"] == canonical_sha256(
            {
                "provider_market_representation_id": str(row["provider_market_representation_id"]),
                "mapping_plan_sha256": row["mapping_plan_sha256"],
                "fixture_lookup_mapping_id": str(row["fixture_lookup_mapping_id"]),
                "home_team_mapping_id": str(row["home_team_mapping_id"]),
                "away_team_mapping_id": str(row["away_team_mapping_id"]),
                "fixture_observation_id": str(row["fixture_observation_id"]),
                "expected_commence_time": expected_commence_time.isoformat(),
            }
        )

    selected = dependencies[0]
    with (
        pytest.raises(DBAPIError, match="IMMUTABLE_MARKET_RECORD"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            update(odds_mapping_dependency)
            .where(
                odds_mapping_dependency.c.provider_market_representation_id
                == selected["provider_market_representation_id"],
                odds_mapping_dependency.c.publication_batch_id == selected["publication_batch_id"],
            )
            .values(dependency_sha256="f" * 64)
        )

    with (
        pytest.raises(DBAPIError, match="ODDS_MAPPING_DEPENDENCY_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.odds_mapping_dependency "
                "DISABLE TRIGGER trg_odds_mapping_dependency_immutable"
            )
        )
        session.execute(
            delete(odds_mapping_dependency).where(
                odds_mapping_dependency.c.provider_market_representation_id
                == selected["provider_market_representation_id"],
                odds_mapping_dependency.c.publication_batch_id == selected["publication_batch_id"],
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.odds_mapping_dependency "
                "ENABLE TRIGGER trg_odds_mapping_dependency_immutable"
            )
        )
        invalid = {
            key: value
            for key, value in selected.items()
            if key not in {"created_at", "home_team_mapping_id", "away_team_mapping_id"}
        }
        invalid["home_team_mapping_id"] = selected["away_team_mapping_id"]
        invalid["away_team_mapping_id"] = selected["home_team_mapping_id"]
        session.execute(insert(odds_mapping_dependency).values(**invalid))


def _seed_published_normalisation(
    repository_root: Path, postgres_session_factory: sessionmaker[Session]
) -> None:
    _replay_happy_path(repository_root)
    probabilities = {
        "HOME": Decimal("0.500000000000"),
        "DRAW": Decimal("0.300000000000"),
        "AWAY": Decimal("0.200000000000"),
    }
    market_probabilities = {
        "HOME": Decimal("0.520000000000"),
        "DRAW": Decimal("0.280000000000"),
        "AWAY": Decimal("0.200000000000"),
    }
    with postgres_session_factory.begin() as session:
        observations = [
            dict(row)
            for row in session.execute(
                select(
                    odds_observation,
                    provider_market_representation.c.provider_id,
                    external_identifier.c.external_id_text.label("operator_key"),
                )
                .join(
                    operator_market_observation,
                    operator_market_observation.c.book_observation_id
                    == odds_observation.c.book_observation_id,
                )
                .join(
                    provider_market_representation,
                    provider_market_representation.c.provider_market_representation_id
                    == operator_market_observation.c.provider_market_representation_id,
                )
                .join(
                    external_identifier,
                    external_identifier.c.external_identifier_id
                    == provider_market_representation.c.operator_mapping_id,
                )
                .order_by(odds_observation.c.market_id, odds_observation.c.outcome)
            ).mappings()
        ]
        assert len(observations) == 6
        fixture_ids = {row["fixture_id"] for row in observations}
        assert len(fixture_ids) == 1
        fixture_id = fixture_ids.pop()
        attested_usable_at = session.scalar(select(odds_publication_attestation.c.usable_at))
        assert isinstance(attested_usable_at, datetime)
        policy_sha256 = "0" * 64
        session.execute(
            insert(market_normalisation_policy).values(
                policy_sha256=policy_sha256,
                policy_id="migration-relational-guard-test",
                policy_version="1.0.0",
                policy_document={},
            )
        )
        run_id = session.execute(
            insert(market_normalisation_run)
            .values(
                fixture_id=fixture_id,
                market_definition="FULL_TIME_1X2",
                as_of=NORMALISATION_AS_OF,
                mapping_cutoff=NORMALISATION_AS_OF,
                policy_sha256=policy_sha256,
                code_identity="migration-relational-guard-test",
                input_signature_sha256="1" * 64,
                semantic_result_sha256="2" * 64,
                status="NORMALISED",
            )
            .returning(market_normalisation_run.c.normalisation_run_id)
        ).scalar_one()
        session.execute(
            insert(market_normalisation_source),
            [
                {
                    "normalisation_run_id": run_id,
                    "odds_observation_id": row["odds_observation_id"],
                    "source_snapshot_id": row["source_snapshot_id"],
                }
                for row in observations
            ],
        )
        grouped: dict[object, list[dict[str, object]]] = {}
        for row in observations:
            grouped.setdefault(row["market_id"], []).append(row)
        assert len(grouped) == 2
        session.execute(
            insert(market_normalisation_book_source),
            [
                {
                    "normalisation_run_id": run_id,
                    "book_observation_id": rows[0]["book_observation_id"],
                    "source_snapshot_id": rows[0]["source_snapshot_id"],
                }
                for rows in grouped.values()
            ],
        )
        for index, rows in enumerate(grouped.values(), start=3):
            first = rows[0]
            raw_probabilities: dict[str, Decimal] = {}
            for row in rows:
                decimal_odds = row["decimal_odds"]
                assert isinstance(decimal_odds, Decimal)
                raw_probabilities[str(row["outcome"])] = (Decimal(1) / decimal_odds).quantize(
                    Decimal("0.000000000001")
                )
            raw_booksum = sum(raw_probabilities.values(), start=Decimal(0))
            parent_id = session.execute(
                insert(normalised_operator_market)
                .values(
                    normalisation_run_id=run_id,
                    fixture_id=fixture_id,
                    market_id=first["market_id"],
                    provider_id=first["provider_id"],
                    operator_id=first["operator_id"],
                    operator_key=first["operator_key"],
                    observed_at=first["observed_at"],
                    usable_at=attested_usable_at,
                    primary_method="POWER",
                    fallback_used=False,
                    raw_booksum=raw_booksum,
                    overround=raw_booksum - 1,
                    power_exponent=Decimal("1.100000000000"),
                    input_signature_sha256=str(index) * 64,
                    result_sha256=str(index + 2) * 64,
                )
                .returning(normalised_operator_market.c.normalised_operator_market_id)
            ).scalar_one()
            session.execute(
                insert(normalised_operator_outcome),
                [
                    {
                        "normalised_operator_market_id": parent_id,
                        "normalisation_run_id": run_id,
                        "outcome": row["outcome"],
                        "decimal_odds": row["decimal_odds"],
                        "raw_implied_probability": raw_probabilities[str(row["outcome"])],
                        "proportional_probability": probabilities[str(row["outcome"])],
                        "market_probability": market_probabilities[str(row["outcome"])],
                    }
                    for row in rows
                ],
            )
            session.execute(
                insert(normalised_operator_market_source),
                [
                    {
                        "normalised_operator_market_id": parent_id,
                        "normalisation_run_id": run_id,
                        "odds_observation_id": row["odds_observation_id"],
                        "source_snapshot_id": row["source_snapshot_id"],
                        "fixture_id": fixture_id,
                    }
                    for row in rows
                ],
            )
        session.execute(
            insert(market_consensus_result).values(
                normalisation_run_id=run_id,
                provider_count=1,
                operator_count=2,
                eligible_operator_count=2,
                operator_disagreement=Decimal("0"),
                method_disagreement=Decimal("0"),
                market_disagreement=Decimal("0"),
                minimum_age_seconds=0,
                maximum_age_seconds=0,
                confidence_grade="B",
                input_signature_sha256="6" * 64,
                result_sha256="7" * 64,
            )
        )
        session.execute(
            insert(market_consensus_outcome),
            [
                {
                    "normalisation_run_id": run_id,
                    "outcome": outcome,
                    "consensus_probability": probability,
                    "lower_bound": probability,
                    "upper_bound": probability,
                }
                for outcome, probability in probabilities.items()
            ],
        )


def _copy_run(session: Session, source: dict[str, object], *, seed: str) -> object:
    return session.execute(
        insert(market_normalisation_run)
        .values(
            fixture_id=source["fixture_id"],
            market_definition=source["market_definition"],
            as_of=source["as_of"],
            mapping_cutoff=source["mapping_cutoff"],
            policy_sha256=source["policy_sha256"],
            code_identity=f"migration-vector-negative-{seed}",
            input_signature_sha256=seed * 64,
            semantic_result_sha256="8" * 64,
            status=source["status"],
        )
        .returning(market_normalisation_run.c.normalisation_run_id)
    ).scalar_one()


def test_attestation_guard_rejects_usable_time_before_usable_event(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay_happy_path(repository_root)
    with (
        pytest.raises(DBAPIError, match="ODDS_ATTESTATION_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        publication = (
            session.execute(
                select(
                    odds_publication_batch.c.publication_batch_id,
                    source_processing_event.c.event_at,
                    source_snapshot.c.received_at,
                )
                .join(
                    source_processing_event,
                    source_processing_event.c.processing_event_id
                    == odds_publication_batch.c.activation_event_id,
                )
                .join(
                    source_snapshot,
                    source_snapshot.c.source_snapshot_id
                    == odds_publication_batch.c.source_snapshot_id,
                )
            )
            .mappings()
            .one()
        )
        regressed = publication["event_at"] - timedelta(microseconds=1)
        assert regressed >= publication["received_at"]
        session.execute(
            insert(odds_publication_attestation).values(
                publication_batch_id=publication["publication_batch_id"],
                usable_at=regressed,
            )
        )


@pytest.mark.parametrize(
    "override",
    (
        {"activation_xid": 0},
        {"activated_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ),
)
def test_publication_batch_guard_rejects_caller_owned_audit_fields(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    override: dict[str, object],
) -> None:
    _replay_happy_path(repository_root)
    with (
        pytest.raises(DBAPIError, match="ODDS_PUBLICATION_BATCH_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        batch = dict(session.execute(select(odds_publication_batch)).mappings().one())
        payload = {
            key: value
            for key, value in batch.items()
            if key not in {"publication_batch_id", "activation_xid", "activated_at"}
        }
        session.execute(insert(odds_publication_batch).values(**payload, **override))


@pytest.mark.parametrize(
    "override_kind",
    ("xid", "audit_time"),
)
def test_attestation_guard_rejects_fabricated_distinct_xid_and_audit_time(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    override_kind: str,
) -> None:
    _replay_happy_path(repository_root)
    with (
        pytest.raises(DBAPIError, match="ODDS_ATTESTATION_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        batch = dict(session.execute(select(odds_publication_batch)).mappings().one())
        attestation = dict(session.execute(select(odds_publication_attestation)).mappings().one())
        overrides = (
            {"attestation_xid": int(batch["activation_xid"]) + 1}
            if override_kind == "xid"
            else {"recorded_at": datetime(2000, 1, 1, tzinfo=UTC)}
        )
        session.execute(
            insert(odds_publication_attestation).values(
                publication_batch_id=batch["publication_batch_id"],
                usable_at=attestation["usable_at"],
                **overrides,
            )
        )


def test_scripted_usable_time_is_valid_without_audit_wall_clock_ordering(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay_happy_path(repository_root)
    with postgres_session_factory() as session:
        usable_at, event_at = session.execute(
            select(odds_publication_attestation.c.usable_at, source_processing_event.c.event_at)
            .join(
                odds_publication_batch,
                odds_publication_batch.c.publication_batch_id
                == odds_publication_attestation.c.publication_batch_id,
            )
            .join(
                source_processing_event,
                source_processing_event.c.processing_event_id
                == odds_publication_batch.c.activation_event_id,
            )
        ).one()
        definition = session.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'betting.guard_odds_publication_attestation()'::regprocedure)"
            )
        )
    assert usable_at == datetime(2026, 8, 20, 12, 0, 10, tzinfo=UTC)
    assert usable_at >= event_at
    assert isinstance(definition, str)
    assert "batch_record.activated_at" not in definition
    assert "activation_event_time" in definition


@pytest.mark.parametrize(
    ("parent_kind", "outcome_count", "error"),
    (
        ("operator", 0, "NORMALISED_VECTOR_INVALID"),
        ("operator", 2, "NORMALISED_VECTOR_INVALID"),
        ("consensus", 0, "CONSENSUS_VECTOR_INVALID"),
        ("consensus", 2, "CONSENSUS_VECTOR_INVALID"),
    ),
)
def test_published_parent_requires_complete_deferred_outcome_vector(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    parent_kind: str,
    outcome_count: int,
    error: str,
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        run = dict(session.execute(select(market_normalisation_run)).mappings().one())
        operator = dict(
            session.execute(select(normalised_operator_market).limit(1)).mappings().one()
        )
        operator_outcomes = [
            dict(row)
            for row in session.execute(
                select(normalised_operator_outcome).where(
                    normalised_operator_outcome.c.normalised_operator_market_id
                    == operator["normalised_operator_market_id"]
                )
            ).mappings()
        ]
        operator_sources = [
            dict(row)
            for row in session.execute(
                select(normalised_operator_market_source).where(
                    normalised_operator_market_source.c.normalised_operator_market_id
                    == operator["normalised_operator_market_id"]
                )
            ).mappings()
        ]
        consensus = dict(session.execute(select(market_consensus_result)).mappings().one())
        consensus_outcomes = [
            dict(row) for row in session.execute(select(market_consensus_outcome)).mappings()
        ]

    seed = "a" if parent_kind == "operator" else "b"
    with (
        pytest.raises(DBAPIError, match=error),
        postgres_session_factory.begin() as session,
    ):
        run_id = _copy_run(session, run, seed=seed)
        if parent_kind == "operator":
            session.execute(
                insert(market_normalisation_source),
                [
                    {
                        "normalisation_run_id": run_id,
                        "odds_observation_id": row["odds_observation_id"],
                        "source_snapshot_id": row["source_snapshot_id"],
                    }
                    for row in operator_sources
                ],
            )
            operator_id = session.execute(
                insert(normalised_operator_market)
                .values(
                    normalisation_run_id=run_id,
                    fixture_id=operator["fixture_id"],
                    market_id=operator["market_id"],
                    provider_id=operator["provider_id"],
                    operator_id=operator["operator_id"],
                    operator_key=operator["operator_key"],
                    observed_at=operator["observed_at"],
                    usable_at=operator["usable_at"],
                    primary_method=operator["primary_method"],
                    fallback_used=operator["fallback_used"],
                    raw_booksum=operator["raw_booksum"],
                    overround=operator["overround"],
                    power_exponent=operator["power_exponent"],
                    input_signature_sha256="c" * 64,
                    result_sha256="d" * 64,
                )
                .returning(normalised_operator_market.c.normalised_operator_market_id)
            ).scalar_one()
            session.execute(
                insert(normalised_operator_market_source),
                [
                    {
                        "normalised_operator_market_id": operator_id,
                        "normalisation_run_id": run_id,
                        "odds_observation_id": row["odds_observation_id"],
                        "source_snapshot_id": row["source_snapshot_id"],
                        "fixture_id": row["fixture_id"],
                    }
                    for row in operator_sources
                ],
            )
            if outcome_count:
                session.execute(
                    insert(normalised_operator_outcome),
                    [
                        {
                            **{
                                key: value
                                for key, value in row.items()
                                if key
                                not in {
                                    "normalised_operator_market_id",
                                    "normalisation_run_id",
                                }
                            },
                            "normalisation_run_id": run_id,
                            "normalised_operator_market_id": operator_id,
                        }
                        for row in operator_outcomes[:outcome_count]
                    ],
                )
        else:
            session.execute(
                insert(market_consensus_result).values(
                    **{
                        key: value
                        for key, value in consensus.items()
                        if key
                        not in {
                            "normalisation_run_id",
                            "input_signature_sha256",
                            "result_sha256",
                        }
                    },
                    normalisation_run_id=run_id,
                    input_signature_sha256="e" * 64,
                    result_sha256="f" * 64,
                )
            )
            if outcome_count:
                session.execute(
                    insert(market_consensus_outcome),
                    [
                        {
                            **{
                                key: value
                                for key, value in row.items()
                                if key != "normalisation_run_id"
                            },
                            "normalisation_run_id": run_id,
                        }
                        for row in consensus_outcomes[:outcome_count]
                    ],
                )


@pytest.mark.parametrize("retained_source_count", (0, 2))
def test_operator_parent_requires_exact_three_deferred_quote_sources(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    retained_source_count: int,
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        parent_id = session.scalar(
            select(normalised_operator_market.c.normalised_operator_market_id).limit(1)
        )
        assert parent_id is not None
        source_ids = list(
            session.scalars(
                select(normalised_operator_market_source.c.odds_observation_id)
                .where(
                    normalised_operator_market_source.c.normalised_operator_market_id == parent_id
                )
                .order_by(normalised_operator_market_source.c.odds_observation_id)
            )
        )
    assert len(source_ids) == 3

    with (
        pytest.raises(DBAPIError, match="NORMALISED_OPERATOR_SOURCE_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market_source "
                "DISABLE TRIGGER trg_normalised_operator_market_source_immutable"
            )
        )
        session.execute(
            delete(normalised_operator_market_source).where(
                normalised_operator_market_source.c.normalised_operator_market_id == parent_id,
                normalised_operator_market_source.c.odds_observation_id.in_(
                    source_ids[retained_source_count:]
                ),
            )
        )


def test_operator_source_rejects_cross_operator_quote_and_is_immutable(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        parents = [
            dict(row)
            for row in session.execute(
                select(normalised_operator_market).order_by(
                    normalised_operator_market.c.operator_id
                )
            ).mappings()
        ]
        assert len(parents) == 2
        foreign_source = dict(
            session.execute(
                select(normalised_operator_market_source)
                .where(
                    normalised_operator_market_source.c.normalised_operator_market_id
                    == parents[1]["normalised_operator_market_id"]
                )
                .limit(1)
            )
            .mappings()
            .one()
        )
        own_source = dict(
            session.execute(
                select(normalised_operator_market_source)
                .where(
                    normalised_operator_market_source.c.normalised_operator_market_id
                    == parents[0]["normalised_operator_market_id"]
                )
                .limit(1)
            )
            .mappings()
            .one()
        )

    with (
        pytest.raises(DBAPIError, match="NORMALISED_OPERATOR_SOURCE_MISMATCH"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market_source "
                "DISABLE TRIGGER trg_normalised_operator_market_source_run_open"
            )
        )
        session.execute(
            insert(normalised_operator_market_source).values(
                normalised_operator_market_id=parents[0]["normalised_operator_market_id"],
                normalisation_run_id=parents[0]["normalisation_run_id"],
                odds_observation_id=foreign_source["odds_observation_id"],
                source_snapshot_id=foreign_source["source_snapshot_id"],
                fixture_id=foreign_source["fixture_id"],
            )
        )

    with (
        pytest.raises(DBAPIError, match="IMMUTABLE_MARKET_RECORD"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            update(normalised_operator_market_source)
            .where(
                normalised_operator_market_source.c.normalised_operator_market_id
                == own_source["normalised_operator_market_id"],
                normalised_operator_market_source.c.odds_observation_id
                == own_source["odds_observation_id"],
            )
            .values(source_snapshot_id=own_source["source_snapshot_id"])
        )


@pytest.mark.parametrize("identity_field", ("provider_id", "operator_key"))
def test_operator_source_rejects_spoofed_parent_identity(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    identity_field: str,
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        parent = dict(session.execute(select(normalised_operator_market).limit(1)).mappings().one())
        if identity_field == "provider_id":
            invalid_value = session.scalar(
                select(data_provider.c.provider_id)
                .where(data_provider.c.provider_id != parent["provider_id"])
                .limit(1)
            )
            assert invalid_value is not None
        else:
            invalid_value = "spoofed-operator-key"

    with (
        pytest.raises(DBAPIError, match="NORMALISED_OPERATOR_SOURCE_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market "
                "DISABLE TRIGGER trg_normalised_operator_market_immutable"
            )
        )
        session.execute(
            update(normalised_operator_market)
            .where(
                normalised_operator_market.c.normalised_operator_market_id
                == parent["normalised_operator_market_id"]
            )
            .values({identity_field: invalid_value})
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize("mismatch_field", ("decimal_odds", "observed_at", "usable_at"))
def test_operator_source_rejects_price_and_parent_time_mismatch(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    mismatch_field: str,
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        parent = dict(session.execute(select(normalised_operator_market).limit(1)).mappings().one())
        outcome = dict(
            session.execute(
                select(normalised_operator_outcome)
                .where(
                    normalised_operator_outcome.c.normalised_operator_market_id
                    == parent["normalised_operator_market_id"]
                )
                .limit(1)
            )
            .mappings()
            .one()
        )

    with (
        pytest.raises(DBAPIError, match="NORMALISED_OPERATOR_SOURCE_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        if mismatch_field == "decimal_odds":
            session.execute(
                text(
                    "ALTER TABLE betting.normalised_operator_outcome "
                    "DISABLE TRIGGER trg_normalised_operator_outcome_immutable"
                )
            )
            session.execute(
                update(normalised_operator_outcome)
                .where(
                    normalised_operator_outcome.c.normalised_operator_market_id
                    == outcome["normalised_operator_market_id"],
                    normalised_operator_outcome.c.outcome == outcome["outcome"],
                )
                .values(decimal_odds=outcome["decimal_odds"] + Decimal("0.01"))
            )
        else:
            session.execute(
                text(
                    "ALTER TABLE betting.normalised_operator_market "
                    "DISABLE TRIGGER trg_normalised_operator_market_immutable"
                )
            )
            session.execute(
                update(normalised_operator_market)
                .where(
                    normalised_operator_market.c.normalised_operator_market_id
                    == parent["normalised_operator_market_id"]
                )
                .values({mismatch_field: parent[mismatch_field] + timedelta(seconds=1)})
            )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_operator_source_rejects_three_outcomes_mixed_across_books(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        parent = dict(session.execute(select(normalised_operator_market).limit(1)).mappings().one())
        existing = (
            session.execute(
                select(
                    normalised_operator_market_source.c.odds_observation_id,
                    odds_observation.c.outcome,
                    odds_observation.c.book_observation_id,
                )
                .join(
                    odds_observation,
                    odds_observation.c.odds_observation_id
                    == normalised_operator_market_source.c.odds_observation_id,
                )
                .where(
                    normalised_operator_market_source.c.normalised_operator_market_id
                    == parent["normalised_operator_market_id"]
                )
                .limit(1)
            )
            .mappings()
            .one()
        )

    _replay_happy_path(repository_root)
    with postgres_session_factory() as session:
        replacement = (
            session.execute(
                select(
                    odds_observation.c.odds_observation_id,
                    odds_observation.c.source_snapshot_id,
                    odds_observation.c.fixture_id,
                )
                .where(
                    odds_observation.c.operator_id == parent["operator_id"],
                    odds_observation.c.outcome == existing["outcome"],
                    odds_observation.c.book_observation_id != existing["book_observation_id"],
                )
                .order_by(odds_observation.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )

    with (
        pytest.raises(DBAPIError, match="NORMALISED_OPERATOR_SOURCE_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.market_normalisation_source "
                "DISABLE TRIGGER trg_market_normalisation_source_run_open"
            )
        )
        session.execute(
            insert(market_normalisation_source).values(
                normalisation_run_id=parent["normalisation_run_id"],
                odds_observation_id=replacement["odds_observation_id"],
                source_snapshot_id=replacement["source_snapshot_id"],
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market_source "
                "DISABLE TRIGGER trg_normalised_operator_market_source_immutable"
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market_source "
                "DISABLE TRIGGER trg_normalised_operator_market_source_run_open"
            )
        )
        session.execute(
            delete(normalised_operator_market_source).where(
                normalised_operator_market_source.c.normalised_operator_market_id
                == parent["normalised_operator_market_id"],
                normalised_operator_market_source.c.odds_observation_id
                == existing["odds_observation_id"],
            )
        )
        session.execute(
            insert(normalised_operator_market_source).values(
                normalised_operator_market_id=parent["normalised_operator_market_id"],
                normalisation_run_id=parent["normalisation_run_id"],
                odds_observation_id=replacement["odds_observation_id"],
                source_snapshot_id=replacement["source_snapshot_id"],
                fixture_id=replacement["fixture_id"],
            )
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize(
    ("target", "invalid_values"),
    (
        ("market", {"raw_booksum": Decimal("NaN")}),
        ("market", {"overround": Decimal("Infinity")}),
        ("market", {"power_exponent": Decimal("Infinity")}),
        ("market", {"power_exponent": None}),
        ("outcome", {"decimal_odds": Decimal("NaN")}),
    ),
)
def test_normalised_numeric_rows_reject_nonfinite_and_incoherent_values(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    target: str,
    invalid_values: dict[str, object],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    table = normalised_operator_market if target == "market" else normalised_operator_outcome
    trigger = (
        "trg_normalised_operator_market_immutable"
        if target == "market"
        else "trg_normalised_operator_outcome_immutable"
    )
    with pytest.raises(DBAPIError), postgres_session_factory.begin() as session:
        session.execute(text(f"ALTER TABLE betting.{table.name} DISABLE TRIGGER {trigger}"))
        session.execute(update(table).values(**invalid_values))


def test_normalised_raw_booksum_must_match_deferred_outcome_sum(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        source = dict(
            session.execute(select(normalised_operator_outcome).limit(1)).mappings().one()
        )
    with (
        pytest.raises(DBAPIError, match="NORMALISED_VECTOR_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_outcome "
                "DISABLE TRIGGER trg_normalised_operator_outcome_immutable"
            )
        )
        session.execute(
            update(normalised_operator_outcome)
            .where(
                normalised_operator_outcome.c.normalised_operator_market_id
                == source["normalised_operator_market_id"],
                normalised_operator_outcome.c.outcome == source["outcome"],
            )
            .values(
                raw_implied_probability=source["raw_implied_probability"]
                + Decimal("0.010000000000")
            )
        )


def test_fallback_operator_requires_market_vector_to_equal_proportional(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        parent_id = session.scalar(
            select(normalised_operator_market.c.normalised_operator_market_id).limit(1)
        )
        assert parent_id is not None
    with (
        pytest.raises(DBAPIError, match="NORMALISED_VECTOR_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market "
                "DISABLE TRIGGER trg_normalised_operator_market_immutable"
            )
        )
        session.execute(
            update(normalised_operator_market)
            .where(normalised_operator_market.c.normalised_operator_market_id == parent_id)
            .values(
                primary_method="PROPORTIONAL",
                fallback_used=True,
                power_exponent=None,
            )
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_public_probability_columns_accept_exact_zero_with_complete_vectors(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory.begin() as session:
        parent_id = session.scalar(
            select(normalised_operator_market.c.normalised_operator_market_id).limit(1)
        )
        assert parent_id is not None
        operator_rows = [
            dict(row)
            for row in session.execute(
                select(normalised_operator_outcome)
                .where(normalised_operator_outcome.c.normalised_operator_market_id == parent_id)
                .order_by(normalised_operator_outcome.c.proportional_probability)
            ).mappings()
        ]
        consensus_rows = [
            dict(row)
            for row in session.execute(
                select(market_consensus_outcome).order_by(
                    market_consensus_outcome.c.consensus_probability
                )
            ).mappings()
        ]
        assert len(operator_rows) == len(consensus_rows) == 3
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market "
                "DISABLE TRIGGER trg_normalised_operator_market_immutable"
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_outcome "
                "DISABLE TRIGGER trg_normalised_operator_outcome_immutable"
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.market_consensus_outcome "
                "DISABLE TRIGGER trg_market_consensus_outcome_immutable"
            )
        )
        smallest_operator, largest_operator = operator_rows[0], operator_rows[-1]
        session.execute(
            update(normalised_operator_outcome)
            .where(normalised_operator_outcome.c.normalised_operator_market_id == parent_id)
            .values(raw_implied_probability=Decimal(0))
        )
        session.execute(
            update(normalised_operator_market)
            .where(normalised_operator_market.c.normalised_operator_market_id == parent_id)
            .values(raw_booksum=Decimal(0), overround=Decimal(-1))
        )
        session.execute(
            update(normalised_operator_outcome)
            .where(
                normalised_operator_outcome.c.normalised_operator_market_id == parent_id,
                normalised_operator_outcome.c.outcome == smallest_operator["outcome"],
            )
            .values(proportional_probability=Decimal(0), market_probability=Decimal(0))
        )
        session.execute(
            update(normalised_operator_outcome)
            .where(
                normalised_operator_outcome.c.normalised_operator_market_id == parent_id,
                normalised_operator_outcome.c.outcome == largest_operator["outcome"],
            )
            .values(
                proportional_probability=largest_operator["proportional_probability"]
                + smallest_operator["proportional_probability"],
                market_probability=largest_operator["market_probability"]
                + smallest_operator["market_probability"],
            )
        )
        smallest_consensus, largest_consensus = consensus_rows[0], consensus_rows[-1]
        session.execute(
            update(market_consensus_outcome)
            .where(market_consensus_outcome.c.outcome == smallest_consensus["outcome"])
            .values(
                consensus_probability=Decimal(0),
                lower_bound=Decimal(0),
            )
        )
        session.execute(
            update(market_consensus_outcome)
            .where(market_consensus_outcome.c.outcome == largest_consensus["outcome"])
            .values(
                consensus_probability=largest_consensus["consensus_probability"]
                + smallest_consensus["consensus_probability"],
                upper_bound=largest_consensus["upper_bound"]
                + smallest_consensus["consensus_probability"],
            )
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_market "
                "ENABLE TRIGGER trg_normalised_operator_market_immutable"
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.normalised_operator_outcome "
                "ENABLE TRIGGER trg_normalised_operator_outcome_immutable"
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.market_consensus_outcome "
                "ENABLE TRIGGER trg_market_consensus_outcome_immutable"
            )
        )

    with postgres_session_factory() as session:
        raw_booksum, overround = session.execute(
            select(
                normalised_operator_market.c.raw_booksum,
                normalised_operator_market.c.overround,
            ).where(normalised_operator_market.c.normalised_operator_market_id == parent_id)
        ).one()
        assert raw_booksum == Decimal(0)
        assert overround == Decimal(-1)
        assert set(
            session.scalars(
                select(normalised_operator_outcome.c.raw_implied_probability).where(
                    normalised_operator_outcome.c.normalised_operator_market_id == parent_id
                )
            )
        ) == {Decimal(0)}
        assert Decimal(0) in set(
            session.scalars(
                select(normalised_operator_outcome.c.market_probability).where(
                    normalised_operator_outcome.c.normalised_operator_market_id == parent_id
                )
            )
        )
        assert Decimal(0) in set(
            session.scalars(select(market_consensus_outcome.c.consensus_probability))
        )


def test_consensus_market_disagreement_must_equal_component_maximum(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with (
        pytest.raises(DBAPIError, match="ck_market_consensus_disagreement_coherence"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.market_consensus_result "
                "DISABLE TRIGGER trg_market_consensus_result_immutable"
            )
        )
        session.execute(
            update(market_consensus_result).values(
                operator_disagreement=Decimal("0.010000000000"),
                method_disagreement=Decimal("0.020000000000"),
                market_disagreement=Decimal("0.010000000000"),
            )
        )


@pytest.mark.parametrize("status", ("NORMALISED", "DEGRADED", "BLOCKED"))
def test_status_requiring_graph_evidence_cannot_publish_without_it(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    status: str,
) -> None:
    _replay_happy_path(repository_root)
    with (
        pytest.raises(DBAPIError, match="NORMALISATION_RUN_GRAPH_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        fixture_id = session.scalar(select(odds_observation.c.fixture_id).limit(1))
        assert fixture_id is not None
        policy_sha256 = "d" * 64
        session.execute(
            insert(market_normalisation_policy).values(
                policy_sha256=policy_sha256,
                policy_id=f"zero-parent-{status.lower()}",
                policy_version="1.0.0",
                policy_document={},
            )
        )
        session.execute(
            insert(market_normalisation_run).values(
                fixture_id=fixture_id,
                market_definition="FULL_TIME_1X2",
                as_of=NORMALISATION_AS_OF,
                mapping_cutoff=NORMALISATION_AS_OF,
                policy_sha256=policy_sha256,
                code_identity="zero-parent-run-graph-test",
                input_signature_sha256=("e" if status == "NORMALISED" else "f") * 64,
                semantic_result_sha256="0" * 64,
                status=status,
            )
        )


def test_degraded_status_requires_warning_or_exclusion(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with (
        pytest.raises(DBAPIError, match="NORMALISATION_RUN_GRAPH_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            text(
                "ALTER TABLE betting.market_normalisation_run "
                "DISABLE TRIGGER trg_market_normalisation_run_immutable"
            )
        )
        session.execute(update(market_normalisation_run).values(status="DEGRADED"))
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_normalised_status_rejects_warning_or_exclusion_rows(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with (
        pytest.raises(DBAPIError, match="NORMALISATION_RUN_GRAPH_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        run_id = session.scalar(select(market_normalisation_run.c.normalisation_run_id))
        assert run_id is not None
        session.execute(
            text(
                "ALTER TABLE betting.market_normalisation_warning "
                "DISABLE TRIGGER trg_market_normalisation_warning_run_open"
            )
        )
        session.execute(
            insert(market_normalisation_warning).values(
                normalisation_run_id=run_id,
                sequence_number=1,
                warning_code="FABRICATED_CLEAN_STATUS",
            )
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize(
    "count_column",
    ("provider_count", "operator_count", "eligible_operator_count"),
)
def test_consensus_counts_must_match_persisted_operator_parents(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    count_column: str,
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with (
        pytest.raises(DBAPIError, match="NORMALISATION_RUN_GRAPH_INVALID"),
        postgres_session_factory.begin() as session,
    ):
        current = session.scalar(select(getattr(market_consensus_result.c, count_column)))
        assert isinstance(current, int)
        session.execute(
            text(
                "ALTER TABLE betting.market_consensus_result "
                "DISABLE TRIGGER trg_market_consensus_result_immutable"
            )
        )
        session.execute(update(market_consensus_result).values({count_column: current + 1}))


@pytest.mark.parametrize(
    "child_kind",
    (
        "book_source",
        "run_source",
        "operator_parent",
        "operator_source",
        "operator_outcome",
        "consensus_parent",
        "consensus_outcome",
        "exclusion",
        "warning",
    ),
)
def test_published_run_rejects_every_late_child_append(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
    child_kind: str,
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        run_id = session.scalar(select(market_normalisation_run.c.normalisation_run_id))
        assert run_id is not None
        if child_kind == "book_source":
            table: Table = market_normalisation_book_source
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "run_source":
            table = market_normalisation_source
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "operator_parent":
            table = normalised_operator_market
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "operator_source":
            table = normalised_operator_market_source
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "operator_outcome":
            table = normalised_operator_outcome
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "consensus_parent":
            table = market_consensus_result
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "consensus_outcome":
            table = market_consensus_outcome
            payload = dict(session.execute(select(table).limit(1)).mappings().one())
        elif child_kind == "exclusion":
            table = market_normalisation_exclusion
            payload = {
                "normalisation_run_id": run_id,
                "sequence_number": 1,
                "operator_key": "late-append",
                "reason": "STALE",
            }
        else:
            table = market_normalisation_warning
            payload = {
                "normalisation_run_id": run_id,
                "sequence_number": 1,
                "warning_code": "LATE_APPEND",
            }

    with (
        pytest.raises(DBAPIError, match="NORMALISATION_RUN_CLOSED"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(insert(table).values(**payload))


def test_source_lineage_rejects_observation_from_another_fixture(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        run = dict(session.execute(select(market_normalisation_run)).mappings().one())
        source = dict(
            session.execute(select(market_normalisation_source).limit(1)).mappings().one()
        )
        original_fixture = dict(
            session.execute(select(fixture).where(fixture.c.fixture_id == run["fixture_id"]))
            .mappings()
            .one()
        )

    with (
        pytest.raises(DBAPIError, match="NORMALISATION_SOURCE_FIXTURE_MISMATCH"),
        postgres_session_factory.begin() as session,
    ):
        other_fixture_id = session.execute(
            insert(canonical_entity)
            .values(entity_type="FIXTURE")
            .returning(canonical_entity.c.entity_id)
        ).scalar_one()
        session.execute(
            insert(fixture).values(
                fixture_id=other_fixture_id,
                competition_id=original_fixture["competition_id"],
                season_id=original_fixture["season_id"],
                home_team_id=original_fixture["home_team_id"],
                away_team_id=original_fixture["away_team_id"],
            )
        )
        altered_run = dict(run)
        altered_run["fixture_id"] = other_fixture_id
        run_id = _copy_run(session, altered_run, seed="9")
        session.execute(
            insert(market_normalisation_source).values(
                normalisation_run_id=run_id,
                odds_observation_id=source["odds_observation_id"],
                source_snapshot_id=source["source_snapshot_id"],
            )
        )


def test_book_source_lineage_rejects_book_from_another_fixture(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _seed_published_normalisation(repository_root, postgres_session_factory)
    with postgres_session_factory() as session:
        run = dict(session.execute(select(market_normalisation_run)).mappings().one())
        source = dict(
            session.execute(select(market_normalisation_book_source).limit(1)).mappings().one()
        )
        original_fixture = dict(
            session.execute(select(fixture).where(fixture.c.fixture_id == run["fixture_id"]))
            .mappings()
            .one()
        )

    with (
        pytest.raises(DBAPIError, match="NORMALISATION_BOOK_SOURCE_FIXTURE_MISMATCH"),
        postgres_session_factory.begin() as session,
    ):
        other_fixture_id = session.execute(
            insert(canonical_entity)
            .values(entity_type="FIXTURE")
            .returning(canonical_entity.c.entity_id)
        ).scalar_one()
        session.execute(
            insert(fixture).values(
                fixture_id=other_fixture_id,
                competition_id=original_fixture["competition_id"],
                season_id=original_fixture["season_id"],
                home_team_id=original_fixture["home_team_id"],
                away_team_id=original_fixture["away_team_id"],
            )
        )
        altered_run = dict(run)
        altered_run["fixture_id"] = other_fixture_id
        run_id = _copy_run(session, altered_run, seed="9")
        session.execute(
            insert(market_normalisation_book_source).values(
                normalisation_run_id=run_id,
                book_observation_id=source["book_observation_id"],
                source_snapshot_id=source["source_snapshot_id"],
            )
        )


def test_book_source_lineage_retains_zero_quote_candidate_and_is_immutable(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _replay_happy_path(repository_root)
    with postgres_session_factory.begin() as session:
        book = dict(session.execute(select(operator_market_observation).limit(1)).mappings().one())
        fixture_id = session.scalar(
            select(odds_observation.c.fixture_id).where(
                odds_observation.c.book_observation_id == book["book_observation_id"]
            )
        )
        assert fixture_id is not None
        policy_sha256 = "a" * 64
        session.execute(
            insert(market_normalisation_policy).values(
                policy_sha256=policy_sha256,
                policy_id="zero-quote-book-lineage-test",
                policy_version="1.0.0",
                policy_document={},
            )
        )
        run_id = session.execute(
            insert(market_normalisation_run)
            .values(
                fixture_id=fixture_id,
                market_definition="FULL_TIME_1X2",
                as_of=NORMALISATION_AS_OF,
                mapping_cutoff=NORMALISATION_AS_OF,
                policy_sha256=policy_sha256,
                code_identity="zero-quote-book-lineage-test",
                input_signature_sha256="b" * 64,
                semantic_result_sha256="c" * 64,
                status="INSUFFICIENT",
            )
            .returning(market_normalisation_run.c.normalisation_run_id)
        ).scalar_one()
        session.execute(
            text(
                "ALTER TABLE betting.odds_observation "
                "DISABLE TRIGGER trg_odds_observation_immutable"
            )
        )
        session.execute(
            delete(odds_observation).where(
                odds_observation.c.book_observation_id == book["book_observation_id"]
            )
        )
        session.execute(
            text(
                "ALTER TABLE betting.odds_observation ENABLE TRIGGER trg_odds_observation_immutable"
            )
        )
        session.execute(
            insert(market_normalisation_book_source).values(
                normalisation_run_id=run_id,
                book_observation_id=book["book_observation_id"],
                source_snapshot_id=book["source_snapshot_id"],
            )
        )

    with postgres_session_factory() as session:
        source = dict(session.execute(select(market_normalisation_book_source)).mappings().one())
        quote_count = session.scalar(
            select(odds_observation.c.odds_observation_id).where(
                odds_observation.c.book_observation_id == book["book_observation_id"]
            )
        )
    assert source["fixture_id"] == fixture_id
    assert quote_count is None

    with (
        pytest.raises(DBAPIError, match="IMMUTABLE_MARKET_RECORD"),
        postgres_session_factory.begin() as session,
    ):
        session.execute(
            update(market_normalisation_book_source)
            .where(
                market_normalisation_book_source.c.normalisation_run_id == run_id,
                market_normalisation_book_source.c.book_observation_id
                == book["book_observation_id"],
            )
            .values(source_snapshot_id=source["source_snapshot_id"])
        )


def test_doctor_detects_a_disabled_critical_trigger(
    postgres_engine: Engine, postgres_url: str
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE provenance.raw_blob DISABLE TRIGGER trg_raw_blob_immutable")
        )
    try:
        doctor = build_database_doctor(postgres_engine, postgres_url)
        assert doctor.status == "DEGRADED"
        assert doctor.capabilities["immutable_point_observations"] is False
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE provenance.raw_blob ENABLE TRIGGER trg_raw_blob_immutable")
            )


def test_nonempty_nrm_downgrade_backfills_odd005_usable_times(
    repository_root: Path,
    postgres_engine: Engine,
    postgres_url: str,
) -> None:
    _replay_happy_path(repository_root)
    with postgres_engine.connect() as connection:
        expected_usable_at = connection.scalar(select(odds_publication_attestation.c.usable_at))
        assert expected_usable_at == datetime(2026, 8, 20, 12, 0, 10, tzinfo=UTC)
        assert (
            connection.scalar(
                select(func.count())
                .select_from(operator_market_observation)
                .where(operator_market_observation.c.usable_at.is_(None))
            )
            == 2
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(odds_observation)
                .where(odds_observation.c.usable_at.is_(None))
            )
            == 6
        )

    postgres_engine.dispose()
    command.downgrade(alembic_config(postgres_url), "20260725_0004")
    try:
        with postgres_engine.connect() as connection:
            book_times = list(
                connection.scalars(
                    text("SELECT usable_at FROM betting.operator_market_observation")
                )
            )
            quote_times = list(
                connection.scalars(text("SELECT usable_at FROM betting.odds_observation"))
            )
        assert len(book_times) == 2
        assert len(quote_times) == 6
        assert set(book_times) == set(quote_times) == {expected_usable_at}
    finally:
        postgres_engine.dispose()
        command.upgrade(alembic_config(postgres_url), "head")


def test_nrm_downgrade_fails_closed_for_unattested_publication(
    repository_root: Path,
    postgres_engine: Engine,
    postgres_url: str,
) -> None:
    _replay_happy_path(repository_root)
    with postgres_engine.begin() as connection:
        attestation = dict(
            connection.execute(select(odds_publication_attestation)).mappings().one()
        )
        connection.execute(
            text(
                "ALTER TABLE betting.odds_publication_attestation "
                "DISABLE TRIGGER trg_odds_publication_attestation_immutable"
            )
        )
        connection.execute(
            delete(odds_publication_attestation).where(
                odds_publication_attestation.c.publication_batch_id
                == attestation["publication_batch_id"]
            )
        )
        connection.execute(
            text(
                "ALTER TABLE betting.odds_publication_attestation "
                "ENABLE TRIGGER trg_odds_publication_attestation_immutable"
            )
        )

    postgres_engine.dispose()
    try:
        with pytest.raises(DBAPIError, match="NRM006_DOWNGRADE_UNATTESTED_PUBLICATION"):
            command.downgrade(alembic_config(postgres_url), "20260725_0004")
        with postgres_engine.connect() as connection:
            assert inspect_schema(connection).alembic_revision == "20260807_0006"
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(operator_market_observation)
                    .where(operator_market_observation.c.usable_at.is_(None))
                )
                == 2
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(odds_observation)
                    .where(odds_observation.c.usable_at.is_(None))
                )
                == 6
            )
    finally:
        postgres_engine.dispose()
        command.upgrade(alembic_config(postgres_url), "head")
        with postgres_engine.begin() as connection:
            batch_exists = connection.scalar(
                select(func.count())
                .select_from(odds_publication_batch)
                .where(
                    odds_publication_batch.c.publication_batch_id
                    == attestation["publication_batch_id"]
                )
            )
            attestation_exists = connection.scalar(
                select(func.count())
                .select_from(odds_publication_attestation)
                .where(
                    odds_publication_attestation.c.publication_batch_id
                    == attestation["publication_batch_id"]
                )
            )
            if batch_exists == 1 and attestation_exists == 0:
                connection.execute(
                    text(
                        "ALTER TABLE betting.odds_publication_attestation "
                        "DISABLE TRIGGER trg_odds_publication_attestation_guard"
                    )
                )
                connection.execute(insert(odds_publication_attestation).values(**attestation))
                connection.execute(
                    text(
                        "ALTER TABLE betting.odds_publication_attestation "
                        "ENABLE TRIGGER trg_odds_publication_attestation_guard"
                    )
                )


def test_nrm_downgrade_restores_the_odd005_quality_guard(
    postgres_engine: Engine, postgres_url: str
) -> None:
    function_names = (
        "betting.guard_odds_quality_subject()",
        "betting.guard_operator_book_observation()",
        "betting.guard_odds_observation_coherence()",
    )
    postgres_engine.dispose()
    command.downgrade(alembic_config(postgres_url), "20260725_0004")
    try:
        with postgres_engine.connect() as connection:
            restored_definitions = {
                function_name: connection.scalar(
                    text("SELECT pg_get_functiondef(to_regprocedure(:function_name))"),
                    {"function_name": function_name},
                )
                for function_name in function_names
            }
        postgres_engine.dispose()
        command.downgrade(alembic_config(postgres_url), "20260725_0003")
        command.upgrade(alembic_config(postgres_url), "20260725_0004")
        with postgres_engine.connect() as connection:
            baseline_definitions = {
                function_name: connection.scalar(
                    text("SELECT pg_get_functiondef(to_regprocedure(:function_name))"),
                    {"function_name": function_name},
                )
                for function_name in function_names
            }
        assert all(isinstance(value, str) for value in restored_definitions.values())
        assert all(isinstance(value, str) for value in baseline_definitions.values())
        assert {
            key: " ".join(str(value).split()) for key, value in restored_definitions.items()
        } == {key: " ".join(str(value).split()) for key, value in baseline_definitions.items()}
        assert "ODDS_QUALITY_ALREADY_PUBLISHED" in str(
            restored_definitions["betting.guard_odds_quality_subject()"]
        )
        book_guard = str(restored_definitions["betting.guard_operator_book_observation()"])
        assert "provenance.rights_decision" in book_guard
        assert "decision.decision <> 'ALLOW'" in book_guard
    finally:
        postgres_engine.dispose()
        command.upgrade(alembic_config(postgres_url), "head")
    with postgres_engine.connect() as connection:
        nrm_definition = connection.scalar(
            text("SELECT pg_get_functiondef('betting.guard_odds_quality_subject()'::regprocedure)")
        )
    assert isinstance(nrm_definition, str)
    assert "ODDS_QUALITY_ALREADY_PUBLISHED" not in nrm_definition


def test_nrm_downgrade_restores_odd005_rights_decision_enforcement(
    repository_root: Path,
    postgres_engine: Engine,
    postgres_url: str,
) -> None:
    _replay_happy_path(repository_root)
    postgres_engine.dispose()
    command.downgrade(alembic_config(postgres_url), "20260725_0004")
    try:
        with postgres_engine.connect() as connection:
            snapshot_id = connection.scalar(
                text("SELECT source_snapshot_id FROM betting.operator_market_observation LIMIT 1")
            )
        assert snapshot_id is not None
        with (
            pytest.raises(DBAPIError, match="ODDS_PUBLICATION_BLOCKED"),
            postgres_engine.begin() as connection,
        ):
            connection.execute(
                text(
                    "ALTER TABLE provenance.rights_decision "
                    "DISABLE TRIGGER trg_rights_decision_immutable"
                )
            )
            deleted = connection.execute(
                text(
                    "DELETE FROM provenance.rights_decision "
                    "WHERE source_snapshot_id = :source_snapshot_id "
                    "AND capability = 'derived_storage'"
                ),
                {"source_snapshot_id": snapshot_id},
            )
            assert deleted.rowcount == 1
            connection.execute(
                text(
                    "ALTER TABLE provenance.rights_decision "
                    "ENABLE TRIGGER trg_rights_decision_immutable"
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO betting.operator_market_observation (
                      book_observation_id, market_id, source_snapshot_id,
                      provider_market_representation_id, market_state,
                      provider_observed_at, received_at, usable_at,
                      missing_outcomes, semantic_sha256, source_semantic_sha256,
                      contract_version, rights_profile_record_id
                    )
                    SELECT uuidv7(), market_id, source_snapshot_id,
                           provider_market_representation_id, market_state,
                           provider_observed_at, received_at, usable_at,
                           missing_outcomes, semantic_sha256, source_semantic_sha256,
                           contract_version, rights_profile_record_id
                    FROM betting.operator_market_observation
                    WHERE source_snapshot_id = :source_snapshot_id
                    LIMIT 1
                    """
                ),
                {"source_snapshot_id": snapshot_id},
            )
    finally:
        postgres_engine.dispose()
        command.upgrade(alembic_config(postgres_url), "head")


def test_clean_downgrade_and_reupgrade(postgres_engine: Engine, postgres_url: str) -> None:
    postgres_engine.dispose()
    downgrade_database(postgres_url)
    with postgres_engine.connect() as connection:
        remaining = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.schemata "
                "WHERE schema_name IN ('core','football','fpl','provenance')"
            )
        ).scalar_one()
    assert remaining == 0
    with pytest.raises(DatabaseError) as behind:
        build_database_doctor(postgres_engine, postgres_url)
    assert behind.value.code == "DATABASE_SCHEMA_BEHIND"
    postgres_engine.dispose()
    upgrade_database(postgres_url)
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT uuidv7() IS NOT NULL")).scalar_one() is True
        assert inspect_schema(connection).alembic_revision == "20260807_0006"
