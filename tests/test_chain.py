"""离线单元测试：不联网、不使用凭据、不写任何链上数据。"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
import chain_scan  # noqa: E402
import erc1155_scan  # noqa: E402
import wallet_scan  # noqa: E402

CONTRACT = '0x' + 'ab' * 20
WALLET = '0x' + '11' * 20
OTHER = '0x' + '22' * 20
WORD = lambda n: '0x' + format(n, '064x')  # noqa: E731


def word(n):
    return format(n, '064x')


def topic_of(address):
    return '0x' + '0' * 24 + address[2:]


def make_log(sig, topics_rest, data='0x', block=100, index=0, tx='0x' + '33' * 32,
             contract=CONTRACT, removed=False):
    return {
        'address': contract,
        'topics': [sig] + topics_rest,
        'data': data,
        'blockNumber': hex(block),
        'blockHash': '0x' + '44' * 31 + format(block % 256, '02x'),
        'transactionHash': tx,
        'transactionIndex': '0x0',
        'logIndex': hex(index),
        'removed': removed,
    }


def erc721_mint(block=100, index=0, sender=common.ZERO_ADDRESS, to=OTHER, **kwargs):
    return make_log(common.ERC721_TRANSFER_TOPIC,
                    [topic_of(sender), topic_of(to), WORD(1)], data='0x',
                    block=block, index=index, **kwargs)


def erc1155_single(block=100, index=0, sender=common.ZERO_ADDRESS, to=OTHER,
                   operator=OTHER, ids=(7,), values=(3,)):
    data = '0x' + word(ids[0]) + word(values[0])
    return make_log(common.ERC1155_TRANSFER_SINGLE_TOPIC,
                    [topic_of(operator), topic_of(sender), topic_of(to)],
                    data=data, block=block, index=index)


def erc1155_batch(block=100, index=0, sender=common.ZERO_ADDRESS, to=OTHER,
                  operator=OTHER, ids=(1, 2), values=(10, 20)):
    head = [64, 64 + 32 + 32 * len(ids)]
    payload = head + [len(ids)] + list(ids) + [len(values)] + list(values)
    data = '0x' + ''.join(word(v) for v in payload)
    return make_log(common.ERC1155_TRANSFER_BATCH_TOPIC,
                    [topic_of(operator), topic_of(sender), topic_of(to)],
                    data=data, block=block, index=index)


class TopicShapeTests(unittest.TestCase):
    def test_topics_derived_from_published_signatures(self):
        self.assertEqual(
            common.ERC721_TRANSFER_TOPIC,
            '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef')
        self.assertEqual(
            common.ERC1155_TRANSFER_SINGLE_TOPIC,
            '0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62')
        self.assertEqual(
            common.ERC1155_TRANSFER_BATCH_TOPIC,
            '0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb')

    def test_topic_length_and_word_shape(self):
        for topic in (common.ERC721_TRANSFER_TOPIC, common.ERC1155_TRANSFER_SINGLE_TOPIC,
                      common.ERC1155_TRANSFER_BATCH_TOPIC, common.ZERO_TOPIC):
            self.assertEqual(len(topic), 66)
            self.assertTrue(common.is_word(topic))
        self.assertFalse(common.is_word('0x' + '1' * 63))
        self.assertFalse(common.is_word(common.ZERO_ADDRESS))

    def test_mint_topic_filters_use_from_index(self):
        # ERC721: from 位于 index 1；ERC1155: from 位于 index 2，operator 不参与过滤。
        self.assertEqual(common.MINT_TOPIC_GROUPS[0],
                         [common.ERC721_TRANSFER_TOPIC, common.ZERO_TOPIC])
        for group, sig in zip(common.MINT_TOPIC_GROUPS[1:], (
                common.ERC1155_TRANSFER_SINGLE_TOPIC, common.ERC1155_TRANSFER_BATCH_TOPIC)):
            self.assertEqual(group, [sig, None, common.ZERO_TOPIC])

    def test_keccak_matches_known_vectors(self):
        self.assertEqual(common.keccak256(b'').hex(),
                         'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')


class Erc721ParsingTests(unittest.TestCase):
    def test_erc20_transfer_is_excluded(self):
        erc20 = make_log(common.ERC721_TRANSFER_TOPIC,
                         [topic_of(common.ZERO_ADDRESS), topic_of(OTHER)],
                         data=WORD(10 ** 18))
        self.assertIsNone(common.parse_mint(erc20))

    def test_four_topic_log_with_value_in_data_is_excluded(self):
        erc20ish = make_log(common.ERC721_TRANSFER_TOPIC,
                            [topic_of(common.ZERO_ADDRESS), topic_of(OTHER), WORD(1)],
                            data=WORD(5))
        self.assertIsNone(common.parse_mint(erc20ish))

    def test_real_erc721_mint_is_accepted(self):
        event = common.parse_mint(erc721_mint())
        self.assertEqual(event['contract'], CONTRACT)
        self.assertEqual(event['receiver'], OTHER)
        self.assertEqual(event['standard'], 'erc721')
        self.assertEqual(event['values'], [1])

    def test_transfer_from_non_zero_is_not_a_mint(self):
        self.assertIsNone(common.parse_mint(erc721_mint(sender=OTHER)))

    def test_removed_log_is_dropped(self):
        self.assertIsNone(common.parse_mint(erc721_mint(removed=True)))

    def test_malformed_logs_raise(self):
        missing = erc721_mint()
        missing.pop('transactionHash')
        bad_topics = erc721_mint()
        bad_topics['topics'] = [common.ERC721_TRANSFER_TOPIC, '0x1234']
        bad_removed = erc721_mint()
        bad_removed['removed'] = 'no'
        bad_data = erc721_mint()
        bad_data['data'] = '0xzz'
        for entry in (missing, bad_topics, bad_removed, bad_data):
            with self.assertRaises(ValueError):
                common.parse_mint(entry)

    def test_truncated_transfer_topics_are_not_counted(self):
        log = erc721_mint()
        log['topics'] = log['topics'][:2]
        self.assertIsNone(common.parse_mint(log))

    def test_missing_removed_field_is_accepted(self):
        log = erc721_mint()
        log.pop('removed')
        self.assertIsNotNone(common.parse_mint(log))


class Erc1155ParsingTests(unittest.TestCase):
    def test_single_mint_parses_id_and_value(self):
        event = common.parse_mint(erc1155_single(ids=(7,), values=(3,)))
        self.assertEqual(event['standard'], 'erc1155')
        self.assertEqual(event['ids'], [7])
        self.assertEqual(event['values'], [3])
        self.assertEqual(event['receiver'], OTHER)

    def test_single_mint_allows_any_operator(self):
        event = common.parse_mint(erc1155_single(operator=WALLET))
        self.assertIsNotNone(event)

    def test_single_from_non_zero_is_not_a_mint(self):
        self.assertIsNone(common.parse_mint(erc1155_single(sender=OTHER)))

    def test_batch_mint_parses_both_arrays(self):
        event = common.parse_mint(erc1155_batch(ids=(1, 2), values=(10, 20)))
        self.assertEqual(event['ids'], [1, 2])
        self.assertEqual(event['values'], [10, 20])

    def test_batch_with_mismatched_arrays_raises(self):
        log = erc1155_batch()
        payload = [64, 128, 2, 1, 2, 3, 10]
        log['data'] = '0x' + ''.join(word(v) for v in payload)
        with self.assertRaises(ValueError):
            common.parse_mint(log)

    def test_single_with_short_data_raises(self):
        log = erc1155_single()
        log['data'] = '0x' + word(7)
        with self.assertRaises(ValueError):
            common.parse_mint(log)

    def test_zero_value_mint_is_not_counted(self):
        self.assertIsNone(common.parse_mint(erc1155_single(values=(0,))))


class AddressValidationTests(unittest.TestCase):
    def test_lowercase_and_checksum_addresses_pass(self):
        self.assertEqual(common.validate_address(WALLET), WALLET)
        checksum = '0x52908400098527886E0F7030069857D2E4169EE7'
        self.assertEqual(common.validate_address(checksum), checksum.lower())

    def test_invalid_addresses_are_rejected(self):
        for value in ('0x123', WALLET + 'ab', 'not-an-address', None, 42,
                      '0x52908400098527886E0F7030069857D2E4169Ee7'):
            with self.assertRaises(ValueError):
                common.validate_address(value)

    def test_topic_address_requires_zero_padding(self):
        self.assertEqual(common.topic_address(topic_of(WALLET)), WALLET)
        with self.assertRaises(ValueError):
            common.topic_address('0x' + 'ff' * 32)


class RpcGuardTests(unittest.TestCase):
    def test_write_methods_are_refused_without_network(self):
        for method in ('eth_sendRawTransaction', 'eth_sendTransaction',
                       'personal_unlockAccount', 'eth_signTransaction'):
            with self.assertRaises(ValueError):
                common.rpc_call(method, [], rpc_url='https://node.example')

    def test_error_message_hides_endpoint_and_secret(self):
        with mock.patch.object(common, 'http_json', side_effect=OSError('boom')):
            with self.assertRaises(common.RPCError) as ctx:
                common.rpc_call('eth_blockNumber', [],
                                rpc_url='https://node.example/v2/SECRET-KEY')
        self.assertNotIn('SECRET-KEY', str(ctx.exception))
        self.assertNotIn('node.example', str(ctx.exception))

    def test_wrong_chain_is_rejected(self):
        envelope = {'jsonrpc': '2.0', 'id': 1, 'result': '0x1'}
        with mock.patch.object(common, 'http_json', return_value=envelope):
            with self.assertRaises(common.RPCError):
                common.rpc_call('eth_blockNumber', [], rpc_url='https://node.example')


class CoverageTests(unittest.TestCase):
    def fake_rpc(self, fail_ranges=(), logs=None, calls=None):
        logs = logs or []

        def call(method, params, rpc_url=None, timeout=25):
            payload = params[0]
            start, end = int(payload['fromBlock'], 16), int(payload['toBlock'], 16)
            if calls is not None:
                calls.append((start, end))
            if (start, end) in fail_ranges or any(
                    a <= start and end <= b for a, b in fail_ranges):
                raise common.RPCError('rpc_read_failed')
            return {'jsonrpc': '2.0', 'id': 1,
                    'result': [dict(log) for log in logs if start <= int(log['blockNumber'], 16) <= end]}
        return call

    def test_failed_range_is_reported_not_treated_as_empty(self):
        calls = []
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc(
                fail_ranges={(125, 149)}, logs=[erc721_mint(block=110)], calls=calls)):
            events, coverage = common.fetch_mint_logs(
                100, 149, [common.MINT_TOPIC_GROUPS[0]], chunk_blocks=25)
        self.assertEqual(len(events), 1)
        self.assertEqual(coverage['status'], 'partial')
        self.assertEqual(coverage['failed_ranges'][0]['from_block'], 125)
        self.assertEqual(coverage['failed_ranges'][0]['reason'], 'rpc_read_failed')
        self.assertEqual(len(calls), 2)  # 单请求读取，不做额外放大

    def test_all_ranges_failing_is_error(self):
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc(
                fail_ranges={(100, 149)})):
            events, coverage = common.fetch_mint_logs(
                100, 149, [common.MINT_TOPIC_GROUPS[0]], chunk_blocks=25)
        self.assertEqual(events, [])
        self.assertEqual(coverage['status'], 'error')
        self.assertEqual(len(coverage['failed_ranges']), 2)

    def test_malformed_logs_mark_range_and_emit_no_fake_data(self):
        broken = erc721_mint(block=101)
        broken['data'] = '0xnothex'
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc(logs=[broken])):
            events, coverage = common.fetch_mint_logs(
                100, 124, [common.MINT_TOPIC_GROUPS[0]], chunk_blocks=25)
        self.assertEqual(events, [])
        self.assertEqual(coverage['rejected_logs'], 1)
        self.assertEqual(coverage['failed_ranges'][0]['reason'], 'malformed_logs')
        self.assertNotEqual(coverage['status'], 'complete')

    def test_duplicate_logs_are_counted_once(self):
        log = erc721_mint(block=101)
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc(logs=[log, log])):
            events, coverage = common.fetch_mint_logs(
                100, 124, [common.MINT_TOPIC_GROUPS[0]], chunk_blocks=25)
        self.assertEqual(len(events), 1)
        self.assertEqual(coverage['duplicates'], 1)

    def test_request_budget_stops_and_reports(self):
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc()):
            _, coverage = common.fetch_mint_logs(
                100, 199, [common.MINT_TOPIC_GROUPS[0]], chunk_blocks=25, max_requests=2)
        self.assertEqual(coverage['requests'], 2)
        self.assertTrue(any(f['reason'] == 'request_budget_exhausted'
                            for f in coverage['failed_ranges']))
        self.assertEqual(coverage['status'], 'partial')


class WindowTests(unittest.TestCase):
    BASE = 1_700_000_000

    def block(self, number):
        return {'number': hex(number), 'hash': '0x' + format(number, '064x'),
                'timestamp': hex(self.BASE + number * number // 10)}

    def fake_rpc(self, chain='0x38', head=1000):
        def call(method, params, rpc_url=None, timeout=25):
            if method == 'eth_chainId':
                return {'jsonrpc': '2.0', 'id': 1, 'result': chain}
            if method == 'eth_blockNumber':
                return {'jsonrpc': '2.0', 'id': 1, 'result': hex(head)}
            if method == 'eth_getLogs':
                return {'jsonrpc': '2.0', 'id': 1, 'result': []}
            number = int(params[0], 16)
            return {'jsonrpc': '2.0', 'id': 1, 'result': self.block(number)}
        return call

    def now(self):
        return common.datetime.fromtimestamp(self.BASE + 1000 * 1000 // 10 + 5, timezone.utc)

    def test_window_uses_actual_block_timestamps(self):
        now = self.now()
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc()):
            window = common.scan_window(10, now)
        target = now.timestamp() - 600
        expected = next(n for n in range(1001) if self.BASE + n * n // 10 >= target)
        self.assertEqual(window['from_block'], expected)
        self.assertEqual(window['head_block'], 1000)
        self.assertAlmostEqual(window['observed_delay_seconds'], 5.0, places=3)
        self.assertNotIn('covered_from', window)  # discover 才补齐覆盖时间
        self.assertEqual(window['requested_to'], common.iso(now))

    def test_non_bsc_chain_is_refused(self):
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc(chain='0x1')):
            with self.assertRaises(common.RPCError):
                common.scan_window(10)

    def test_discover_reports_error_instead_of_empty_result(self):
        with mock.patch.object(common, 'rpc_call', side_effect=common.RPCError('down')):
            events, metadata = common.discover(10, [common.MINT_TOPIC_GROUPS[0]])
        self.assertEqual(events, [])
        self.assertEqual(metadata['coverage']['status'], 'error')
        self.assertTrue(metadata['coverage_warnings'])

    def test_discover_carries_window_bounds(self):
        now = self.now()
        with mock.patch.object(common, 'rpc_call', side_effect=self.fake_rpc()), \
             mock.patch.object(common, 'utc_now', return_value=now):
            events, metadata = common.discover(10, [common.MINT_TOPIC_GROUPS[0]])
        target = now.timestamp() - 600
        expected = next(n for n in range(1001) if self.BASE + n * n // 10 >= target)
        self.assertEqual(metadata['from_block'], expected)
        self.assertTrue(metadata['covered_from'].endswith('Z'))
        self.assertTrue(metadata['covered_to'].endswith('Z'))
        self.assertEqual(metadata['coverage']['status'], 'complete')
        self.assertNotIn('_blocks', metadata)  # 内部缓存不进入输出


class CliAndScanTests(unittest.TestCase):
    def test_scan_native_marks_coverage_incomplete(self):
        now = WindowTests.BASE
        window = {'head_block': 120, 'from_block': 100, 'window_minutes': 10,
                  'observed_delay_seconds': 1.0, 'covered_from': None, 'covered_to': None}
        events = [common.parse_mint(erc721_mint(block=110, index=i, to=OTHER)) for i in range(3)]
        metadata = {**window, 'scanned_at': '2026-11-01T00:00:00Z',
                    'coverage': {'status': 'partial', 'failed_ranges': [
                        {'from_block': 115, 'to_block': 120, 'reason': 'rpc_read_failed'}]},
                    'coverage_warnings': ['覆盖不完整']}
        with mock.patch.object(chain_scan, 'discover', return_value=(events, metadata)):
            result = chain_scan.scan_native(minutes=10, mint_threshold=1, wallet_threshold=1, limit=5)
        self.assertEqual(result['coverage']['status'], 'partial')
        self.assertEqual(result['total_candidates'], 1)
        self.assertIn('覆盖不完整', result['coverage_note'])

    def test_erc1155_scan_counts_units_and_ids(self):
        metadata = {'scanned_at': '2026-11-01T00:00:00Z', 'head_block': 1, 'from_block': 0,
                    'window_minutes': 5, 'observed_delay_seconds': 0.0, 'covered_from': None,
                    'covered_to': None,
                    'coverage': {'status': 'complete', 'failed_ranges': []},
                    'coverage_warnings': []}
        events = [common.parse_mint(erc1155_batch(block=1, index=0, to=OTHER)),
                  common.parse_mint(erc1155_single(block=1, index=1, to=WALLET, ids=(9,), values=(1,)))]
        with mock.patch.object(erc1155_scan, 'discover', return_value=(events, metadata)):
            result = erc1155_scan.scan(minutes=5, min_mints=1, min_wallets=1, limit=5)
        self.assertEqual(result['total_candidates'], 1)
        self.assertEqual(result['candidates'][0]['mint_count'], 2)  # 2 次 mint 事件
        self.assertEqual(result['candidates'][0]['unique_wallets'], 2)
        self.assertIn('31 个单位', result['candidates'][0]['detail'])

    def test_wallet_scan_separates_direct_from_received(self):
        direct_log = erc721_mint(block=10, index=0, to=WALLET, tx='0x' + '55' * 32)
        received_log = erc721_mint(block=11, index=1, to=WALLET, tx='0x' + '66' * 32)
        events = [common.parse_mint(direct_log), common.parse_mint(received_log)]
        metadata = {'scanned_at': '2026-11-01T00:00:00Z', 'head_block': 12, 'from_block': 9,
                    'window_minutes': 5, 'observed_delay_seconds': 0.0, 'covered_from': None,
                    'covered_to': None, 'coverage': {'status': 'complete', 'failed_ranges': []},
                    'coverage_warnings': []}
        senders = {'0x' + '55' * 32: WALLET, '0x' + '66' * 32: OTHER}
        with mock.patch.object(wallet_scan.common, 'discover', return_value=(events, metadata)), \
             mock.patch.object(wallet_scan.common, 'rpc_call',
                               side_effect=lambda m, p, **kw: {'result': {'from': senders[p[0]]}}):
            result = wallet_scan.scan([WALLET], minutes=5, limit=5)
        candidate = result['candidates'][0]
        self.assertEqual(candidate['mint_count'], 1)          # 只有 direct 计为主动交易
        self.assertIn('received:erc721', candidate['tags'])
        self.assertIn('direct:erc721', candidate['tags'])

    def test_invalid_address_file_is_rejected(self,):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'watch.txt'
            path.write_text('# comment\n0xNOTANADDRESS\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                wallet_scan.load_addresses(path)

    def test_cli_rejects_out_of_range_minutes(self):
        with mock.patch.object(sys, 'argv', ['chain_scan.py', '--minutes', '0']):
            with redirect_stdout(io.StringIO()), mock.patch.object(sys, 'stderr', io.StringIO()):
                with self.assertRaises(SystemExit):
                    chain_scan.main()

    def test_json_output_is_serialisable_and_read_only(self):
        events, metadata = [], {'scanned_at': '2026-11-01T00:00:00Z', 'head_block': 5,
                                'from_block': 0, 'window_minutes': 5, 'observed_delay_seconds': 0.0,
                                'covered_from': None, 'covered_to': None,
                                'coverage': {'status': 'complete', 'failed_ranges': []},
                                'coverage_warnings': []}
        with mock.patch.object(chain_scan, 'discover', return_value=(events, metadata)):
            result = chain_scan.scan_native(minutes=5, mint_threshold=1, wallet_threshold=1, limit=5)
        json.dumps(result)
        self.assertEqual(result['coverage']['status'], 'complete')


if __name__ == '__main__':
    unittest.main(verbosity=2)
