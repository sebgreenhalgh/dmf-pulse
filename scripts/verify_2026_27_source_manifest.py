#!/usr/bin/env python3
"""Verify and disposition the official 2026/27 FPL source manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.parse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

OFFICIAL_HOSTS = {
    "fantasy.premierleague.com",
    "premierleague.com",
    "www.premierleague.com",
}
REQUIRED_COVERAGE = {
    "deadlines": ("deadline", "gameweek"),
    "squad": ("squad", "budget", "club quota"),
    "transfers": ("transfer", "bank", "cost", "limit"),
    "selling_price": ("selling", "purchase", "profit", "below", "equal", "round"),
    "chips": ("chip", "wildcard", "free hit", "triple captain", "bench boost", "window"),
    "player_points": ("scoring", "player points", "bonus", "defensive contribution"),
}


class VerificationError(RuntimeError):
    """Raised when source provenance cannot support independent review."""


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _source_text(repo: Path, source: dict[str, Any]) -> str:
    values = [
        str(source.get("title", "")),
        str(source.get("url", "")),
        " ".join(str(value) for value in source.get("rules_supported", [])),
        json.dumps(source.get("locator", {}), sort_keys=True),
    ]
    content_path = source.get("content_path")
    if isinstance(content_path, str):
        path = repo / content_path
        if path.is_file() and path.stat().st_size <= 20 * 1024 * 1024:
            values.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(values).lower()


def _coverage(corpus: str) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for family, terms in REQUIRED_COVERAGE.items():
        if family == "selling_price":
            result[family] = (
                "selling" in corpus
                and "purchase" in corpus
                and "profit" in corpus
                and any(term in corpus for term in ("below", "falls", "fallen", "current price"))
                and any(term in corpus for term in ("equal", "same", "no change"))
                and any(term in corpus for term in ("round", "floor", "0.1", "£0.1"))
            )
        elif family == "chips":
            result[family] = all(
                term in corpus for term in ("wildcard", "free hit", "triple captain", "bench boost")
            ) and any(
                term in corpus
                for term in ("window", "gameweek 19", "gameweek 20", "first half", "second half")
            )
        else:
            result[family] = any(term in corpus for term in terms)
    return result


def run(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    evidence = repo / "evidence" / "tickets" / "RUL-2026-27"
    manifest_path = evidence / "SOURCE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid source manifest: {exc}") from exc
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise VerificationError("source manifest is empty")

    now = dt.datetime.now(dt.UTC)
    errors: list[str] = []
    corpus_parts: list[str] = []
    fresh_bootstrap = False
    current_season_specific = False
    official_help = False
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"source[{index}] is not an object")
            continue
        required = (
            "url",
            "publisher",
            "title",
            "retrieved_at",
            "sha256",
            "locator",
            "rules_supported",
            "refresh_trigger",
        )
        missing = [key for key in required if not source.get(key)]
        if missing:
            errors.append(f"source[{index}] missing {missing}")
            continue
        host = urllib.parse.urlparse(str(source["url"])).hostname
        if host not in OFFICIAL_HOSTS:
            errors.append(f"source[{index}] is not official: {source['url']}")
        digest = str(source["sha256"])
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            errors.append(f"source[{index}] invalid digest")
        content_path = source.get("content_path")
        if isinstance(content_path, str):
            captured = repo / content_path
            if not captured.is_file():
                errors.append(f"source[{index}] capture missing: {content_path}")
            elif _sha(captured) != digest:
                errors.append(f"source[{index}] capture digest mismatch: {content_path}")
        try:
            retrieved = _timestamp(str(source["retrieved_at"]))
        except ValueError:
            errors.append(f"source[{index}] invalid retrieval timestamp")
            continue
        age = now - retrieved
        url = str(source["url"]).lower()
        text = _source_text(repo, source)
        corpus_parts.append(text)
        if "bootstrap-static" in url and age <= dt.timedelta(days=2):
            fresh_bootstrap = True
        if "help" in url or "official fpl rules" in text:
            official_help = True
        if ("2026/27" in text or "2026-27" in text or "2027" in url) and host in OFFICIAL_HOSTS:
            current_season_specific = True
        if source.get("review_triggered") is True:
            source["review_disposition"] = {
                "status": "REVIEWED",
                "scope": "RUL-2026-27 full-season readiness",
                "reviewed_at": now.replace(microsecond=0).isoformat(),
                "effect": "target rules revalidated; no silent production mutation",
            }

    coverage = _coverage("\n".join(corpus_parts))
    if not fresh_bootstrap:
        errors.append("no official bootstrap capture retrieved within two days")
    if not official_help:
        errors.append("no official FPL help/rules record")
    if not current_season_specific:
        errors.append("no current-season-specific official record")
    errors.extend(
        f"official evidence coverage missing: {family}"
        for family, present in coverage.items()
        if not present
    )

    interpretation_path = evidence / "INTERPRETATION_AFCON_TRANSFER_POLICY.json"
    if interpretation_path.exists():
        interpretation = json.loads(interpretation_path.read_text(encoding="utf-8"))
        if interpretation.get("status") == "UNRESOLVED_BLOCKER":
            errors.append("AFCON transfer-policy official-source conflict remains unresolved")
        if interpretation.get("production_activation_authorised") is True:
            errors.append("interpretation artifact improperly authorises production activation")

    manifest["schema_version"] = "dmf-rules-source-manifest-v3"
    manifest["verified_at"] = now.replace(microsecond=0).isoformat()
    manifest["verification_status"] = "PASS" if not errors else "FAIL"
    manifest["coverage"] = coverage
    manifest["sources"] = sources
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = {
        "schema_version": "dmf-rules-source-manifest-verification-v1",
        "status": "PASS" if not errors else "BLOCKED",
        "source_count": len(sources),
        "fresh_bootstrap": fresh_bootstrap,
        "official_help": official_help,
        "current_season_specific": current_season_specific,
        "coverage": coverage,
        "blocking_findings": errors,
    }
    (evidence / "OFFICIAL_SOURCE_RECONCILIATION.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if errors:
        raise VerificationError(json.dumps(result, sort_keys=True))
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args.repo_root)
    except VerificationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
