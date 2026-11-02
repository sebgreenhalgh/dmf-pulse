"""Read newly supplied JWT time claims locally; never authenticate their issuer."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import SecretStr

from dmf_pulse.credentials.service import CredentialError, _utc, _validate


@dataclass(frozen=True, slots=True)
class _Expiry:
    code: str | None = None
    expires_at: datetime | None = None


def validate_fpl_jwt_lifetime_bounds(
    minimum_remaining_seconds: int, maximum_remaining_seconds: int | None = None
) -> None:
    """Validate caller policy, without inventing a supplier token lifetime."""
    if (
        type(minimum_remaining_seconds) is not int
        or minimum_remaining_seconds < 1
        or (
            maximum_remaining_seconds is not None
            and (
                type(maximum_remaining_seconds) is not int
                or maximum_remaining_seconds < minimum_remaining_seconds
            )
        )
    ):
        raise CredentialError("CREDENTIAL_POLICY_INVALID")


def _segment(value: str) -> bytes:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None or len(value) % 4 == 1:
        raise ValueError("invalid compact segment")
    result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(result).decode("ascii").rstrip("=") != value:
        raise ValueError("noncanonical compact segment")
    return result


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate claim")
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise ValueError("nonfinite claim")


def _object(value: bytes) -> dict[str, object]:
    decoded: object = json.loads(
        value.decode("utf-8", errors="strict"),
        object_pairs_hook=_unique,
        parse_constant=_nonfinite,
    )
    if not isinstance(decoded, dict):
        raise ValueError("object required")
    return cast(dict[str, object], decoded)


def _date(value: object) -> datetime:
    # The accepted application input subset uses integer NumericDate seconds;
    # floats, booleans, strings and millisecond conversions are never inferred.
    if type(value) is not int:
        raise ValueError("integer NumericDate required")
    return datetime.fromtimestamp(value, UTC)


def _expiry_scope(
    secret: SecretStr,
    now: datetime,
    minimum_remaining_seconds: int,
    maximum_remaining_seconds: int | None,
) -> _Expiry:
    """Unwind decoded claims and decoder exception graphs before public failure."""
    try:
        validate_fpl_jwt_lifetime_bounds(minimum_remaining_seconds, maximum_remaining_seconds)
        now = _utc(now)
        value = secret.get_secret_value()
        _validate(value, "fpl")
        parts = value.split(".")
        if len(parts) != 3:
            return _Expiry(code="CREDENTIAL_JWT_INVALID")
        header, claims = _object(_segment(parts[0])), _object(_segment(parts[1]))
        _segment(parts[2])  # Syntax only: no signature, key, issuer or authentication check.
        algorithm = header.get("alg")
        if not isinstance(algorithm, str) or not algorithm or algorithm.casefold() == "none":
            return _Expiry(code="CREDENTIAL_JWT_INVALID")
        expires_at = _date(claims.get("exp"))
        for name in ("iat", "nbf"):
            if name in claims:
                claimed_at = _date(claims[name])
                if claimed_at >= expires_at:
                    return _Expiry(code="CREDENTIAL_JWT_INVALID")
                if claimed_at > now:
                    return _Expiry(code="CREDENTIAL_NOT_YET_VALID")
        if expires_at <= now:
            return _Expiry(code="CREDENTIAL_EXPIRED")
        remaining = (expires_at - now).total_seconds()
        if remaining < minimum_remaining_seconds:
            return _Expiry(code="CREDENTIAL_LIFETIME_INSUFFICIENT")
        if maximum_remaining_seconds is not None and remaining > maximum_remaining_seconds:
            return _Expiry(code="CREDENTIAL_LIFETIME_EXCESSIVE")
        return _Expiry(expires_at=expires_at)
    except CredentialError as error:
        return _Expiry(code=error.code)
    except Exception:
        return _Expiry(code="CREDENTIAL_JWT_INVALID")


def fpl_jwt_expiry(
    secret: SecretStr,
    *,
    now: datetime,
    minimum_remaining_seconds: int,
    maximum_remaining_seconds: int | None = None,
) -> datetime:
    """Return unverified ``exp`` only from this new input, never a stored token."""
    result = _expiry_scope(secret, now, minimum_remaining_seconds, maximum_remaining_seconds)
    del secret, now
    if result.code is not None:
        raise CredentialError(result.code) from None
    if result.expires_at is None:
        raise CredentialError("CREDENTIAL_JWT_INVALID") from None
    return result.expires_at
