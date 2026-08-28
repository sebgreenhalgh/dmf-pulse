"""Read-only DAT-003 canonical fixture/provider/operator resolution tests."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import pytest

from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityRepository,
    CurrentMarketConstraintError,
    current_market_identity_view_sha256,
)

from .current_market_test_support import build_market_context

PROVIDER_ID = UUID("00000000-0000-0000-0000-000000029001")


class _MappingsResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> list[dict[str, object]]:
        return self.rows


class _ReadOnlySession:
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self.responses = list(responses)
        self.statements: list[object] = []

    def execute(self, statement):
        assert statement.is_select is True
        self.statements.append(statement)
        return _MappingsResult(self.responses.pop(0))

    def add(self, _value: object) -> None:
        raise AssertionError("current canonical resolution attempted a write")

    def flush(self) -> None:
        raise AssertionError("current canonical resolution attempted a write")

    def commit(self) -> None:
        raise AssertionError("current canonical resolution attempted a write")


def _responses(context, *, mismatched_event: bool = False):
    rows: list[list[dict[str, object]]] = [
        [
            {
                "provider_id": PROVIDER_ID,
                "provider_key": "the_odds_api",
                "rights_profile_key": "the_odds_api_private_analytics_v1",
            }
        ]
    ]
    canonical_by_fixture: dict[int, UUID] = {}
    for index, mapping in enumerate(context.identity_map.fixture_mappings, start=1):
        canonical_id = UUID(f"00000000-0000-0000-0000-{2910 + index:012d}")
        canonical_by_fixture[mapping.official_fpl_fixture_id] = canonical_id
        rows.append(
            [
                {
                    "canonical_entity_id": canonical_id,
                    "external_identifier_id": UUID(f"00000000-0000-0000-0000-{2920 + index:012d}"),
                }
            ]
        )
        odds_canonical = (
            UUID("00000000-0000-0000-0000-000000029999")
            if mismatched_event and index == 1
            else canonical_id
        )
        rows.append(
            [
                {
                    "canonical_entity_id": odds_canonical,
                    "external_identifier_id": UUID(f"00000000-0000-0000-0000-{2930 + index:012d}"),
                }
            ]
        )
    target_ids = {item.provider_event_id for item in context.identity_map.fixture_mappings}
    keys = sorted(
        {
            bookmaker.bookmaker_key
            for event in context.odds_input.events
            if event.provider_event_id in target_ids
            for bookmaker in event.bookmakers
        }
    )
    for index, key in enumerate(keys, start=1):
        rows.append(
            [
                {
                    "canonical_entity_id": UUID(f"00000000-0000-0000-0000-{2940 + index:012d}"),
                    "external_identifier_id": UUID(f"00000000-0000-0000-0000-{2950 + index:012d}"),
                    "operator_key": f"CANONICAL_{key.upper()}",
                }
            ]
        )
    return rows, canonical_by_fixture


def test_repository_uses_select_only_and_resolves_both_fixture_namespaces(
    repository_root, tmp_path
) -> None:
    context, _test_view, _request, _result = build_market_context(repository_root, tmp_path)
    responses, canonical_by_fixture = _responses(context)
    session = _ReadOnlySession(responses)

    view = CurrentMarketCanonicalIdentityRepository(session).resolve(
        context.bundle,
        resolved_at=context.bundle.decision_information_at,
    )

    assert view.authority == "DAT_003_READ_ONLY"
    assert view.database_read_performed is True
    assert view.database_write_performed is False
    assert view.provider_id == PROVIDER_ID
    assert view.semantic_sha256 == current_market_identity_view_sha256(view)
    assert {
        item.official_fpl_fixture_id: item.canonical_fixture_id for item in view.fixtures
    } == canonical_by_fixture
    assert all(
        item.official_fpl_external_mapping_id != item.odds_event_external_mapping_id
        for item in view.fixtures
    )
    assert len(session.statements) == 1 + (2 * len(view.fixtures)) + len(view.operators)
    assert not session.responses


def test_repository_rejects_disagreeing_fpl_and_odds_canonical_fixture(
    repository_root, tmp_path
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    responses, _canonical = _responses(context, mismatched_event=True)
    session = _ReadOnlySession(responses)

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=context.bundle.decision_information_at,
        )

    surfaces = (
        str(caught.value),
        repr(caught.value),
        json.dumps(caught.value.as_error_object(), sort_keys=True),
    )
    assert caught.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"
    assert all(
        mapping.provider_event_id not in surface
        for mapping in context.identity_map.fixture_mappings
        for surface in surfaces
    )


@pytest.mark.parametrize(
    "resolved_at",
    [
        datetime(2026, 8, 24, 10, 0),
        datetime.fromisoformat("2026-08-26T12:00:01+00:00"),
    ],
)
def test_repository_rejects_naive_or_post_cutoff_resolution_safely(
    repository_root, tmp_path, resolved_at: datetime
) -> None:
    context, _view, _request, _result = build_market_context(repository_root, tmp_path)
    session = _ReadOnlySession([])

    with pytest.raises(CurrentMarketConstraintError) as caught:
        CurrentMarketCanonicalIdentityRepository(session).resolve(
            context.bundle,
            resolved_at=resolved_at,
        )

    assert caught.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"
    assert not session.statements
