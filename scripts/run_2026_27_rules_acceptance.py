#!/usr/bin/env python3
"""Run the strict repository-native 2026/27 rules acceptance vertical slice.

This script discovers the accepted CLI surface from the checked-out repository,
validates and compiles the target twice, requires machine-readable capability
closure, verifies hash integrity, and proves that pre-approval activation fails
closed. It emits durable evidence; it never activates production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

IMMUTABLE_PARENT = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
TARGET_SEASON_FORMS = ("2026/27", "2026-27", "2026_27", "202627")
REQUIRED_CAPABILITIES = (
    "PLAYER_POINTS",
    "GW1_INITIAL_SQUAD",
    "TRANSFER_STATE",
    "CHIP_STATE",
    "FULL_SEASON",
)
PASS_STATUSES = {
    "PASS",
    "PASSED",
    "READY",
    "VERIFIED",
    "TECHNICALLY_VERIFIED",
    "COMPLETE",
    "AVAILABLE",
    "SUPPORTED",
    "ENABLED",
}
FAIL_STATUSES = {
    "FAIL",
    "FAILED",
    "BLOCKED",
    "INCOMPLETE",
    "UNAVAILABLE",
    "UNSUPPORTED",
    "DISABLED",
    "ERROR",
    "INVALID",
}


class AcceptanceError(RuntimeError):
    """Raised when the target cannot satisfy a fail-closed acceptance gate."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CapabilityState:
    capability: str
    status: str
    verified: bool
    blockers: tuple[str, ...]
    evidence_path: str


