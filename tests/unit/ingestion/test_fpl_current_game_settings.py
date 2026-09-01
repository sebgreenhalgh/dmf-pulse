"""PRIVATE-V1-ONE-COMMAND-001D game-settings adapter regressions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplDirectInputRequest,
    CurrentFplInputRequest,
    CurrentFplInputService,
    _canonical_game_setting,
)

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 18, 12, tzinfo=UTC)
RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0.0"), "0"),
        (Decimal("-0.000"), "0"),
        (Decimal("1.2300"), "1.23"),
        (Decimal("42"), "42"),
        (
            Decimal("1234567890.123456789012345678901234567890"),
            "1234567890.12345678901234567890123456789",
        ),
        (None, None),
        (False, False),
        (7, 7),
        ("1.2300", "1.2300"),
    ],
)
def test_canonical_game_setting_preserves_exact_supported_scalars(
    value: object, expected: object
) -> None:
    projected = _canonical_game_setting(value)

    assert projected == expected
    assert type(projected) is type(expected)


def test_canonical_game_setting_recurses_through_objects_and_arrays() -> None:
    projected = _canonical_game_setting(
        {
            "direct": Decimal("1.2500"),
            "nested": {"fraction": Decimal("0.125000")},
            "values": [Decimal("2.500"), {"integer": Decimal("3.0")}],
        }
    )

    assert projected == {
        "direct": "1.25",
        "nested": {"fraction": "0.125"},
        "values": ["2.5", {"integer": "3"}],
    }
    assert json.dumps(projected, allow_nan=False, sort_keys=True)


@pytest.mark.parametrize(
    "value",
    [object(), (Decimal("1.25"),), Decimal("NaN"), Decimal("Infinity")],
)
def test_canonical_game_setting_rejects_values_outside_strict_json_contract(
    value: object,
) -> None:
    with pytest.raises(IngestionError) as raised:
        _canonical_game_setting(value)

    assert raised.value.code == "INTERNAL_INVARIANT"
    assert raised.value.message == "FPL game settings are invalid"


def test_canonical_game_setting_rejects_non_string_object_keys() -> None:
    with pytest.raises(IngestionError) as raised:
        _canonical_game_setting({1: Decimal("1.25")})

    assert raised.value.code == "INTERNAL_INVARIANT"
    assert raised.value.message == "FPL game settings are invalid"


def test_equivalent_decimal_forms_and_object_orders_have_stable_hashes() -> None:
    left = _canonical_game_setting({"z": Decimal("1.2300"), "a": {"value": Decimal("0.500")}})
    right = _canonical_game_setting({"a": {"value": Decimal("0.5")}, "z": Decimal("1.23")})

    assert left == {"z": "1.23", "a": {"value": "0.5"}}
    assert right == {"a": {"value": "0.5"}, "z": "1.23"}
    assert canonical_sha256(left) == canonical_sha256(right)


def _fixture(repository_root: Path, name: str) -> bytes:
    return (repository_root / "fixtures/fpl/FPL-004/happy_path" / name).read_bytes()


def _bootstrap_with_decimal_settings(repository_root: Path) -> bytes:
    bootstrap = json.loads(_fixture(repository_root, "bootstrap.json"))
    bootstrap["game_settings"] = {
        "nested": {"fraction": "__FRACTION__"},
        "values": ["__ZERO__", {"integer": "__INTEGER__"}],
    }
    rendered = json.dumps(bootstrap, separators=(",", ":"))
    return (
        rendered.replace('"__FRACTION__"', "1.2300")
        .replace('"__ZERO__"', "0.000")
        .replace('"__INTEGER__"', "2.0")
        .encode()
    )


def _manual_request(bootstrap_path: Path, fixtures_path: Path) -> CurrentFplInputRequest:
    return CurrentFplInputRequest(
        bootstrap_path=bootstrap_path,
        fixtures_path=fixtures_path,
        competition_key="PL",
        season_code="2026/27",
        target_gameweek=1,
        captured_at=CAPTURED,
        information_cutoff=CUTOFF,
        rights_profile_id="fpl_official_private_manual_v1",
    )


def _direct_request() -> CurrentFplDirectInputRequest:
    return CurrentFplDirectInputRequest(
        competition_key="PL",
        season_code="2026/27",
        target_gameweek=1,
        captured_at=CAPTURED,
        information_cutoff=CUTOFF,
    )


def test_manual_and_direct_compilation_share_exact_decimal_semantics(
    repository_root: Path, tmp_path: Path
) -> None:
    bootstrap_body = _bootstrap_with_decimal_settings(repository_root)
    fixtures_body = _fixture(repository_root, "fixtures.json")
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_bytes(bootstrap_body)
    fixtures_path.write_bytes(fixtures_body)
    service = CurrentFplInputService(clock=lambda: RECEIVED)

    manual = service.compile(_manual_request(bootstrap_path, fixtures_path))
    direct = service.compile_direct(
        _direct_request(), bootstrap_body=bootstrap_body, fixtures_body=fixtures_body
    )

    expected = '{"nested":{"fraction":"1.23"},"values":["0",{"integer":"2"}]}'
    assert manual.game_settings.canonical_json == expected
    assert direct.game_settings.canonical_json == expected
    assert manual.game_settings.semantic_sha256 == direct.game_settings.semantic_sha256


def test_integer_only_frozen_game_settings_hash_is_unchanged(
    repository_root: Path, tmp_path: Path
) -> None:
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_bytes(_fixture(repository_root, "bootstrap.json"))
    fixtures_path.write_bytes(_fixture(repository_root, "fixtures.json"))

    bundle = CurrentFplInputService(clock=lambda: RECEIVED).compile(
        _manual_request(bootstrap_path, fixtures_path)
    )

    assert bundle.game_settings.canonical_json == (
        '{"league_join_private_max":30,"squad_squadplay":11}'
    )
    assert bundle.game_settings.semantic_sha256 == (
        "cb1c285a7b527f6cc1cf6ba7fe69def9e6cc6c85eb5a6bca59c9ec84091dfc69"
    )
