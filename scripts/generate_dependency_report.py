"""Generate honest direct/transitive dependency evidence from the frozen uv lock."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence" / "tickets" / "FND-001"
UNKNOWN_LICENSE = "UNKNOWN"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _dependency_name(requirement: str) -> str:
    return _normalize_name(re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0])


def _license(name: str) -> str:
    if name == "dmf-pulse":
        return "LicenseRef-Proprietary"
    try:
        metadata = importlib.metadata.metadata(name)
    except importlib.metadata.PackageNotFoundError:
        return UNKNOWN_LICENSE
    expression = (metadata.get("License-Expression") or "").strip()
    if expression and expression.casefold() != "unknown":
        return expression
    license_value = (metadata.get("License") or "").strip()
    if license_value and license_value.casefold() != "unknown" and len(license_value) <= 160:
        return " ".join(license_value.split())
    classifiers = sorted(
        {
            item.removeprefix("License :: ")
            for item in metadata.get_all("Classifier", [])
            if item.startswith("License :: ")
        }
    )
    return "; ".join(classifiers) if classifiers else UNKNOWN_LICENSE


def _locked_dependencies(package: dict[str, Any]) -> list[str]:
    dependencies = package.get("dependencies", [])
    if not isinstance(dependencies, list):
        return []
    names = {
        _normalize_name(str(item.get("name", "")))
        for item in dependencies
        if isinstance(item, dict) and item.get("name")
    }
    return sorted(names)


def build_report(generated_at: str) -> dict[str, Any]:
    pyproject_path = REPOSITORY_ROOT / "pyproject.toml"
    lock_path = REPOSITORY_ROOT / "uv.lock"
    with pyproject_path.open("rb") as handle:
        pyproject = tomllib.load(handle)
    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)

    project = pyproject["project"]
    groups = pyproject["dependency-groups"]
    runtime = {_dependency_name(item) for item in project["dependencies"]}
    development = {_dependency_name(item) for item in groups["dev"]}
    locked = lock.get("package", [])
    if not isinstance(locked, list):
        raise ValueError("uv.lock package table is malformed")

    packages: list[dict[str, Any]] = []
    for item in locked:
        if not isinstance(item, dict):
            raise ValueError("uv.lock contains a malformed package")
        name = _normalize_name(str(item.get("name", "")))
        version = str(item.get("version", ""))
        if name == "dmf-pulse" and not version:
            version = importlib.metadata.version("dmf-pulse")
        if not name or not version:
            raise ValueError("uv.lock package is missing name or version")
        relationships = []
        if name == "dmf-pulse":
            relationships.append("project")
        if name in runtime:
            relationships.append("direct-runtime")
        if name in development:
            relationships.append("direct-development")
        if not relationships:
            relationships.append("transitive")
        packages.append(
            {
                "dependencies": _locked_dependencies(item),
                "license": _license(name),
                "name": name,
                "relationships": relationships,
                "version": version,
            }
        )
    packages.sort(key=lambda item: item["name"])
    return {
        "direct_development": sorted(development),
        "direct_runtime": sorted(runtime),
        "generated_at": generated_at,
        "license_discovery": (
            "Installed distribution metadata: License-Expression, then short License, then "
            "License classifiers; UNKNOWN is retained when no reliable value is present."
        ),
        "lock_package_count": len(packages),
        "lock_sha256": _sha256(lock_path),
        "packages": packages,
        "platform": {
            "architecture": platform.machine(),
            "operating_system": platform.system(),
            "python": platform.python_version(),
        },
        "pyproject_sha256": _sha256(pyproject_path),
        "schema_version": "1.0",
        "unknown_license_packages": [
            item["name"] for item in packages if item["license"] == UNKNOWN_LICENSE
        ],
    }


def _markdown(report: dict[str, Any], ticket: str) -> str:
    packages = report["packages"]
    rows = [
        "| Package | Version | Relationship | Licence |",
        "|---|---:|---|---|",
    ]
    for package in packages:
        relationship = ", ".join(package["relationships"])
        license_value = str(package["license"]).replace("|", "\\|")
        rows.append(
            f"| `{package['name']}` | `{package['version']}` | {relationship} | {license_value} |"
        )
    unknown = report["unknown_license_packages"]
    unknown_text = ", ".join(f"`{name}`" for name in unknown) if unknown else "None."
    return (
        f"# {ticket} dependency report\n\n"
        f"Generated: `{report['generated_at']}`\n\n"
        f"Frozen lock SHA-256: `{report['lock_sha256']}`\n\n"
        f"Locked packages: **{report['lock_package_count']}**\n\n"
        "Runtime direct dependencies: "
        + ", ".join(f"`{name}`" for name in report["direct_runtime"])
        + ".\n\nDevelopment direct dependencies: "
        + ", ".join(f"`{name}`" for name in report["direct_development"])
        + ". Hatchling is locked as the sanctioned build backend; pytest-cov is the adapter "
        "required by the literal coverage command. Neither is a runtime dependency.\n\n"
        + "\n".join(rows)
        + "\n\nLicences unavailable from installed distribution metadata are reported as UNKNOWN, not "
        f"inferred: {unknown_text}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", choices=("FND-001", "RUL-002"), default="FND-001")
    arguments = parser.parse_args()
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = build_report(generated_at)
    evidence_root = REPOSITORY_ROOT / "evidence" / "tickets" / arguments.ticket
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "dependency_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (evidence_root / "DEPENDENCY_REPORT.md").write_text(
        _markdown(report, arguments.ticket), encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "lock_package_count": report["lock_package_count"],
                "status": "PASS",
                "unknown_license_count": len(report["unknown_license_packages"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
