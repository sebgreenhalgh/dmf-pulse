from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterator

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = REPO_ROOT / "evidence" / "tickets" / "RUL-2026-27"
REQUIRED_CAPABILITIES = {
    "PLAYER_POINTS",
    "GW1_INITIAL_SQUAD",
    "TRANSFER_STATE",
    "CHIP_STATE",
    "FULL_SEASON",
}
ACCEPTED_TECHNICAL_STATUSES = {
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


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _flatten(value: Any, trail: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(child, (*trail, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten(child, (*trail, str(index)))
    else:
        yield trail, value


def _target_values() -> list[tuple[str, Any]]:
    authoring = _load(EVIDENCE / "TARGET_AUTHORING_REPORT.json")
    root = REPO_ROOT / authoring["target_root"]
    values: list[tuple[str, Any]] = []
    for pattern in ("*.yaml", "*.yml"):
        for path in sorted(root.rglob(pattern)):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            values.extend((f"{path.name}:{'.'.join(trail)}".lower(), value) for trail, value in _flatten(document))
    return values


def test_acceptance_and_compiled_hash_are_canonical() -> None:
    acceptance = _load(EVIDENCE / "ACCEPTANCE_RESULT.json")
    assert acceptance["status"] == "PASS"
    assert acceptance["production_status"] == "NOT_ACTIVE"
    assert acceptance["human_approval_status"] == "PENDING_HUMAN_APPROVAL"
    compiled = REPO_ROOT / acceptance["compiled_artifact"]
    assert compiled.is_file() and compiled.stat().st_size > 0
    assert _sha(compiled) == acceptance["compiled_sha256"]
    json.loads(compiled.read_text(encoding="utf-8"))


def test_capability_closure_comes_from_machine_readable_evidence() -> None:
    artifact = _load(EVIDENCE / "CAPABILITY_READINESS.json")
    assert artifact["production_status"] == "NOT_ACTIVE"
    assert artifact["human_approval_status"] == "PENDING_HUMAN_APPROVAL"
    assert set(artifact["capabilities"]) == REQUIRED_CAPABILITIES
    for name, state in artifact["capabilities"].items():
        assert name in REQUIRED_CAPABILITIES
        assert state["verified"] is True
        assert state["status"] in ACCEPTED_TECHNICAL_STATUSES
        assert state["blockers"] == []
        assert state.get("active") is not True


def test_pending_human_approval_is_not_forged() -> None:
    approval = _load(EVIDENCE / "PENDING_HUMAN_APPROVAL.json")
    assert approval["status"] == "PENDING_HUMAN_APPROVAL"
    assert approval["approved"] is False
    assert approval["approved_by"] is None
    assert approval["approved_at"] is None
    assert approval.get("ruleset_hash") in (None, "")


def test_activation_is_explicitly_fail_closed() -> None:
    evidence = _load(EVIDENCE / "ACTIVATION_FAIL_CLOSED.json")
    assert evidence["status"] == "PASS"
    assert evidence["human_approval_status"] == "PENDING_HUMAN_APPROVAL"
    assert evidence["production_status"] == "NOT_ACTIVE"
    assert evidence["activation_cli_failure"] or evidence["activation_governance_tests"]


def test_every_official_source_record_is_locatable_and_hashed() -> None:
    manifest = _load(EVIDENCE / "SOURCE_MANIFEST.json")
    assert manifest["target_season"] == "2026/27"
    assert len(manifest["sources"]) >= 2
    for source in manifest["sources"]:
        for key in (
            "url",
            "publisher",
            "title",
            "retrieved_at",
            "sha256",
            "locator",
            "rules_supported",
            "refresh_trigger",
        ):
            assert source[key]
        assert source["url"].startswith("https://")
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
        if source.get("content_path"):
            capture = REPO_ROOT / source["content_path"]
            assert capture.is_file()
            assert _sha(capture) == source["sha256"]


def test_target_contains_all_38_official_deadlines() -> None:
    deadlines = {
        value
        for path, value in _target_values()
        if "deadline" in path
        and isinstance(value, str)
        and re.fullmatch(r"2026-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
    }
    assert len(deadlines) == 38


def test_target_encodes_integer_selling_price_branches() -> None:
    values = _target_values()
    text = "\n".join(str(value).lower() for _, value in values)
    paths = "\n".join(path for path, _ in values)
    assert "purchase" in paths or "purchase" in text
    assert "current" in paths or "current" in text
    assert "selling" in paths or "selling" in text
    assert "below" in text or "current_price < purchase_price" in text
    assert "equal" in text or "current_price == purchase_price" in text
    assert "floor" in text or "round" in text
    assert "tenths" in text or "integer" in text or "0.1" in text


def test_chip_windows_and_effects_are_data_driven() -> None:
    values = _target_values()
    text = "\n".join(f"{path}={value}" for path, value in values).lower().replace("-", "_").replace(" ", "_")
    for token in ("wildcard", "free_hit", "triple_captain", "bench_boost"):
        assert token in text
    for boundary in ("gameweek_1", "gameweek_19", "gameweek_20", "gameweek_38"):
        assert boundary in text or boundary.split("_")[-1] in text
    for semantic in ("restore", "consecutive", "one_chip", "saved_transfer"):
        assert semantic in text


def test_post_match_reconciliation_is_not_silently_waived() -> None:
    evidence = _load(EVIDENCE / "REPRESENTATIVE_OFFICIAL_GAME_RECONCILIATION.json")
    assert evidence["status"] == "TEMPORALLY_UNAVAILABLE"
    assert evidence["pre_gameweek_official_configuration_reconciliation"] == "PASS"
    assert evidence["production_activation_blocker"] is True
    assert evidence["waived"] is False


def test_final_handoff_is_review_ready_but_not_active() -> None:
    handoff = _load(EVIDENCE / "FINAL_READINESS_HANDOFF.json")
    assert handoff["review_handoff_status"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert handoff["human_approval_status"] == "PENDING_HUMAN_APPROVAL"
    assert handoff["production_activation_status"] == "BLOCKED"
    assert handoff["review_handoff_blockers"] == []
    blocker_codes = {row["code"] for row in handoff["production_activation_blockers"]}
    assert "HUMAN_APPROVAL_PENDING" in blocker_codes
    assert "POST_MATCH_RECONCILIATION_TEMPORALLY_UNAVAILABLE" in blocker_codes
