#!/usr/bin/env python3
"""BSC ERC1155 只读发现；mint 由 from 为全零决定。"""
from __future__ import annotations

import argparse

from common import Candidate, MINT_TOPIC_GROUPS, bounded_int, discover, render_scan


def scan(minutes=15, min_mints=5, min_wallets=3, limit=20):
    bounded_int(minutes, 'minutes', 1440)
    bounded_int(min_mints, 'min_mints')
    bounded_int(min_wallets, 'min_wallets')
    bounded_int(limit, 'limit', 1000)
    # Single 与 Batch 覆盖不同事件，缺失其一会被记为失败范围。
    events, metadata = discover(minutes, list(MINT_TOPIC_GROUPS[1:]))
    stats = {}
    for event in events:
        row = stats.setdefault(event['contract'], {'mints': 0, 'units': 0, 'wallets': set(),
                                                   'ids': set(), 'first_block': event['block'],
                                                   'standards': set()})
        row['mints'] += 1
        row['units'] += sum(event['values'])
        row['wallets'].add(event['receiver'])
        row['ids'].update(event['ids'])
        row['standards'].add(event['standard'])
        row['first_block'] = min(row['first_block'], event['block'])
    candidates = []
    for contract, row in stats.items():
        wallets = len(row['wallets'])
        if row['mints'] < min_mints or wallets < min_wallets:
            continue
        breadth = wallets / row['mints']
        candidates.append(Candidate(
            source='chain', title=contract, contract=contract,
            detail=f"{row['mints']} 次 {row['standards'].pop()} mint 事件（{row['units']} 个单位），"
                   f"{len(row['ids'])} 个 id，{wallets} 个接收地址",
            first_seen=f"block {row['first_block']}", mint_count=row['mints'], unique_wallets=wallets,
            score=min(wallets, 40) + int(breadth * 20) + (10 if breadth >= 0.5 else 0),
            tags=['erc1155', f'ids:{len(row["ids"])}'],
            caveats=['事件不能证明免费、安全或接收方主动发起'],
        ).to_dict())
    candidates.sort(key=lambda c: (-c['score'], c['contract']))
    note = '仅识别符合 ERC1155 格式的 mint 事件；ERC721 由 chain_scan.py 负责。'
    if metadata['coverage']['status'] != 'complete':
        note += ' 覆盖不完整，空结果不能解释为没有项目；见 coverage.failed_ranges。'
    return {**metadata, 'layer': 'chain', 'standard': 'erc1155', 'logs_scanned': len(events),
            'contracts_with_mints': len(stats), 'candidates': candidates[:limit],
            'total_candidates': len(candidates), 'coverage_note': note}


def main():
    ap = argparse.ArgumentParser(description='BSC ERC1155 只读发现')
    ap.add_argument('--minutes', type=int, default=15)
    ap.add_argument('--min-mints', type=int, default=5)
    ap.add_argument('--min-wallets', type=int, default=3)
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    try:
        result = scan(args.minutes, args.min_mints, args.min_wallets, args.limit)
    except ValueError as exc:
        ap.error(str(exc))
    return render_scan(result, args.json)


if __name__ == '__main__':
    raise SystemExit(main())
