"""Headless console publication through the same current worker and DeskRuntime."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic, sleep
from typing import Literal, cast

from dmf_pulse.dashboard.authorization import AuthorizationError, production_approvals
from dmf_pulse.dashboard.current import CurrentRefreshSession
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.dashboard.views import DeskView
from dmf_pulse.operation.models import Metadata, Ref


class ConsoleRunReceipt(Metadata):
    schema_version: Literal["operator-console-run-v1"] = "operator-console-run-v1"
    status: Literal["COMPLETE"] = "COMPLETE"
    job_id: Ref
    dataset_mode: Literal["SYNTHETIC_CURRENT_MODE", "PRIVATE_TRANSIENT"]
    horizon: Literal[1, 3]
    production_active: Literal[False] = False
    retention: Literal["TRANSIENT_PUBLICATION_NO_FORECAST_STORAGE"] = (
        "TRANSIENT_PUBLICATION_NO_FORECAST_STORAGE"
    )


def _horizon(value: object) -> Literal[1, 3]:
    if type(value) is not int or value not in (1, 3):
        raise AuthorizationError("AUTHORIZATION_HORIZON_NOT_APPROVED")
    return cast(Literal[1, 3], value)


def run_enrolled_current(
    *,
    authorization_id: str,
    entry_id: int,
    horizon: Literal[1, 3],
    publish: Callable[[DeskView], None],
    progress: Callable[[str], None] | None = None,
) -> ConsoleRunReceipt:
    """Only a fixed installed approval can open this production execution path.

    No caller deadline, credential, source file, quota snapshot or grant is
    accepted. The current session rechecks installed code, exact manager/routes,
    rights, canonical budget and deadline before creating its normal worker.
    """
    horizon = _horizon(horizon)
    if type(entry_id) is not int or entry_id < 1:
        raise AuthorizationError("AUTHORIZATION_SCOPE_MISMATCH")
    rows = [row for row in production_approvals() if row.authorization_id == authorization_id]
    if len(rows) != 1:
        raise AuthorizationError(
            "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED", "RIGHTS_APPROVAL_REQUIRED"
        )
    approval = rows[0]
    if approval.qualified_deadline_at is None:
        raise AuthorizationError("AUTHORIZATION_DEADLINE_SCOPE_MISMATCH")
    session = CurrentRefreshSession.enrolled(
        authorization_id=authorization_id,
        entry_id=entry_id,
        deadline_at=approval.qualified_deadline_at,
    )
    runtime = DeskRuntime(current_session=session)
    return publish_runtime(runtime, horizon=horizon, publish=publish, progress=progress)


def publish_runtime(
    runtime: DeskRuntime,
    *,
    horizon: Literal[1, 3],
    publish: Callable[[DeskView], None],
    progress: Callable[[str], None] | None = None,
    wait: Callable[[float], None] = sleep,
    elapsed: Callable[[], float] = monotonic,
) -> ConsoleRunReceipt:
    """Drive one existing runtime, publish once while valid, and always close it.

    This seam supports owned/injected acceptance. It cannot authorize a runtime;
    runtime.refresh and every publication perform their existing checks.
    """
    try:
        horizon = _horizon(horizon)
    except AuthorizationError:
        runtime.close()
        raise
    started = elapsed()
    seen: tuple[str, ...] = ()
    try:
        state = runtime.refresh(horizon)
        while state.status == "RUNNING":
            if elapsed() - started >= 900:
                raise AuthorizationError("RUN_TIMEOUT")
            if progress is not None and state.stages != seen:
                # Runtime already bounds and sanitizes this existing progress channel.
                progress(state.stages[-1])
                seen = state.stages
            wait(0.05)
            state = runtime.tick()
        if state.status != "COMPLETE":
            raise AuthorizationError(state.error_code or "RUN_OR_PUBLICATION_INVALID")
        view = runtime.view()
        # view() checks grant revocation, result HMAC, wall/monotone expiry again.
        if view is None or view.dataset_mode not in {"SYNTHETIC_CURRENT_MODE", "PRIVATE_TRANSIENT"}:
            raise AuthorizationError("RUN_OR_PUBLICATION_INVALID")
        if len(view.gameweeks) != horizon or view.job_id != state.job_id:
            raise AuthorizationError("RUN_OR_PUBLICATION_INVALID")
        publish(view)
        return ConsoleRunReceipt(
            job_id=view.job_id,
            dataset_mode=cast(
                Literal["SYNTHETIC_CURRENT_MODE", "PRIVATE_TRANSIENT"], view.dataset_mode
            ),
            horizon=horizon,
        )
    finally:
        runtime.close()
