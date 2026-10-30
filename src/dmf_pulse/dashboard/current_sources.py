"""Existing provider clients with acquisition guards and explicitly owned transports."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from importlib.resources import files
from typing import Literal, Protocol

from dmf_pulse.credentials.providers import (
    AutomaticFplCredentialProvider,
    AutomaticOddsCredentialProvider,
)
from dmf_pulse.dashboard.synthetic import demo_inputs
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
    DirectTransport,
    DirectUrllibTransport,
)
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.client import (
    HttpClientOddsTransport,
    OddsClient,
    OddsHttpRequest,
    OddsHttpResponse,
    OddsTransport,
)
from dmf_pulse.ingestion.odds.config import load_provider_config as odds_provider_config
from dmf_pulse.ingestion.odds.credentials import (
    CredentialProvider,
    EnvironmentOddsCredentialProvider,
)
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.models import QuotaState
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.ingestion.openfootball.client import (
    HttpClientOpenFootballTransport,
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
    OpenFootballTransport,
)
from dmf_pulse.ingestion.openfootball.config import (
    OpenFootballProviderConfig,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorResult,
    CurrentScorePriorService,
)

Provider = Literal["FPL", "ODDS", "OPENFOOTBALL"]


class AcquisitionGuard(Protocol):
    def credential_failed(self, code: object) -> None: ...
    def before_transport(self) -> None: ...
    def preflight_send(self, provider: Provider, method: str, host: str, path: str) -> None: ...
    def before_send(self, provider: Provider, method: str, host: str, path: str) -> None: ...
    def finish_acquisition(self) -> None: ...


class _GuardedOddsCredentialProvider:
    """Read exact live route permission immediately before accepted key resolution."""

    def __init__(self, guard: AcquisitionGuard, delegate: CredentialProvider) -> None:
        self._guard, self._delegate = guard, delegate

    def get_credential(self) -> str | None:
        config = odds_provider_config()
        self._guard.preflight_send("ODDS", "GET", config.host, config.path)
        try:
            return self._delegate.get_credential()
        except IngestionError as error:
            self._guard.credential_failed(error.code)
            raise


class GuardedFplTransport:
    def __init__(
        self,
        guard: AcquisitionGuard,
        delegate: DirectTransport,
        *,
        check_expiry: Callable[[], None] | None = None,
    ) -> None:
        self._guard, self._delegate = guard, delegate
        self._check_expiry = check_expiry

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        self._guard.before_send("FPL", request.method, request.host, request.path)
        self._guard.before_transport()
        if self._check_expiry is not None and request.path.startswith("/api/my-team/"):
            # The control transaction can wait. Recheck metadata after it, with
            # no second credential read, immediately before authenticated I/O.
            self._check_expiry()
        return self._delegate.send(request)


class GuardedOddsTransport:
    transport_id: Literal["injected"] = "injected"

    def __init__(self, guard: AcquisitionGuard, delegate: OddsTransport) -> None:
        self._guard, self._delegate = guard, delegate

    def send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse:
        self._guard.before_send("ODDS", request.method, request.host, request.path)
        self._guard.before_transport()
        return self._delegate.send(request, credential)


class GuardedScoreTransport:
    transport_id = "guarded_current_source"

    def __init__(self, guard: AcquisitionGuard, delegate: OpenFootballTransport) -> None:
        self._guard, self._delegate = guard, delegate

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        self._guard.before_send("OPENFOOTBALL", request.method, request.host, request.path)
        self._guard.before_transport()
        return self._delegate.send(request)


class _ClosingScoreService(CurrentScorePriorService):
    acquisition_guard: AcquisitionGuard

    def build(self, request: CurrentScorePriorBuildRequest) -> CurrentScorePriorResult:
        try:
            return super().build(request)
        finally:
            self.acquisition_guard.finish_acquisition()


class OwnedFplTransport:
    """Consume only authenticated packaged, repository-owned source bytes."""

    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = list(bodies)

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        del request
        if not self._bodies:
            raise ValueError("owned FPL input exhausted")
        return DirectHttpResponse(200, "application/json", self._bodies.pop(0))


def owned_odds_body() -> bytes:
    """Re-encode exact owned market values into the existing provider parser schema."""
    source = OddsProviderCurrentInput.model_validate_json(demo_inputs()["odds.json"])
    events = []
    for event in source.events:
        books = []
        for book in event.bookmakers:
            markets = []
            for market in book.markets:
                markets.append(
                    {
                        "key": "h2h",
                        "last_update": market.provider_last_update.isoformat()
                        if market.provider_last_update is not None
                        else None,
                        "outcomes": [
                            {"name": row.provider_name, "price": float(row.decimal_price)}
                            for row in market.outcomes
                        ],
                    }
                )
            for totals in book.totals_markets:
                markets.append(
                    {
                        "key": "totals",
                        "last_update": totals.provider_last_update.isoformat()
                        if totals.provider_last_update is not None
                        else None,
                        "outcomes": [
                            {
                                "name": row.provider_name,
                                "price": float(row.decimal_price),
                                "point": float(row.point),
                            }
                            for row in totals.outcomes
                        ],
                    }
                )
            books.append(
                {
                    "key": book.bookmaker_key,
                    "title": book.bookmaker_title,
                    "last_update": book.provider_last_update.isoformat(),
                    "markets": markets,
                }
            )
        events.append(
            {
                "id": event.provider_event_id,
                "sport_key": event.sport_key,
                "sport_title": "Owned synthetic EPL fixture",
                "commence_time": event.commence_time.isoformat(),
                "home_team": event.provider_home_team,
                "away_team": event.provider_away_team,
                "bookmakers": books,
            }
        )
    return json.dumps(events, separators=(",", ":")).encode("utf-8")


class OwnedOddsTransport:
    transport_id: Literal["injected"] = "injected"

    def __init__(self) -> None:
        self._sent = False

    def send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse:
        del request, credential
        if self._sent:
            raise ValueError("owned Odds acquisition already consumed")
        self._sent = True
        return OddsHttpResponse(
            200,
            "application/json",
            {"x-requests-remaining": "98", "x-requests-used": "2", "x-requests-last": "2"},
            owned_odds_body(),
        )


class OwnedScoreTransport:
    transport_id = "repository_owned_current_mode"

    def __init__(self, config: OpenFootballProviderConfig, bodies: dict[str, bytes]) -> None:
        self._config = config
        manifest = json.loads(
            files("dmf_pulse.dashboard.resources")
            .joinpath("demo/manifest.json")
            .read_text(encoding="utf-8")
        )
        self._bodies = {
            config.raw_path(path): bodies[name] for path, name in manifest["score_paths"].items()
        }

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        if request.path not in self._bodies:
            raise ValueError("owned score path not present")
        return OpenFootballHttpResponse(
            status_code=200,
            content_type="text/plain"
            if request.path.endswith("LICENSE.md")
            else "application/json",
            headers={},
            body=self._bodies[request.path],
        )


class CurrentSourceFactories:
    """Credential providers stay inside the child and never enter its launch spec."""

    def __init__(
        self,
        *,
        guard: AcquisitionGuard,
        owned: bool,
        fpl_profile: RightsProfile,
        odds_profile: RightsProfile,
        quota: QuotaState,
        clock: Callable[[], datetime],
    ) -> None:
        self._guard, self._owned, self._clock = guard, owned, clock
        self._fpl_profile, self._odds_profile, self._quota = fpl_profile, odds_profile, quota
        self._inputs = demo_inputs() if owned else {}

    def direct(self, attestation: DirectFplRunAttestation) -> DirectFplClient:
        delegate: DirectTransport
        if self._owned:
            delegate = OwnedFplTransport([self._inputs[f"fpl-{index}.json"] for index in range(8)])
            credentials = DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": "placeholder"})
        else:
            delegate = DirectUrllibTransport()
            credentials = AutomaticFplCredentialProvider(clock=self._clock)
        return DirectFplClient(
            attestation,
            profile=self._fpl_profile,
            transport=GuardedFplTransport(
                self._guard,
                delegate,
                check_expiry=credentials.check_expiry
                if isinstance(credentials, AutomaticFplCredentialProvider)
                else None,
            ),
            credential_provider=credentials,
            before_credential=lambda method, host, path: self._guard.preflight_send(
                "FPL", method, host, path
            ),
            clock=self._clock,
            maximum_attempts=1,
            sleeper=(lambda _: None) if self._owned else time.sleep,
            pace_seconds=0 if self._owned else 0.25,
        )

    def odds(self, clock: Callable[[], datetime]) -> CurrentOddsTransientService:
        delegate_credentials = (
            EnvironmentOddsCredentialProvider(
                environment={"THE_ODDS_API_KEY": "placeholder" + "-placeholder"}
            )
            if self._owned
            else AutomaticOddsCredentialProvider()
        )
        credentials = _GuardedOddsCredentialProvider(self._guard, delegate_credentials)

        def client(profile: RightsProfile, **kwargs: object) -> OddsClient:
            del kwargs
            delegate: OddsTransport = (
                OwnedOddsTransport() if self._owned else HttpClientOddsTransport()
            )
            return OddsClient(
                profile,
                credential_provider=credentials,
                transport_factory=lambda: GuardedOddsTransport(self._guard, delegate),
                clock=clock,
                maximum_attempts=1,
            )

        return CurrentOddsTransientService(
            credential_provider=credentials,
            client_factory=client,
            rights_profile=self._odds_profile,
            quota=self._quota,
            require_known_quota=True,
            maximum_attempts=1,
            clock=clock,
        )

    def score(self, clock: Callable[[], datetime]) -> CurrentScorePriorService:
        delegate: OpenFootballTransport
        if self._owned:
            config = OpenFootballProviderConfig.model_validate_json(
                self._inputs["score-config.json"]
            )
            delegate = OwnedScoreTransport(config, self._inputs)
        else:
            from dmf_pulse.ingestion.openfootball.config import load_provider_config

            config = load_provider_config()
            delegate = HttpClientOpenFootballTransport()
        service = _ClosingScoreService(
            provider_config=config,
            rights_profiles=load_rights_profiles(),
            transport=GuardedScoreTransport(self._guard, delegate),
            clock=clock,
            provider_config_identity="a" * 64 if self._owned else None,
            rights_config_identity="b" * 64 if self._owned else None,
        )
        service.acquisition_guard = self._guard
        return service
