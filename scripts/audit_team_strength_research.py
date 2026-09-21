"""Offline audit of the recovered research and P0-pinned OpenFootball corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--research-script", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    registry = json.loads(
        (root / "config/providers/openfootball_historical_team_identity.json").read_text()
    )
    aliases = {
        (season, row["source_team_name"]): row["canonical_team_id"]
        for row in registry["records"]
        for season in row["season_scope"]
    }
    observations: list[tuple[str, int, date, str, str, int, int]] = []
    resources = []
    for snapshot in registry["source_snapshots"]:
        raw = subprocess.check_output(
            [
                "git",
                "-C",
                str(args.source_repository),
                "show",
                f"{snapshot['commit_sha']}:{snapshot['path']}",
            ],
            timeout=30,
        )
        digest = hashlib.sha256(raw).hexdigest()
        if digest != snapshot["content_sha256"]:
            raise ValueError("source differs from the P0-pinned content hash")
        payload = json.loads(raw)
        season = snapshot["season_code"]
        score_count = 0
        pairs: set[tuple[str, str]] = set()
        for row in payload["matches"]:
            home = aliases[(season, row["team1"])]
            away = aliases[(season, row["team2"])]
            pair = (home, away)
            if home == away or pair in pairs:
                raise ValueError("duplicate or invalid canonical season fixture")
            pairs.add(pair)
            score = row.get("score")
            if isinstance(score, dict):
                score = score.get("ft")
            if score is None:
                continue
            score_count += 1
            observations.append(
                (
                    season,
                    int(row["round"].removeprefix("Matchday ")),
                    date.fromisoformat(row["date"]),
                    home,
                    away,
                    score[0],
                    score[1],
                )
            )
        resources.append(
            {
                "season": season,
                "path": snapshot["path"],
                "content_sha256": digest,
                "byte_length": len(raw),
                "git_blob_sha1": hashlib.sha1(
                    f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
                ).hexdigest(),
                "scheduled_matches": len(payload["matches"]),
                "scored_matches": score_count,
            }
        )
    differences = []
    holdout = [row for row in observations if row[0] == "2025/26"]
    for round_number in range(1, 39):
        cutoff = min(row[2] for row in holdout if row[1] == round_number)
        previous_day = [row for row in observations if row[2] == cutoff - timedelta(days=1)]
        if previous_day:
            differences.append(
                {
                    "holdout_round": round_number,
                    "cutoff": cutoff.isoformat(),
                    "research_includes_but_d_plus_2_excludes": len(previous_day),
                    "fixtures": [
                        {"season": row[0], "round": row[1], "played_on": row[2].isoformat()}
                        for row in previous_day
                    ],
                }
            )
    print(
        json.dumps(
            {
                "research_script_sha256": hashlib.sha256(
                    args.research_script.read_bytes()
                ).hexdigest(),
                "source_commit": registry["source_commit_sha"],
                "identity_semantic_sha256": registry["root_semantic_sha256"],
                "canonical_clubs": registry["canonical_club_count"],
                "aliases": registry["alias_count"],
                "resources": resources,
                "holdout_fixtures": len(holdout),
                "historical_scored_matches": sum(row[0] < "2026/27" for row in observations),
                "replay_d_plus_2_differences": differences,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
