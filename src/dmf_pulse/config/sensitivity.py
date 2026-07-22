"""Shared conservative credential-shape detection without secret resolution."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
KNOWN_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"ghp_[A-Za-z0-9_-]{8,}|"
    r"github_pat_[A-Za-z0-9_-]{8,}|"
    r"xox[baprs]-[A-Za-z0-9_-]{8,}"
    r")"
)
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
AWS_ACCESS_KEY_PATTERN = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._~+/-]{8,}|"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|authorization|credential)"
    r"\s*[=:]\s*\S+)"
)
SENSITIVE_QUERY_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "secret",
    "token",
}


def looks_sensitive_string(value: str) -> bool:
    """Return whether a string resembles a credential-bearing value."""

    if any(
        pattern.search(value)
        for pattern in (
            PRIVATE_KEY_PATTERN,
            KNOWN_TOKEN_PATTERN,
            JWT_PATTERN,
            AWS_ACCESS_KEY_PATTERN,
            SECRET_VALUE_PATTERN,
        )
    ):
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return True
    if parsed.scheme and (parsed.username is not None or parsed.password is not None):
        return True
    if parsed.query:
        query_names = {
            name.casefold() for name, _ in parse_qsl(parsed.query, keep_blank_values=True)
        }
        if query_names & SENSITIVE_QUERY_NAMES:
            return True
    return False
