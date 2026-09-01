from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.private_v1.artifacts import load_execution_input
from dmf_pulse.private_v1.errors import PrivateV1Error


def test_duplicate_json_key_fails_before_private_model_validation(tmp_path: Path) -> None:
    path = tmp_path / "private.json"
    path.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")

    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(path)

    assert caught.value.code == "DUPLICATE_JSON_KEY"
    assert str(path) not in str(caught.value)


def test_nonfinite_json_and_oversized_input_fail_closed(tmp_path: Path) -> None:
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(nonfinite)
    assert caught.value.code == "MALFORMED_JSON"

    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(PrivateV1Error) as caught:
        load_execution_input(oversized)
    assert caught.value.code == "PAYLOAD_TOO_LARGE"
