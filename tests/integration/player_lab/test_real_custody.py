"""Native PG tests of real branches with invented owned inputs, never real scores."""

import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import player_research_artifact as table
from dmf_pulse.database.migrate import downgrade_database, upgrade_database
from dmf_pulse.evaluation.artifacts import canonical_json_bytes
from dmf_pulse.evaluation.artifacts import seal as stage_seal
from dmf_pulse.operation.models import OperationError
from dmf_pulse.player_lab import real_integrity, real_rights, real_store
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.real import RealPointFreeze
from dmf_pulse.player_lab.real_rights import AcceptedProtocolIntent, HistoricalFreezeProof
from dmf_pulse.player_lab.store import PostgresResearchLedger
from tests.unit.player_lab.real_support import owned_case, owned_full, reseal

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture(scope="module", params=("POINT_ADAPTER", "FULL_LEGACY"))
def owned(postgres_url, request):
    now = datetime.now(UTC)
    protocol, populations, forecasts, labels, registry = owned_case(now)
    native_protocol, native_populations, native_forecasts, _native_labels, _native_registry = (
        owned_case(now, prospective=True)
    )
    catalogue = registry.sources[0].model_copy(
        update={
            "qualified_population_sha256s": (
                *registry.sources[0].qualified_population_sha256s,
                *(canonical_sha256(row.model_dump(mode="json")) for row in native_populations),
            )
        }
    )
    registry = registry.model_copy(update={"sources": (catalogue, registry.sources[1])})
    patch = pytest.MonkeyPatch()
    for module in (real_rights, real_store, real_integrity):
        patch.setattr(module, "real_source_registry", lambda: registry)
    if request.param == "FULL_LEGACY":
        from dmf_pulse.player_lab.real import adapt_qualified_full_forecast

        forecasts = tuple(
            adapt_qualified_full_forecast(
                owned_full(row), information_grade="RAW_OBSERVED", now=now
            )
            for row in forecasts
        )
    proofs = []
    for kind, rows in (("DEADLINE_POPULATION", populations), ("POINT_FORECAST", forecasts)):
        for row in rows:
            original = (
                row.original_full_forecast
                if kind == "POINT_FORECAST" and row.original_full_forecast is not None
                else row
            )
            body = original.model_dump_json().encode()
            digest = (
                canonical_sha256(row.model_dump(mode="json"))
                if kind == "DEADLINE_POPULATION"
                else row.semantic_sha256
            )
            frozen = (
                row.deadline_at - timedelta(hours=2)
                if kind == "DEADLINE_POPULATION"
                else row.generated_at + timedelta(seconds=1)
            )
            proofs.append(
                HistoricalFreezeProof(
                    artifact_kind=kind,
                    artifact_semantic_sha256=digest,
                    original_artifact_format="DEADLINE_POPULATION_V1"
                    if kind == "DEADLINE_POPULATION"
                    else "PLAYER_FORECAST_V1"
                    if row.original_full_forecast is not None
                    else "QUALIFIED_POINT_ADAPTER_V1",
                    original_semantic_sha256=digest
                    if kind == "DEADLINE_POPULATION"
                    else original.semantic_sha256,
                    information_grade="RAW_OBSERVED"
                    if kind == "POINT_FORECAST" and row.original_full_forecast is not None
                    else None,
                    sources=(row.catalogue_source,)
                    if kind == "DEADLINE_POPULATION"
                    else row.sources,
                    original_artifact_byte_sha256=hashlib.sha256(body).hexdigest(),
                    original_frozen_at=frozen,
                    external_predeadline_evidence_sha256="a" * 64,
                    independent_review_sha256="b" * 64,
                    accepted_at=now - timedelta(minutes=1),
                )
            )
    intent = AcceptedProtocolIntent(
        intent_sha256=real_store.protocol_intent_sha256(protocol),
        owner_decision_ref="OWNED_ENGINEERING_ONLY",
        independent_review_sha256="c" * 64,
        accepted_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=2),
    )
    registry = registry.model_copy(
        update={
            "historical_freezes": tuple(proofs),
            "accepted_protocol_intents": (
                intent,
                intent.model_copy(
                    update={"intent_sha256": real_store.protocol_intent_sha256(native_protocol)}
                ),
            ),
        }
    )
    name = "dmf_pulse_accel005_owned_" + uuid4().hex[:12]
    assert re.fullmatch(r"dmf_pulse_accel005_owned_[0-9a-f]{12}", name)
    admin = create_engine(
        make_url(postgres_url).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as con:
        con.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url, hide_parameters=True)
    try:
        upgrade_database(url)
        ledger = PostgresResearchLedger(lambda: engine)
        stored_protocol = ledger.register_real_protocol(protocol)
        registrations = []
        for pop, proof in zip(populations, proofs[: len(populations)], strict=True):
            registrations.append(
                ledger.register_real_population(
                    stored_protocol.semantic_sha256,
                    pop,
                    external_proof_sha256=proof.semantic_sha256,
                    original_body=pop.model_dump_json().encode(),
                )
            )
        frozen = []
        for point, proof in zip(forecasts, proofs[len(populations) :], strict=True):
            reg = registrations[point.key.gameweek - 9]
            frozen.append(
                ledger.freeze_real_forecast(
                    stored_protocol.semantic_sha256,
                    reg.semantic_sha256,
                    point,
                    external_proof_sha256=proof.semantic_sha256,
                    original_body=(point.original_full_forecast or point)
                    .model_dump_json()
                    .encode(),
                )
            )
        for label in labels:
            ledger.append_real_label(label)
        yield (
            engine,
            ledger,
            stored_protocol,
            tuple(registrations),
            tuple(frozen),
            labels,
            registry,
            url,
            (native_protocol, native_populations, native_forecasts),
        )
    finally:
        engine.dispose()
        with admin.connect() as con:
            con.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
        patch.undo()


