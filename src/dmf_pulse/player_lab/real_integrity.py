"""Authenticate the existing research schema before any real ledger operation."""

from __future__ import annotations

import json
from importlib import import_module
from typing import TYPE_CHECKING

from dmf_pulse.operation.models import OperationError
from dmf_pulse.player_lab.real_rights import real_source_registry

if TYPE_CHECKING:
    from sqlalchemy import Connection


def require_real_database(connection: Connection) -> None:
    from sqlalchemy import text

    from dmf_pulse.database.schema import current_alembic_revision

    if connection.execute(text("SHOW session_replication_role")).scalar_one() != "origin":
        raise OperationError("REAL_PLAYER_DATABASE_GUARD_REQUIRED")
    if current_alembic_revision(connection) != "20261030_0009":
        raise OperationError("REAL_PLAYER_DATABASE_REVISION_REQUIRED")
    installed = real_source_registry().model_dump(mode="json")
    if connection.execute(text("SELECT evaluation.real_authority()")).scalar_one() != installed:
        raise OperationError("REAL_PLAYER_DATABASE_AUTHORITY_MISMATCH")
    expected = {
        "trg_research_real_source": ("qualified_source", "guard_real_source"),
        "trg_research_real_artifact": ("research_artifact", "guard_real_artifact"),
        "trg_research_complete_artifact": ("research_artifact", "guard_score_complete"),
        "trg_research_complete_pair": ("score_pair", "guard_score_complete"),
        **{
            "trg_research_immutable_" + name: (name, "reject_change")
            for name in ("qualified_source", "research_artifact", "score_pair")
        },
    }
    rows = connection.execute(
        text(
            "SELECT t.tgname, c.relname, p.proname, t.tgenabled,pg_get_triggerdef(t.oid) "
            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_proc p ON p.oid=t.tgfoid WHERE n.nspname='evaluation' AND NOT t.tgisinternal"
        )
    ).all()
    actual = {
        name: (table, function, definition)
        for name, table, function, enabled, definition in rows
        if enabled in {"O", "A"}
    }
    for name, (table, function) in expected.items():
        if function == "guard_score_complete":
            definition = f"CREATE CONSTRAINT TRIGGER {name} AFTER INSERT ON evaluation.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION evaluation.{function}()"
        elif function == "reject_change":
            definition = f"CREATE TRIGGER {name} BEFORE DELETE OR UPDATE ON evaluation.{table} FOR EACH ROW EXECUTE FUNCTION evaluation.{function}()"
        else:
            mode = (
                "PROSPECTIVE_REAL"
                if table == "research_artifact"
                else "INDEPENDENTLY_QUALIFIED_REAL"
            )
            definition = f"CREATE TRIGGER {name} BEFORE INSERT ON evaluation.{table} FOR EACH ROW WHEN ((new.dataset_mode = '{mode}'::text)) EXECUTE FUNCTION evaluation.{function}()"
        if actual.get(name) != (table, function, definition):
            raise OperationError("REAL_PLAYER_DATABASE_GUARD_REQUIRED")
    bodies = {}
    for module_name, pairs in (
        (
            "20261029_0007_player_research",
            (("guard_score_complete", "PAIR_GUARD"), ("reject_change", "IMMUTABLE")),
        ),
        (
            "20261030_0009_real_player_custody",
            (("guard_real_source", "SOURCE_GUARD"), ("guard_real_artifact", "ARTIFACT_GUARD")),
        ),
    ):
        module = import_module("dmf_pulse.database.migrations.versions." + module_name)
        for function, constant in pairs:
            bodies[function] = getattr(module, constant).split("$$", 2)[1]
    encoded = json.dumps(installed, sort_keys=True, separators=(",", ":")).encode().hex()
    bodies["real_authority"] = (
        " SELECT convert_from(decode('" + encoded + "','hex'),'UTF8')::jsonb "
    )
    canonical = import_module(
        "dmf_pulse.database.migrations.versions.20260807_0006_min007f_availability"
    )
    canonical_parts = canonical.CANONICAL_JSON_FUNCTION.split("$$")
    bodies["canonical_json_text"] = canonical_parts[1]
    bodies["canonical_json_sha256"] = canonical_parts[3]
    found = {
        str(name): str(body)
        for name, body, language, config, security, volatility, strict in connection.execute(
            text(
                "SELECT p.proname,p.prosrc,l.lanname,p.proconfig,p.prosecdef,p.provolatile,p.proisstrict "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
                "WHERE p.oid IN ('evaluation.guard_score_complete()'::regprocedure,'evaluation.reject_change()'::regprocedure,"
                "'evaluation.guard_real_source()'::regprocedure,'evaluation.guard_real_artifact()'::regprocedure,'evaluation.real_authority()'::regprocedure,"
                "'football.canonical_json_text(jsonb)'::regprocedure,'football.canonical_json_sha256(jsonb)'::regprocedure)"
            )
        ).all()
        if config is None
        and security is False
        and language
        == ("sql" if name in {"real_authority", "canonical_json_sha256"} else "plpgsql")
        and volatility
        == (
            "i"
            if name in {"real_authority", "canonical_json_sha256", "canonical_json_text"}
            else "v"
        )
        and strict == (name in {"canonical_json_sha256", "canonical_json_text"})
    }
    if found != bodies:
        raise OperationError("REAL_PLAYER_DATABASE_GUARD_IDENTITY_MISMATCH")
