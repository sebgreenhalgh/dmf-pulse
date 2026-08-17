from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_SEASON_FORMS = ("2026/27", "2026-27", "2026_27")
REQUIRED_CAPABILITIES = (
    "PLAYER_POINTS",
    "GW1_INITIAL_SQUAD",
    "TRANSFER_STATE",
    "CHIP_STATE",
    "FULL_SEASON",
)


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _candidate_yaml() -> Iterator[Path]:
    for path in REPO_ROOT.rglob("*.yaml"):
        if any(part in {".git", ".venv", "site-packages"} for part in path.parts):
            continue
        yield path
    for path in REPO_ROOT.rglob("*.yml"):
        if any(part in {".git", ".venv", "site-packages"} for part in path.parts):
            continue
        yield path


def _target_root() -> Path:
    author_report = REPO_ROOT / "evidence" / "tickets" / "RUL-2026-27" / "TARGET_AUTHORING_REPORT.json"
    if author_report.exists():
        value = json.loads(author_report.read_text(encoding="utf-8"))
        candidate = REPO_ROOT / value["target_root"]
        if candidate.is_dir():
            return candidate
    scored: dict[Path, int] = {}
    for path in _candidate_yaml():
        text = path.read_text(encoding="utf-8", errors="ignore")
        score = sum(20 for form in TARGET_SEASON_FORMS if form in text or form in path.as_posix())
        if "target" in path.as_posix().lower():
            score += 10
        if "rules" in path.as_posix().lower():
            score += 5
        if any(token in path.as_posix().lower() for token in ("fixture", "test", "evidence")):
            score -= 12
        if score > 0:
            scored[path.parent] = scored.get(path.parent, 0) + score
    assert scored, "No 2026/27 target split-YAML ruleset found"
    return sorted(scored, key=lambda path: (-scored[path], len(path.parts), path.as_posix()))[0]


def _documents() -> list[tuple[Path, Any]]:
    root = _target_root()
    paths = sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")])
    assert paths, f"No YAML documents under target root {root}"
    return [(path, yaml.safe_load(path.read_text(encoding="utf-8"))) for path in paths]


