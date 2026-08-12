"""MIN-007R5F4 unit guard for complete-only exact lookup."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from dmf_pulse.availability.persistence import get_prediction_run
from dmf_pulse.data_model.errors import DataModelError


class _EmptyMappings:
    def one_or_none(self) -> None:
        return None


class _EmptyResult:
    def mappings(self) -> _EmptyMappings:
        return _EmptyMappings()


class _RecordingSession:
    statement: Any

    def execute(self, statement: Any) -> _EmptyResult:
        self.statement = statement
        return _EmptyResult()


def test_exact_prediction_lookup_requires_complete_core_state() -> None:
    session = _RecordingSession()

    with pytest.raises(DataModelError, match="prediction signature was not found") as error:
        get_prediction_run(session, "a" * 64)  # type: ignore[arg-type]

    assert error.value.code == "PREDICTION_NOT_FOUND"
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert "football.prediction_run.core_state = %(core_state_1)s" in str(compiled)
    assert compiled.params["core_state_1"] == "COMPLETE"
