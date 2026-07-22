"""Deterministic property tests for independent merge/hash/redaction invariants."""

from __future__ import annotations

from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.config import deep_merge, redact_sensitive

json_scalars = st.none() | st.booleans() | st.integers() | st.text(max_size=20)
json_values = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(min_size=1, max_size=12), children, max_size=4)
    ),
    max_leaves=12,
)
mapping_strategy = st.dictionaries(st.text(min_size=1, max_size=12), json_values, max_size=5)


def _oracle_merge(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    result = deepcopy(base)
    for key, value in overlay.items():
        prior = result.get(key)
        if isinstance(prior, dict) and isinstance(value, dict):
            result[key] = _oracle_merge(prior, value)
        else:
            result[key] = deepcopy(value)
    return result


@pytest.mark.property
@given(base=mapping_strategy, overlay=mapping_strategy)
def test_merge_matches_independent_oracle_and_is_repeatable(
    base: dict[str, object], overlay: dict[str, object]
) -> None:
    base_before = deepcopy(base)
    overlay_before = deepcopy(overlay)
    expected = _oracle_merge(base, overlay)
    assert deep_merge(base, overlay) == expected
    assert deep_merge(base, overlay) == expected
    assert base == base_before
    assert overlay == overlay_before


@pytest.mark.property
@given(value=json_values)
def test_canonical_hash_is_stable_under_round_trip_and_mapping_order(value: object) -> None:
    assert canonical_sha256(value) == canonical_sha256(deepcopy(value))
    if isinstance(value, dict):
        assert canonical_sha256(value) == canonical_sha256(dict(reversed(list(value.items()))))


@pytest.mark.property
@given(value=json_values)
def test_redaction_is_idempotent(value: object) -> None:
    once = redact_sensitive(value)
    assert redact_sensitive(once) == once


@pytest.mark.property
@given(prefix=st.text(alphabet=st.characters(whitelist_categories=("L", "N")), max_size=20))
def test_redaction_removes_constructed_mapping_and_url_secrets(prefix: str) -> None:
    fake = "fake-" + prefix + "-credential-987654321"
    value = {
        "password": fake,
        "message": "failed with token=" + fake,
        "url": "https://example.invalid/path?api_key=" + fake,
    }
    rendered = repr(redact_sensitive(value))
    assert fake not in rendered
