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


def _dependency_request(item: object) -> tuple[str, frozenset[str]] | None:
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        return None
    raw_extras = item.get("extra", item.get("extras", []))
    if not isinstance(raw_extras, list) or not all(isinstance(extra, str) for extra in raw_extras):
        raise ValueError(f"locked dependency extras malformed: {item['name']}")
    return item["name"], frozenset(raw_extras)


def _resolve_runtime_graph(
    packages: dict[str, dict[str, Any]], roots: list[object]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, set[str]]]:
    selected_dependencies: dict[str, list[dict[str, Any]]] = {}
    activated_extras: dict[str, set[str]] = {}
    pending = [request for item in roots if (request := _dependency_request(item))]
    while pending:
        name, extras = pending.pop()
        prior_extras = activated_extras.setdefault(name, set())
        if name in selected_dependencies and extras.issubset(prior_extras):
            continue
        prior_extras.update(extras)
        package = packages.get(name)
        if not isinstance(package, dict):
            raise ValueError(f"locked runtime package missing: {name}")
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"locked dependencies malformed: {name}")
        expanded = list(dependencies)
        optional = package.get("optional-dependencies", {})
        if not isinstance(optional, dict):
            raise ValueError(f"locked optional dependencies malformed: {name}")
        for extra in sorted(prior_extras):
            extra_dependencies = optional.get(extra)
            if not isinstance(extra_dependencies, list):
                raise ValueError(f"locked dependency extra is missing: {name}[{extra}]")
            expanded.extend(extra_dependencies)
        selected_dependencies[name] = expanded
        pending.extend(request for item in expanded if (request := _dependency_request(item)))
    return selected_dependencies, activated_extras


def build_manifest(lock_path: Path = LOCK_PATH) -> dict[str, object]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    raw_packages = lock.get("package")
    if not isinstance(raw_packages, list):
        raise ValueError("uv.lock package table is missing")
    packages: dict[str, dict[str, Any]] = {
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
    selected_dependencies, activated_extras = _resolve_runtime_graph(packages, roots)
    selected = set(selected_dependencies)
    records: list[dict[str, Any]] = []
    for name in sorted(selected):
        package = packages[name]
        version = package.get("version")
        if not isinstance(version, str):
            raise ValueError(f"locked runtime version missing: {name}")
        dependencies = selected_dependencies[name]
        records.append(
            {
                "activated_extras": sorted(activated_extras[name]),
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
        "manifest_version": "1.1",
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
