"""Deterministic first-party credential scanner with fingerprint-only allowlisting."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dmf_pulse.config.sensitivity import (
    AWS_ACCESS_KEY_PATTERN,
    JWT_PATTERN,
    KNOWN_TOKEN_PATTERN,
    PRIVATE_KEY_PATTERN,
    looks_sensitive_string,
)

MAX_SCANNED_FILE_BYTES = 5 * 1024 * 1024
EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "review_pack",
}
EXCLUDED_FILE_NAMES = {".coverage"}
EXPLICIT_BINARY_FILE_HASHES = {
    "src/dmf_pulse/_data/zoneinfo/Europe/London": (
        "676541f0b8ad457c744c093f807589adcad909e3fd03f901787d08786eedbd33"
    )
}
SENSITIVE_NAMES = (
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "session",
    "token",
)
DSN_CREDENTIAL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]{4,}@[^\s/]+")
NAME_PATTERN = "|".join(re.escape(name) for name in SENSITIVE_NAMES)
ASSIGNMENT_PATTERN = re.compile(
    rf"(?i)(?:['\"]?(?:{NAME_PATTERN})['\"]?)\s*[:=]\s*['\"]?([^\s,'\"}}]{{8,}})"
)
QUERY_PATTERN = re.compile(rf"(?i)(?:{NAME_PATTERN})=([^&\s'\"]{{6,}})")


@dataclass(frozen=True, slots=True, order=True)
class SecretFinding:
    """A leak signal that never contains the matched value."""

    path: str
    line: int
    rule_id: str
    fingerprint: str
    message: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "fingerprint": self.fingerprint,
            "line": self.line,
            "message": self.message,
            "path": self.path,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    path: str
    rule_id: str
    fingerprint: str
    rationale: str


class SecretScanConfigurationError(Exception):
    """The narrow allowlist itself is malformed or unsafe."""


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _looks_high_risk_opaque(value: str) -> bool:
    if len(value) < 32 or len(value) > 512 or re.fullmatch(r"[0-9a-fA-F]+", value):
        return False
    if not any(character in value for character in "+/="):
        return False
    character_classes = sum(
        bool(pattern.search(value))
        for pattern in (re.compile(r"[a-z]"), re.compile(r"[A-Z]"), re.compile(r"\d"))
    )
    return character_classes == 3 and _entropy(value) >= 4.2


def _finding(path: str, line: int, rule_id: str, value: str, message: str) -> SecretFinding:
    return SecretFinding(
        path=path,
        line=line,
        rule_id=rule_id,
        fingerprint=_fingerprint(value),
        message=message,
    )


def scan_text(text: str, *, path: str = "<memory>") -> list[SecretFinding]:
    """Scan arbitrary text, URLs, and exception messages for likely credentials."""

    findings: set[SecretFinding] = set()
    for line_number, line in enumerate(text.splitlines() or [text], start=1):
        for match in PRIVATE_KEY_PATTERN.finditer(line):
            findings.add(
                _finding(path, line_number, "PRIVATE_KEY", match.group(0), "private-key marker")
            )
        for match in KNOWN_TOKEN_PATTERN.finditer(line):
            findings.add(
                _finding(path, line_number, "KNOWN_TOKEN", match.group(0), "known token prefix")
            )
        for match in JWT_PATTERN.finditer(line):
            findings.add(_finding(path, line_number, "JWT", match.group(0), "JWT-like token"))
        for match in AWS_ACCESS_KEY_PATTERN.finditer(line):
            findings.add(
                _finding(
                    path,
                    line_number,
                    "AWS_ACCESS_KEY",
                    match.group(0),
                    "AWS access-key identifier",
                )
            )
        for match in DSN_CREDENTIAL_PATTERN.finditer(line):
            findings.add(
                _finding(
                    path,
                    line_number,
                    "CREDENTIAL_URL",
                    match.group(0),
                    "URL or DSN contains credentials",
                )
            )
        for match in QUERY_PATTERN.finditer(line):
            value = match.group(1).rstrip(")]}")
            if value.casefold() not in {"changeme", "example", "redacted", "placeholder"}:
                findings.add(
                    _finding(
                        path,
                        line_number,
                        "SENSITIVE_QUERY_VALUE",
                        value,
                        "sensitive URL query value",
                    )
                )
        for match in ASSIGNMENT_PATTERN.finditer(line):
            value = match.group(1).rstrip(")]}")
            python_syntax = path.casefold().endswith(".py") and (
                line.lstrip().startswith(("def ", "async def ", "class "))
                or "lambda " in line
                or ") ->" in line
                or "(" in value
            )
            if python_syntax:
                continue
            if value.casefold() not in {"changeme", "example", "redacted", "placeholder"}:
                findings.add(
                    _finding(
                        path,
                        line_number,
                        "CREDENTIAL_ASSIGNMENT",
                        value,
                        "sensitive key has a likely raw value",
                    )
                )
        if "://" not in line:
            for word in re.findall(r"[A-Za-z0-9+/=]{32,512}", line):
                if _looks_high_risk_opaque(word):
                    findings.add(
                        _finding(
                            path,
                            line_number,
                            "HIGH_ENTROPY_TOKEN",
                            word,
                            "high-entropy opaque token",
                        )
                    )
    return sorted(findings)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    return normalized in SENSITIVE_NAMES or any(
        normalized.endswith(f"_{name}") for name in SENSITIVE_NAMES
    )


def scan_value(value: object, *, path: str = "<value>") -> list[SecretFinding]:
    """Scan nested mappings/sequences as well as embedded strings."""

    findings: set[SecretFinding] = set()

    def walk(item: object, location: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, nested in item.items():
                key = str(raw_key)
                nested_location = f"{location}.{key}"
                if (
                    _is_sensitive_key(key)
                    and nested is not None
                    and nested != ""
                    and nested != "<redacted>"
                ):
                    is_safe_ref = key.casefold().endswith("_ref") and isinstance(nested, str)
                    if not is_safe_ref or looks_sensitive_string(nested):
                        findings.add(
                            _finding(
                                path,
                                0,
                                "SENSITIVE_MAPPING_VALUE",
                                str(nested),
                                f"raw value under sensitive mapping key at {nested_location}",
                            )
                        )
                walk(nested, nested_location)
        elif isinstance(item, (list, tuple)):
            for index, nested in enumerate(item):
                walk(nested, f"{location}[{index}]")
        elif isinstance(item, str):
            findings.update(scan_text(item, path=path))

    walk(value, "$")
    return sorted(findings)


def load_allowlist(path: Path) -> tuple[AllowlistEntry, ...]:
    """Load exact path/rule/fingerprint entries; wildcards and raw values are prohibited."""

    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecretScanConfigurationError("secret-scan allowlist is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or raw.get("version") != "1.0":
        raise SecretScanConfigurationError("secret-scan allowlist version must be 1.0")
    raw_entries = raw.get("entries")
    if not isinstance(raw_entries, list):
        raise SecretScanConfigurationError("secret-scan allowlist entries must be an array")
    entries = []
    for item in raw_entries:
        if not isinstance(item, dict) or set(item) != {
            "fingerprint",
            "path",
            "rationale",
            "rule_id",
        }:
            raise SecretScanConfigurationError(
                "each allowlist entry must use the four exact fields"
            )
        if not all(isinstance(item[key], str) and item[key] for key in item):
            raise SecretScanConfigurationError("allowlist entry values must be non-empty strings")
        if "*" in item["path"] or "?" in item["path"] or Path(item["path"]).is_absolute():
            raise SecretScanConfigurationError("allowlist paths must be exact relative paths")
        if re.fullmatch(r"[0-9a-f]{64}", item["fingerprint"]) is None:
            raise SecretScanConfigurationError("allowlist fingerprints must be lowercase SHA-256")
        entries.append(AllowlistEntry(**item))
    return tuple(entries)


def scan_repository(root: Path, *, allowlist_path: Path | None = None) -> list[SecretFinding]:
    """Scan bounded UTF-8 repository files and apply only exact fingerprint allowlisting."""

    selected_allowlist = allowlist_path or root / ".secret-scan-allowlist.json"
    allowlist = load_allowlist(selected_allowlist)
    allowed = {(item.path, item.rule_id, item.fingerprint) for item in allowlist}
    findings = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if any(part in EXCLUDED_PARTS for part in candidate.parts):
            continue
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            findings.append(
                _finding(
                    relative,
                    0,
                    "SCAN_COVERAGE",
                    relative,
                    "symbolic-link content was not scanned",
                )
            )
            continue
        if not candidate.is_file():
            continue
        if candidate.name in EXCLUDED_FILE_NAMES:
            continue
        if relative == selected_allowlist.relative_to(root).as_posix():
            continue
        expected_binary_hash = EXPLICIT_BINARY_FILE_HASHES.get(relative)
        if expected_binary_hash is not None:
            try:
                actual_binary_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError:
                actual_binary_hash = ""
            if actual_binary_hash != expected_binary_hash:
                findings.append(
                    _finding(
                        relative,
                        0,
                        "BINARY_HASH_MISMATCH",
                        relative,
                        "explicit binary asset hash does not match its reviewed value",
                    )
                )
            continue
        try:
            if candidate.stat().st_size > MAX_SCANNED_FILE_BYTES:
                findings.append(
                    _finding(
                        relative,
                        0,
                        "SCAN_COVERAGE",
                        relative,
                        "file exceeds the bounded secret-scan size",
                    )
                )
                continue
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(
                _finding(
                    relative,
                    0,
                    "SCAN_COVERAGE",
                    relative,
                    "file could not be scanned as UTF-8 text",
                )
            )
            continue
        for finding in scan_text(text, path=relative):
            if (finding.path, finding.rule_id, finding.fingerprint) not in allowed:
                findings.append(finding)
    return sorted(set(findings))
