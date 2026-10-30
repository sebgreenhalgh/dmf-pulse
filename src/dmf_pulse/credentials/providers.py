"""Lazy acquisition providers; source authorization belongs to accepted callers."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import SecretStr

from dmf_pulse.credentials.service import CredentialError, CredentialService, ResolvedCredential
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplCredential, DirectFplCredentialProvider

ODDS_SOURCE_VARIABLE = "DMF_ODDS_CREDENTIAL_SOURCE"
FPL_SOURCE_VARIABLE = "DMF_FPL_CREDENTIAL_SOURCE"
CredentialSource = Literal["AUTO", "ENVIRONMENT", "SYSTEMD"]


class AutomaticOddsCredentialProvider:
    """AUTO uses Windows vault or existing Linux systemd, with no env fallback.

    Legacy session environment use is an explicit nonsecret selection:
    DMF_ODDS_CREDENTIAL_SOURCE=environment. No constructor reads that selector,
    key, vault or directory. Resolution happens only inside get_credential().
    """

    def __init__(
        self,
        *,
        service_factory: Callable[[], CredentialService] | None = None,
        platform: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._service_factory = service_factory or CredentialService
        self._platform = platform
        self._environment = environment

    def __repr__(self) -> str:
        return "AutomaticOddsCredentialProvider(<lazy-protected-source>)"

    def configuration_hint(self) -> bool | None:
        """Preserve Linux missing-directory refusal without reading any secret.

        A Windows vault or explicit environment selection stays unknown. This
        method never calls a backend, reads a key value, or probes a provider.
        """
        environment = os.environ if self._environment is None else self._environment
        selection = environment.get(ODDS_SOURCE_VARIABLE, "auto").casefold()
        platform = os.name if self._platform is None else self._platform
        if selection in {"auto", "systemd"} and not (platform == "nt" and selection == "auto"):
            return bool(environment.get("CREDENTIALS_DIRECTORY"))
        return None

    def get_credential(self) -> str:
        outcome = _odds_scope(self)
        del self
        if isinstance(outcome, CredentialError):
            raise IngestionError(outcome.code, outcome.message) from None
        return outcome.value.get_secret_value()


def _odds_scope(provider: AutomaticOddsCredentialProvider) -> ResolvedCredential | CredentialError:
    try:
        environment = os.environ if provider._environment is None else provider._environment
        selection = environment.get(ODDS_SOURCE_VARIABLE, "auto").casefold()
        if selection == "environment":
            from pydantic import SecretStr

            from dmf_pulse.ingestion.odds.credentials import EnvironmentOddsCredentialProvider

            value = EnvironmentOddsCredentialProvider(environment=environment).get_credential()
            return ResolvedCredential(SecretStr(value), None)
        if selection not in {"auto", "systemd"}:
            return CredentialError("CREDENTIAL_INVALID")
        platform = os.name if provider._platform is None else provider._platform
        if platform == "nt" and selection == "auto":
            return provider._service_factory().resolve("odds")
        from pydantic import SecretStr

        from dmf_pulse.ingestion.odds.credentials import RuntimeOddsCredentialProvider

        systemd_value = RuntimeOddsCredentialProvider(environment=environment).get_credential()
        if systemd_value is None:
            return CredentialError("CREDENTIAL_NOT_CONFIGURED")
        return ResolvedCredential(SecretStr(systemd_value), None)
    except CredentialError as exc:
        code = exc.code
    except IngestionError:
        code = "CREDENTIAL_NOT_CONFIGURED"
    except Exception:
        code = "CREDENTIAL_BACKEND_UNAVAILABLE"
    return CredentialError(code)


class AutomaticFplCredentialProvider(DirectFplCredentialProvider):
    """Independent short-lived token; never renews or extracts browser sessions."""

    def __init__(
        self,
        *,
        service_factory: Callable[[], CredentialService] | None = None,
        platform: str | None = None,
        environment: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._factory = service_factory or (lambda: CredentialService(clock=clock))
        self._platform = platform
        self._environment = environment
        self._clock = clock
        self._expires_at: datetime | None = None

    def __repr__(self) -> str:
        return "AutomaticFplCredentialProvider(<lazy-short-lived-source>)"

    def get(self) -> DirectFplCredential:
        outcome = _fpl_scope(self)
        if isinstance(outcome, CredentialError):
            code, message = outcome.code, outcome.message
            del self, outcome
            raise IngestionError(code, message) from None
        self._expires_at = outcome.expires_at
        return DirectFplCredential(
            source="OS_VAULT" if outcome.expires_at is not None else "ENVIRONMENT",
            bearer_token=SecretStr(outcome.value.get_secret_value()),
            expires_at=outcome.expires_at,
        )

    def check_expiry(self) -> None:
        if self._expires_at is not None:
            now = self._clock()
            if (
                now.tzinfo is None
                or now.utcoffset() is None
                or now.astimezone(UTC) >= self._expires_at
            ):
                raise IngestionError(
                    "CREDENTIAL_EXPIRED", "The FPL bearer token expired before transport."
                )


def _fpl_scope(provider: AutomaticFplCredentialProvider) -> ResolvedCredential | CredentialError:
    try:
        environment = os.environ if provider._environment is None else provider._environment
        selection = environment.get(FPL_SOURCE_VARIABLE, "auto").casefold()
        platform = os.name if provider._platform is None else provider._platform
        if selection == "auto" and platform == "nt":
            return provider._factory().resolve("fpl")
        if selection != "environment":
            return CredentialError("CREDENTIAL_NOT_CONFIGURED")
        from dmf_pulse.ingestion.fpl.direct import DirectFplCredentialProvider

        credential = DirectFplCredentialProvider(environ=environment).get()
        return ResolvedCredential(credential.bearer_token, None)
    except CredentialError as exc:
        code = exc.code
    except IngestionError:
        code = "CREDENTIAL_NOT_CONFIGURED"
    except Exception:
        code = "CREDENTIAL_BACKEND_UNAVAILABLE"
    return CredentialError(code)
