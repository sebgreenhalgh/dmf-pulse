"""Canonical PostgreSQL standing-operation custody and event deduplication."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, insert, select
from sqlalchemy.exc import SQLAlchemyError

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.dashboard.authorization import RefreshGrant
from dmf_pulse.dashboard.postgres_authorization import ConnectionFactory, PostgresUsageLedger
from dmf_pulse.dashboard.views import DeskView
from dmf_pulse.data_model.tables import operator_journal
from dmf_pulse.database.schema import current_alembic_revision
from dmf_pulse.operation.diagnostics import DiagnosticReport
from dmf_pulse.operation.enrollment import InstalledEnrollment
from dmf_pulse.operation.models import ChargedQuotaStatus, MetadataTime, OperationError
from dmf_pulse.operation.standing import (
    QuotaProof,
    StandingPolicy,
    VerifiedPeriod,
    derive_enrollment,
    execution_key,
    verify_period,
)

PAID_ROUTE_SHA = canonical_sha256(
    ["ODDS", "GET", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds"]
)

if TYPE_CHECKING:
    from dmf_pulse.operation.discovery import EventDiscovery
    from dmf_pulse.operation.quota import QuotaFailureEvidence, QuotaObservation


class OperationJournal:
    """No replacement ledger, generic authority import or database initialization."""

    def __init__(self, policy: StandingPolicy, factory: ConnectionFactory) -> None:
        self.policy, self.factory = policy, factory
        self.ledger = PostgresUsageLedger(
            factory, policy.ledger_id, account_ref=policy.odds_account_ref
        )

    @classmethod
    def production(cls, policy: StandingPolicy) -> OperationJournal:
        from dmf_pulse.dashboard.current import _control_connection

        return cls(policy, lambda: _control_connection("OPERATOR_CONTROL_DATABASE"))

    @contextmanager
    def _transaction(self) -> Iterator[tuple[Connection, list[dict[str, Any]]]]:
        # Authenticate the existing original chain before touching new custody.
        self.ledger.audit()
        try:
            with self.factory() as connection, connection.begin():
                PostgresUsageLedger._prepare(connection, self.ledger.account_sha256)
                if current_alembic_revision(connection) != "20261101_0010":
                    raise OperationError("STANDING_CONTROL_MIGRATION_REQUIRED")
                rows = [
                    dict(row)
                    for row in connection.execute(
                        select(operator_journal)
                        .where(operator_journal.c.ledger_id == self.policy.ledger_id)
                        .order_by(operator_journal.c.sequence)
                    ).mappings()
                ]
                previous = "0" * 64
                previous_at = datetime.min.replace(tzinfo=UTC)
                for sequence, row in enumerate(rows):
                    body = self._body(row)
                    at = MetadataTime(checked_at=row["at"]).checked_at
                    if (
                        row["sequence"] != sequence
                        or row["previous_sha256"] != previous
                        or row["sha256"] != canonical_sha256(body)
                        or at < previous_at
                        or datetime.fromisoformat(row["payload"]["recorded_at"]) != at
                        or set(row["payload"]) != {"recorded_at", "value"}
                        or len(canonical_json_bytes(body)) > 8_388_608
                    ):
                        raise OperationError("STANDING_JOURNAL_INVALID")
                    previous, previous_at = row["sha256"], at
                yield connection, rows
        except OperationError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError, KeyError, OverflowError):
            raise OperationError("STANDING_CONTROL_UNAVAILABLE_OR_INVALID") from None

    @staticmethod
    def _body(row: Mapping[str, Any]) -> dict[str, object]:
        return {
            "ledger_id": row["ledger_id"],
            "sequence": row["sequence"],
            "previous_sha256": row["previous_sha256"],
            "at": row["payload"]["recorded_at"],
            "kind": row["kind"],
            "execution_key": row["execution_key"],
            "payload": row["payload"],
        }

    def _append(
        self,
        connection: Connection,
        rows: list[dict[str, Any]],
        kind: str,
        value: dict[str, Any],
        *,
        now: datetime,
        key: str | None = None,
    ) -> str:
        now = MetadataTime(checked_at=now).checked_at
        if rows and now < rows[-1]["at"]:
            raise OperationError("STANDING_CLOCK_REGRESSED")
        row: dict[str, Any] = {
            "ledger_id": self.policy.ledger_id,
            "sequence": len(rows),
            "previous_sha256": rows[-1]["sha256"] if rows else "0" * 64,
            "at": now,
            "kind": kind,
            "execution_key": key,
            "payload": {"recorded_at": now.isoformat(), "value": value},
        }
        body = self._body(row)
        if len(canonical_json_bytes(body)) > 4_194_304:
            raise OperationError("STANDING_RECEIPT_TOO_LARGE")
        row["sha256"] = canonical_sha256(body)
        connection.execute(insert(operator_journal).values(**row))
        rows.append(row)
        return str(row["sha256"])

    def recover(self) -> dict[str, object]:
        original = self.ledger.audit()
        with self._transaction() as (_, rows):
            return {
                "ledger_id": original.ledger_id,
                "original_event_count": original.event_count,
                "original_head_sha256": original.head_sha256,
                "standing_event_count": len(rows),
                "standing_head_sha256": rows[-1]["sha256"] if rows else "0" * 64,
            }

    def local_refresh_check(self, *, now: datetime) -> None:
        """Read-only preliminary checks; official discovery/enroll remain mandatory."""
        now = MetadataTime(checked_at=now).checked_at
        if not self.policy.accepted_at <= now < self.policy.valid_until:
            raise OperationError("STANDING_PERMISSION_REVIEW_EXPIRED")
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self._transaction() as (connection, rows):
            used, unresolved = self._paid_state(connection, rows, self.policy, start)
            if unresolved:
                raise OperationError("QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION")
            known = [row for row in rows if row["kind"] == "DISCOVERY"]
            if known:
                event = known[-1]["payload"]["value"]
                if now < datetime.fromisoformat(event["deadline_at"]):
                    key = execution_key(self.policy, event["target_gameweek"])
                    if any(row["kind"] == "ENROLL" and row["execution_key"] == key for row in rows):
                        raise OperationError("GAMEWEEK_ACQUISITION_ALREADY_RECORDED")
            reservations = [
                record
                for record in self.ledger._read_records(connection)
                if record["kind"] == "RESERVATION"
                and record["account_sha256"] == self.ledger.account_sha256
            ]
            daily = sum(record["day"] == now.date().isoformat() for record in reservations)
            monthly = sum(record["period"] == start.isoformat() for record in reservations)
            limits = self.policy.limits
            if daily + 1 > limits.daily_requests or 2 * (daily + 1) > limits.daily_credits:
                raise OperationError("DAILY_BUDGET_EXHAUSTED")
            if monthly + 1 > limits.monthly_requests or 2 * (monthly + 1) > limits.monthly_credits:
                raise OperationError("MONTHLY_BUDGET_EXHAUSTED")
            if self.policy.plan_credit_allowance - used < limits.safety_reserve_credits + 2:
                raise OperationError("QUOTA_BELOW_SAFETY_RESERVE")
            enrolled = [row for row in rows if row["kind"] == "ENROLL" and row["at"] >= start]
            if (
                len(enrolled) >= self.policy.limits.monthly_requests
                or sum(row["at"].date() == now.date() for row in enrolled)
                >= self.policy.limits.daily_requests
            ):
                raise OperationError("STANDING_REQUEST_BUDGET_EXHAUSTED")

    def analysis_publications(self) -> list[dict[str, Any]]:
        """Authenticated immutable publication facts only; no enrollment or append."""
        with self._transaction() as (_, rows):
            return [
                {
                    "key": row["execution_key"],
                    "sha256": row["sha256"],
                    "at": row["at"],
                    "value": row["payload"]["value"],
                }
                for row in rows
                if row["kind"] == "PUBLICATION"
            ]

    def require_no_live_execution(self, *, now: datetime) -> None:
        """Maintenance cannot hide a previous release's unexpired grant or lease."""
        now = MetadataTime(checked_at=now).checked_at
        with self._transaction() as (_, rows):
            closed = {
                row["payload"]["value"]["launch_id"] for row in rows if row["kind"] == "CLOSE"
            }
            for row in rows:
                value = row["payload"]["value"]
                if row["kind"] == "ENROLL" and now < datetime.fromisoformat(value["expires_at"]):
                    raise OperationError("MAINTENANCE_REQUIRES_FINISHED_EXECUTION_WINDOW")
                if (
                    row["kind"] == "LAUNCH"
                    and value["launch_id"] not in closed
                    and now < datetime.fromisoformat(value["lease_until"])
                ):
                    raise OperationError("MAINTENANCE_REQUIRES_FINISHED_LAUNCH_LEASE")

    def begin_launch(self, *, now: datetime) -> str:
        with self._transaction() as (connection, rows):
            closed = {
                row["payload"]["value"]["launch_id"] for row in rows if row["kind"] == "CLOSE"
            }
            for row in rows:
                if row["kind"] == "LAUNCH":
                    value = row["payload"]["value"]
                    if value["launch_id"] not in closed and now < datetime.fromisoformat(
                        value["lease_until"]
                    ):
                        raise OperationError("ANOTHER_OPERATOR_LAUNCH_IS_RUNNING")
            identity = token_hex(32)
            self._append(
                connection,
                rows,
                "LAUNCH",
                {
                    "launch_id": identity,
                    "policy_sha256": self.policy.semantic_sha256,
                    "lease_until": (
                        now
                        + timedelta(seconds=self.policy.limits.credential_minimum_remaining_seconds)
                    ).isoformat(),
                },
                now=now,
            )
            return identity

    def close_launch(self, launch_id: str, *, now: datetime) -> None:
        with self._transaction() as (connection, rows):
            if not any(
                row["kind"] == "LAUNCH" and row["payload"]["value"]["launch_id"] == launch_id
                for row in rows
            ):
                raise OperationError("OPERATOR_LAUNCH_NOT_FOUND")
            if not any(
                row["kind"] == "CLOSE" and row["payload"]["value"]["launch_id"] == launch_id
                for row in rows
            ):
                self._append(connection, rows, "CLOSE", {"launch_id": launch_id}, now=now)

    def record_quota(
        self, proof: QuotaProof, *, now: datetime, observation: QuotaObservation | None = None
    ) -> None:
        with self._transaction() as (connection, rows):
            self._append(
                connection,
                rows,
                "QUOTA",
                {
                    "proof": proof.model_dump(mode="json"),
                    "observation": None
                    if observation is None
                    else observation.model_dump(mode="json"),
                },
                now=now,
            )

    def record_discovery(self, event: EventDiscovery, *, now: datetime) -> None:
        with self._transaction() as (connection, rows):
            self._append(connection, rows, "DISCOVERY", event.model_dump(mode="json"), now=now)

    def _paid_state(
        self,
        connection: Connection,
        rows: list[dict[str, Any]],
        policy: StandingPolicy,
        start: datetime,
    ) -> tuple[int, int]:
        if policy != self.policy:
            raise OperationError("PRIOR_USAGE_ORIGINAL_ACCOUNT_BINDING_INVALID")
        original = [
            row
            for row in self.ledger._read_records(connection)
            if datetime.fromisoformat(row["at"]) >= start
        ]
        paid = {
            row["reservation_id"]
            for row in original
            if row["kind"] == "ATTEMPT" and row["route_sha256"] == PAID_ROUTE_SHA
        }
        from dmf_pulse.operation.campaign_journal import is_diagnostic_settlement

        settlements = [
            row["payload"]["value"]
            for row in rows
            if (row["kind"] == "SETTLEMENT" or is_diagnostic_settlement(row)) and row["at"] >= start
        ]
        settled = {
            item["reservation_id"]
            for item in settlements
            if item["consistent"] is True and item["period_started_at"] == start.isoformat()
        }
        if (
            len({item["reservation_id"] for item in settlements}) != len(settlements)
            or settled - paid
            or len(settled) != len([s for s in settlements if s["consistent"] is True])
        ):
            raise OperationError("QUOTA_SETTLEMENT_LEDGER_CONTRADICTION")
        from dmf_pulse.operation.prior_usage import attributed_usage_credits

        attributed = attributed_usage_credits(rows, original, policy, start)
        return attributed + sum(
            item["last_request_cost"] for item in settlements if item["reservation_id"] in settled
        ), len(paid - settled)

    def record_owner_attributed_prior_usage(self) -> str:
        """Append one fixed signed account fact; never a settlement or request."""
        from dmf_pulse.operation.prior_usage import (
            KIND,
            load_prior_usage_import,
            validate_canonical_fact,
        )

        verified = load_prior_usage_import()
        if verified.policy != self.policy:
            raise OperationError("PRIOR_USAGE_CURRENT_INSTALLED_POLICY_REQUIRED")
        evidence = verified.evidence
        now = datetime.now(UTC)
        if not evidence.fact.period_started_at <= now < evidence.fact.period_resets_at:
            raise OperationError("PRIOR_USAGE_IMPORT_PERIOD_CLOSED")
        with self._transaction() as (connection, rows):
            if any(r["payload"]["value"].get("subtype") == KIND for r in rows):
                raise OperationError("PRIOR_USAGE_DUPLICATE_OR_INVALID_ATTRIBUTION")
            original = self.ledger._read_records(connection)
            validate_canonical_fact(evidence.fact, self.policy, rows, original, recorded_at=now)
            return self._append(
                connection,
                rows,
                "QUOTA",
                {"subtype": KIND, "evidence": evidence.model_dump(mode="json")},
                now=now,
            )

    def qualify_quota(self, quota: QuotaProof, *, now: datetime) -> VerifiedPeriod:
        with self._transaction() as (connection, rows):
            start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            used, unresolved = self._paid_state(connection, rows, self.policy, start)
            return verify_period(
                self.policy,
                quota,
                now=now,
                settled_credits=used,
                unresolved_paid_attempts=unresolved,
            )

    def enroll(self, event: EventDiscovery, quota: QuotaProof, *, now: datetime) -> str:
        """Called only by explicit installed launch after real fixed-route acquisition."""
        key = execution_key(self.policy, event.target_gameweek)
        with self._transaction() as (connection, rows):
            if any(row["kind"] == "ENROLL" and row["execution_key"] == key for row in rows):
                raise OperationError("GAMEWEEK_ACQUISITION_ALREADY_RECORDED")
            start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            used, unresolved = self._paid_state(connection, rows, self.policy, start)
            period = verify_period(
                self.policy,
                quota,
                now=now,
                settled_credits=used,
                unresolved_paid_attempts=unresolved,
            )
            same_period = [row for row in rows if row["kind"] == "ENROLL" and row["at"] >= start]
            same_day = [row for row in same_period if row["at"].date() == now.date()]
            if (
                len(same_period) >= self.policy.limits.monthly_requests
                or len(same_day) >= self.policy.limits.daily_requests
            ):
                raise OperationError("STANDING_REQUEST_BUDGET_EXHAUSTED")
            enrollment = derive_enrollment(self.policy, event, quota, period, created_at=now)
            approval = enrollment.approvals[0]
            self._append(
                connection,
                rows,
                "ENROLL",
                {
                    "policy_sha256": self.policy.semantic_sha256,
                    "event": event.model_dump(mode="json"),
                    "quota": quota.model_dump(mode="json"),
                    "period": period.model_dump(mode="json"),
                    "approval_sha256": canonical_sha256(approval.model_dump(mode="json")),
                    "expires_at": approval.expires_at.isoformat(),
                },
                now=now,
                key=key,
            )
        return key

    def active_enrollment(
        self, policy: StandingPolicy, *, now: datetime
    ) -> InstalledEnrollment | None:
        from dmf_pulse.operation.discovery import EventDiscovery

        with self._transaction() as (_, rows):
            active = []
            for row in rows:
                if row["kind"] != "ENROLL":
                    continue
                value = row["payload"]["value"]
                if value["policy_sha256"] != policy.semantic_sha256 or not row[
                    "at"
                ] <= now < datetime.fromisoformat(value["expires_at"]):
                    continue
                event = EventDiscovery.model_validate_json(json.dumps(value["event"]))
                quota = QuotaProof.model_validate_json(json.dumps(value["quota"]))
                period = VerifiedPeriod.model_validate_json(json.dumps(value["period"]))
                enrolled = derive_enrollment(policy, event, quota, period, created_at=row["at"])
                if row["execution_key"] != execution_key(policy, event.target_gameweek) or value[
                    "approval_sha256"
                ] != canonical_sha256(enrolled.approvals[0].model_dump(mode="json")):
                    raise OperationError("DERIVED_STANDING_GRANT_INVALID")
                active.append(enrolled)
            if len(active) > 1:
                raise OperationError("AMBIGUOUS_STANDING_EXECUTION")
            return active[0] if active else None

    def saved_view(self, key: str) -> DeskView | None:
        with self._transaction() as (_, rows):
            publications = [
                row for row in rows if row["execution_key"] == key and row["kind"] == "PUBLICATION"
            ]
            if len(publications) > 1:
                raise OperationError("AMBIGUOUS_STANDING_PUBLICATION")
            if not publications:
                return None
            return DeskView.model_validate_json(
                json.dumps(publications[0]["payload"]["value"]["view"])
            )

    def contains_event(self, key: str) -> bool:
        with self._transaction() as (_, rows):
            return any(row["kind"] == "ENROLL" and row["execution_key"] == key for row in rows)

    def charged_quota_status(self, key: str) -> ChargedQuotaStatus | None:
        with self._transaction() as (_, rows):
            settlements = [
                row for row in rows if row["kind"] == "SETTLEMENT" and row["execution_key"] == key
            ]
            if not settlements:
                return None
            if len(settlements) != 1:
                raise OperationError("AMBIGUOUS_ACTUAL_QUOTA_RECEIPT")
            row = settlements[0]
            value = row["payload"]["value"]
            return ChargedQuotaStatus(
                remaining_credits=value["remaining_credits"],
                used_credits=value["used_credits"],
                last_request_cost=value["last_request_cost"],
                reserved_credits=value["reserved_credits"],
                received_at=row["at"],
                provider_status=value["provider_status"],
                consistent_with_ledger=value["consistent"],
                receipt_sha256=row["sha256"],
            )

    def publish(
        self,
        key: str,
        view: DeskView,
        *,
        now: datetime,
        diagnostics: DiagnosticReport | None = None,
        analysis_sha256: str | None = None,
    ) -> str:
        if view.dataset_mode != "PRIVATE_TRANSIENT" or view.market_quota_receipt is None:
            raise OperationError("REAL_PRIVATE_PUBLICATION_REQUIRED")
        if analysis_sha256 is not None and (
            len(analysis_sha256) != 64 or any(c not in "0123456789abcdef" for c in analysis_sha256)
        ):
            raise OperationError("REAL_PRIVATE_PUBLICATION_REQUIRED")
        with self._transaction() as (connection, rows):
            if not any(
                row["kind"] == "SETTLEMENT"
                and row["execution_key"] == key
                and row["payload"]["value"]["consistent"] is True
                for row in rows
            ):
                raise OperationError("ACTUAL_ODDS_SETTLEMENT_REQUIRED")
            if any(row["kind"] == "PUBLICATION" and row["execution_key"] == key for row in rows):
                raise OperationError("AMBIGUOUS_STANDING_PUBLICATION")
            return self._append(
                connection,
                rows,
                "PUBLICATION",
                {
                    "view": view.model_dump(mode="json"),
                    "retention": "PRIVATE_DERIVED_AS_OF",
                    "unvalidated": True,
                    **({"analysis_sha256": analysis_sha256} if analysis_sha256 else {}),
                    **(
                        {"diagnostics": diagnostics.model_dump(mode="json")}
                        if diagnostics is not None
                        else {}
                    ),
                },
                now=now,
                key=key,
            )

    def fail(
        self,
        key: str | None,
        code: str,
        *,
        now: datetime,
        quota_evidence: QuotaFailureEvidence | None = None,
        diagnostics: DiagnosticReport | None = None,
    ) -> None:
        from dmf_pulse.current_failures import CURRENT_FAILURE_CODES

        if type(code) is not str or code not in CURRENT_FAILURE_CODES:
            code = "CURRENT_TYPED_FAILURE_UNRECOGNIZED"
        with self._transaction() as (connection, rows):
            self._append(
                connection,
                rows,
                "FAILURE",
                {
                    "error_code": code,
                    **(
                        {"diagnostics": diagnostics.model_dump(mode="json")}
                        if diagnostics is not None
                        else {}
                    ),
                    "quota_evidence": None
                    if quota_evidence is None
                    else quota_evidence.model_dump(mode="json"),
                },
                now=now,
                key=key,
            )

    def settle_response(
        self, grant: RefreshGrant, headers: Mapping[str, str], status: int, *, now: datetime
    ) -> None:
        from dmf_pulse.operation.quota import parse_quota_header_values

        values = parse_quota_header_values(headers)
        key = grant.request.authorization_id.removeprefix("OPR001-")
        with self._transaction() as (connection, rows):
            matches = [
                row for row in rows if row["kind"] == "ENROLL" and row["execution_key"] == key
            ]
            if len(matches) != 1:
                raise OperationError("STANDING_EXECUTION_NOT_FOUND")
            value = matches[0]["payload"]["value"]
            before = QuotaProof.model_validate_json(json.dumps(value["quota"]))
            period = VerifiedPeriod.model_validate_json(json.dumps(value["period"]))
            consistent = (
                values.remaining_credits + values.used_credits == self.policy.plan_credit_allowance
                and values.last_request_cost <= grant.reserved_odds_credits
                and values.used_credits == before.used_credits + values.last_request_cost
                and values.remaining_credits == before.remaining_credits - values.last_request_cost
                and period.started_at <= now < period.resets_at
            )
            self._append(
                connection,
                rows,
                "SETTLEMENT",
                {
                    "reservation_id": grant.reservation_id,
                    "period_started_at": period.started_at.isoformat(),
                    "reserved_credits": grant.reserved_odds_credits,
                    "remaining_credits": values.remaining_credits,
                    "used_credits": values.used_credits,
                    "last_request_cost": values.last_request_cost,
                    "provider_status": status,
                    "source": "ACTUAL_CHARGED_RESPONSE_HEADERS",
                    "consistent": consistent,
                },
                now=now,
                key=key,
            )
        # Retain the actual contradictory evidence before withholding publication.
        if not consistent:
            raise OperationError("CHARGED_QUOTA_HEADERS_CONTRADICT_LEDGER")