def test_owned_descriptive_import_scores_exact_complete_vintage(owned):
    engine, ledger, protocol, registrations, frozen, labels, registry, _, *_ = owned
    report = ledger.evaluate_real(
        protocol.semantic_sha256,
        "owned-point",
        expected_sources=tuple(row.source for row in registry.sources),
        label_sha256s=tuple(row.semantic_sha256 for row in labels),
    )
    assert report.evaluation_classification == "POST_ORIGIN_DESCRIPTIVE" and report.count == 4
    assert report.point_metrics.mae == 2 and report.holdout_metrics.count == 4
    if frozen[0].forecast.original_full_forecast is None:
        assert report.probability_5plus is None and report.component_metrics is None
    else:
        assert report.probability_5plus.count == 4 and len(report.component_metrics) == 13
        assert len(report.distribution_metrics) == 4
    assert report.information_grade == "RAW_OBSERVED" and report.promotion == "FORBIDDEN"
    assert all(row.recorded_at > row.original_frozen_at for row in frozen)
    assert all(row.registered_at > row.original_population_frozen_at for row in registrations)
    again = ledger.evaluate_real(
        protocol.semantic_sha256,
        "owned-point",
        expected_sources=tuple(row.source for row in registry.sources),
        label_sha256s=tuple(row.semantic_sha256 for row in labels),
    )
    assert again.point_metrics == report.point_metrics
    with engine.connect() as con:
        assert (
            con.execute(
                text("SELECT count(*) FROM evaluation.score_pair WHERE score_sha256=:sha"),
                {"sha": report.semantic_sha256},
            ).scalar_one()
            == 4
        )


