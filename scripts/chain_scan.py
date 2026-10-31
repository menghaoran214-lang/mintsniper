#!/usr/bin/env python3
"""BSC ERC721 只读发现；默认 native，mintradar 仅读取显式本地副本的数据库。"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from common import Candidate, MINT_TOPIC_GROUPS, bounded_int, discover, iso, utc_now, render_scan, validate_address


def scan_with_mintradar(minutes=30, limit=20, mintradar_path=None):
    """外部快照无法证明时间覆盖或合约安全，也不执行其代码。"""
    bounded_int(minutes, 'minutes', 1440)
    bounded_int(limit, 'limit', 1000)
    if not mintradar_path:
        raise ValueError('mintradar 必须显式提供 --mintradar-path 本地副本目录')
    base = Path(mintradar_path).resolve()
    if not base.is_dir() or not (base / 'radar.py').is_file():
        raise ValueError('mintradar 本地副本缺少 radar.py')
    result = {'layer': 'chain', 'backend': 'mintradar', 'scanned_at': iso(utc_now()),
              'window_minutes': minutes, 'covered_from': None, 'covered_to': None,
              'observed_delay_seconds': None, 'candidates': [], 'total_candidates': 0,
              'coverage': {'status': 'error', 'failed_ranges': [
                  {'from_block': None, 'to_block': None, 'reason': 'external_coverage_unverified'}]},
              'coverage_warnings': ['外部数据库快照时间及链 ID 未验证'],
              'coverage_note': '仅读取本地 mintradar 快照；不执行代码。外部 backend 不可作为安全证书，无法证明请求窗口覆盖。'}
    db = next((p for p in (base / 'radar.db', base / 'state' / 'radar.db') if p.is_file()), None)
    if db is None:
        return result
    try:
        con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
        try:
            con.execute('PRAGMA query_only = ON')
            rows = con.execute('SELECT alamat, nama, jumlah_mint, ts_panas FROM kontrak '
                               'WHERE ts_panas IS NOT NULL ORDER BY ts_panas DESC LIMIT ?', (limit,)).fetchall()
        finally:
            con.close()
        for addr, name, count, seen in rows:
            addr = validate_address(addr)
            count = int(count or 0)
            if count < 0:
                raise ValueError('无效计数')
            result['candidates'].append(Candidate(
                source='chain', title=str(name or addr), contract=addr,
                detail=f'外部快照记录 {count} 个事件，时间及链未验证', mint_count=count,
                tags=['external-unverified'], caveats=[result['coverage_note']],
            ).to_dict())
        result['total_candidates'] = len(result['candidates'])
    except (sqlite3.Error, ValueError, TypeError):
        result['candidates'] = []
        result['coverage_warnings'].append('本地外部数据库读取或校验失败')
    return result


def scan_native(minutes=30, mint_threshold=15, wallet_threshold=8, limit=20):
    bounded_int(minutes, 'minutes', 1440)
    bounded_int(mint_threshold, 'mint_threshold')
    bounded_int(wallet_threshold, 'wallet_threshold')
    bounded_int(limit, 'limit', 1000)
    events, metadata = discover(minutes, [MINT_TOPIC_GROUPS[0]])
    stats = {}
    for event in events:
        row = stats.setdefault(event['contract'], {'mints': 0, 'wallets': set(), 'first_block': event['block']})
        row['mints'] += 1
        row['wallets'].add(event['receiver'])
        row['first_block'] = min(row['first_block'], event['block'])
    candidates = []
    for contract, row in stats.items():
        wallets = len(row['wallets'])
        if row['mints'] < mint_threshold or wallets < wallet_threshold:
            continue
        breadth = wallets / row['mints']
        candidates.append(Candidate(
            source='chain', title=contract, contract=contract,
            detail=f"{row['mints']} 个 ERC721 mint 事件，{wallets} 个接收地址",
            first_seen=f"block {row['first_block']}", mint_count=row['mints'], unique_wallets=wallets,
            score=min(wallets, 40) + int(breadth * 20) + (10 if breadth >= 0.5 else 0),
            tags=['erc721', f'breadth:{breadth:.2f}'],
            caveats=['事件不能证明免费、安全或接收方主动发起；未验证完整 ERC721 接口'],
        ).to_dict())
    candidates.sort(key=lambda c: (-c['score'], c['contract']))
    note = '仅识别符合 ERC721 格式的 mint 事件；未进行合约安全或价格分析。'
    if metadata['coverage']['status'] != 'complete':
        note += ' 覆盖不完整，空结果不能解释为没有项目；见 coverage.failed_ranges。'
    return {**metadata, 'layer': 'chain', 'backend': 'native', 'logs_scanned': len(events),
            'contracts_with_mints': len(stats), 'candidates': candidates[:limit],
            'total_candidates': len(candidates), 'coverage_note': note}


def main():
    ap = argparse.ArgumentParser(description='BSC ERC721 只读发现')
    ap.add_argument('--backend', choices=['mintradar', 'native'], default='native')
    ap.add_argument('--mintradar-path', help='现成本地副本目录；只读 radar.db 或 state/radar.db，不执行代码')
    ap.add_argument('--minutes', type=int, default=30)
    ap.add_argument('--mint-threshold', type=int, default=15)
    ap.add_argument('--wallet-threshold', type=int, default=8)
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    try:
        if args.backend == 'mintradar':
            result = scan_with_mintradar(args.minutes, args.limit, args.mintradar_path)
        else:
            result = scan_native(args.minutes, args.mint_threshold, args.wallet_threshold, args.limit)
    except ValueError as exc:
        ap.error(str(exc))
    return render_scan(result, args.json)


if __name__ == '__main__':
    raise SystemExit(main())
