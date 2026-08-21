"""Build the aggregate-only GW1-PLY-002 role-prior candidate from local CC-BY files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.role_priors import (
    WyscoutInputPaths,
    WyscoutSourceFile,
    WyscoutSourceGovernance,
    build_role_prior_candidate,
)


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise IngestionError("SOURCE_FILE_MISSING", f"download is missing: {path}")
    return sha256(path.read_bytes()).hexdigest()


def _source(retrieved_at: datetime) -> WyscoutSourceGovernance:
    return WyscoutSourceGovernance(
        dataset_owner="Pappalardo / Wyscout Soccer Match Event Dataset",
        paper=(
            "Pappalardo et al. (2019), A public data set of spatio-temporal match events "
            "in soccer competitions, Scientific Data 6:236, https://doi.org/10.1038/s41597-019-0247-7"
        ),
        figshare_collection="https://figshare.com/collections/Soccer_match_event_dataset/4415000/2",
        figshare_collection_version=5,
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        attribution=(
            "Pappalardo, Luca; Massucco, Emanuele (2019). Soccer match event dataset, "
            "figshare collection 10.6084/m9.figshare.c.4415000; cite Pappalardo et al. (2019)."
        ),
        retrieved_at=retrieved_at,
        files=(
            WyscoutSourceFile(
                item_id=7770599,
                item_version=1,
                file_id=14464685,
                file_name="events.zip",
                download_url="https://ndownloader.figshare.com/files/14464685",
                supplied_md5="7c20e8647e7eda58d7838a0c7b1ec6ab",
                download_sha256="877e015b716ffdeea18f04418e3f24fed307ed03c37ff305cabe1f47c4822a45",
                used_member="events_England.json",
                member_sha256="301599543aa1a7fa457bb8ef33c9fe860bf81dca65d418d618d68abcda3defad",
            ),
            WyscoutSourceFile(
                item_id=7770422,
                item_version=1,
                file_id=14464622,
                file_name="matches.zip",
                download_url="https://ndownloader.figshare.com/files/14464622",
                supplied_md5="51d80beb17480919f69a53a0152c2d71",
                download_sha256="c8f92bb7533e5c127e043cee764c991b5c25b4f5e70a65be931baae0b1765ce9",
                used_member="matches_England.json",
                member_sha256="620725c2e6a58b4db3e574ed6c559136477451d81af543f8a06bd85c3da3fe29",
            ),
            WyscoutSourceFile(
                item_id=7765196,
                item_version=3,
                file_id=15073721,
                file_name="players.json",
                download_url="https://ndownloader.figshare.com/files/15073721",
                supplied_md5="f28ddf6326281efeda6488b2169f5609",
                download_sha256="877a111cb1005b73df5645e9338bd74fb4b496bace2fbc545a72abb3b73efa2e",
                used_member="players.json",
                member_sha256="877a111cb1005b73df5645e9338bd74fb4b496bace2fbc545a72abb3b73efa2e",
            ),
        ),
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--players-download", type=Path, required=True)
    parser.add_argument("--matches-download", type=Path, required=True)
    parser.add_argument("--events-download", type=Path, required=True)
    parser.add_argument("--retrieved-at", type=_parse_utc, required=True)
    parser.add_argument("--transformation-code-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = _source(args.retrieved_at)
    archive_paths = {
        "events.zip": args.events_download,
        "matches.zip": args.matches_download,
        "players.json": args.players_download,
    }
    for item in source.files:
        if _sha256(archive_paths[item.file_name]) != item.download_sha256:
            raise IngestionError("SOURCE_HASH_MISMATCH", f"{item.file_name} download hash mismatch")
    artifact = build_role_prior_candidate(
        paths=WyscoutInputPaths(players=args.players, matches=args.matches, events=args.events),
        source=source,
        transformation_code_commit=args.transformation_code_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(artifact.artifact_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