def test_owned_missing_label_and_wrong_historical_bytes_denied(owned):
    _, ledger, protocol, regs, frozen, labels, registry, _, *_ = owned
    with pytest.raises(OperationError, match="LEDGER_REJECTED"):
        ledger.evaluate_real(
            protocol.semantic_sha256,
            "owned-point",
            expected_sources=tuple(row.source for row in registry.sources),
            label_sha256s=tuple(row.semantic_sha256 for row in labels[:-1]),
        )
    with pytest.raises(OperationError, match="BYTES_MISMATCH"):
        ledger.freeze_real_forecast(
            protocol.semantic_sha256,
            regs[0].semantic_sha256,
            frozen[0].forecast,
            external_proof_sha256=frozen[0].external_custody_sha256,
            original_body=b"owned-wrong-body",
        )


def test_real_runtime_rejects_disabled_guard_before_write(owned):
    engine, ledger, _, _, _, labels, _, _, *_ = owned
    with engine.begin() as con:
        con.execute(
            text(
                "ALTER TABLE evaluation.research_artifact DISABLE TRIGGER trg_research_real_artifact"
            )
        )
    try:
        with pytest.raises(OperationError, match="DATABASE_GUARD_REQUIRED"):
            ledger.append_real_label(labels[0])
    finally:
        with engine.begin() as con:
            con.execute(
                text(
                    "ALTER TABLE evaluation.research_artifact ENABLE TRIGGER trg_research_real_artifact"
                )
            )


@pytest.mark.parametrize(
    "field,change",
    [
        ("recorded_at", "remove"),
        ("recorded_at", "null"),
        ("custody", "remove"),
        ("population_registration_sha256", "null"),
        ("forecast", "remove"),
        ("semantic_sha256", "null"),
    ],
)
def test_real_direct_sql_missing_fields_rejected(owned, field, change):
    engine, _, _, _, frozen, _, _, _, *_ = owned
    with engine.connect() as con:
        row = (
            con.execute(select(table).where(table.c.artifact_sha256 == frozen[0].semantic_sha256))
            .mappings()
            .one()
        )
    values = {key: value for key, value in row.items() if key != "stored_at"}
    payload = dict(values["payload"])
    if change == "remove":
        payload.pop(field)
    else:
        payload[field] = None
    payload["semantic_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "semantic_sha256"}
    )
    values.update(payload=payload, artifact_sha256=payload["semantic_sha256"])
    with pytest.raises(DBAPIError), engine.begin() as con:
        con.execute(insert(table).values(**values))


def test_real_rows_are_append_only_and_downgrade_never_discards(owned):
    engine, _, _, _, _, _, _, url, *_ = owned
    for statement in (
        "UPDATE evaluation.research_artifact SET model_id='owned-tamper'",
        "DELETE FROM evaluation.research_artifact",
    ):
        with pytest.raises(DBAPIError), engine.begin() as con:
            con.execute(text(statement))
    with pytest.raises(ValueError, match="custody prevents"):
        downgrade_database(url, "20261029_0008")


def test_real_runtime_rejects_same_name_guard_when_false(owned):
    engine, ledger, *_ = owned
    with engine.begin() as con:
        con.execute(text("DROP TRIGGER trg_research_real_artifact ON evaluation.research_artifact"))
        con.execute(
            text(
                "CREATE TRIGGER trg_research_real_artifact BEFORE INSERT ON evaluation.research_artifact FOR EACH ROW WHEN (FALSE) EXECUTE FUNCTION evaluation.guard_real_artifact()"
            )
        )
    try:
        with pytest.raises(OperationError, match="DATABASE_GUARD_REQUIRED"):
            ledger.append_real_label(owned[5][0])
    finally:
        with engine.begin() as con:
            con.execute(
                text("DROP TRIGGER trg_research_real_artifact ON evaluation.research_artifact")
            )
            con.execute(
                text(
                    "CREATE TRIGGER trg_research_real_artifact BEFORE INSERT ON evaluation.research_artifact FOR EACH ROW WHEN (NEW.dataset_mode='PROSPECTIVE_REAL') EXECUTE FUNCTION evaluation.guard_real_artifact()"
                )
            )


