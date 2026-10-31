"""Shared helpers for mintsniper.

Standard library only. No third-party imports.
Every network function here is read-only.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BSC_CHAIN_ID = 56


def keccak256(data: bytes) -> bytes:
    """Ethereum Keccak-256（不是 hashlib.sha3_256），用于签名及 EIP-55。"""
    rotations = ((0, 36, 3, 41, 18), (1, 44, 10, 45, 2),
                 (62, 6, 43, 15, 61), (28, 55, 25, 21, 56), (27, 20, 39, 8, 14))
    constants = (
        0x1, 0x8082, 0x800000000000808A, 0x8000000080008000,
        0x808B, 0x80000001, 0x8000000080008081, 0x8000000000008009,
        0x8A, 0x88, 0x80008009, 0x8000000A, 0x8000808B,
        0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
        0x8000000000008002, 0x8000000000000080, 0x800A,
        0x800000008000000A, 0x8000000080008081, 0x8000000000008080,
        0x80000001, 0x8000000080008008,
    )
    mask = (1 << 64) - 1

    def rotate(value, shift):
        return ((value << shift) | (value >> (64 - shift))) & mask

    padded = bytearray(data)
    padded.append(1)
    padded.extend(bytes((-len(padded)) % 136))
    padded[-1] |= 0x80
    state = [0] * 25
    for offset in range(0, len(padded), 136):
        for i in range(17):
            state[i] ^= int.from_bytes(padded[offset + i * 8:offset + i * 8 + 8], 'little')
        for rc in constants:
            c = [state[x] ^ state[x+5] ^ state[x+10] ^ state[x+15] ^ state[x+20]
                 for x in range(5)]
            for x in range(5):
                d = c[(x-1) % 5] ^ rotate(c[(x+1) % 5], 1)
                for y in range(5):
                    state[x + 5*y] ^= d
            b = [0] * 25
            for x in range(5):
                for y in range(5):
                    b[y + 5*((2*x + 3*y) % 5)] = rotate(state[x + 5*y], rotations[x][y])
            for x in range(5):
                for y in range(5):
                    state[x + 5*y] = b[x + 5*y] ^ ((~b[(x+1) % 5 + 5*y]) & b[(x+2) % 5 + 5*y])
            state[0] ^= rc
    return b''.join(v.to_bytes(8, 'little') for v in state)[:32]


# 签名来自 https://eips.ethereum.org/EIPS/eip-721 和 /EIPS/eip-1155。
EVENT_SIGNATURES = (
    'Transfer(address,address,uint256)',
    'TransferSingle(address,address,address,uint256,uint256)',
    'TransferBatch(address,address,address,uint256[],uint256[])',
)
ERC721_TRANSFER_TOPIC, ERC1155_TRANSFER_SINGLE_TOPIC, ERC1155_TRANSFER_BATCH_TOPIC = (
    '0x' + keccak256(signature.encode('ascii')).hex() for signature in EVENT_SIGNATURES
)
if any(len(topic) != 66 for topic in (
    ERC721_TRANSFER_TOPIC, ERC1155_TRANSFER_SINGLE_TOPIC, ERC1155_TRANSFER_BATCH_TOPIC
)):
    raise RuntimeError('事件 topic 必须为 32 字节')

ZERO_ADDRESS = "0x" + "0" * 40

# A topic value is a 32-byte word, so the zero address must be left-padded to
# 64 hex characters. Using the 40-character address form makes the RPC
# reject the request with "hex has invalid length 20; expected 32".
ZERO_TOPIC = "0x" + "0" * 64

# Public BSC RPC endpoints. Free and unauthenticated.
#
# Important: most public BSC endpoints REJECT eth_getLogs without an
# "address" filter. Measured on 2026-11-01:
#   bsc-dataseed.bnbchain.org / defibit / binance.org / ninicoin -> "limit exceeded"
#   bsc.publicnode.com                              -> "specify an address"
#   jp-bscscutum.blockrazor.xyz + bsc.blockrazor.xyz -> WORKS without address
#
# The first two in this list are therefore the default log endpoints. The
# others are kept as fallbacks for non-log calls such as eth_blockNumber.
# Users running continuous scans should supply a dedicated node through
# MINTSNIPER_RPC.
DEFAULT_LOG_RPC = [
    "https://jp-bscscutum.blockrazor.xyz",
    "https://bsc.blockrazor.xyz",
]

DEFAULT_RPC = [
    "https://jp-bscscutum.blockrazor.xyz",
    "https://bsc.blockrazor.xyz",
    "https://bsc-dataseed.bnbchain.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc.publicnode.com",
]

STATE_DIR = Path(
    os.environ.get("MINTSNIPER_STATE")
    or Path(__file__).resolve().parent.parent / "state"
)

USER_AGENT = "mintsniper/1.0 (read-only discovery; +https://github.com/menghaoran214-lang/mintsniper)"


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def days_ago_str(days: int) -> str:
    return (utc_now() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_json(
    url: str,
    *,
    headers: dict | None = None,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 30,
    retries: int = 3,
) -> dict | list:
    """Perform a JSON HTTP request with retry and exponential backoff.

    Read-only endpoints only. This helper never signs or submits transactions.
    """
    payload = None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (403, 429):
                # Rate limited or forbidden: wait longer, then retry.
                wait = 5 * (attempt + 1)
                if exc.code == 403:
                    wait = 15 * (attempt + 1)
                time.sleep(wait)
                continue
            if exc.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("HTTP 请求失败") from None


READ_ONLY_RPC_METHODS = frozenset({
    'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber',
    'eth_getLogs', 'eth_getTransactionByHash',
})


class RPCError(RuntimeError):
    pass


# 端点只需成功校验一次链 ID，避免每个 eth_getLogs 都重复探测。
_VERIFIED_CHAIN: dict[str, str] = {}


def rpc_call(method: str, params: list, rpc_url: str | None = None, timeout: int = 25) -> dict:
    """只允许发现所需的读取方法；错误不包含端点、响应正文或凭据。"""
    if method not in READ_ONLY_RPC_METHODS:
        raise ValueError('RPC 方法不在只读白名单中')
    if not isinstance(params, list) or not 1 <= timeout <= 60:
        raise ValueError('RPC 参数或超时无效')
    urls = [rpc_url] if rpc_url else rpc_urls(log_only=method == 'eth_getLogs')
    failures = []

    def request(url, name, arguments):
        try:
            response = http_json(url, method='POST', body={
                'jsonrpc': '2.0', 'id': 1, 'method': name, 'params': arguments,
            }, timeout=timeout, retries=2)
        except Exception:
            raise RPCError('transport_error') from None
        if not isinstance(response, dict) or response.get('jsonrpc') != '2.0' or response.get('id') != 1:
            raise RPCError('invalid_envelope')
        if 'error' in response:
            error = response['error']
            code = error.get('code') if isinstance(error, dict) else None
            raise RPCError(f'rpc_error({code})' if type(code) is int else 'rpc_error')
        if 'result' not in response:
            raise RPCError('missing_result')
        return response

    for index, url in enumerate(urls[:5]):
        try:
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                raise RPCError('invalid_endpoint')
            if url not in _VERIFIED_CHAIN:
                chain = request(url, 'eth_chainId', [])
                if chain.get('result') != hex(BSC_CHAIN_ID):
                    raise RPCError('wrong_chain_expected_56')
                _VERIFIED_CHAIN[url] = chain['result']
            if method == 'eth_chainId':
                result = {'jsonrpc': '2.0', 'id': 1, 'result': _VERIFIED_CHAIN[url]}
            else:
                result = request(url, method, params)
            payload = result['result']
            if method == 'eth_getLogs' and not isinstance(payload, list):
                raise RPCError('invalid_logs_result')
            if method in ('eth_blockNumber', 'eth_chainId'):
                quantity(payload)
            if method in ('eth_getBlockByNumber', 'eth_getTransactionByHash') and not isinstance(payload, dict):
                raise RPCError('missing_object_result')
            # 空列表是成功的读取结果，不伪造事件，也不将错误变为空列表。
            return result
        except (RPCError, ValueError):
            # 仅保存内部固定错误码，不传播服务端提供的字符串。
            exc = sys.exc_info()[1]
            reason = str(exc) if isinstance(exc, RPCError) else 'invalid_response'
            failures.append(f'endpoint_{index + 1}:{reason}')
    raise RPCError(f'{method} failed: ' + '; '.join(failures)) from None


def bounded_int(value, name='参数', maximum=1000000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} 必须为 1..{maximum} 的整数')
    return value


def quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', value):
        raise ValueError('无效十六进制数量')
    return int(value, 16)


def is_word(value):
    return isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{64}', value) is not None


def validate_address(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', value):
        raise ValueError('地址必须为 0x 加 40 位十六进制字符')
    text = value[2:]
    if text != text.lower() and text != text.upper():
        digest = keccak256(text.lower().encode('ascii')).hex()
        expected = ''.join(c.upper() if int(digest[i], 16) >= 8 else c
                           for i, c in enumerate(text.lower()))
        if text != expected:
            raise ValueError('混合大小写地址的 EIP-55 校验失败')
    return value.lower()


def topic_address(topic):
    if not is_word(topic) or topic[2:26] != '0' * 24:
        raise ValueError('无效地址 topic')
    return '0x' + topic[-40:].lower()


MINT_TOPIC_GROUPS = (
    [ERC721_TRANSFER_TOPIC, ZERO_TOPIC],
    [ERC1155_TRANSFER_SINGLE_TOPIC, None, ZERO_TOPIC],
    [ERC1155_TRANSFER_BATCH_TOPIC, None, ZERO_TOPIC],
)


def parse_mint(entry):
    """返回已验证的 mint；普通转账/ERC20/removed 返回 None，畸形日志报错。"""
    if not isinstance(entry, dict):
        raise ValueError('日志不是对象')
    if entry.get('removed') is True:
        return None
    if entry.get('removed') not in (None, False):
        raise ValueError('无效 removed')
    topics = entry.get('topics')
    if not isinstance(topics, list) or not topics or not all(is_word(t) for t in topics):
        raise ValueError('无效 topics')
    sig = topics[0].lower()
    if sig not in (ERC721_TRANSFER_TOPIC, ERC1155_TRANSFER_SINGLE_TOPIC, ERC1155_TRANSFER_BATCH_TOPIC):
        return None
    data = entry.get('data')
    if not isinstance(data, str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', data):
        raise ValueError('无效 data')
    if sig == ERC721_TRANSFER_TOPIC and (len(topics) != 4 or data != '0x'):
        return None  # 标准 ERC20（3 topics + 数量）或非标准 ERC721 形态，均不计入。
    if len(topics) != 4:
        raise ValueError('NFT 转移事件必须恰有四个 topics')
    contract = validate_address(entry.get('address'))
    if contract == ZERO_ADDRESS:
        raise ValueError('无效合约地址')
    for key in ('blockHash', 'transactionHash'):
        if not is_word(entry.get(key)):
            raise ValueError('缺失或无效日志哈希')
    block = quantity(entry.get('blockNumber'))
    index = quantity(entry.get('logIndex'))
    if sig == ERC721_TRANSFER_TOPIC:
        sender, receiver = topic_address(topics[1]), topic_address(topics[2])
        ids, values, standard = [int(topics[3], 16)], [1], 'erc721'
    else:
        topic_address(topics[1])  # operator 不参与 mint 条件。
        sender, receiver = topic_address(topics[2]), topic_address(topics[3])
        if (len(data) - 2) % 64:
            raise ValueError('1155 data 非 ABI 字边界')
        words = [int(data[i:i+64], 16) for i in range(2, len(data), 64)]
        standard = 'erc1155'
        if sig == ERC1155_TRANSFER_SINGLE_TOPIC:
            if len(words) != 2:
                raise ValueError('TransferSingle 必须包含 id 和 value')
            ids, values = [words[0]], [words[1]]
        else:
            if len(words) < 4 or words[0] != 64:
                raise ValueError('TransferBatch 数组偏移无效')
            size = words[2]
            second = 3 + size
            if second >= len(words) or words[1] != second * 32:
                raise ValueError('TransferBatch 数组越界或重叠')
            if words[second] != size or len(words) != second + 1 + size:
                raise ValueError('TransferBatch 数组长度不匹配')
            ids, values = words[3:second], words[second+1:]
    if sender != ZERO_ADDRESS or receiver == ZERO_ADDRESS or not any(values):
        return None
    return {'contract': contract, 'receiver': receiver, 'standard': standard,
            'ids': ids, 'values': values, 'block': block,
            'transaction_hash': entry['transactionHash'].lower(),
            'block_hash': entry['blockHash'].lower(),
            'key': (entry['blockHash'].lower(), entry['transactionHash'].lower(), index)}


def block_info(number):
    block = rpc_call('eth_getBlockByNumber', [hex(number), False])['result']
    if not isinstance(block, dict) or quantity(block.get('number')) != number or not is_word(block.get('hash')):
        raise RPCError('invalid_block')
    quantity(block.get('timestamp'))
    return block


def scan_window(minutes, now=None):
    """以观察时刻为窗口末端，二分查找实际时间戳，不假设出块间隔。"""
    bounded_int(minutes, 'minutes', 1440)
    now = now or utc_now()
    if quantity(rpc_call('eth_chainId', [])['result']) != BSC_CHAIN_ID:
        raise RPCError('wrong_chain_expected_56')
    head = quantity(rpc_call('eth_blockNumber', [])['result'])
    cache = {}

    def timestamp(number):
        if number not in cache:
            cache[number] = block_info(number)
        return quantity(cache[number]['timestamp'])

    head_time = timestamp(head)
    observed = now.timestamp()
    if head_time > observed:
        raise RPCError('block_timestamp_in_future')
    target = observed - minutes * 60
    if head_time <= target:
        from_block = head
    else:
        # 从链头向后指数探路再二分，避免探测到公共节点已裁剪的远古区块。
        high, low, step = head, head, 256
        while low > 0 and timestamp(low) > target:
            high, low = low, max(0, low - step)
            step = min(step * 2, 1 << 20)
        while low < high:
            mid = (low + high) // 2
            if timestamp(mid) < target:
                low = mid + 1
            else:
                high = mid
        from_block = low
    if from_block > 0 and timestamp(from_block - 1) >= target:
        raise RPCError('inconsistent_block_timestamps')
    return {'head_block': head, 'from_block': from_block, 'window_minutes': minutes,
            'requested_from': iso(datetime.fromtimestamp(target, timezone.utc)),
            'requested_to': iso(now), 'observed_at': iso(now),
            'observed_delay_seconds': round(observed - head_time, 3),
            'head_hash': cache[head]['hash'].lower(), '_blocks': cache}


def fetch_mint_logs(from_block, to_block, topic_groups, chunk_blocks=25, max_requests=2000):
    """顺序、单请求读取；每个 topic/区块范围独立记录成功或失败。"""
    bounded_int(chunk_blocks, 'chunk_blocks', 1000)
    bounded_int(max_requests, 'max_requests', 10000)
    if type(from_block) is not int or type(to_block) is not int or min(from_block, to_block) < 0:
        raise ValueError('区块范围无效')
    if not topic_groups or any(group not in MINT_TOPIC_GROUPS for group in topic_groups):
        raise ValueError('不支持的 mint topics')
    events, seen, failed, successful = [], {}, [], []
    rejected = duplicates = requests = 0
    for topics in topic_groups:
        start = from_block
        while start <= to_block:
            end = min(start + chunk_blocks - 1, to_block)
            scope = {'topic': topics[0], 'from_block': start, 'to_block': end}
            if requests >= max_requests:
                failed.append({**scope, 'to_block': to_block, 'reason': 'request_budget_exhausted'})
                break
            requests += 1
            try:
                logs = rpc_call('eth_getLogs', [{'fromBlock': hex(start), 'toBlock': hex(end),
                                                'topics': topics}])['result']
                if not isinstance(logs, list):
                    raise ValueError('日志结果不是列表')
            except Exception:
                failed.append({**scope, 'reason': 'rpc_read_failed'})
                start = end + 1
                continue
            invalid = False
            for entry in logs:
                try:
                    event = parse_mint(entry)
                    if event is None:
                        continue
                    if not start <= event['block'] <= end or entry['topics'][0].lower() != topics[0]:
                        raise ValueError('日志超出查询范围')
                    if event['key'] in seen:
                        if seen[event['key']] != event:
                            raise ValueError('同一日志内容冲突')
                        duplicates += 1
                        continue
                    seen[event['key']] = event
                    events.append(event)
                except (ValueError, TypeError, KeyError):
                    rejected += 1
                    invalid = True
            if invalid:
                failed.append({**scope, 'reason': 'malformed_logs'})
            else:
                successful.append(scope)
            start = end + 1
    status = 'complete' if not failed else ('partial' if successful or events else 'error')
    return events, {'status': status, 'failed_ranges': failed, 'successful_ranges': successful,
                    'requests': requests, 'rejected_logs': rejected, 'duplicates': duplicates}


def discover(minutes, topic_groups):
    """三个扫描器共用窗口、错误、覆盖和重组检查。"""
    started = utc_now()
    try:
        window = scan_window(minutes, started)
    except Exception:
        return [], {'scanned_at': iso(started), 'head_block': None, 'from_block': None,
                    'window_minutes': minutes, 'covered_from': None, 'covered_to': None,
                    'observed_at': iso(started), 'observed_delay_seconds': None,
                    'coverage': {'status': 'error', 'failed_ranges': [
                        {'from_block': None, 'to_block': None, 'reason': 'window_or_chain_check_failed'}]},
                    'coverage_warnings': ['无法确定 BSC 时间窗口；不代表没有项目']}
    events, coverage = fetch_mint_logs(window['from_block'], window['head_block'], topic_groups)
    cache = window.pop('_blocks')
    covered_from = covered_to = None
    try:
        if block_info(window['head_block'])['hash'].lower() != window['head_hash']:
            raise RPCError('head_changed')
        # covered_from/to 只描述所有 topic 都完整覆盖的连续前缀；其余详见范围列表。
        end = min([r['from_block'] - 1 for r in coverage['failed_ranges']] + [window['head_block']])
        if window['from_block'] <= end:
            def stamp(number):
                block = cache.get(number) or block_info(number)
                return iso(datetime.fromtimestamp(quantity(block['timestamp']), timezone.utc))
            covered_from, covered_to = stamp(window['from_block']), stamp(end)
    except Exception:
        coverage['status'] = 'error'
        coverage['failed_ranges'].append({'from_block': window['from_block'],
            'to_block': window['head_block'], 'reason': 'snapshot_or_timestamp_check_failed'})
        events = []
        covered_from = covered_to = None
    if window['from_block'] > window['head_block']:
        coverage['status'] = 'error'
        coverage['failed_ranges'].append({'from_block': None, 'to_block': None,
                                         'reason': 'head_older_than_window'})
    warnings = [] if coverage['status'] == 'complete' else ['覆盖不完整；失败范围不能解释为没有项目']
    return events, {**window, 'scanned_at': iso(started), 'covered_from': covered_from,
                    'covered_to': covered_to, 'coverage': coverage, 'coverage_warnings': warnings}


def render_scan(result, json_output=False):
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['layer']} - {result['scanned_at']}")
        print(f"coverage: {result['coverage']['status']}; UTC {result.get('covered_from')} .. {result.get('covered_to')}")
        print(f"observed delay: {result.get('observed_delay_seconds')} seconds")
        for failure in result['coverage'].get('failed_ranges', []):
            print('failed: ' + json.dumps(failure, ensure_ascii=False))
        print(f"candidates: {result['total_candidates']}")
        for candidate in result['candidates']:
            print(f"{candidate['contract']}  {candidate['detail']}")
        print(result['coverage_note'])
    return 0 if result['coverage']['status'] == 'complete' else 2


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def github_token() -> str | None:
    """Read the user's own GitHub token.

    Every user must supply their own token. Anonymous GitHub search is limited
    to 10 requests per minute and 60 core requests per hour, which a shared
    token cannot survive under concurrent use.
    """
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "MINTSNIPER_GITHUB_TOKEN"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    token_file = STATE_DIR / "github_token"
    if token_file.exists():
        val = token_file.read_text(encoding="utf-8").strip()
        if val:
            return val
    return None


def rpc_urls(log_only: bool = False) -> list[str]:
    custom = os.environ.get("MINTSNIPER_RPC", "").strip()
    if custom:
        urls = [u.strip() for u in custom.split(",") if u.strip()]
        return urls
    return list(DEFAULT_LOG_RPC if log_only else DEFAULT_RPC)


def ensure_state() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """A single discovered project or contract."""

    source: str  # github | chain | wallet
    title: str
    url: str = ""
    contract: str = ""
    detail: str = ""
    first_seen: str = ""  # ISO UTC
    mint_count: int = 0
    unique_wallets: int = 0
    watchers: int = 0
    score: int = 0
    tags: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def save_json(name: str, payload) -> Path:
    ensure_state()
    path = STATE_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_json(name: str, default=None):
    path = STATE_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
