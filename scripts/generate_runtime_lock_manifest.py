"""Generate the runtime dependency graph and versions from the frozen uv lock."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "uv.lock"
OUTPUT = ROOT / "specs/manifests/runtime_lock_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(lock_path: Path = LOCK_PATH) -> dict[str, object]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    raw_packages = lock.get("package")
    if not isinstance(raw_packages, list):
        raise ValueError("uv.lock package table is missing")
    packages = {
        item["name"]: item
        for item in raw_packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    project = packages.get("dmf-pulse")
    if not isinstance(project, dict):
        raise ValueError("uv.lock project package is missing")
    roots = project.get("dependencies")
    if not isinstance(roots, list):
        raise ValueError("uv.lock project runtime dependencies are missing")
    selected: set[str] = set()
    pending = [item.get("name") for item in roots if isinstance(item, dict)]
    while pending:
        name = pending.pop()
        if not isinstance(name, str) or name in selected:
            continue
        package = packages.get(name)
        if not isinstance(package, dict):
            raise ValueError(f"locked runtime package missing: {name}")
        selected.add(name)
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"locked dependencies malformed: {name}")
        pending.extend(item.get("name") for item in dependencies if isinstance(item, dict))
    records: list[dict[str, Any]] = []
    for name in sorted(selected):
        package = packages[name]
        version = package.get("version")
        if not isinstance(version, str):
            raise ValueError(f"locked runtime version missing: {name}")
        dependencies = package.get("dependencies", [])
        records.append(
            {
                "dependencies": sorted(
                    [
                        {
                            "marker": item.get("marker"),
                            "name": item["name"],
                        }
                        for item in dependencies
                        if isinstance(item, dict)
                        and isinstance(item.get("name"), str)
                        and item["name"] in selected
                    ],
                    key=lambda item: (item["name"], str(item["marker"])),
                ),
                "name": name,
                "version": version,
            }
        )
    return {
        "lock_sha256": _sha256(lock_path),
        "manifest_version": "1.0",
        "packages": records,
        "project": "dmf-pulse",
        "roots": sorted(item["name"] for item in roots if isinstance(item, dict)),
    }


def main() -> int:
    manifest = build_manifest()
    OUTPUT.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {len(manifest['packages'])} locked runtime packages to {OUTPUT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
