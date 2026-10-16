"""Fixed synthetic input captured from accepted code, portable across test hosts."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from dmf_pulse.evaluation.team_strength_prospective import PublicTeamStrengthForecastV1


@lru_cache(maxsize=1)
def captured_synthetic_forecast() -> PublicTeamStrengthForecastV1:
    root = Path(__file__).resolve().parents[2] / "fixtures/evaluation/a02_legacy_forecast_input"
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert [row["path"] for row in manifest["parts"]] == [
        f"part-{index:03}.json.part" for index in range(5)
    ]
    parts = []
    for row in manifest["parts"]:
        data = (root / row["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["byte_sha256"]
        parts.append(data)
    data = b"".join(parts)
    assert (
        hashlib.sha256(data).hexdigest()
        == "1c2c0df07078456822c6cf40cb52fd6e97e551c0cdd6dd030851f72e0c5ffb0d"
    )
    forecast = PublicTeamStrengthForecastV1.model_validate_json(data)
    assert forecast.dataset_mode == "RECONSTRUCTED"
    return forecast
