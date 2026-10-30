"""Canonical PostgreSQL refresh-control custody; provider/private facts never persist."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from secrets import token_hex
from typing import Any, Literal

from sqlalchemy import Connection, insert, select, text
from sqlalchemy.exc import SQLAlchemyError

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.dashboard.authorization import (
    AuthorizationError,
    LedgerInspection,
    OperatorRefreshApproval,
    RefreshGrant,
    RefreshRequest,
    UsageLedger,
)
from dmf_pulse.data_model.tables import refresh_control_event, refresh_control_ledger
from dmf_pulse.database.schema import current_alembic_revision

ConnectionFactory = Callable[[], AbstractContextManager[Connection]]
DatabaseRef = Literal["OPERATOR_CONTROL_DATABASE", "SYNTHETIC_TEST_DATABASE"]
CONTROL_VERSION = "postgres-refresh-control-v1"
CONTROL_REVISION = "20261029_0008"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
_COMMON = {"kind", "at", "reservation_id", "ledger_id", "sequence", "previous_sha256", "sha256"}
_FIELDS = {
    "RESERVATION": {
        "grant_sha256",
        "approval_sha256",
        "account_sha256",
        "authorization_sha256",
        "day",
        "period",
    },
    "CLAIM": {"worker_sha256"},
    "CHECK": set(),
    "ATTEMPT": {"route_sha256"},
}


def _aware(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    return parsed.astimezone(UTC)


def _validated_record(value: dict[str, Any], *, ledger_id: str, account_sha256: str) -> None:
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in _FIELDS or set(value) != _COMMON | _FIELDS[kind]:
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    if type(value.get("sequence")) is not int or not 0 <= value["sequence"] < 100000:
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    if value.get("ledger_id") != ledger_id or len(canonical_json_bytes(value)) > 4096:
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    for name in set(value) - {"kind", "at", "sequence", "day", "period"}:
        if not isinstance(value[name], str) or not _SHA.fullmatch(value[name]):
            raise AuthorizationError("USAGE_LEDGER_INVALID")
    when = _aware(value["at"])
    if kind == "RESERVATION" and (
        value["account_sha256"] != account_sha256
        or value["day"] != when.date().isoformat()
        or _aware(value["period"]) > when
    ):
        raise AuthorizationError("USAGE_LEDGER_ACCOUNT_MISMATCH")
    if (
        canonical_sha256({key: item for key, item in value.items() if key != "sha256"})
        != value["sha256"]
    ):
        raise AuthorizationError("USAGE_LEDGER_INVALID")


class PostgresUsageLedger(UsageLedger):
    """Reuse the accepted authorization policy under an atomic SQL transaction.

    Construction has no connection, environment lookup or other side effects.
    The factory is resolved locally by the operator/worker; database_ref is an
    identifier, never a URL or credential. Initialize is explicit and idempotent
    for the canonical account binding, including existing consumed quota history.
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        ledger_id: str,
        *,
        account_ref: str,
        database_ref: DatabaseRef = "OPERATOR_CONTROL_DATABASE",
    ) -> None:
        if (
            not isinstance(account_ref, str)
            or not isinstance(ledger_id, str)
            or not _REF.fullmatch(account_ref)
            or not _SHA.fullmatch(ledger_id)
            or database_ref not in {"OPERATOR_CONTROL_DATABASE", "SYNTHETIC_TEST_DATABASE"}
        ):
            raise AuthorizationError("USAGE_LEDGER_CONFIGURATION_INVALID")
        self.database_ref = database_ref
        self.account_sha256 = canonical_sha256(account_ref)
        self._connection_factory = connection_factory
        self._active: ContextVar[Connection | None] = ContextVar(
            "refresh_control_connection", default=None
        )
        super().__init__(
            ledger_id,
            backend="POSTGRES",
            transaction=self._sql_transaction,
            append=self._sql_append,
        )

    def reserve(self, approval: OperatorRefreshApproval, grant: RefreshGrant) -> None:
        if (
            approval.classification == "PRIVATE_CURRENT"
            and self.database_ref != "OPERATOR_CONTROL_DATABASE"
        ):
            raise AuthorizationError("PRIVATE_CONTROL_DATABASE_REQUIRED")
        super().reserve(approval, grant)

    def preflight(
        self, approval: OperatorRefreshApproval, request: RefreshRequest, *, now: datetime
    ) -> LedgerInspection:
        if (
            approval.classification == "PRIVATE_CURRENT"
            and self.database_ref != "OPERATOR_CONTROL_DATABASE"
        ):
            raise AuthorizationError("PRIVATE_CONTROL_DATABASE_REQUIRED")
        return super().preflight(approval, request, now=now)

    def _valid_grant(self, grant: RefreshGrant, worker_id: str, now: datetime) -> None:
        if (
            grant.classification == "PRIVATE_CURRENT"
            and self.database_ref != "OPERATOR_CONTROL_DATABASE"
        ):
            raise AuthorizationError("PRIVATE_CONTROL_DATABASE_REQUIRED")
        super()._valid_grant(grant, worker_id, now)

    @staticmethod
    def _prepare(connection: Connection, account_sha256: str) -> None:
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '10s'"))
        connection.execute(text("SET LOCAL synchronous_commit = 'on'"))
        if (
            current_alembic_revision(connection) != CONTROL_REVISION
            or str(connection.execute(text("SHOW timezone")).scalar_one()) != "UTC"
            or str(connection.execute(text("SHOW fsync")).scalar_one()) != "on"
        ):
            raise AuthorizationError("USAGE_LEDGER_SCHEMA_NOT_READY")
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:account, 0))"),
            {"account": account_sha256},
        )

    @classmethod
    def initialize(
        cls,
        connection_factory: ConnectionFactory,
        *,
        account_ref: str,
        database_ref: DatabaseRef = "OPERATOR_CONTROL_DATABASE",
    ) -> PostgresUsageLedger:
        # Validate configuration before invoking even the connection factory.
        candidate = cls(
            connection_factory, "0" * 64, account_ref=account_ref, database_ref=database_ref
        )
        try:
            with connection_factory() as connection, connection.begin():
                cls._prepare(connection, candidate.account_sha256)
                existing = connection.execute(
                    select(refresh_control_ledger.c.ledger_id)
                    .where(refresh_control_ledger.c.account_sha256 == candidate.account_sha256)
                    .with_for_update()
                ).scalar_one_or_none()
                identity = str(existing) if existing is not None else token_hex(32)
                if existing is None:
                    binding = {
                        "ledger_id": identity,
                        "account_sha256": candidate.account_sha256,
                        "schema_version": CONTROL_VERSION,
                    }
                    connection.execute(
                        insert(refresh_control_ledger).values(
                            **binding, binding_sha256=canonical_sha256(binding)
                        )
                    )
        except AuthorizationError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError):
            raise AuthorizationError("USAGE_LEDGER_UNAVAILABLE") from None
        result = cls(
            connection_factory, identity, account_ref=account_ref, database_ref=database_ref
        )
        with result._sql_transaction():
            # Authenticate the complete existing history rather than silently reset it.
            return result

    @contextmanager
    def _sql_transaction(self) -> Iterator[list[dict[str, Any]]]:
        try:
            with self._connection_factory() as connection, connection.begin():
                self._prepare(connection, self.account_sha256)
                binding = (
                    connection.execute(
                        select(refresh_control_ledger)
                        .where(refresh_control_ledger.c.account_sha256 == self.account_sha256)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                expected = {
                    "ledger_id": self.ledger_id,
                    "account_sha256": self.account_sha256,
                    "schema_version": CONTROL_VERSION,
                }
                if binding is None or dict(binding) != {
                    **expected,
                    "binding_sha256": canonical_sha256(expected),
                }:
                    raise AuthorizationError("USAGE_LEDGER_IDENTITY_MISMATCH")
                rows = (
                    connection.execute(
                        select(refresh_control_event)
                        .where(refresh_control_event.c.ledger_id == self.ledger_id)
                        .order_by(refresh_control_event.c.sequence)
                        .limit(100001)
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > 100000:
                    raise AuthorizationError("USAGE_LEDGER_CAPACITY_REACHED")
                records: list[dict[str, Any]] = []
                previous = "0" * 64
                last_at: datetime | None = None
                for row in rows:
                    value = dict(row["payload"])
                    _validated_record(
                        value, ledger_id=self.ledger_id, account_sha256=self.account_sha256
                    )
                    when = _aware(value["at"])
                    if (
                        value["sequence"] != len(records)
                        or value["previous_sha256"] != previous
                        or any(
                            row[name] != value[name]
                            for name in (
                                "ledger_id",
                                "sequence",
                                "sha256",
                                "previous_sha256",
                                "kind",
                            )
                        )
                        or row["at"] != when
                        or (last_at is not None and when < last_at)
                    ):
                        raise AuthorizationError("USAGE_LEDGER_INVALID")
                    records.append(value)
                    previous, last_at = value["sha256"], when
                token = self._active.set(connection)
                try:
                    yield records
                finally:
                    self._active.reset(token)
        except AuthorizationError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError, KeyError):
            raise AuthorizationError("USAGE_LEDGER_UNAVAILABLE") from None

    def _sql_append(self, records: list[dict[str, Any]], payload: dict[str, object]) -> None:
        connection = self._active.get()
        if connection is None:
            raise AuthorizationError("USAGE_LEDGER_TRANSACTION_REQUIRED")
        record = {
            **payload,
            "ledger_id": self.ledger_id,
            "sequence": len(records),
            "previous_sha256": records[-1]["sha256"] if records else "0" * 64,
        }
        value = {**record, "sha256": canonical_sha256(record)}
        _validated_record(value, ledger_id=self.ledger_id, account_sha256=self.account_sha256)
        connection.execute(
            insert(refresh_control_event).values(
                **{
                    key: value[key]
                    for key in ("ledger_id", "sequence", "sha256", "previous_sha256", "kind")
                },
                at=_aware(value["at"]),
                payload=value,
            )
        )
