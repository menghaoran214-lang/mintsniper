#!/usr/bin/env python3
"""BSC 观察地址活跃探测：匹配在本地完成，地址不外发；只报告事件，不构成建议。"""
from __future__ import annotations

import argparse
from pathlib import Path

import common
from common import (
    Candidate, MINT_TOPIC_GROUPS, bounded_int, render_scan, validate_address,
)

MAX_OBSERVED_ADDRESSES = 500
MAX_TRANSACTION_LOOKUPS = 120


def load_addresses(path):
    """读取本地观察地址；非法行报错而非静默忽略。"""
    if not path.is_file():
        raise ValueError(f'地址文件不存在: {path}')
    seen, addresses, invalid = set(), [], []
    for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
        text = line.strip()
        if not text or text.startswith('#') or text.startswith('//'):
            continue
        for token in text.replace(',', ' ').replace('\t', ' ').split():
            if token.lower().startswith('0x') and len(token) == 42:
                try:
                    token = validate_address(token)
                except ValueError:
                    invalid.append(f'{number}:{token[:12]}')
                else:
                    if token not in seen:
                        seen.add(token)
                        addresses.append(token)
                break
        else:
            invalid.append(f'{number}:{text[:12]}')
    if invalid:
        raise ValueError('非法地址行: ' + ', '.join(invalid[:5]))
    bounded_int(len(addresses), '观察地址数量', MAX_OBSERVED_ADDRESSES)
    return addresses


def scan(addresses, minutes=15, limit=20):
    bounded_int(minutes, 'minutes', 1440)
    bounded_int(limit, 'limit', 1000)
    if not addresses:
        raise ValueError('观察地址列表为空')
    observed = {validate_address(a) for a in addresses}
    events, metadata = common.discover(minutes, list(MINT_TOPIC_GROUPS))
    stats = {}
    senders, lookups = {}, 0
    for event in events:
        if event['receiver'] not in observed:
            continue
        tx_hash = event['transaction_hash']
        if tx_hash not in senders:
            if lookups < MAX_TRANSACTION_LOOKUPS:
                lookups += 1
                try:
                    tx = common.rpc_call('eth_getTransactionByHash', [tx_hash])['result']
                    senders[tx_hash] = validate_address(tx.get('from'))
                except Exception:
                    senders[tx_hash] = None
            else:
                senders[tx_hash] = None
        # 只有交易发起者是该观察地址时才是 direct；其余按接收事件保留。
        kind = 'direct' if senders[tx_hash] == event['receiver'] else 'received'
        row = stats.setdefault(event['contract'], {'direct': 0, 'received': 0, 'wallets': set(),
                                                   'first_block': event['block'], 'notes': set()})
        row[kind] += 1
        if kind == 'direct':
            row['wallets'].add(event['receiver'])
        row['first_block'] = min(row['first_block'], event['block'])
        row['notes'].add(f"{kind}:{event['standard']}")
    candidates = []
    for contract, row in stats.items():
        candidates.append(Candidate(
            source='wallet', title=contract, contract=contract,
            detail=f"已确认 {row['direct']} 次该地址发起的交易；{row['received']} 次仅为收到事件"
                   f"（发起方未知，可能含空投或路由）",
            first_seen=f"block {row['first_block']}", mint_count=row['direct'],
            unique_wallets=len(row['wallets']), score=5 * len(row['wallets']) + min(row['direct'], 30),
            tags=sorted(row['notes']) + ['observed-address'],
            caveats=['观察地址收到事件不代表其主动 mint，也不代表安全或有利'],
        ).to_dict())
    candidates.sort(key=lambda c: (-c['score'], c['contract']))
    note = ('观察地址仅在本地集合内匹配，RPC 请求不含这些地址；direct 需交易发起者为该地址。'
            '覆盖不完整时空结果不代表无活动。')
    if metadata['coverage']['status'] != 'complete':
        note += ' 覆盖不完整，空结果不能解释为没有项目；见 coverage.failed_ranges。'
    if lookups >= MAX_TRANSACTION_LOOKUPS:
        # 超出预算的交易一律按“收到”保留，不会升级为 direct。
        metadata['coverage_warnings'] = list(metadata.get('coverage_warnings', [])) + [
            f'交易发起者查询达到上限 {MAX_TRANSACTION_LOOKUPS}，剩余事件按收到事件保留']
        note += ' 部分交易发起者未确认，一律按收到事件保留。'
    return {**metadata, 'layer': 'wallet', 'watched_addresses': len(observed),
            'candidates': candidates[:limit], 'total_candidates': len(candidates),
            'coverage_note': note}


def main():
    ap = argparse.ArgumentParser(description='观察地址 BSC 活跃探测')
    ap.add_argument('--addresses', required=True, help='本地地址列表文件')
    ap.add_argument('--minutes', type=int, default=15)
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    try:
        result = scan(load_addresses(Path(args.addresses)), args.minutes, args.limit)
    except ValueError as exc:
        ap.error(str(exc))
    return render_scan(result, args.json)


if __name__ == '__main__':
    raise SystemExit(main())
