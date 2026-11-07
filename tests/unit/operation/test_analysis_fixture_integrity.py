"""Owned fixture corruption and cross-consumer mutation cannot become test inputs."""

import pytest

from tests.unit.operation.analysis_test_support import FIXTURE, load_owned_snapshot


def test_fixture_bytes_are_authenticated_before_parsing(tmp_path):
    changed = tmp_path / "changed.json"
    changed.write_bytes(FIXTURE.read_bytes() + b" ")
    with pytest.raises(ValueError, match="BYTES_CHANGED"):
        load_owned_snapshot(changed)


def test_consumers_receive_independent_nested_models():
    first = load_owned_snapshot()
    first.presentation.gameweeks[0].summaries.clear()
    second = load_owned_snapshot()
    assert len(second.presentation.gameweeks[0].summaries) == 120
    assert first is not second
