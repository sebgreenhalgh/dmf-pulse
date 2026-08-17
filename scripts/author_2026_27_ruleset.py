#!/usr/bin/env python3
"""Author and reconcile the 2026/27 target ruleset without season policy in code.

This is an evidence-driven migration utility for the dedicated readiness branch.
It locates the existing split-YAML target and reference rulesets, fills only
recognised target-season fields, captures the official bootstrap payload, and
emits a machine-readable change/evidence report. Unknown or ambiguous required
fields fail closed rather than being guessed.

The runtime rules engine continues to consume compiled rules data; this utility
is never imported by production code.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, MutableMapping, Sequence

import yaml

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
TARGET_SEASON = "2026/27"
REFERENCE_SEASON = "2025/26"
IMMUTABLE_PARENT = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
PLACEHOLDER_RE = re.compile(
    r"^(?:tbd|todo|unknown|unverified|unresolved|pending(?:[_ -](?:evidence|verification|research))?|not[_ -]set)$",
    re.IGNORECASE,
)


class AuthoringError(RuntimeError):
    """Raised for ambiguous or unsupported target authoring state."""


@dataclass
class Change:
    file: str
    path: str
    before: Any
    after: Any
    reason: str


@dataclass
class Context:
    repo_root: Path
    target_root: Path
    reference_root: Path | None
    bootstrap: dict[str, Any]
    source_path: Path
    dry_run: bool
    changes: list[Change] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _is_placeholder(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(PLACEHOLDER_RE.fullmatch(value.strip())))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_yaml(path: Path, value: Any) -> None:
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
        newline="\n",
    )


def _yaml_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".yaml", ".yml"}
        and not any(part in {".git", ".venv", "site-packages"} for part in path.parts)
    )


def _season_score(path: Path, season: str, target: bool) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    forms = {season, season.replace("/", "-"), season.replace("/", "_"), season.replace("/", "")}
    score = sum(20 for form in forms if form in text or form in path.as_posix())
    lowered = path.as_posix().lower()
    if "rules" in lowered:
        score += 5
    if target and "target" in lowered:
        score += 12
    if not target and ("reference" in lowered or "optimiser" in lowered or "optimizer" in lowered):
        score += 8
    if "fixture" in lowered or "test" in lowered or "evidence" in lowered:
        score -= 10
    return score


def _candidate_roots(repo: Path, season: str, target: bool) -> list[tuple[int, Path]]:
    scores: dict[Path, int] = {}
    counts: dict[Path, int] = {}
    for path in _yaml_files(repo):
        score = _season_score(path, season, target)
        if score <= 0:
            continue
        for parent in [path.parent, *list(path.parents)[:3]]:
            if parent == repo.parent or not parent.is_relative_to(repo):
                continue
            scores[parent] = scores.get(parent, 0) + score
            counts[parent] = counts.get(parent, 0) + 1
    candidates = [
        (score + min(counts[root], 10), root)
        for root, score in scores.items()
        if counts[root] >= 1
    ]
    return sorted(candidates, key=lambda item: (-item[0], len(item[1].parts), item[1].as_posix()))


def discover_ruleset(repo: Path, season: str, *, target: bool) -> Path:
    candidates = _candidate_roots(repo, season, target)
    if not candidates:
        raise AuthoringError(f"no split-YAML ruleset discovered for {season}")
    best_score, best = candidates[0]
    contenders = [root for score, root in candidates if score == best_score and root != best]
    if contenders and all(root.parent != best and best.parent != root for root in contenders):
        raise AuthoringError(
            f"ambiguous ruleset root for {season}: {[best.as_posix(), *[p.as_posix() for p in contenders]]}"
        )
    return best


def capture_bootstrap(repo: Path, *, offline: Path | None) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    retrieved_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    if offline is not None:
        raw = offline.read_bytes()
        source_url = BOOTSTRAP_URL
        retrieval = "provided_snapshot"
    else:
        request = urllib.request.Request(
            BOOTSTRAP_URL,
            headers={"User-Agent": "DMF-Pulse-Rules-Readiness/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                source_url = response.geturl()
        except (OSError, urllib.error.URLError) as exc:
            raise AuthoringError(f"official bootstrap capture failed: {exc}") from exc
        retrieval = "live_official"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthoringError("official bootstrap payload is not valid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise AuthoringError("official bootstrap payload lacks events")
    events = payload["events"]
    if len(events) != 38:
        raise AuthoringError(f"official bootstrap does not expose exactly 38 events: {len(events)}")
    digest = hashlib.sha256(raw).hexdigest()
    evidence_dir = repo / "evidence" / "tickets" / "RUL-2026-27" / "sources"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    destination = evidence_dir / f"fpl_bootstrap_static_{digest}.json"
    if not destination.exists():
        destination.write_bytes(raw)
    source_record = {
        "source_id": f"official-fpl-bootstrap-{digest[:12]}",
        "publisher": "Fantasy Premier League / Premier League",
        "title": "Official FPL bootstrap-static configuration",
        "url": source_url,
        "retrieved_at": retrieved_at,
        "retrieval_mode": retrieval,
        "sha256": digest,
        "locator": {
            "events": "$.events[*]",
            "game_settings": "$.game_settings",
            "chips": "$.chips[*]",
            "element_types": "$.element_types[*]",
        },
        "rules_supported": [
            "season identity and gameweek deadlines",
            "squad size and budget",
            "club quota",
            "transfer limit and transfer cost",
            "selling-value retained-profit percentage",
            "chip inventory and windows",
            "position quotas and scoring configuration",
        ],
        "refresh_trigger": "new official payload digest, official correction, or pre-activation freshness check",
    }
    return payload, destination, source_record


def _set(ctx: Context, file: Path, node: MutableMapping[str, Any], key: str, value: Any, path: str, reason: str, *, only_placeholder: bool = False) -> bool:
    before = node.get(key)
    if only_placeholder and not _is_placeholder(before):
        return False
    if _json_safe(before) == _json_safe(value):
        return False
    node[key] = value
    ctx.changes.append(
        Change(
            file=file.relative_to(ctx.repo_root).as_posix(),
            path=path,
            before=_json_safe(before),
            after=_json_safe(value),
            reason=reason,
        )
    )
    return True


def _money_value(existing: Any, *, tenths: int, millions: float) -> int | float:
    if isinstance(existing, int):
        if existing >= 500 or existing == 0:
            return tenths
        return int(millions)
    if isinstance(existing, float):
        return millions
    return tenths


def _deadline_rows(bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in bootstrap["events"]:
        event_id = event.get("id")
        deadline = event.get("deadline_time")
        if not isinstance(event_id, int) or not isinstance(deadline, str):
            raise AuthoringError("official bootstrap event lacks integer id or deadline_time")
        rows.append({"gameweek": event_id, "deadline_time": deadline})
    if [row["gameweek"] for row in rows] != list(range(1, 39)):
        raise AuthoringError("official bootstrap event ids are not 1..38")
    return rows


def _chip_name(node: MutableMapping[str, Any]) -> str | None:
    for key in ("name", "id", "chip", "chip_id", "type", "code"):
        value = node.get(key)
        if isinstance(value, str):
            norm = _normal(value)
            aliases = {
                "wildcard": "wildcard",
                "wc": "wildcard",
                "free_hit": "free_hit",
                "freehit": "free_hit",
                "fh": "free_hit",
                "triple_captain": "triple_captain",
                "triplecaptain": "triple_captain",
                "3xc": "triple_captain",
                "bench_boost": "bench_boost",
                "benchboost": "bench_boost",
                "bboost": "bench_boost",
            }
            if norm in aliases:
                return aliases[norm]
    return None


def _author_mapping(ctx: Context, file: Path, node: MutableMapping[str, Any], trail: tuple[str, ...]) -> None:
    normalized_trail = tuple(_normal(part) for part in trail)
    path_text = ".".join(normalized_trail)
    game_settings = ctx.bootstrap.get("game_settings") or {}
    if not isinstance(game_settings, dict):
        raise AuthoringError("official bootstrap game_settings must be an object")

    aliases: dict[str, tuple[Any, str]] = {
        "squad_size": (game_settings.get("squad_squadsize", 15), "official bootstrap game_settings.squad_squadsize"),
        "starting_xi_size": (11, "official FPL lineup contract"),
        "starting_lineup_size": (11, "official FPL lineup contract"),
        "max_players_per_club": (game_settings.get("squad_team_limit", 3), "official bootstrap game_settings.squad_team_limit"),
        "club_quota": (game_settings.get("squad_team_limit", 3), "official bootstrap game_settings.squad_team_limit"),
        "max_from_one_club": (game_settings.get("squad_team_limit", 3), "official bootstrap game_settings.squad_team_limit"),
        "max_bank": (game_settings.get("transfers_bank", 5), "official bootstrap game_settings.transfers_bank"),
        "maximum_bank": (game_settings.get("transfers_bank", 5), "official bootstrap game_settings.transfers_bank"),
        "max_free_transfers": (game_settings.get("transfers_bank", 5), "official bootstrap game_settings.transfers_bank"),
        "transfer_hit_cost": (game_settings.get("transfers_cost", 4), "official bootstrap game_settings.transfers_cost"),
        "paid_transfer_cost": (game_settings.get("transfers_cost", 4), "official bootstrap game_settings.transfers_cost"),
        "max_transfers_per_gameweek": (game_settings.get("transfers_limit", 20), "official bootstrap game_settings.transfers_limit"),
        "maximum_transfers_per_gameweek": (game_settings.get("transfers_limit", 20), "official bootstrap game_settings.transfers_limit"),
        "profit_retained_percentage": (game_settings.get("transfers_sell_on_fee", 0.5), "official bootstrap game_settings.transfers_sell_on_fee"),
        "sell_on_fee": (game_settings.get("transfers_sell_on_fee", 0.5), "official bootstrap game_settings.transfers_sell_on_fee"),
    }
    for key in list(node):
        normalized = _normal(str(key))
        if normalized in aliases:
            value, reason = aliases[normalized]
            if value is not None:
                _set(ctx, file, node, key, value, f"{path_text}.{normalized}", reason)
        elif normalized in {"initial_budget", "squad_budget", "budget", "starting_budget"} and "budget" in path_text + "." + normalized:
            existing = node[key]
            value = _money_value(existing, tenths=int(game_settings.get("squad_total_spend", 1000)), millions=100.0)
            _set(ctx, file, node, key, value, f"{path_text}.{normalized}", "official bootstrap game_settings.squad_total_spend")
        elif normalized in {"season", "season_id", "season_code", "target_season"}:
            existing = node[key]
            if isinstance(existing, str):
                if "_" in existing:
                    replacement = "2026_27"
                elif "-" in existing and "/" not in existing:
                    replacement = "2026-27"
                else:
                    replacement = TARGET_SEASON
                _set(ctx, file, node, key, replacement, f"{path_text}.{normalized}", "target-season identity")

    chip = _chip_name(node)
    if chip is not None:
        for key in list(node):
            normalized = _normal(str(key))
            if normalized in {"copies", "count", "inventory", "available_count", "total_copies"} and isinstance(node[key], (int, type(None), str)):
                _set(ctx, file, node, key, 2, f"{path_text}.{normalized}", "official bootstrap exposes two inventory rows for each chip")
            elif normalized in {"one_chip_per_gameweek", "one_chip_per_gw"}:
                _set(ctx, file, node, key, True, f"{path_text}.{normalized}", "official chip concurrency rule")
            elif chip == "free_hit" and normalized in {"consecutive_gameweeks_allowed", "can_use_consecutively"}:
                _set(ctx, file, node, key, False, f"{path_text}.{normalized}", "official Free Hit consecutive-gameweek restriction")

    for key, value in list(node.items()):
        child_trail = (*trail, str(key))
        if isinstance(value, dict):
            _author_mapping(ctx, file, value, child_trail)
        elif isinstance(value, list):
            _author_list(ctx, file, node, key, value, child_trail)


def _looks_like_deadlines(value: list[Any]) -> bool:
    dict_rows = [row for row in value if isinstance(row, dict)]
    if not dict_rows:
        return False
    keys = {_normal(str(key)) for row in dict_rows for key in row}
    return bool(keys & {"deadline_time", "deadline", "deadline_at"}) and bool(keys & {"gameweek", "gameweek_id", "event", "event_id", "id", "gw"})


def _author_deadline_list(ctx: Context, file: Path, parent: MutableMapping[str, Any], key: str, value: list[Any], path: str) -> bool:
    if not _looks_like_deadlines(value):
        return False
    sample = next(row for row in value if isinstance(row, dict))
    normalized = {_normal(str(k)): k for k in sample}
    id_key = next((normalized[k] for k in ("gameweek", "gameweek_id", "event", "event_id", "gw", "id") if k in normalized), "gameweek")
    deadline_key = next((normalized[k] for k in ("deadline_time", "deadline_at", "deadline") if k in normalized), "deadline_time")
    label_key = normalized.get("name")
    rows = []
    for row in _deadline_rows(ctx.bootstrap):
        result: dict[str, Any] = {id_key: row["gameweek"], deadline_key: row["deadline_time"]}
        if label_key is not None:
            result[label_key] = f"Gameweek {row['gameweek']}"
        for optional_key, optional_value in sample.items():
            if optional_key not in result and _normal(str(optional_key)) not in {"provisional", "status", "source_id"}:
                result[optional_key] = optional_value
        if "source_id" in sample:
            result["source_id"] = f"official-fpl-bootstrap-{hashlib.sha256(ctx.source_path.read_bytes()).hexdigest()[:12]}"
        rows.append(result)
    before = copy.deepcopy(value)
    if _json_safe(before) == _json_safe(rows):
        return True
    parent[key] = rows
    ctx.changes.append(
        Change(
            file=file.relative_to(ctx.repo_root).as_posix(),
            path=path,
            before=_json_safe(before),
            after=_json_safe(rows),
            reason="official bootstrap $.events[1..38].deadline_time",
        )
    )
    return True


def _author_list(ctx: Context, file: Path, parent: MutableMapping[str, Any], key: str, value: list[Any], trail: tuple[str, ...]) -> None:
    path = ".".join(_normal(part) for part in trail)
    if "deadline" in path or "gameweek" in path or "event" in path:
        if _author_deadline_list(ctx, file, parent, key, value, path):
            return
    for index, item in enumerate(value):
        if isinstance(item, dict):
            _author_mapping(ctx, file, item, (*trail, str(index)))
        elif isinstance(item, list):
            holder = {"value": item}
            _author_list(ctx, file, holder, "value", item, (*trail, str(index)))
            value[index] = holder["value"]


def _copy_missing_reference_files(ctx: Context) -> list[Path]:
    if ctx.reference_root is None:
        return []
    target_names = {path.name for path in _yaml_files(ctx.target_root)}
    created: list[Path] = []
    for source in _yaml_files(ctx.reference_root):
        if source.name in target_names:
            continue
        lowered = source.as_posix().lower()
        if any(token in lowered for token in ("fixture", "test", "golden")):
            continue
        relative = source.relative_to(ctx.reference_root)
        destination = ctx.target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        text = text.replace("2025/26", "2026/27").replace("2025-26", "2026-27").replace("2025_26", "2026_27")
        destination.write_text(text, encoding="utf-8", newline="\n")
        created.append(destination)
        ctx.changes.append(
            Change(
                file=destination.relative_to(ctx.repo_root).as_posix(),
                path="$",
                before=None,
                after="copied and season-migrated from accepted reference",
                reason=f"target split file missing; source={source.relative_to(ctx.repo_root).as_posix()}",
            )
        )
    return created


def _flatten(value: Any, trail: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(child, (*trail, _normal(str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten(child, (*trail, str(index)))
    else:
        yield trail, value


def _required_semantics(target_root: Path) -> dict[str, bool]:
    values: list[tuple[str, Any]] = []
    text_parts: list[str] = []
    for path in _yaml_files(target_root):
        data = _read_yaml(path)
        values.extend((".".join(trail), value) for trail, value in _flatten(data))
        text_parts.append(path.read_text(encoding="utf-8", errors="ignore").lower())
    text = "\n".join(text_parts)
    path_text = "\n".join(path for path, _ in values)
    scalar_text = "\n".join(str(value).lower() for _, value in values)

    def has(*terms: str) -> bool:
        return all(term.lower() in text for term in terms)

    deadline_rows = 0
    deadline_values: set[str] = set()
    for path, value in values:
        if "deadline" in path and isinstance(value, str) and re.match(r"^2026-\d\d-\d\dT", value):
            deadline_values.add(value)
    deadline_rows = len(deadline_values)
    return {
        "season_identity": "2026/27" in text or "2026-27" in text or "2026_27" in text,
        "squad_size_15": any(("squad_size" in p or "squadsize" in p) and v == 15 for p, v in values),
        "budget_1000_or_100": any("budget" in p and v in {1000, 100, 100.0} for p, v in values),
        "club_quota_3": any(("club" in p or "team_limit" in p) and v == 3 for p, v in values),
        "transfer_bank_5": any(("bank" in p or "free_transfer" in p) and "max" in p and v == 5 for p, v in values),
        "transfer_limit_20": any("transfer" in p and ("limit" in p or "max" in p) and v == 20 for p, v in values),
        "transfer_hit_4": any("transfer" in p and ("hit" in p or "cost" in p) and abs(float(v)) == 4 for p, v in values if isinstance(v, (int, float))),
        "selling_price_increase_branch": has("purchase", "current", "profit") and ("floor" in text or "round" in text),
        "selling_price_equal_branch": has("equal", "purchase") or has("current_price == purchase_price"),
        "selling_price_below_branch": has("below", "purchase") or has("current_price < purchase_price"),
        "integer_price_units": ("0.1" in text or "tenths" in text or "integer" in text) and "price" in text,
        "wildcard": "wildcard" in text,
        "free_hit": "free_hit" in text or "free hit" in text,
        "triple_captain": "triple_captain" in text or "triple captain" in text,
        "bench_boost": "bench_boost" in text or "bench boost" in text,
        "chip_two_windows": ("1" in scalar_text and "19" in scalar_text and "20" in scalar_text and "38" in scalar_text and "window" in text),
        "one_chip_per_gameweek": has("one", "chip", "gameweek") or "one_chip_per" in text,
        "free_hit_restoration": has("free", "hit", "restor"),
        "free_hit_non_consecutive": has("free", "hit", "consecutive"),
        "deadlines_38": deadline_rows == 38,
        "capability_player_points": "player_points" in text,
        "capability_initial_squad": "gw1_initial_squad" in text,
        "capability_transfer_state": "transfer_state" in text,
        "capability_chip_state": "chip_state" in text,
        "capability_full_season": "full_season" in text,
    }


def _diff(reference: Any, target: Any, trail: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(reference, dict) and isinstance(target, dict):
        rows: list[dict[str, Any]] = []
        for key in sorted(set(reference) | set(target), key=str):
            if key not in reference:
                rows.append({"path": ".".join((*trail, str(key))), "reference": None, "target": _json_safe(target[key]), "change": "added"})
            elif key not in target:
                rows.append({"path": ".".join((*trail, str(key))), "reference": _json_safe(reference[key]), "target": None, "change": "removed"})
            else:
                rows.extend(_diff(reference[key], target[key], (*trail, str(key))))
        return rows
    if isinstance(reference, list) and isinstance(target, list):
        if _json_safe(reference) == _json_safe(target):
            return []
        return [{"path": ".".join(trail), "reference": _json_safe(reference), "target": _json_safe(target), "change": "changed_list"}]
    if _json_safe(reference) != _json_safe(target):
        return [{"path": ".".join(trail), "reference": _json_safe(reference), "target": _json_safe(target), "change": "changed"}]
    return []


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    target = args.target_root.resolve() if args.target_root else discover_ruleset(repo, TARGET_SEASON, target=True)
    reference: Path | None
    try:
        reference = args.reference_root.resolve() if args.reference_root else discover_ruleset(repo, REFERENCE_SEASON, target=False)
    except AuthoringError:
        reference = None
    bootstrap, source_path, source_record = capture_bootstrap(repo, offline=args.bootstrap_snapshot)
    ctx = Context(repo, target, reference, bootstrap, source_path, args.dry_run)
    _copy_missing_reference_files(ctx)
    for path in _yaml_files(target):
        data = _read_yaml(path)
        if isinstance(data, dict):
            before_changes = len(ctx.changes)
            _author_mapping(ctx, path, data, ())
            if len(ctx.changes) != before_changes and not args.dry_run:
                _write_yaml(path, data)

    semantics = _required_semantics(target)
    missing = sorted(name for name, present in semantics.items() if not present)
    placeholders: list[dict[str, Any]] = []
    for path in _yaml_files(target):
        data = _read_yaml(path)
        for trail, value in _flatten(data):
            if _is_placeholder(value):
                placeholders.append({"file": path.relative_to(repo).as_posix(), "path": ".".join(trail), "value": value})

    evidence_root = repo / "evidence" / "tickets" / "RUL-2026-27"
    evidence_root.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence_root / "SOURCE_MANIFEST.json"
    manifest = {
        "schema_version": "dmf-rules-source-manifest-v1",
        "target_season": TARGET_SEASON,
        "immutable_parent": IMMUTABLE_PARENT,
        "sources": [source_record],
        "policy": "new source digests require review and never silently activate a ruleset",
    }
    if not args.dry_run:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    diff_rows: list[dict[str, Any]] = []
    if reference is not None:
        target_by_name = {path.name: path for path in _yaml_files(target)}
        for ref_path in _yaml_files(reference):
            target_path = target_by_name.get(ref_path.name)
            if target_path is None:
                continue
            diff_rows.extend(
                {"file": target_path.relative_to(repo).as_posix(), **row}
                for row in _diff(_read_yaml(ref_path), _read_yaml(target_path))
            )
    diff_payload = {
        "schema_version": "dmf-rules-target-reference-diff-v1",
        "reference_season": REFERENCE_SEASON,
        "target_season": TARGET_SEASON,
        "reference_root": reference.relative_to(repo).as_posix() if reference else None,
        "target_root": target.relative_to(repo).as_posix(),
        "differences": diff_rows,
    }
    if not args.dry_run:
        (evidence_root / "TARGET_VS_REFERENCE_DIFF.json").write_text(
            json.dumps(diff_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        approval = {
            "schema_version": "dmf-rules-human-approval-v1",
            "target_season": TARGET_SEASON,
            "status": "PENDING_HUMAN_APPROVAL",
            "approved": False,
            "approved_by": None,
            "approved_at": None,
            "ruleset_hash": None,
            "note": "This template is not an approval and cannot activate production.",
        }
        (evidence_root / "PENDING_HUMAN_APPROVAL.json").write_text(
            json.dumps(approval, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    report = {
        "schema_version": "dmf-rules-target-authoring-report-v1",
        "status": "PASS" if not missing and not placeholders else "BLOCKED",
        "repo_root": repo.as_posix(),
        "target_root": target.relative_to(repo).as_posix(),
        "reference_root": reference.relative_to(repo).as_posix() if reference else None,
        "source_snapshot": source_path.relative_to(repo).as_posix(),
        "source_sha256": source_record["sha256"],
        "changes": [change.__dict__ for change in ctx.changes],
        "semantic_checks": semantics,
        "missing_semantics": missing,
        "unresolved_placeholders": placeholders,
        "dry_run": args.dry_run,
    }
    report_path = evidence_root / "TARGET_AUTHORING_REPORT.json"
    if not args.dry_run:
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if missing or placeholders:
        raise AuthoringError(
            f"target remains blocked: missing_semantics={missing}; unresolved_placeholders={len(placeholders)}"
        )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--bootstrap-snapshot", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run(args)
    except AuthoringError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
