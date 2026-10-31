#!/usr/bin/env python3
"""Merge the three discovery layers into one ranked report.

Also contains a small safety-labelling helper that annotates candidates with
what is known and what is NOT known. It never asserts that a project is safe
or profitable, because no public data source can support that claim.

Usage:
    python3 merge_report.py --github gh.json --chain chain.json [--wallet w.json] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import iso, save_json, utc_now  # noqa: E402

# What each source can and cannot tell us. Used verbatim in the report so a
# reader never mistakes "detected" for "verified".
SOURCE_NOTES = {
    "github": {
        "label": "GitHub development signal",
        "knows": "a repository started shipping code for this project",
        "unknown": "whether the project launched, is mintable, or is safe",
    },
    "chain": {
        "label": "On-chain mint activity",
        "knows": "many distinct wallets minted this contract recently",
        "unknown": "whether the mint was free, whether the contract is safe, whether it sold",
    },
    "wallet": {
        "label": "Watched wallet activity",
        "knows": "a supplied wallet minted this contract",
        "unknown": "whether the mint was safe or profitable",
    },
}


def load(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def merge(sources: list[dict]) -> dict:
    """Merge layer results. Contracts seen by several layers rank higher."""
    by_key: dict[str, dict] = {}

    for src in sources:
        if not src:
            continue
        for cand in src.get("candidates", []) or []:
            key = cand.get("contract") or cand.get("url") or cand.get("title")
            if not key:
                continue
            entry = by_key.setdefault(
                key,
                {
                    "key": key,
                    "title": cand.get("title", ""),
                    "contract": cand.get("contract", ""),
                    "url": cand.get("url", ""),
                    "detail": cand.get("detail", ""),
                    "first_seen": cand.get("first_seen", ""),
                    "mint_count": 0,
                    "unique_wallets": 0,
                    "watchers": 0,
                    "score": 0,
                    "sources": [],
                    "tags": [],
                    "caveats": [],
                },
            )
            if cand.get("source") not in entry["sources"]:
                entry["sources"].append(cand.get("source"))
            entry["mint_count"] = max(entry["mint_count"], cand.get("mint_count", 0) or 0)
            entry["unique_wallets"] = max(
                entry["unique_wallets"], cand.get("unique_wallets", 0) or 0
            )
            entry["watchers"] = max(entry["watchers"], cand.get("watchers", 0) or 0)
            entry["score"] += cand.get("score", 0) or 0
            for t in cand.get("tags", []) or []:
                if t not in entry["tags"]:
                    entry["tags"].append(t)
            for c in cand.get("caveats", []) or []:
                if c not in entry["caveats"]:
                    entry["caveats"].append(c)
            if not entry["url"] and cand.get("url"):
                entry["url"] = cand["url"]
            if cand.get("source") == "chain" and not entry["detail"]:
                entry["detail"] = cand.get("detail", "")

    for entry in by_key.values():
        # Cross-source confirmation is a meaningful signal.
        if len(entry["sources"]) > 1:
            entry["score"] += 12
            entry["tags"].append("multi-source")
        entry["source_labels"] = [
            SOURCE_NOTES[s]["label"] for s in entry["sources"] if s in SOURCE_NOTES
        ]
        entry["not_established"] = [
            SOURCE_NOTES[s]["unknown"] for s in entry["sources"] if s in SOURCE_NOTES
        ]

    ranked = sorted(by_key.values(), key=lambda e: (-e["score"], e["title"]))
    return {
        "generated_at": iso(utc_now()),
        "candidates": ranked,
        "total": len(ranked),
        "layer_counts": {
            "github": sum(1 for e in ranked if "github" in e["sources"]),
            "chain": sum(1 for e in ranked if "chain" in e["sources"]),
            "wallet": sum(1 for e in ranked if "wallet" in e["sources"]),
            "multi_source": sum(1 for e in ranked if len(e["sources"]) > 1),
        },
    }


def render_text(report: dict, layers: list[dict]) -> str:
    out: list[str] = []
    out.append("=" * 78)
    out.append("mintsniper - discovery report (read-only)")
    out.append(f"generated: {report['generated_at']}")
    out.append("=" * 78)
    out.append("")

    for src in layers:
        if not src:
            continue
        label = SOURCE_NOTES.get(src.get("layer", ""), {}).get("label", src.get("layer", "?"))
        out.append(f"[{label}] scanned {src.get('scanned_at','?')}")
        if src.get("coverage_note"):
            out.append(f"    coverage: {src['coverage_note']}")
        if src.get("queries_failed"):
            out.append(f"    failed queries: {len(src['queries_failed'])}")
        out.append("")

    counts = report["layer_counts"]
    out.append(
        f"candidates: {report['total']} "
        f"(github {counts['github']}, chain {counts['chain']}, "
        f"wallet {counts['wallet']}, multi-source {counts['multi_source']})"
    )
    out.append("")

    if not report["candidates"]:
        out.append("no candidates above the configured thresholds")
        return "\n".join(out)

    out.append(f"{'score':<7}{'src':<20}{'mints':<8}{'wallets':<9}name / contract")
    out.append("-" * 110)
    for e in report["candidates"]:
        src = "+".join(e["sources"])[:18]
        out.append(
            f"{e['score']:<7}{src:<20}{e['mint_count']:<8}{e['unique_wallets']:<9}"
            f"{e['title'][:46]}"
        )
        if e.get("url"):
            out.append(f"{'':<44}{e['url'][:64]}")
        for note in e.get("not_established", []):
            out.append(f"{'':<44}! not established: {note}")
    out.append("")
    out.append("This tool is read-only. It does not connect a wallet, does not sign,")
    out.append("does not submit transactions and does not judge profitability.")
    out.append("Verify every contract independently before acting.")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge mintsniper layers into one report")
    ap.add_argument("--github", help="github_scan.py --json output file")
    ap.add_argument("--chain", help="chain_scan.py --json output file")
    ap.add_argument("--wallet", help="wallet_scan.py --json output file")
    ap.add_argument("--out", help="write merged JSON report to this path")
    ap.add_argument("--json", action="store_true", help="print merged JSON only")
    args = ap.parse_args()

    layers = [load(args.github), load(args.chain), load(args.wallet)]
    report = merge([l for l in layers if l])

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        save_json("last_report.json", report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report, [l for l in layers if l]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