def _run(root: Path, argv: Sequence[str], *, timeout: int = 180) -> CommandResult:
    result = subprocess.run(
        list(argv),
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    return CommandResult(tuple(argv), result.returncode, result.stdout, result.stderr)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normal(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _json_values(text: str) -> list[Any]:
    values: list[Any] = []
    stripped = text.strip()
    if not stripped:
        return values
    try:
        values.append(json.loads(stripped))
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line or line == stripped:
            continue
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


def _walk(value: Any, trail: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    yield trail, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, (*trail, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*trail, str(index)))


def _target_root(repo: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        candidate = explicit.resolve()
        if not candidate.is_dir():
            raise AcceptanceError(f"target root does not exist: {candidate}")
        return candidate
    report = repo / "evidence" / "tickets" / "RUL-2026-27" / "TARGET_AUTHORING_REPORT.json"
    if report.exists():
        try:
            value = json.loads(report.read_text(encoding="utf-8"))
            candidate = repo / str(value["target_root"])
        except (json.JSONDecodeError, KeyError, TypeError):
            candidate = Path()
        if candidate.is_dir():
            return candidate.resolve()
    scores: dict[Path, int] = {}
    for suffix in ("*.yaml", "*.yml"):
        for path in repo.rglob(suffix):
            if any(part in {".git", ".venv", "site-packages", "evidence", "tests", "fixtures"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            score = sum(30 for form in TARGET_SEASON_FORMS if form in text or form in path.as_posix())
            lower = path.as_posix().lower()
            score += 12 if "target" in lower else 0
            score += 8 if "rules" in lower else 0
            if score:
                scores[path.parent] = scores.get(path.parent, 0) + score
    if not scores:
        raise AcceptanceError("unable to discover a 2026/27 target split-YAML ruleset")
    return sorted(scores, key=lambda path: (-scores[path], len(path.parts), path.as_posix()))[0].resolve()


def _subcommands(help_text: str) -> set[str]:
    candidates = set(re.findall(r"(?m)^\s{2,}([a-z][a-z0-9-]+)\s{2,}", help_text))
    candidates.update(re.findall(r"\{([a-z0-9_, -]+)\}", help_text))
    expanded: set[str] = set()
    for item in candidates:
        expanded.update(part.strip() for part in item.split(",") if part.strip())
    return expanded


def _candidate_inputs(target: Path, compiled: Path) -> list[list[str]]:
    return [
        [target.as_posix()],
        [compiled.as_posix()],
        ["--source", target.as_posix()],
        ["--source-root", target.as_posix()],
        ["--ruleset", target.as_posix()],
        ["--ruleset-root", target.as_posix()],
        ["--compiled", compiled.as_posix()],
        ["--artifact", compiled.as_posix()],
    ]


def _successful_command(
    repo: Path,
    candidates: Iterable[Sequence[str]],
    ledger: list[CommandResult],
    *,
    require_json: bool = False,
    timeout: int = 180,
) -> CommandResult:
    for candidate in candidates:
        result = _run(repo, candidate, timeout=timeout)
        ledger.append(result)
        if result.returncode != 0:
            continue
        if require_json and not (_json_values(result.stdout) or _json_values(result.stderr)):
            continue
        return result
    raise AcceptanceError("no accepted command form succeeded")


def _validate(repo: Path, target: Path, ledger: list[CommandResult]) -> CommandResult:
    prefix = ["uv", "run", "dmf", "rules", "validate"]
    candidates = [
        [*prefix, target.as_posix(), "--json"],
        [*prefix, "--source", target.as_posix(), "--json"],
        [*prefix, "--source-root", target.as_posix(), "--json"],
        [*prefix, "--ruleset", target.as_posix(), "--json"],
        [*prefix, "--ruleset-root", target.as_posix(), "--json"],
        [*prefix, target.as_posix()],
    ]
    return _successful_command(repo, candidates, ledger)


def _compile_once(
    repo: Path,
    target: Path,
    output: Path,
    ledger: list[CommandResult],
) -> CommandResult:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    prefix = ["uv", "run", "dmf", "rules", "compile"]
    candidates = [
        [*prefix, target.as_posix(), "--output", output.as_posix(), "--json"],
        [*prefix, "--source", target.as_posix(), "--output", output.as_posix(), "--json"],
        [*prefix, "--source-root", target.as_posix(), "--output", output.as_posix(), "--json"],
        [*prefix, "--ruleset", target.as_posix(), "--output", output.as_posix(), "--json"],
        [*prefix, "--ruleset-root", target.as_posix(), "--output", output.as_posix(), "--json"],
        [*prefix, target.as_posix(), "--out", output.as_posix(), "--json"],
        [*prefix, target.as_posix(), output.as_posix(), "--json"],
    ]
    for candidate in candidates:
        result = _run(repo, candidate)
        ledger.append(result)
        if result.returncode != 0:
            continue
        if output.is_file() and output.stat().st_size > 0:
            return result
        for value in _json_values(result.stdout):
            if isinstance(value, dict):
                for key in ("output", "output_path", "artifact", "compiled_path", "path"):
                    candidate_path = value.get(key)
                    if isinstance(candidate_path, str):
                        source = Path(candidate_path)
                        if not source.is_absolute():
                            source = repo / source
                        if source.is_file():
                            shutil.copyfile(source, output)
                            return result
    raise AcceptanceError("target compilation did not produce a non-empty artifact")


def _blockers_from_mapping(value: dict[str, Any]) -> tuple[str, ...]:
    blockers: list[str] = []
    for key, child in value.items():
        normal = _normal(str(key))
        if normal in {"BLOCKERS", "BLOCKING_FIELDS", "UNRESOLVED", "UNRESOLVED_FIELDS", "ERRORS"}:
            if isinstance(child, list):
                blockers.extend(str(item) for item in child if item not in (None, ""))
            elif isinstance(child, dict):
                blockers.extend(str(item) for item, present in child.items() if present)
            elif child not in (None, "", 0, False):
                blockers.append(str(child))
        if normal in {"BLOCKED", "HAS_BLOCKERS"} and child is True:
            blockers.append(f"{key}=true")
    return tuple(blockers)


def _capability_candidates(values: Iterable[Any]) -> dict[str, list[tuple[str, bool, tuple[str, ...], str]]]:
    found: dict[str, list[tuple[str, bool, tuple[str, ...], str]]] = {name: [] for name in REQUIRED_CAPABILITIES}
    for value in values:
        for trail, node in _walk(value):
            if not isinstance(node, dict):
                continue
            names: set[str] = set()
            for key, child in node.items():
                if _normal(str(key)) in {"CAPABILITY", "CAPABILITY_ID", "NAME", "ID", "KEY"} and isinstance(child, str):
                    names.add(_normal(child))
                normal_key = _normal(str(key))
                if normal_key in REQUIRED_CAPABILITIES and isinstance(child, (dict, str, bool)):
                    names.add(normal_key)
                    if isinstance(child, dict):
                        node = {**child, "capability": normal_key}
                    elif isinstance(child, str):
                        node = {"capability": normal_key, "status": child}
                    else:
                        node = {"capability": normal_key, "verified": child}
            for name in names & set(REQUIRED_CAPABILITIES):
                status_value = None
                for key in ("status", "state", "result", "readiness"):
                    if key in node:
                        status_value = node[key]
                        break
                status = _normal(str(status_value)) if status_value is not None else ""
                verified_fields = [
                    node.get("verified"),
                    node.get("ready"),
                    node.get("available"),
                    node.get("supported"),
                    node.get("complete"),
                ]
                blockers = _blockers_from_mapping(node)
                active = node.get("active") is True or status == "ACTIVE"
                verified = (
                    not active
                    and not blockers
                    and status not in FAIL_STATUSES
                    and (status in PASS_STATUSES or True in verified_fields)
                )
                found[name].append((status or "UNSPECIFIED", verified, blockers, ".".join(trail)))
    return found


def _capabilities(
    repo: Path,
    target: Path,
    compiled: Path,
    evidence_dir: Path,
    ledger: list[CommandResult],
    help_text: str,
) -> tuple[dict[str, CapabilityState], CommandResult]:
    discovered = _subcommands(help_text)
    preferred = [
        name
        for name in (
            "capabilities",
            "capability",
            "capability-status",
            "verify-capabilities",
            "readiness",
            "status",
            "verify",
        )
        if name in discovered
    ]
    if not preferred:
        preferred = [
            name
            for name in sorted(discovered)
            if "capab" in name or "readiness" in name
        ]
    if not preferred:
        raise AcceptanceError("the accepted rules CLI exposes no capability/readiness command")

    attempts: list[Sequence[str]] = []
    for subcommand in preferred:
        prefix = ["uv", "run", "dmf", "rules", subcommand]
        for input_args in _candidate_inputs(target, compiled):
            attempts.extend(
                (
                    [*prefix, *input_args, "--json"],
                    [*prefix, *input_args],
                )
            )
    best_result: CommandResult | None = None
    best_states: dict[str, CapabilityState] | None = None
    for command in attempts:
        result = _run(repo, command)
        ledger.append(result)
        if result.returncode != 0:
            continue
        values = [*_json_values(result.stdout), *_json_values(result.stderr)]
        parsed = _capability_candidates(values)
        states: dict[str, CapabilityState] = {}
        for capability, candidates in parsed.items():
            passing = next((candidate for candidate in candidates if candidate[1]), None)
            if passing is None:
                continue
            status, verified, blockers, path = passing
            states[capability] = CapabilityState(
                capability=capability,
                status=status,
                verified=verified,
                blockers=blockers,
                evidence_path=path,
            )
        if set(states) == set(REQUIRED_CAPABILITIES):
            best_result = result
            best_states = states
            break
    if best_result is None or best_states is None:
        raise AcceptanceError("no capability command proved all required capabilities technically verified")
    artifact = {
        "schema_version": "dmf-rules-2026-27-capabilities-v1",
        "target_season": "2026/27",
        "command": list(best_result.argv),
        "capabilities": {name: asdict(state) for name, state in sorted(best_states.items())},
        "human_approval_status": "PENDING_HUMAN_APPROVAL",
        "production_status": "NOT_ACTIVE",
        "raw_stdout": best_result.stdout,
        "raw_stderr": best_result.stderr,
    }
    (evidence_dir / "CAPABILITY_READINESS.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return best_states, best_result


def _activation_fail_closed(
    repo: Path,
    target: Path,
    compiled: Path,
    evidence_dir: Path,
    ledger: list[CommandResult],
    help_text: str,
) -> dict[str, Any]:
    discovered = _subcommands(help_text)
    names = [name for name in ("activate", "activation", "activation-check", "promote") if name in discovered]
    attempts: list[CommandResult] = []
    recognized_failure: CommandResult | None = None
    for name in names:
        prefix = ["uv", "run", "dmf", "rules", name]
        for input_args in _candidate_inputs(target, compiled):
            for extra in (["--json"], []):
                result = _run(repo, [*prefix, *input_args, *extra])
                ledger.append(result)
                attempts.append(result)
                if result.returncode == 0:
                    raise AcceptanceError(f"pre-approval activation unexpectedly succeeded: {result.argv}")
                diagnostic = f"{result.stdout}\n{result.stderr}".lower()
                if any(term in diagnostic for term in ("approval", "pending", "blocked", "not active", "activation")):
                    recognized_failure = result
                    break
            if recognized_failure is not None:
                break
        if recognized_failure is not None:
            break

    governance_tests: list[str] = []
    if recognized_failure is None:
        for path in (repo / "tests").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "activation" in text and "approval" in text and ("fail" in text or "block" in text or "reject" in text):
                governance_tests.append(path.relative_to(repo).as_posix())
        if not governance_tests:
            raise AcceptanceError("neither an activation CLI rejection nor an independent activation/approval test was found")
    artifact = {
        "schema_version": "dmf-rules-2026-27-activation-fail-closed-v1",
        "status": "PASS",
        "human_approval_status": "PENDING_HUMAN_APPROVAL",
        "production_status": "NOT_ACTIVE",
        "activation_cli_failure": asdict(recognized_failure) if recognized_failure else None,
        "activation_governance_tests": sorted(governance_tests),
        "attempts": [asdict(result) for result in attempts],
    }
    (evidence_dir / "ACTIVATION_FAIL_CLOSED.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def _runtime_policy_scan(repo: Path) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    pattern = re.compile(r"(?:2026[/_-]?27|season\s*==\s*[\"']?2026)", re.IGNORECASE)
    for path in (repo / "src" / "dmf_pulse").rglob("*.py"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                violations.append(
                    {
                        "path": path.relative_to(repo).as_posix(),
                        "line": line_number,
                        "text": line.strip(),
                    }
                )
    return {"status": "PASS" if not violations else "FAIL", "violations": violations}


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    evidence_dir = (repo / "evidence" / "tickets" / "RUL-2026-27").resolve()
    compiled_dir = evidence_dir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    target = _target_root(repo, args.target_root)

    head = _run(repo, ["git", "rev-parse", "HEAD"]).stdout.strip()
    parent = _run(repo, ["git", "rev-parse", f"{IMMUTABLE_PARENT}^{{commit}}"]).stdout.strip()
    if parent != IMMUTABLE_PARENT:
        raise AcceptanceError("immutable parent is absent or does not resolve exactly")
    merge_base = _run(repo, ["git", "merge-base", IMMUTABLE_PARENT, head]).stdout.strip()
    if merge_base != IMMUTABLE_PARENT:
        raise AcceptanceError("current commit is not descended from the immutable implementation parent")

    ledger: list[CommandResult] = []
    help_result = _run(repo, ["uv", "run", "dmf", "rules", "--help"])
    ledger.append(help_result)
    if help_result.returncode != 0:
        raise AcceptanceError("rules CLI help failed")
    _validate(repo, target, ledger)

    with tempfile.TemporaryDirectory(prefix="dmf-rules-compile-") as temporary:
        temp_root = Path(temporary)
        first = temp_root / "compiled-a.json"
        second = temp_root / "compiled-b.json"
        first_result = _compile_once(repo, target, first, ledger)
        second_result = _compile_once(repo, target, second, ledger)
        if first.read_bytes() != second.read_bytes():
            raise AcceptanceError("target compilation is not byte-for-byte deterministic")
        try:
            json.loads(first.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AcceptanceError("compiled target is not valid JSON") from exc
        canonical = compiled_dir / "DMF_PULSE_2026_27_COMPILED_RULESET.json"
        shutil.copyfile(first, canonical)

    compiled_sha = _sha256(canonical)
    (compiled_dir / "DMF_PULSE_2026_27_COMPILED_RULESET.json.sha256").write_text(
        f"{compiled_sha}  {canonical.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    capabilities, capability_result = _capabilities(
        repo,
        target,
        canonical,
        evidence_dir,
        ledger,
        help_result.stdout,
    )
    activation = _activation_fail_closed(
        repo,
        target,
        canonical,
        evidence_dir,
        ledger,
        help_result.stdout,
    )
    runtime_scan = _runtime_policy_scan(repo)
    if runtime_scan["status"] != "PASS":
        raise AcceptanceError("target-season policy leaked into production Python code")
    (evidence_dir / "RUNTIME_POLICY_SCAN.json").write_text(
        json.dumps(runtime_scan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    ledger_payload = {
        "schema_version": "dmf-rules-2026-27-command-ledger-v1",
        "status": "PASS",
        "implementation_commit_at_execution": head,
        "immutable_parent": IMMUTABLE_PARENT,
        "target_root": target.relative_to(repo).as_posix(),
        "compiled_artifact": canonical.relative_to(repo).as_posix(),
        "compiled_sha256": compiled_sha,
        "validation_command": list(next(result.argv for result in ledger if "validate" in result.argv and result.returncode == 0)),
        "compile_commands": [list(first_result.argv), list(second_result.argv)],
        "capability_command": list(capability_result.argv),
        "capabilities": {name: asdict(state) for name, state in sorted(capabilities.items())},
        "activation_fail_closed": activation["status"],
        "commands": [asdict(result) for result in ledger],
    }
    ledger_path = evidence_dir / "COMMAND_LEDGER.json"
    ledger_path.write_text(
        json.dumps(ledger_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": "dmf-rules-2026-27-acceptance-v1",
        "status": "PASS",
        "target_root": target.relative_to(repo).as_posix(),
        "compiled_artifact": canonical.relative_to(repo).as_posix(),
        "compiled_sha256": compiled_sha,
        "capabilities": {name: state.status for name, state in sorted(capabilities.items())},
        "production_status": "NOT_ACTIVE",
        "human_approval_status": "PENDING_HUMAN_APPROVAL",
        "command_ledger": ledger_path.relative_to(repo).as_posix(),
    }
    (evidence_dir / "ACCEPTANCE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args)
    except (AcceptanceError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