def test_native_clock_positive_and_nine_resealed_sql_substitutions(owned):
    engine, ledger, *_ = owned
    proposal, populations, points = owned[8]
    protocol = ledger.register_real_protocol(proposal)
    registration = ledger.register_real_population(protocol.semantic_sha256, populations[0])
    with engine.connect() as con:
        issued = con.execute(text("SELECT clock_timestamp()")).scalar_one()

    def at_clock(point):
        stage = stage_seal(
            point.stage12.model_copy(
                update={
                    "issued_at": issued,
                    "lineage": point.stage12.lineage.model_copy(update={"forecast_origin": issued}),
                    "forecast_sha256": "0" * 64,
                }
            ),
            "forecast_sha256",
        )
        return reseal(point, stage12=stage, generated_at=issued)

    first = ledger.freeze_real_forecast(
        protocol.semantic_sha256, registration.semantic_sha256, at_clock(points[0])
    )
    assert first.recorded_at == first.original_frozen_at and first.custody == "DATABASE_PREDEADLINE"
    assert first.recorded_at >= registration.registered_at
    pending = at_clock(points[1])
    for attack in (
        "cutoff_null",
        "manifest_null",
        "target_substitution",
        "benchmark_substitution",
        "nan",
        "extra_body",
        "ruleset_null",
        "future_training",
        "boolean_seed",
    ):
        with engine.connect() as con:
            recorded = con.execute(text("SELECT clock_timestamp()")).scalar_one()
        wrapper = seal(
            RealPointFreeze.model_construct(
                forecast=pending,
                population_registration_sha256=registration.semantic_sha256,
                recorded_at=recorded,
                original_frozen_at=recorded,
                custody="DATABASE_PREDEADLINE",
                external_custody_sha256=None,
                semantic_sha256="0" * 64,
            )
        )
        values = dict(
            artifact_sha256=wrapper.semantic_sha256,
            kind="FORECAST",
            dataset_mode="PROSPECTIVE_REAL",
            target_id=pending.key.target_id(),
            model_id=pending.model_id,
            experiment_sha256=protocol.semantic_sha256,
            revision=0,
            source_refs=[row.model_dump(mode="json") for row in pending.sources],
            payload=wrapper.model_dump(mode="json"),
        )
        with engine.connect() as con:
            tx = con.begin()
            try:
                con.execute(insert(table).values(**values))
            finally:
                tx.rollback()
        payload = deepcopy(values["payload"])
        point = payload["forecast"]
        if attack == "cutoff_null":
            point["information_cutoff"] = None
        elif attack == "manifest_null":
            point["stage12"]["lineage"]["dataset_manifest_sha256"] = None
        elif attack == "target_substitution":
            point["stage12"]["target_id"] = "owned-wrong-target"
        elif attack == "benchmark_substitution":
            point["stage12"]["benchmark_id"] = "owned-wrong-model"
        elif attack == "nan":
            point["stage12"]["point_forecast"] = "NaN"
        elif attack == "ruleset_null":
            point["stage12"]["lineage"]["ruleset_id"] = None
        elif attack == "future_training":
            point["stage12"]["lineage"]["training_cutoff"] = (
                (issued + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
            )
        elif attack == "boolean_seed":
            point["stage12"]["lineage"]["random_seed"] = True
        else:
            payload["restricted_body"] = {"owned_engineering_marker": True}
        point["stage12"]["forecast_sha256"] = None
        point["stage12"]["forecast_sha256"] = hashlib.sha256(
            canonical_json_bytes(point["stage12"])
        ).hexdigest()
        point["semantic_sha256"] = canonical_sha256(
            {k: v for k, v in point.items() if k != "semantic_sha256"}
        )
        payload["semantic_sha256"] = canonical_sha256(
            {k: v for k, v in payload.items() if k != "semantic_sha256"}
        )
        values.update(payload=payload, artifact_sha256=payload["semantic_sha256"])
        with pytest.raises(DBAPIError) as error, engine.begin() as con:
            con.execute(insert(table).values(**values))
        assert "REAL_PLAYER_FORECAST_" in error.value.orig.diag.message_primary
