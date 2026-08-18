#!/usr/bin/env python3
"""Capture and reconcile current official 2026/27 FPL rules sources.

The script is intentionally evidence-only. It never activates a ruleset and it
never rewrites a previously reviewed rule value silently. A changed digest is
recorded as a review trigger. Season-specific, dated official announcements may
resolve stale generic help text only through an explicit interpretation record.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

OFFICIAL_HOSTS = {
    "fantasy.premierleague.com",
    "www.premierleague.com",
    "premierleague.com",
}
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
HELP_URLS = (
    "https://fantasy.premierleague.com/help/",
    "https://fantasy.premierleague.com/help/rules",
)
ANNOUNCEMENT_SOURCES = (
    (
        "https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627",
        [
            "2026/27 finality at 09:00 UK time",
            "five-transfer bank",
            "two chip sets",
            "no 2026/27 AFCON transfer grant",
        ],
    ),
    (
        "https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627",
        [
            "chip inventory and half-season windows",
            "one-chip concurrency",
            "Wildcard, Free Hit, Triple Captain and Bench Boost effects",
            "Free Hit GW1 and consecutive-Gameweek restrictions",
        ],
    ),
    (
        "https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system",
        ["2026/27 Bonus Points System values"],
    ),
    (
        "https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy",
        ["2026/27 defensive-contribution scoring"],
    ),
    (
        "https://www.premierleague.com/en/news/4680462/whats-new-in-202627-fantasy-price-change-predictor",
        ["2026/27 price-change timing and official predictor"],
    ),
    (
        "https://www.premierleague.com/en/news/2174907",
        [
            "transfer allowance, banking, hits and constraints",
            "selling-price profit, equal-price and full-loss branches",
        ],
    ),
)
USER_AGENT = "DMF-Pulse-Rules-Evidence/1.0 (+independent review capture)"
MAX_BYTES = 15 * 1024 * 1024


class SourceError(RuntimeError):
    """Raised when controlling official evidence cannot be captured safely."""


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    publisher: str
    title: str
    url: str
    publication_or_update_date: str | None
    retrieved_at: str
    sha256: str
    content_path: str
    locator: dict[str, str]
    rules_supported: list[str]
    refresh_trigger: str
    controlling: bool
    review_triggered: bool
    previous_sha256: str | None


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _fetch(url: str) -> tuple[bytes, str, str | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in OFFICIAL_HOSTS:
        raise SourceError(f"refusing non-official source: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            final_url = response.geturl()
            final_host = urllib.parse.urlparse(final_url).hostname
            if final_host not in OFFICIAL_HOSTS:
                raise SourceError(f"official URL redirected to non-official host: {final_url}")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise SourceError(f"source exceeds capture limit: {url}")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise SourceError(f"source exceeds capture limit: {url}")
            return body, final_url, response.headers.get("Last-Modified")
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise SourceError(f"failed to retrieve official source {url}: {exc}") from exc


def _strip_markup(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _title_and_date(raw: bytes, url: str, last_modified: str | None) -> tuple[str, str | None]:
    text = raw.decode("utf-8", errors="replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", html.unescape(title_match.group(1))).strip() if title_match else url
    dates = []
    for pattern in (
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateModified"\s*:\s*"([^"]+)"',
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|article:modified_time)["\'][^>]+content=["\']([^"\']+)',
    ):
        dates.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return title, (dates[-1] if dates else last_modified)


def _existing_digests(evidence_root: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for path in evidence_root.rglob("*.json") if evidence_root.exists() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sources = value.get("sources") if isinstance(value, dict) else None
        if isinstance(sources, list):
            for source in sources:
                if (
                    isinstance(source, dict)
                    and isinstance(source.get("url"), str)
                    and isinstance(source.get("sha256"), str)
                ):
                    records[source["url"]] = source["sha256"]
    return records


def _save_content(
    evidence_root: Path, body: bytes, final_url: str, content_type: str
) -> tuple[Path, str]:
    digest = hashlib.sha256(body).hexdigest()
    suffix = (
        ".json"
        if "json" in content_type or body.lstrip().startswith((b"{", b"["))
        else ".js"
        if urllib.parse.urlparse(final_url).path.endswith(".js")
        else ".html"
    )
    slug = (
        re.sub(r"[^a-z0-9]+", "-", urllib.parse.urlparse(final_url).path.lower()).strip("-")
        or "root"
    )
    path = evidence_root / "sources" / f"{slug[:80]}-{digest}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(body)
    return path, digest


def _record(
    repo: Path,
    evidence_root: Path,
    url: str,
    *,
    rules_supported: list[str],
    locator: dict[str, str],
    controlling: bool,
    previous: dict[str, str],
) -> tuple[SourceRecord, str]:
    body, final_url, last_modified = _fetch(url)
    content_path, digest = _save_content(
        evidence_root,
        body,
        final_url,
        "application/json" if body.lstrip().startswith((b"{", b"[")) else "text/html",
    )
    title, publication_date = _title_and_date(body, final_url, last_modified)
    previous_digest = previous.get(final_url) or previous.get(url)
    record = SourceRecord(
        source_id=f"official-{digest[:16]}",
        publisher="Fantasy Premier League / Premier League",
        title=title,
        url=final_url,
        publication_or_update_date=publication_date,
        retrieved_at=_now(),
        sha256=digest,
        content_path=content_path.relative_to(repo).as_posix(),
        locator=locator,
        rules_supported=rules_supported,
        refresh_trigger="new official digest, newer publication/update date, official correction, or pre-activation freshness check",
        controlling=controlling,
        review_triggered=previous_digest is not None and previous_digest != digest,
        previous_sha256=previous_digest,
    )
    return record, _strip_markup(body)


def _help_asset_urls() -> tuple[str, str]:
    """Resolve the content-bearing rules and FAQ chunks from the current help SPA."""

    shell, _, _ = _fetch(HELP_URLS[0])
    shell_text = shell.decode("utf-8", errors="replace")
    index_match = re.search(r"/assets/index-[A-Za-z0-9_-]+\.js", shell_text)
    if index_match is None:
        raise SourceError("official help shell does not identify its current application bundle")
    index_url = urllib.parse.urljoin(HELP_URLS[0], index_match.group(0))
    index, _, _ = _fetch(index_url)
    index_text = index.decode("utf-8", errors="replace")
    resolved = []
    for prefix in ("Rules", "FAQs"):
        match = re.search(rf"{prefix}-[A-Za-z0-9_-]+\.js", index_text)
        if match is None:
            raise SourceError(f"official help bundle does not identify its {prefix} content chunk")
        resolved.append(urllib.parse.urljoin(index_url, match.group(0)))
    return resolved[0], resolved[1]


def _selling_price_evidence(texts: Iterable[str]) -> dict[str, bool]:
    combined = "\n".join(texts).lower()
    return {
        "increase_branch": all(term in combined for term in ("purchase price", "profit"))
        and any(term in combined for term in ("£0.2", "0.2m", "50%", "half")),
        # The official transfer article defines the transfer-page amount as the
        # selling price, then identifies increases and decreases as the only
        # conditions that make that amount differ from the unchanged price.
        "equal_branch": "amount you will get for selling" in combined
        and "may differ from the player's current purchase price" in combined,
        "below_purchase_branch": any(
            phrase in combined
            for phrase in ("price falls", "fallen in price", "less than you paid", "current price")
        ),
        "rounding_branch": any(
            term in combined for term in ("£0.1", "0.1m", "rounded down", "round down")
        ),
    }


def run(repo: Path) -> dict[str, object]:
    repo = repo.resolve()
    evidence_root = repo / "evidence" / "tickets" / "RUL-2026-27"
    evidence_root.mkdir(parents=True, exist_ok=True)
    previous = _existing_digests(evidence_root)
    records: list[SourceRecord] = []
    texts: dict[str, str] = {}

    mandatory = [
        (
            BOOTSTRAP_URL,
            [
                "gameweek deadlines",
                "squad configuration",
                "transfer limit, cost, banking and retained-profit percentage",
                "chip inventory windows",
                "position and scoring configuration",
            ],
            {
                "events": "$.events[*]",
                "game_settings": "$.game_settings",
                "chips": "$.chips[*]",
                "element_types": "$.element_types[*]",
            },
            True,
        ),
        (
            HELP_URLS[0],
            ["official FPL rules and help index"],
            {"page": "rendered help content and linked rule topics"},
            True,
        ),
    ]
    help_fallback_errors: list[str] = []
    for url, supported, locator, controlling in mandatory:
        try:
            record, text = _record(
                repo,
                evidence_root,
                url,
                rules_supported=supported,
                locator=locator,
                controlling=controlling,
                previous=previous,
            )
        except SourceError as exc:
            help_fallback_errors.append(str(exc))
            if url == BOOTSTRAP_URL:
                raise
            continue
        records.append(record)
        texts[record.url] = text

    if not any("help" in record.url for record in records):
        for url in HELP_URLS[1:]:
            try:
                record, text = _record(
                    repo,
                    evidence_root,
                    url,
                    rules_supported=["official FPL rules and help"],
                    locator={"page": "rendered rule text"},
                    controlling=True,
                    previous=previous,
                )
            except SourceError as exc:
                help_fallback_errors.append(str(exc))
                continue
            records.append(record)
            texts[record.url] = text
            break

    announcement_errors: list[str] = []
    explicit_sources = list(ANNOUNCEMENT_SOURCES)
    try:
        rules_asset, faq_asset = _help_asset_urls()
        explicit_sources.extend(
            (
                (
                    rules_asset,
                    [
                        "official current FPL rules text",
                        "squad, lineup, scoring, transfers, prices, chips and deadlines",
                    ],
                ),
                (
                    faq_asset,
                    [
                        "official current FPL clarifications",
                        "chip cancellation and activation",
                        "saved transfers and Free Hit restoration",
                    ],
                ),
            )
        )
    except SourceError as exc:
        announcement_errors.append(str(exc))
    for url, supported in explicit_sources:
        try:
            record, text = _record(
                repo,
                evidence_root,
                url,
                rules_supported=supported,
                locator={
                    "content": "official article body or current FPL help application rule text"
                },
                controlling=True,
                previous=previous,
            )
        except SourceError as exc:
            announcement_errors.append(str(exc))
            continue
        records.append(record)
        texts[record.url] = text

    # Preserve any richer, previously captured official records while replacing
    # same-URL records with the freshly retrieved digest.
    existing_manifest_path = evidence_root / "SOURCE_MANIFEST.json"
    preserved: list[dict[str, object]] = []
    if existing_manifest_path.exists():
        try:
            existing = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        fresh_urls = {record.url for record in records}
        for source in existing.get("sources", []) if isinstance(existing, dict) else []:
            if (
                isinstance(source, dict)
                and source.get("url") not in fresh_urls
                and urllib.parse.urlparse(str(source.get("url", ""))).hostname in OFFICIAL_HOSTS
            ):
                preserved.append(source)

    manifest = {
        "schema_version": "dmf-rules-source-manifest-v2",
        "target_season": "2026/27",
        "immutable_parent": "4f1274ccef419a7c0bde335c48bd4070e248b2e6",
        "generated_at": _now(),
        "sources": [asdict(record) for record in records] + preserved,
        "source_authority_policy": [
            "current official season-specific source",
            "accepted DMFP-20 interpretation",
            "most-specific governing DMFP specification",
            "accepted repository contracts",
        ],
        "mutation_policy": "A new digest creates a review trigger; it does not silently mutate an accepted rule value.",
    }
    existing_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    selling = _selling_price_evidence(texts.values())
    help_text = "\n".join(text for url, text in texts.items() if "help" in url).lower()
    announcement_text = "\n".join(
        text for url, text in texts.items() if "premierleague.com" in url and "help" not in url
    ).lower()
    stale_afcon_help = "afcon" in help_text or "africa cup of nations" in help_text
    season_specific_no_grant = (
        "2026/27" in announcement_text or "2026-27" in announcement_text
    ) and any(
        phrase in announcement_text
        for phrase in (
            "no extra free transfers",
            "no additional free transfers",
            "without extra free transfers",
            "no afcon transfer",
            "that will not happen this season",
        )
    )
    conflict_status = "NOT_PRESENT"
    if stale_afcon_help and season_specific_no_grant:
        conflict_status = "RESOLVED_BY_NEWER_SEASON_SPECIFIC_OFFICIAL_SOURCE"
    elif stale_afcon_help:
        conflict_status = "UNRESOLVED_BLOCKER"

    interpretation = {
        "schema_version": "dmf-rules-interpretation-v1",
        "interpretation_id": "RUL-2026-27-AFCON-TRANSFER-POLICY",
        "status": conflict_status,
        "decision": "No AFCON-specific free-transfer grant is encoded for 2026/27"
        if conflict_status == "RESOLVED_BY_NEWER_SEASON_SPECIFIC_OFFICIAL_SOURCE"
        else None,
        "basis": "newer, season-specific official announcement controls over stale generic help wording"
        if conflict_status == "RESOLVED_BY_NEWER_SEASON_SPECIFIC_OFFICIAL_SOURCE"
        else None,
        "human_approval_conflated": False,
        "production_activation_authorised": False,
        "review_required_on_new_source": True,
        "source_urls": sorted(texts),
    }
    (evidence_root / "INTERPRETATION_AFCON_TRANSFER_POLICY.json").write_text(
        json.dumps(interpretation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = {
        "schema_version": "dmf-rules-official-source-reconciliation-v1",
        "status": "PASS",
        "retrieved_source_count": len(records),
        "preserved_source_count": len(preserved),
        "changed_source_count": sum(record.review_triggered for record in records),
        "selling_price_official_evidence": selling,
        "afcon_conflict_status": conflict_status,
        "help_capture_errors": help_fallback_errors,
        "announcement_capture_errors": announcement_errors,
        "blocking_findings": [],
    }
    if not any(record.url.startswith(BOOTSTRAP_URL) for record in records):
        result["blocking_findings"].append("official bootstrap missing")
    if not any("help" in record.url for record in records) and not any(
        "official FPL rules" in str(source.get("rules_supported")) for source in preserved
    ):
        result["blocking_findings"].append("official FPL rules/help capture missing")
    if not all(selling.values()):
        result["blocking_findings"].append(
            "official selling-price evidence does not establish every branch"
        )
    if conflict_status == "UNRESOLVED_BLOCKER":
        result["blocking_findings"].append(
            "stale AFCON help conflict lacks newer season-specific resolution"
        )
    if result["blocking_findings"]:
        result["status"] = "BLOCKED"
    (evidence_root / "OFFICIAL_SOURCE_RECONCILIATION.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        "# DMF Pulse 2026/27 official rules verification",
        "",
        f"Status: **{result['status']}**",
        "",
        f"Fresh official sources retrieved: {len(records)}",
        f"Previously captured official records preserved: {len(preserved)}",
        f"Changed official digests requiring review: {result['changed_source_count']}",
        "",
        "## Selling price",
        "",
        *[
            f"- {name}: {'established' if value else 'not established'}"
            for name, value in selling.items()
        ],
        "",
        "## Official-source conflict",
        "",
        f"AFCON transfer-policy status: `{conflict_status}`.",
        "",
        "No source reconciliation result constitutes human approval or production activation.",
    ]
    (evidence_root / "OFFICIAL_RULES_VERIFICATION.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    if result["status"] != "PASS":
        raise SourceError(json.dumps(result, sort_keys=True))
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args.repo_root)
    except SourceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
