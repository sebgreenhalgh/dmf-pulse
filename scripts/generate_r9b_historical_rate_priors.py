"""Generate the compact R9B rate-prior resource from immutable local Git evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import SOURCE_HASHES, HistoricalRateResource

HISTORICAL_IMPLEMENTATION_SHA = "b4353dbdcebd31f2a807bee90ec04b3ee8b07389"
CENTRAL_POSTERIOR_SHA = "537b2ab3c19aba381e6020972cd037b3f62665309c423037049020f0d4f0239f"
_ARTIFACTS = {
    "CENTRAL_TEMPORARY": "GW1_CURRENT_PLAYER_POSTERIOR_CENTRAL.json",
    "LOW_SHRINKAGE": "GW1_CURRENT_PLAYER_POSTERIOR_LOW.json",
    "HIGH_SHRINKAGE": "GW1_CURRENT_PLAYER_POSTERIOR_HIGH.json",
}
_ROOT = Path(__file__).resolve().parents[1]
_OUTPUT = _ROOT / "src/dmf_pulse/fpl_points/resources/r9b_historical_rate_priors_v1.json"


def _artifact(name: str) -> dict[str, object]:
    path = f"evidence/tickets/GW1-PLY-003/{name}"
    result = subprocess.run(
        ["git", "show", f"{HISTORICAL_IMPLEMENTATION_SHA}:{path}"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("historical posterior artifact is not an object")
    return value


def _rates(value: dict[str, object]) -> list[dict[str, object]]:
    players = value.get("players")
    if not isinstance(players, list):
        raise ValueError("historical posterior players are invalid")
    rows: list[dict[str, object]] = []
    for player in players:
        if not isinstance(player, dict):
            raise ValueError("historical posterior player is invalid")
        row: dict[str, object] = {"source_official_fpl_player_id": player["source_player_id"]}
        for source, target in (
            ("goal_rate", "goal"),
            ("assist_rate", "assist"),
            ("yellow_rate", "yellow"),
            ("red_rate", "red"),
            ("save_rate", "save"),
        ):
            rate = player.get(source)
            if not isinstance(rate, dict):
                raise ValueError("historical posterior rate is invalid")
            row[f"{target}_mean_per90"] = rate["mean_per90"]
            row[f"{target}_variance_per90"] = rate["variance_per90"]
        rows.append(row)
    if [row["source_official_fpl_player_id"] for row in rows] != sorted(
        row["source_official_fpl_player_id"] for row in rows
    ):
        rows.sort(key=lambda row: int(row["source_official_fpl_player_id"]))
    if len({row["source_official_fpl_player_id"] for row in rows}) != len(rows):
        raise ValueError("historical posterior source IDs are duplicated")
    return rows


def main() -> None:
    worlds: list[dict[str, object]] = []
    for index, (world, name) in enumerate(_ARTIFACTS.items()):
        artifact = _artifact(name)
        artifact_sha = artifact.get("artifact_sha256")
        if not isinstance(artifact_sha, str):
            raise ValueError("historical posterior hash is invalid")
        if artifact_sha != SOURCE_HASHES[index] or artifact_sha != canonical_sha256(
            {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        ):
            raise ValueError("historical posterior source hash differs")
        worlds.append(
            {
                "sensitivity_world": world,
                "source_posterior_artifact_sha256": artifact_sha,
                "rates": _rates(artifact),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "r9b-historical-rate-priors-v1",
        "originating_implementation_sha": HISTORICAL_IMPLEMENTATION_SHA,
        "central_source_posterior_artifact_sha256": CENTRAL_POSTERIOR_SHA,
        "worlds": worlds,
        "semantic_sha256": "0" * 64,
    }
    payload["semantic_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "semantic_sha256"}
    )
    HistoricalRateResource.model_validate_json(json.dumps(payload))
    _OUTPUT.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