def _flatten(value: Any, trail: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(child, (*trail, _normal(str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten(child, (*trail, str(index)))
    else:
        yield trail, value


def _target_values() -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for path, document in _documents():
        rows.extend((f"{path.name}:{'.'.join(trail)}", value) for trail, value in _flatten(document))
    return rows


def _target_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path, _ in _documents()
    )


def _has_path_value(rows: list[tuple[str, Any]], terms: tuple[str, ...], values: set[Any]) -> bool:
    return any(all(term in path for term in terms) and value in values for path, value in rows)


def _scenario_matrix() -> dict[str, Any]:
    path = REPO_ROOT / "fixtures" / "rules" / "RUL-2026-27" / "adversarial_scenarios.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _selling_price(purchase: int, current: int) -> int:
    if current <= purchase:
        return current
    return purchase + (current - purchase) // 2


def _try_cli(commands: list[list[str]]) -> tuple[list[str], subprocess.CompletedProcess[str]]:
    failures: list[dict[str, Any]] = []
    for command in commands:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            return command, result
        failures.append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
    pytest.fail(f"No accepted CLI form succeeded: {json.dumps(failures, indent=2)}")


def test_adversarial_matrix_is_complete_and_self_consistent() -> None:
    matrix = _scenario_matrix()
    assert matrix["schema_version"] == "dmf-rules-2026-27-adversarial-scenarios-v1"
    assert matrix["target_season"] == "2026/27"
    assert {row["id"] for row in matrix["player_points_boundaries"]} == {
        "MINUTES-0",
        "MINUTES-1",
        "MINUTES-59",
        "MINUTES-60",
    }
    for row in matrix["selling_price"]:
        assert _selling_price(row["purchase_price_tenths"], row["current_price_tenths"]) == row[
            "expected_selling_price_tenths"
        ]
    assert any(row["id"] == "SELL-BELOW" for row in matrix["selling_price"])
    assert any(row["id"] == "FREE-HIT-RESTORES-SQUAD" for row in matrix["chips"])
    assert any(row["id"] == "ACTIVATION-WITHOUT-APPROVAL" for row in matrix["governance"])


def test_target_squad_budget_formation_and_club_quota() -> None:
    values = _target_values()
    text = _target_text().lower()
    assert _has_path_value(values, ("squad", "size"), {15}) or _has_path_value(
        values, ("squadsize",), {15}
    )
    assert _has_path_value(values, ("budget",), {1000, 100, 100.0})
    assert any(
        ("club" in path or "team_limit" in path) and value == 3 for path, value in values
    )
    for position, quota in {"gk": 2, "def": 5, "mid": 5, "fwd": 3}.items():
        assert any(position in path and ("squad" in path or "quota" in path) and value == quota for path, value in values), position
    for token in ("captain", "vice", "automatic", "substitution", "formation"):
        assert token in text
    assert ("goalkeeper" in text or "gk" in text) and "bench" in text


def test_target_player_points_contract_preserves_accepted_boundaries() -> None:
    values = _target_values()
    text = _target_text().lower()
    assert any("appearance" in path and "threshold" in path and value in {1, 60} for path, value in values)
    for token in (
        "assist",
        "clean_sheet",
        "save",
        "penalty_save",
        "penalty_miss",
        "own_goal",
        "yellow",
        "red",
        "bps",
        "bonus",
        "defensive",
    ):
        assert token in text, token
    assert "tie" in text and "bonus" in text
    assert "60" in text and "59" in text or "minutes" in text


def test_target_transfer_and_selling_price_state_is_closed() -> None:
    values = _target_values()
    text = _target_text().lower()
    assert any("bank" in path and "max" in path and value == 5 for path, value in values)
    assert any("transfer" in path and ("hit" in path or "cost" in path) and abs(float(value)) == 4 for path, value in values if isinstance(value, (int, float)))
    assert any("transfer" in path and ("limit" in path or "max" in path) and value == 20 for path, value in values)
    for token in ("purchase", "current", "selling", "profit", "round"):
        assert token in text, token
    assert "below" in text or "current_price < purchase_price" in text
    assert "equal" in text or "current_price == purchase_price" in text
    assert "0.1" in text or "tenths" in text or "integer" in text
    for token in ("afford", "bank", "club", "position"):
        assert token in text


def test_target_chip_state_machine_has_both_windows_and_executable_effects() -> None:
    text = _target_text().lower().replace("-", "_").replace(" ", "_")
    for token in ("wildcard", "free_hit", "triple_captain", "bench_boost"):
        assert token in text, token
    for boundary in ("1", "19", "20", "38"):
        assert boundary in text
    for token in ("expire", "one_chip", "cancel", "restore", "consecutive"):
        assert token in text, token
    assert "saved" in text and "transfer" in text
    assert "multiplier" in text or "triple" in text
    assert "bench" in text and ("count" in text or "score" in text)


def test_target_has_all_38_official_deadlines() -> None:
    deadline_values = {
        value
        for path, value in _target_values()
        if "deadline" in path and isinstance(value, str) and re.match(r"^2026-\d{2}-\d{2}T", value)
    }
    assert len(deadline_values) == 38


def test_target_capability_names_are_explicit() -> None:
    text = _target_text().upper()
    for capability in REQUIRED_CAPABILITIES:
        assert capability in text, capability


def test_source_manifest_has_digests_locators_and_refresh_triggers() -> None:
    manifest_path = REPO_ROOT / "evidence" / "tickets" / "RUL-2026-27" / "SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["target_season"] == "2026/27"
    assert manifest["sources"]
    for source in manifest["sources"]:
        assert source["publisher"]
        assert source["title"]
        assert source["url"].startswith("https://")
        assert source["retrieved_at"]
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
        assert source["locator"]
        assert source["rules_supported"]
        assert source["refresh_trigger"]
    bootstrap_sources = [source for source in manifest["sources"] if "bootstrap" in source["title"].lower()]
    assert bootstrap_sources
    for source in bootstrap_sources:
        matches = list((manifest_path.parent / "sources").glob(f"*{source['sha256']}*"))
        assert matches
        assert hashlib.sha256(matches[0].read_bytes()).hexdigest() == source["sha256"]


def test_no_forged_human_approval_or_active_target() -> None:
    evidence_root = REPO_ROOT / "evidence" / "tickets" / "RUL-2026-27"
    approval_path = evidence_root / "PENDING_HUMAN_APPROVAL.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    assert approval["status"] == "PENDING_HUMAN_APPROVAL"
    assert approval["approved"] is False
    assert approval["approved_by"] is None
    assert approval["approved_at"] is None
    for path in [*_target_root().rglob("*.yaml"), *evidence_root.rglob("*.json")]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(r"approved_by\s*[\":= ]+Sebastian Greenhalgh", text, re.IGNORECASE)
        assert not re.search(r"approved\s*[\":= ]+true", text, re.IGNORECASE)


def test_target_season_policy_is_not_encoded_as_runtime_conditionals() -> None:
    violations: list[str] = []
    for path in (REPO_ROOT / "src" / "dmf_pulse").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                continue
            constants = {
                value.value
                for value in ast.walk(node)
                if isinstance(value, ast.Constant) and isinstance(value.value, (str, int))
            }
            if 2026 in constants or any(form in constants for form in TARGET_SEASON_FORMS):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{getattr(node, 'lineno', 0)}")
    assert not violations, violations


def test_target_validation_and_compilation_are_deterministic(tmp_path: Path) -> None:
    assert shutil.which("dmf"), "dmf console script is not installed"
    target = _target_root().as_posix()
    _try_cli(
        [
            ["dmf", "rules", "validate", target, "--json"],
            ["dmf", "rules", "validate", "--source", target, "--json"],
            ["dmf", "rules", "validate", "--ruleset", target, "--json"],
        ]
    )
    first = tmp_path / "compiled-a.json"
    second = tmp_path / "compiled-b.json"
    compile_commands = lambda output: [
        ["dmf", "rules", "compile", target, "--output", output.as_posix(), "--json"],
        ["dmf", "rules", "compile", "--source", target, "--output", output.as_posix(), "--json"],
        ["dmf", "rules", "compile", "--ruleset", target, "--output", output.as_posix(), "--json"],
    ]
    _try_cli(compile_commands(first))
    _try_cli(compile_commands(second))
    assert first.read_bytes() == second.read_bytes()


def test_activation_fails_closed_without_human_approval() -> None:
    assert shutil.which("dmf"), "dmf console script is not installed"
    help_result = subprocess.run(
        ["dmf", "rules", "--help"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    target = _target_root().as_posix()
    commands = [name for name in ("activate", "activation-check", "promote") if name in help_result.stdout]
    if commands:
        for name in commands:
            result = subprocess.run(
                ["dmf", "rules", name, target, "--json"],
                cwd=REPO_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert result.returncode != 0, (name, result.stdout, result.stderr)
        return
    activation_tests = [
        path
        for path in (REPO_ROOT / "tests").rglob("*.py")
        if path != Path(__file__)
        and "activation" in path.read_text(encoding="utf-8", errors="ignore").lower()
        and "approval" in path.read_text(encoding="utf-8", errors="ignore").lower()
    ]
    assert activation_tests, "No activation CLI and no independent activation/approval contract tests"


def test_reference_and_synthetic_rulesets_remain_valid() -> None:
    assert shutil.which("dmf"), "dmf console script is not installed"
    candidates = [
        REPO_ROOT / "fixtures" / "rules" / "RUL-002" / "synthetic_complete",
        REPO_ROOT / "fixtures" / "rules" / "RUL-002" / "optimiser_reference_v1_0",
        REPO_ROOT / "fixtures" / "rules" / "RUL-002" / "optimiser_reference_v1_1",
    ]
    existing = [path for path in candidates if path.exists()]
    assert existing
    for ruleset in existing:
        _try_cli(
            [
                ["dmf", "rules", "validate", ruleset.as_posix(), "--json"],
                ["dmf", "rules", "validate", "--source", ruleset.as_posix(), "--json"],
                ["dmf", "rules", "validate", "--ruleset", ruleset.as_posix(), "--json"],
            ]
        )
