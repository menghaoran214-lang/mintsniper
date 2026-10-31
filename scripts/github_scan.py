#!/usr/bin/env python3
"""Layer 1 - GitHub development-signal scan.

Finds repositories that recently started shipping on-chain projects, before
those projects announce themselves publicly. Read-only: only the GitHub REST
search API is used.

Usage:
    python3 github_scan.py [--days 5] [--limit 20] [--json]

Requires a personal GitHub token for reliable use:
    export GITHUB_TOKEN=ghp_xxx      (or write it to <skill>/state/github_token)

Anonymous access works but is limited to 10 search requests per minute, so
scans with many query groups are slow or may fail without a token.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    Candidate,
    days_ago_str,
    github_token,
    http_json,
    iso,
    log,
    utc_now,
)

# Each group is a narrow query. Broad keyword queries are deliberately avoided:
# they match tens of thousands of unrelated repositories and dilute the signal.
QUERY_GROUPS = [
    ("agent-wallet", 'created:>{since} ("agent id" OR "agentic wallet" OR "agent id exclusive") in:readme,description'),
    ("agent-mint", 'created:>{since} ("free mint" OR "fair mint" OR "agent-gated" OR "agent-only") in:readme,description'),
    ("bnb-launchpad", 'created:>{since} (bonding-curve OR launchpad OR "fair launch") (bnb OR bsc) in:name,description,readme'),
    ("bsc-nft-mint", 'created:>{since} ("free mint" OR "mint live" OR "minting now") bsc in:name,description'),
    ("topic-fair-launch", "created:>{since} topic:fair-launch"),
    ("topic-bnb-chain", "created:>{since} topic:bnb-chain"),
    ("topic-ai-agents", "created:>{since} topic:ai-agents"),
]

# Strong signals: worth many points. Weak signals: worth few.
STRONG_SIGNALS = {
    "agent id": 6,
    "agentic wallet": 6,
    "agent id exclusive": 6,
    "free mint": 5,
    "fair mint": 5,
    "agent-gated": 5,
    "agent-only": 5,
    "agent only launchpad": 5,
    "proof of agent": 5,
    "whitelist": 4,
    "allowlist": 3,
    "claim nft": 4,
    "mint": 3,
    "bnb chain": 4,
    "bnbchain": 4,
    "bsc": 3,
    "launchpad": 4,
    "bonding curve": 3,
    "airdrop": 3,
    "binance": 3,
    "soulbound": 3,
}

WEAK_SIGNALS = {"mint", "nft", "agent", "crypto", "token", "bsc"}


def score_repo(item: dict) -> tuple[int, list[str]]:
    """Score a repository by how likely it is to be a mintable project."""
    blob = " ".join(
        [
            item.get("name") or "",
            item.get("description") or "",
            " ".join(item.get("topics") or []),
        ]
    ).lower()

    score = 0
    tags: list[str] = []
    for needle, weight in STRONG_SIGNALS.items():
        if needle in blob:
            score += weight
            tags.append(needle)
    # A homepage usually means the project is live and therefore mintable.
    if item.get("homepage"):
        score += 3
        tags.append("has-homepage")
    # Attention is a weak tiebreaker only; new projects usually have few stars.
    score += min(int(item.get("stargazers_count") or 0), 8)
    return score, tags


def fetch_group(query: str, since: str, per_page: int, token: str | None) -> list[dict]:
    q = query.format(since=since)
    encoded = _quote_plus(q)
    url = (
        "https://api.github.com/search/repositories"
        f"?q={encoded}&sort=created&order=desc&per_page={per_page}"
    )
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = http_json(url, headers=headers, timeout=30, retries=3)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return []


def _quote_plus(text: str) -> str:
    import urllib.parse

    return urllib.parse.quote_plus(text)


def scan(days: int = 5, limit: int = 20, min_score: int = 8) -> dict:
    token = github_token()
    since = days_ago_str(days)
    started = utc_now()

    if not token:
        log(
            "[github] no GITHUB_TOKEN found - anonymous search is limited to "
            "10 requests/minute, results may be partial"
        )

    seen: dict[str, dict] = {}
    per_group: dict[str, int] = {}
    failures: list[str] = []

    for name, query in QUERY_GROUPS:
        try:
            items = fetch_group(query, since, 30, token)
        except Exception as exc:  # noqa: BLE001 - keep scanning other groups
            failures.append(f"{name}: {exc}")
            log(f"[github] group '{name}' failed: {exc}")
            time.sleep(2)
            continue
        per_group[name] = len(items)
        for item in items:
            full = item.get("full_name")
            if not full:
                continue
            entry = seen.setdefault(full, item)
            entry.setdefault("_groups", [])
            if name not in entry["_groups"]:
                entry["_groups"].append(name)
        time.sleep(3 if token else 7)

    candidates: list[Candidate] = []
    for item in seen.values():
        score, tags = score_repo(item)
        if score < min_score:
            continue
        groups = item.get("_groups") or []
        # A repo found by several independent query groups is a stronger signal.
        if len(groups) > 1:
            score += 4
            tags.append("multi-group")
        created = item.get("created_at") or ""
        homepage = item.get("homepage") or ""
        caveats = [
            "repository creation time is not the same as the public launch or the first mint",
        ]
        if not homepage:
            caveats.append("no homepage declared, so the project may not be live yet")
        if not item.get("description"):
            caveats.append("no description, mechanism is unknown")
        candidates.append(
            Candidate(
                source="github",
                title=item.get("full_name") or "",
                url=item.get("html_url") or "",
                detail=(item.get("description") or "")[:200],
                first_seen=created,
                mint_count=0,
                unique_wallets=0,
                watchers=int(item.get("stargazers_count") or 0),
                score=score,
                tags=tags + [f"group:{g}" for g in groups],
                caveats=caveats,
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.first_seen))
    return {
        "layer": "github",
        "scanned_at": iso(started),
        "window_days": days,
        "since": since,
        "token_used": bool(token),
        "queries_run": len(QUERY_GROUPS),
        "queries_failed": failures,
        "repos_seen": len(seen),
        "candidates": [c.to_dict() for c in candidates[:limit]],
        "total_candidates": len(candidates),
        "coverage_note": (
            "GitHub covers only projects that publish code. Projects without a "
            "public repository are invisible to this layer."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan GitHub for new on-chain mint projects")
    ap.add_argument("--days", type=int, default=5, help="look back N days (default 5)")
    ap.add_argument("--limit", type=int, default=20, help="max candidates to return")
    ap.add_argument("--min-score", type=int, default=8, help="minimum relevance score")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    args = ap.parse_args()

    result = scan(days=args.days, limit=args.limit, min_score=args.min_score)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"GitHub layer - scanned {result['scanned_at']} (window {result['window_days']}d)")
    print(f"  token: {'yes' if result['token_used'] else 'NO (anonymous, rate limited)'}")
    print(f"  repos seen: {result['repos_seen']}  candidates: {result['total_candidates']}")
    if result["queries_failed"]:
        print(f"  failed groups: {len(result['queries_failed'])}")
    print()
    if not result["candidates"]:
        print("  no candidate passed the score threshold")
        return 0
    print(f"{'score':<6}{'created':<18}{'repo':<44}notes")
    print("-" * 120)
    for c in result["candidates"]:
        print(
            f"{c['score']:<6}{c['first_seen'][:16]:<18}{c['title'][:42]:<44}"
            f"{c['detail'][:46]}"
        )
    print()
    print(f"coverage: {result['coverage_note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
