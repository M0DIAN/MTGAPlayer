"""Actual cross-process qualification and discriminating association failures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import qualify_delivery as delivery


class DeliveryQualificationTests(unittest.TestCase):
    def test_real_script_all_paths_and_safe_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'qualification.json'
            process = subprocess.run([sys.executable, 'scripts/qualify_delivery.py', '--samples', '8',
                '--interval', '.01', '--output', str(output)], cwd=ROOT, capture_output=True, timeout=20)
            self.assertEqual(process.returncode, 0,
                f'qualification stdout={process.stdout!r}; stderr={process.stderr!r}')
            report = json.loads(output.read_text(encoding='utf-8'))
            records = [json.loads(line) for line in output.with_name('qualification-samples.jsonl').read_text().splitlines()]
        self.assertEqual(report['result'], 'QUALIFIED_LOCAL_READONLY')
        self.assertEqual(report['counts']['steady_verified'], 8)
        self.assertEqual(report['counts']['failure_records'], 0)
        self.assertEqual(report['counts']['scenario_failures'], 0)
        self.assertEqual(report['normal_terminal']['producer_exit'], 0)
        self.assertEqual(report['normal_terminal']['consumer_exit'], 0)
        self.assertFalse(report['normal_terminal']['final_cached_state_present'])
        consumption = next(r for r in records if r['phase'] == 'steady' and r['category'] == 'request_consumed')
        self.assertEqual(consumption['event_order'], ['invalidate', 'snapshot', 'liveness'])
        self.assertEqual(consumption['consumer_statuses'], ['INVALIDATED', 'OBSERVING', 'OBSERVING'])
        self.assertTrue(consumption['correct_revocation'])
        burst = next(r for r in records if r['category'] == 'same_poll_three_requests')
        self.assertEqual((burst['input_changes'], burst['snapshot_count']), (3, 1))
        self.assertEqual(report['abnormal_exit']['reason'], ['unexpected_eof'])
        self.assertEqual(report['silent_open_pipe']['reason'], ['event_silence_expired'])
        self.assertTrue(report['silent_open_pipe']['producer_alive_at_expiry'])
        self.assertEqual(report['backpressure']['timely_invalidation_while_output_blocked'], 'not_guaranteed')
        self.assertIn(report['backpressure']['consumer_status'], ('PROTOCOL_ERROR', 'STALE', 'CLOSED'))
        self.assertFalse(report['backpressure']['final_cached_state_present'])
        self.assertFalse(report['silent_open_pipe']['final_cached_state_present'])
        self.assertFalse(report['abnormal_exit']['final_cached_state_present'])
        self.assertLess(report['backpressure']['output_bytes'], delivery.OUTPUT_LIMIT)
        self.assertEqual(report['stages_ms']['steady']['poll_read_ns']['sample_count'], 8)
        self.assertEqual(report['groups']['startup/first_history_snapshot']['write_to_observed_ms']['sample_count'], 0)
        self.assertEqual(report['groups']['startup/first_history_snapshot']['launch_to_history_ms']['sample_count'], 1)
        text = json.dumps(report) + '\n' + '\n'.join(json.dumps(r) for r in records)
        for forbidden in ('fixture-match', 'fixture-local', 'binding_tag', 'request_id', 'card_id', 'grpId'):
            self.assertNotIn(forbidden, text)
        for record in records:
            if 't_consumer_ack_observed_ns' in record:
                self.assertEqual(record['write_to_ack_ns'], record['t_consumer_ack_observed_ns'] - record['t_before_write_ns'])
                self.assertEqual(record['flush_to_ack_ns'], record['t_consumer_ack_observed_ns'] - record['t_after_flush_ns'])

    def test_real_wrong_reason_and_binding_cannot_count_as_success(self):
        for mismatch in ('reason', 'binding'):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                session = delivery.Session(directory, .01, 100)
                try:
                    session.startup()
                    with self.assertRaises(delivery.QualificationError):
                        session.change('negative_association', [delivery.request(41, 1)],
                            reason='request_consumed' if mismatch == 'reason' else 'request_replaced',
                            state_id=1, request_id=40 if mismatch == 'binding' else 41)
                    self.assertIn(session.records[-1]['outcome'], ('incorrect_revocation', 'unassociated_result'))
                    self.assertEqual(delivery.distribution(session.records, 'write_to_ack_ns')['sample_count'], 0)
                finally:
                    session.cleanup()
                self.assertTrue(all(p.poll() is not None for p in session.processes))
                self.assertTrue(all(not t.is_alive() for t in session.threads))

    def test_failures_and_signed_flush_latency_have_honest_denominators(self):
        records = [
            {'phase': 'steady', 'category': 'new_request', 'outcome': 'verified',
             'input_changes': 1, 'write_to_ack_ns': 20_000_000, 'flush_to_ack_ns': -1_000_000},
            {'phase': 'steady', 'category': 'new_request', 'outcome': 'sample_timeout', 'input_changes': 1},
            {'phase': 'steady', 'category': 'new_request', 'outcome': 'unassociated_result', 'input_changes': 1}]
        group = delivery.summarize(records)['steady/new_request']
        self.assertEqual((group['attempts'], group['verified'], group['input_changes']), (3, 1, 3))
        self.assertEqual(group['outcomes'], {'sample_timeout': 1, 'unassociated_result': 1, 'verified': 1})
        self.assertEqual(group['write_to_observed_ms']['sample_count'], 1)
        self.assertEqual(group['write_to_observed_ms']['p99_ms'], 20)
        self.assertEqual(group['flush_to_observed_ms']['p50_ms'], -1)

    def test_controller_output_bound_closes_owned_processes(self):
        previous = delivery.OUTPUT_LIMIT
        with tempfile.TemporaryDirectory() as directory:
            session = delivery.Session(directory, .01, 100)
            try:
                delivery.OUTPUT_LIMIT = 1
                with self.assertRaisesRegex(delivery.QualificationError, 'controller_output_limit'):
                    session.startup()
            finally:
                session.cleanup()
                delivery.OUTPUT_LIMIT = previous
            self.assertTrue(all(p.poll() is not None for p in session.processes))
            self.assertTrue(all(not t.is_alive() for t in session.threads))

    def test_default_replay_watch_compatibility_through_real_CLI(self):
        for command in (['replay', 'examples/synthetic.jsonl'], ['dry-run', 'examples/synthetic.jsonl'],
                        ['watch', 'tests/fixtures/player_log_minimal.jsonl', '--samples', '1']):
            result = subprocess.run([sys.executable, '-m', 'mtgaplayer', *command], cwd=ROOT,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            self.assertNotIn('event_type', document)
            self.assertNotIn('decision_state', document)


if __name__ == '__main__':
    unittest.main()
