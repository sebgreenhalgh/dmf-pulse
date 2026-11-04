"""Explicitly constructed loopback-only FastAPI application with one private session."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from importlib.resources import files
from secrets import token_urlsafe
from time import monotonic
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, SecretStr, StrictStr, field_validator
from starlette.responses import JSONResponse, Response

from dmf_pulse.dashboard.current import CurrentEligibility
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.dashboard.views import PlayerComparison
from dmf_pulse.player_lab.recovery import RecoveryError, recovery_catalogue
from dmf_pulse.private_v1.presentation import PresentationModel

_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _lookup_call[LookupResult](call: Callable[[], LookupResult]) -> LookupResult:
    """Translate absent items before iterator exceptions cross an async Future."""
    try:
        return call()
    except StopIteration:
        raise ValueError("PLAYER_UNAVAILABLE") from None


class RefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    horizon: Literal[1, 3] = 1

    @field_validator("horizon", mode="before")
    @classmethod
    def exact_horizon(cls, value: object) -> object:
        if type(value) is not int or value not in (1, 3):
            raise ValueError("unsupported horizon")
        return value


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pairing_code: StrictStr


class FplCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    token: SecretStr
    challenge: StrictStr


class HistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: StrictStr


class HistoryCompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    first_run_id: StrictStr
    second_run_id: StrictStr


class SessionContext(PresentationModel):
    schema_version: Literal["desk-session-v2"] = "desk-session-v2"
    demo: bool
    synthetic_sources: bool
    execution_mode: Literal["DEMO", "PRIVATE_CURRENT"]
    eligibility: CurrentEligibility | None
    persistent_history: bool = False


def _error(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error_code": code}, status_code=status, headers=_HEADERS)


def create_app(
    *,
    runtime: DeskRuntime,
    pairing_code: str,
    port: int,
    elapsed_clock: Callable[[], float] = monotonic,
    trusted_local_navigation: bool = False,
) -> FastAPI:
    """No listener, browser, environment or filesystem mutation until the CLI starts it."""
    if not 1024 <= port <= 65535 or len(pairing_code) < 20:
        raise ValueError("invalid local session configuration")
    origin = f"http://127.0.0.1:{port}"
    session: str | None = None
    session_started = 0.0
    login_attempts = 0
    paired = False

    def context() -> SessionContext:
        return SessionContext(
            demo=runtime.demo,
            synthetic_sources=runtime.synthetic_sources,
            execution_mode="DEMO" if runtime.demo else "PRIVATE_CURRENT",
            eligibility=runtime.eligibility(),
            persistent_history=bool(getattr(runtime, "persistent", False)),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app

        async def sweep() -> None:
            while True:
                await asyncio.sleep(1)
                if session is not None and elapsed_clock() - session_started >= 3600:
                    await asyncio.to_thread(runtime.cancel)
                await asyncio.to_thread(runtime.tick)

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await asyncio.to_thread(runtime.close)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> Response:
        del request, error  # Never echo input, especially the pairing code.
        return _error("INPUT_INVALID", 422)

    @app.exception_handler(Exception)
    async def safe_failure(request: Request, error: Exception) -> Response:
        del request, error
        await asyncio.to_thread(runtime.cancel)
        return _error("REQUEST_FAILED", 500)

    @app.middleware("http")
    async def private_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Host pinning also defeats DNS rebinding; proxy forwarding is not supported.
        if (
            request.headers.get("host") != f"127.0.0.1:{port}"
            or request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.scope.get("scheme") != "http"
            or any(key.lower().startswith("x-forwarded-") for key in request.headers)
            or "forwarded" in request.headers
            or request.url.query
        ):
            return _error("LOCAL_ORIGIN_REQUIRED", 403)
        supplied_origin = request.headers.get("origin")
        if supplied_origin is not None and supplied_origin != origin:
            return _error("ORIGIN_REJECTED", 403)
        if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
            return _error("ORIGIN_REJECTED", 403)
        if request.method not in {"GET", "POST"}:
            return _error("METHOD_REJECTED", 405)
        if request.method == "POST":
            if (
                supplied_origin != origin
                or request.headers.get("x-dmf-action") != "operator"
                or request.headers.get("content-type") != "application/json"
            ):
                return _error("CSRF_REJECTED", 403)
            # Do not buffer an unbounded request, including a chunked body.
            size = 0
            chunks = []
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 4096:
                            return _error("REQUEST_TOO_LARGE", 413)
                        chunks.append(chunk)
            except TimeoutError:
                return _error("REQUEST_TIMEOUT", 408)
            request._body = b"".join(chunks)
            chunks.clear()
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            if session is not None and elapsed_clock() - session_started >= 3600:
                await asyncio.to_thread(runtime.cancel)
                return _error("SESSION_REQUIRED", 401)
            cookie = request.cookies.get("dmf_session", "")
            if (
                session is None
                or not hmac.compare_digest(
                    hashlib.sha256(cookie.encode("utf-8", errors="surrogatepass")).digest(),
                    hashlib.sha256(session.encode()).digest(),
                )
                or elapsed_clock() - session_started >= 3600
            ):
                return _error("SESSION_REQUIRED", 401)
        response = await call_next(request)
        if (
            request.url.path.startswith("/api/")
            and request.url.path not in {"/api/session", "/api/logout"}
            and (session is None or elapsed_clock() - session_started >= 3600)
        ):
            await asyncio.to_thread(runtime.cancel)
            return _error("SESSION_REQUIRED", 401)
        response.headers.update(_HEADERS)
        return response

    @app.get("/")
    async def index(request: Request) -> Response:
        nonlocal session, session_started, paired, pairing_code
        response = Response(
            files("dmf_pulse.dashboard.resources").joinpath("index.html").read_bytes(),
            media_type="text/html",
            headers=_HEADERS,
        )
        if trusted_local_navigation and (
            not paired
            or session is None
            or elapsed_clock() - session_started >= 3600
            or request.cookies.get("dmf_session") != session
        ):
            # Explicit `dmf start` owns this loopback listener. Only a top-level
            # direct browser navigation can bootstrap its one local session;
            # cross-site requests, frames, scripts and API calls cannot pair it.
            if (
                request.headers.get("sec-fetch-site") != "none"
                or request.headers.get("sec-fetch-mode") != "navigate"
                or request.headers.get("sec-fetch-dest") != "document"
                or request.headers.get("origin") is not None
            ):
                return _error("DIRECT_LOCAL_NAVIGATION_REQUIRED", 403)
            paired, pairing_code = True, ""
            session, session_started = token_urlsafe(32), elapsed_clock()
            response.set_cookie(
                "dmf_session", session, httponly=True, samesite="strict", max_age=3600, path="/"
            )
        return response

    @app.get("/assets/{name}")
    async def asset(name: str) -> Response:
        content_type = {"desk.js": "text/javascript", "desk.css": "text/css"}.get(name)
        if content_type is None:
            return _error("ASSET_NOT_FOUND", 404)
        return Response(
            files("dmf_pulse.dashboard.resources").joinpath(name).read_bytes(),
            media_type=content_type,
            headers=_HEADERS,
        )

    @app.post("/api/session")
    async def pair(value: SessionInput) -> Response:
        nonlocal session, session_started, login_attempts, paired, pairing_code
        login_attempts += 1
        if (
            paired
            or login_attempts > 5
            or not hmac.compare_digest(
                hashlib.sha256(value.pairing_code.encode("utf-8", errors="surrogatepass")).digest(),
                hashlib.sha256(pairing_code.encode()).digest(),
            )
        ):
            return _error("PAIRING_REJECTED", 403)
        paired = True
        pairing_code = ""
        session = token_urlsafe(32)
        session_started = elapsed_clock()
        response = JSONResponse(
            {"status": "PAIRED", **context().model_dump(mode="json")}, headers=_HEADERS
        )
        response.set_cookie("dmf_session", session, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/context")
    async def session_context() -> Response:
        return Response(
            context().model_dump_json(),
            media_type="application/json",
            headers=_HEADERS,
        )

    @app.get("/api/eligibility")
    async def eligibility() -> Response:
        value = runtime.eligibility()
        return JSONResponse(None if value is None else value.model_dump(mode="json"))

    @app.post("/api/refresh")
    async def refresh(value: RefreshInput) -> Response:
        nonlocal session_started
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        if isinstance(runtime, PersistentDeskRuntime):
            # An explicit authenticated action gives preparation + the unchanged
            # bounded run its full browser window. It renews no provider grant.
            session_started = elapsed_clock()
        state = await asyncio.to_thread(runtime.refresh, value.horizon)
        result = state.model_dump(mode="json")
        if isinstance(runtime, PersistentDeskRuntime):
            result["credential_challenge"] = runtime.credential_challenge()
        response = JSONResponse(result)
        if isinstance(runtime, PersistentDeskRuntime) and session is not None:
            response.set_cookie(
                "dmf_session", session, httponly=True, samesite="strict", max_age=3600, path="/"
            )
        return response

    @app.post("/api/credentials/fpl")
    async def register_fpl(value: FplCredentialInput, request: Request) -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        # Remove framework/body references promptly. No exception or validation
        # handler may return submitted values; access logging is disabled.
        request._body = b""
        if hasattr(request, "_json"):
            request._json = None
        if not isinstance(runtime, PersistentDeskRuntime):
            return _error("BROWSER_CREDENTIAL_ENTRY_NOT_ENABLED", 403)
        secret, challenge = value.token, value.challenge
        del value
        try:
            state = await asyncio.to_thread(runtime.submit_fpl, secret, challenge)
            return JSONResponse(state.model_dump(mode="json"))
        finally:
            del secret

    @app.get("/api/history")
    async def history() -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        if not isinstance(runtime, PersistentDeskRuntime):
            return _error("HISTORY_NOT_ENABLED", 404)
        return JSONResponse(await asyncio.to_thread(runtime.history))

    @app.post("/api/history/select")
    async def select_history(value: HistoryInput) -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        if not isinstance(runtime, PersistentDeskRuntime):
            return _error("HISTORY_NOT_ENABLED", 404)
        selected = await asyncio.to_thread(runtime.select_run, value.run_id)
        return (
            _error("HISTORICAL_RUN_UNAVAILABLE", 404)
            if selected is None
            else Response(
                selected.model_dump_json(), media_type="application/json", headers=_HEADERS
            )
        )

    @app.get("/api/analysis/status")
    async def analysis_status() -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        return JSONResponse(
            await asyncio.to_thread(runtime.analysis_status)
            if isinstance(runtime, PersistentDeskRuntime)
            else {"historical": False}
        )

    @app.post("/api/history/compare")
    async def compare_history(value: HistoryCompareInput) -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        if not isinstance(runtime, PersistentDeskRuntime):
            return _error("HISTORY_NOT_ENABLED", 404)
        comparison = await asyncio.to_thread(
            runtime.compare_runs, value.first_run_id, value.second_run_id
        )
        return (
            _error("HISTORICAL_COMPARISON_UNAVAILABLE", 422)
            if comparison is None
            else JSONResponse(comparison)
        )

    @app.get("/api/analysis/optimizer")
    async def optimizer_evidence() -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        if not isinstance(runtime, PersistentDeskRuntime):
            return _error("HISTORY_NOT_ENABLED", 404)
        return JSONResponse(await asyncio.to_thread(runtime.optimizer_evidence))

    @app.get("/api/status")
    async def status() -> Response:
        return JSONResponse((await asyncio.to_thread(runtime.tick)).model_dump(mode="json"))

    def publish(value: PresentationModel) -> Response:
        body = value.model_dump_json().encode()
        if not getattr(runtime, "persistent", False) and runtime.tick().status != "COMPLETE":
            return _error("NO_CURRENT_RECOMMENDATION", 409)
        return Response(body, media_type="application/json", headers=_HEADERS)

    @app.get("/api/desk")
    async def desk() -> Response:
        value = await asyncio.to_thread(runtime.view)
        return _error("NO_CURRENT_RECOMMENDATION", 409) if value is None else publish(value)

    @app.get("/api/players/{official_id}")
    async def player(official_id: int) -> Response:
        try:
            return publish(
                await asyncio.to_thread(_lookup_call, lambda: runtime.player(official_id))
            )
        except (ValueError, StopIteration):
            return _error("PLAYER_UNAVAILABLE", 404)

    @app.get("/api/compare/{first}/{second}")
    async def compare(first: int, second: int) -> Response:
        from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

        try:
            if isinstance(runtime, PersistentDeskRuntime):
                left, right = await asyncio.to_thread(
                    _lookup_call, lambda: runtime.player_pair(first, second)
                )
            else:
                left = await asyncio.to_thread(_lookup_call, lambda: runtime.player(first))
                right = await asyncio.to_thread(_lookup_call, lambda: runtime.player(second))
            if (
                first == second
                or left.job_id != right.job_id
                or not left.gameweeks
                or left.gameweeks.keys() != right.gameweeks.keys()
            ):
                return _error("COMPARISON_HORIZON_INVALID", 422)
            return publish(PlayerComparison(left=left, right=right))
        except (ValueError, StopIteration):
            return _error("PLAYER_UNAVAILABLE", 404)

    @app.get("/api/performance")
    async def performance() -> Response:
        try:
            recovered = recovery_catalogue()
        except RecoveryError as error:
            return _error(error.code, 503)
        result: dict[str, object] = {
            "real_cohort_status": "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT",
            "real_cohort_scope": "PLAYER_COHORT; recovered P01 is a separate MATCH forecast",
            "recovery": recovered.model_dump(mode="json"),
        }
        if runtime.synthetic_sources and not getattr(runtime, "persistent", False):
            from dmf_pulse.player_lab.demo import synthetic_evaluation

            evaluation = synthetic_evaluation()
            result["synthetic_report"] = evaluation.scorecard.model_dump(mode="json")
            result["synthetic_holdout"] = evaluation.holdout.model_dump(mode="json")
            from dmf_pulse.player_lab.runner import operational_synthetic_evaluation

            result["operational_report"] = operational_synthetic_evaluation().model_dump(
                mode="json"
            )
        return JSONResponse(result)

    @app.post("/api/cancel")
    async def cancel() -> Response:
        return JSONResponse((await asyncio.to_thread(runtime.cancel)).model_dump(mode="json"))

    @app.post("/api/logout")
    async def logout() -> Response:
        nonlocal session
        await asyncio.to_thread(runtime.cancel)
        session = None
        response = JSONResponse({"status": "SIGNED_OUT"})
        response.delete_cookie("dmf_session", path="/")
        return response

    return app
