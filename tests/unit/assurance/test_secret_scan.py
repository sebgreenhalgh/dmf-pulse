"""Fake-secret detection and narrow allowlist tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dmf_pulse.assurance import secret_scan as secret_scan_module
from dmf_pulse.assurance.secret_scan import (
    SecretScanConfigurationError,
    load_allowlist,
    scan_repository,
    scan_text,
    scan_value,
)


def _fake_token() -> str:
    return "ghp_" + "FakeCredentialValue987654321"


@pytest.mark.unit
def test_fake_secrets_in_strings_urls_exceptions_and_mappings_are_detected() -> None:
    fixture_value = _fake_token()
    private_marker = "-----BEGIN " + "PRIVATE KEY-----"
    values = {
        "mapping": {"pass" + "word": fixture_value},
        "string": "authorization=" + fixture_value,
        "url": "https://example.invalid/path?api_key=" + fixture_value,
        "exception": RuntimeError("provider failed token=" + fixture_value),
        "private": private_marker,
    }
    findings = scan_value(
        {
            "mapping": values["mapping"],
            "strings": [
                values["string"],
                values["url"],
                str(values["exception"]),
                values["private"],
            ],
        }
    )
    rules = {finding.rule_id for finding in findings}
    assert {
        "SENSITIVE_MAPPING_VALUE",
        "KNOWN_TOKEN",
        "SENSITIVE_QUERY_VALUE",
        "PRIVATE_KEY",
    } <= rules
    assert fixture_value not in repr([finding.as_dict() for finding in findings])


@pytest.mark.unit
def test_odd005_canaries_are_detected_without_embedding_them_in_findings() -> None:
    fake_canary = "ODD005_FAKE_API_" + "KEY_DO_NOT_LOG_91d3a5"
    raw_body = "ODD005_RAW_BODY_" + "CANARY_7c4f91"
    findings = scan_text(f"{fake_canary}\n{raw_body}", path="unexpected.txt")
    assert {finding.rule_id for finding in findings} == {
        "ODD005_FAKE_CREDENTIAL",
        "ODD005_RAW_BODY_CANARY",
    }
    serialized = repr([finding.as_dict() for finding in findings])
    assert fake_canary not in serialized
    assert raw_body not in serialized


@pytest.mark.unit
def test_safe_reference_and_placeholder_are_not_findings() -> None:
    assert scan_value({"database_dsn_ref": "systemd/database-dsn"}) == []
    assert scan_text("api_key=placeholder") == []


@pytest.mark.unit
def test_python_session_syntax_and_explicit_placeholders_are_not_credentials() -> None:
    text = "\n".join(
        (
            "def commit_session(session: Session) -> None:",
            "session = factory()",
            "value = lambda session: operation(session)",
            "export PGPASSWORD=changeme",
        )
    )
    assert scan_text(text, path="example.py") == []

    patch = "\n".join(f"+{line}" for line in text.splitlines())
    assert scan_text(patch, path="04_FULL_DIFF.patch") == []

    code_references = "\n".join(
        (
            "self._credential = credential",
            "request(credential=credential)",
            "render_as_string(hide_password=False)",
        )
    )
    assert scan_text(code_references, path="example.py") == []

    fake_password = "Fake" + "CredentialValue987654321"
    assignment = "+" + "".join(("pass", "word")) + f' = "{fake_password}"'
    findings = scan_text(assignment, path="04_FULL_DIFF.patch")
    assert {finding.rule_id for finding in findings} == {"CREDENTIAL_ASSIGNMENT"}


@pytest.mark.unit
def test_exact_fingerprint_allowlist_and_malformed_wildcard(tmp_path: Path) -> None:
    fixture_value = _fake_token()
    source = tmp_path / "safe_fixture.txt"
    source.write_text("token=" + fixture_value, encoding="utf-8")
    initial = scan_repository(tmp_path)
    assert len(initial) >= 1
    finding = next(item for item in initial if item.rule_id == "KNOWN_TOKEN")
    allowlist = tmp_path / ".secret-scan-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": [
                    {
                        "path": finding.path,
                        "rule_id": finding.rule_id,
                        "fingerprint": finding.fingerprint,
                        "rationale": "constructed non-secret unit fixture",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    remaining = scan_repository(tmp_path)
    assert all(item.rule_id != "KNOWN_TOKEN" for item in remaining)

    malformed = json.loads(allowlist.read_text(encoding="utf-8"))
    malformed["entries"][0]["path"] = "*.txt"
    allowlist.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(SecretScanConfigurationError, match="exact relative"):
        load_allowlist(allowlist)


@pytest.mark.unit
def test_jwt_dsn_high_entropy_and_assignment_rules() -> None:
    jwt = "eyJ" + "A" * 20 + "." + "B" * 12 + "." + "C" * 12
    dsn = "scheme://service:" + "credential987" + "@host.invalid/path"
    opaque = "AbCdEfGhIjKlMnOp" + "QrStUvWxYz012345+/="
    assignment = "client_" + "secret=" + "constructed-value-12345"
    aws_identifier = "AKIA" + "IOSFODNN7EXAMPLE"
    rules = {
        finding.rule_id
        for finding in scan_text("\n".join((jwt, dsn, opaque, assignment, aws_identifier)))
    }
    assert {
        "JWT",
        "AWS_ACCESS_KEY",
        "CREDENTIAL_URL",
        "HIGH_ENTROPY_TOKEN",
        "CREDENTIAL_ASSIGNMENT",
    } <= rules


@pytest.mark.unit
@pytest.mark.parametrize("key_kind", ["", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED ", "DSA "])
def test_private_key_header_variants_are_detected(key_kind: str) -> None:
    marker = "-----BEGIN " + key_kind + "PRIVATE KEY-----"
    assert {finding.rule_id for finding in scan_text(marker)} == {"PRIVATE_KEY"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, message",
    [
        ("not-json", "valid UTF-8 JSON"),
        ('{"version": "2.0", "entries": []}', "version"),
        ('{"version": "1.0", "entries": {}}', "entries"),
        ('{"version": "1.0", "entries": [{}]}', "four exact"),
        (
            '{"version":"1.0","entries":[{"path":"x","rule_id":"R","fingerprint":"bad","rationale":"why"}]}',
            "fingerprints",
        ),
    ],
)
def test_allowlist_malformed_shapes_fail(tmp_path: Path, value: str, message: str) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(SecretScanConfigurationError, match=message):
        load_allowlist(path)


@pytest.mark.unit
def test_repository_fails_closed_for_large_binary_and_skips_operational_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dmf_pulse.assurance.secret_scan.MAX_SCANNED_FILE_BYTES", 1)
    (tmp_path / "large.txt").write_text("safe", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"\xff\xfe")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/secret.txt").write_text("token=" + _fake_token(), encoding="utf-8")
    findings = scan_repository(tmp_path)
    assert {finding.rule_id for finding in findings} == {"SCAN_COVERAGE"}
    assert {finding.path for finding in findings} == {"binary.dat", "large.txt"}


@pytest.mark.unit
def test_exact_hashed_zoneinfo_binary_is_the_only_binary_exception(
    repository_root: Path, tmp_path: Path
) -> None:
    relative = Path("src/dmf_pulse/_data/zoneinfo/Europe/London")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    shutil.copy2(repository_root / relative, target)
    assert scan_repository(tmp_path) == []
    target.write_bytes(target.read_bytes() + b"tamper")
    assert {finding.rule_id for finding in scan_repository(tmp_path)} == {"BINARY_HASH_MISMATCH"}


@pytest.mark.unit
def test_repository_scan_fails_closed_for_symbolic_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = tmp_path / "linked.txt"
    link.write_text("safe\n", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda candidate: candidate == link or original(candidate)
    )
    findings = scan_repository(tmp_path)
    assert {(finding.path, finding.rule_id) for finding in findings} == {
        ("linked.txt", "SCAN_COVERAGE")
    }


@pytest.mark.unit
def test_odd005_canary_allowlist_is_exact_path_and_fingerprint(
    repository_root: Path, tmp_path: Path
) -> None:
    shutil.copy2(repository_root / ".secret-scan-allowlist.json", tmp_path)
    for name in ("raw_forbidden_canary.json", "security_fake_credential.txt"):
        source = repository_root / "fixtures/odds/ODD-005" / name
        approved = tmp_path / "fixtures/odds/ODD-005" / name
        approved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, approved)
    assert scan_repository(tmp_path) == []

    unexpected = tmp_path / "copied_canary.txt"
    shutil.copy2(
        repository_root / "fixtures/odds/ODD-005/security_fake_credential.txt",
        unexpected,
    )
    findings = scan_repository(tmp_path)
    assert {(item.path, item.rule_id) for item in findings} == {
        ("copied_canary.txt", "ODD005_FAKE_CREDENTIAL")
    }


@pytest.mark.unit
def test_scanner_covers_safe_placeholders_refs_scalars_and_excluded_state(
    tmp_path: Path,
) -> None:
    assert secret_scan_module._entropy("") == 0.0
    assert secret_scan_module._looks_high_risk_opaque("AbCdEfGhIjKlMnOpQrStUvWxYz012345") is False
    assert scan_text("https://example.invalid/?api_key=placeholder") == []
    assert scan_text("password=placeholder") == []
    assert scan_value({"api_key_ref": "env:SAFE_REFERENCE"}) == []
    assert scan_value(1) == []

    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "fingerprint": "a" * 64,
                        "path": "safe.txt",
                        "rationale": "",
                        "rule_id": "SAFE",
                    }
                ],
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SecretScanConfigurationError, match="non-empty"):
        load_allowlist(allowlist)

    (tmp_path / ".coverage").write_text("token=" + _fake_token(), encoding="utf-8")
    allowlist.unlink()
    assert scan_repository(tmp_path) == []
