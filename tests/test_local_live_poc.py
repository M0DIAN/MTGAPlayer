"""Collector integration uses sanitized fixtures; it cannot establish live P1-P9."""
import json
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import local_live_poc as poc
from test_response_evidence import source_rows, save


def rows(path):
    return [value for _, value in poc.complete_rows(path)]


def fake_capture(hwnd, pid, path, method='printwindow'):
    # Deliberately a test byte artifact, never a game frame.
    path.write_bytes(b'unit-test-artifact-not-real-game-image')
    return {'status': 'success', 'size': [2, 2], 'synthetic_test_only': True}


class LocalLivePocTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.root = Path(self.temporary.name)
        self.log = self.root / 'Player.log'
        self.output = self.root / 'session'
        self.collector = None

    def tearDown(self):
        if self.collector is not None and not self.collector.closed:
            self.collector.close('test_cleanup')
        # Snapshots deliberately mark evidence files read-only on Windows.
        for path in self.root.rglob('*'):
            if path.is_file():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)
        self.temporary.cleanup()

    def collect(self, capture=fake_capture):
        self.collector = poc.Collector(self.log, self.output, interval=.02,
            capture=capture, find_window=lambda: {'pid': 1, 'hwnd': 2})
        return self.collector

    def test_partial_completion_reset_unknown_and_malformed_evidence(self):
        source = source_rows()[:12]
        save(self.log, source)
        with self.log.open('ab') as stream:
            stream.write(b'{"unknownFutureEnvelope":')
        collector = self.collect()
        collector.poll_once(screenshots=False)
        states = rows(self.output / 'state_observations.jsonl')
        self.assertTrue(states[-1]['framer_partial_at_poll_end'])
        self.assertFalse(states[-1]['document']['current']['valid'])
        self.assertEqual(states[-1]['document']['error'], 'partial_raw_record_waiting')
        self.assertTrue(states[-1]['document']['diagnostic_current_before_source_invalidation']['valid'])
        with self.log.open('ab') as stream:
            stream.write(b'{"literal":"retained"}}\n{broken}\n')
        collector.poll_once(screenshots=False)
        raw = rows(self.output / 'raw_records.jsonl')
        self.assertEqual(raw[-2]['entry'], {'unknownFutureEnvelope': {'literal': 'retained'}})
        self.assertIsNone(raw[-1]['entry'])
        self.assertEqual(raw[-1]['source']['precision'], 'poll_span_not_record_span')
        self.assertEqual(collector.counts['malformed_records'], 1)
        self.log.write_text('{"new_unknown_record":true}\n', encoding='utf-8')
        collector.poll_once(screenshots=False)
        self.assertEqual(collector.follower.generation, 2)
        self.assertEqual(collector.counts['file_resets_after_startup'], 1)
        self.assertFalse(rows(self.output / 'state_observations.jsonl')[-1]['document']['current']['valid'])

    def test_recordless_partial_poll_publishes_invalid_boundary_and_snapshot_health(self):
        save(self.log, source_rows()[:12])
        collector = self.collect()
        collector.poll_once(screenshots=False)
        initial = rows(self.output / 'state_observations.jsonl')
        initial_raw_count = len(rows(self.output / 'raw_records.jsonl'))
        self.assertTrue(initial[-1]['document']['current']['valid'])
        with self.log.open('ab') as stream:
            stream.write(b'{"unknownFutureEnvelope":')
        collector.poll_once(screenshots=False)
        states = rows(self.output / 'state_observations.jsonl')
        self.assertEqual(len(states), len(initial) + 1)
        self.assertEqual(len(rows(self.output / 'raw_records.jsonl')), initial_raw_count)
        boundary = states[-1]
        self.assertEqual(boundary['kind'], 'poll_boundary')
        self.assertIsNone(boundary['record_id'])
        self.assertEqual(boundary['last_record_id'], initial_raw_count)
        self.assertFalse(boundary['document']['current']['valid'])
        self.assertFalse(boundary['document']['current']['actionable'])
        self.assertEqual(boundary['document']['error'], 'partial_raw_record_waiting')
        self.assertTrue(boundary['document']['diagnostic_current_before_source_invalidation']['valid'])
        frozen = self.root / 'partial-frozen'
        poc.snapshot(self.output, frozen)
        manifest = json.loads((frozen / 'manifest.json').read_text())
        self.assertTrue(manifest['boundary_log_health']['partial_record'])
        self.assertEqual(manifest['boundary_log_health']['framing_errors'], 0)
        self.assertEqual(manifest['boundary_log_health']['source']['generation'], 1)
        self.assertEqual(manifest['boundary_log_health']['records'], 0)
        self.assertFalse(rows(frozen / 'state_observations.jsonl')[-1]['document']['current']['valid'])

    def test_same_poll_request_submission_order_is_not_lost_in_final_state(self):
        source = source_rows()[:12]
        save(self.log, source)
        collector = self.collect()
        collector.poll_once(screenshots=False)
        raw = rows(self.output / 'raw_records.jsonl')
        self.assertEqual([row['entry'] for row in raw], source)
        observations = rows(self.output / 'log_observations.jsonl')
        response = next(row for row in observations
            if row['client_response_type'] == 'ClientMessageType_PerformActionResp')
        self.assertTrue(response['exact_current_own_response_paired'])
        self.assertEqual(response['pair_confirmation'], 'client_submission_only')
        states = rows(self.output / 'state_observations.jsonl')
        accepted = [event for row in states for event in row['semantic_observer_events']
                    if event['event'] == 'request_accepted']
        self.assertTrue(any(event['details']['request']['id'] == 37 for event in accepted))
        self.assertIsNone(states[-1]['document']['current']['request'])
        self.assertTrue(all(row['poll_id'] == 1 for row in raw))

    def test_snapshot_excludes_uncommitted_poll_partial_line_and_late_capture(self):
        save(self.log, source_rows()[:12])
        collector = self.collect()
        collector.poll_once()
        committed_raw = (self.output / 'raw_records.jsonl').read_bytes()
        collector.write('raw_records.jsonl', {'poll_id': 2, 'record_id': 999,
                                            'entry': {'future': True}})
        with (self.output / 'log_observations.jsonl').open('ab') as stream:
            stream.write(b'{"poll_id":2')
        collector.write('screenshots.jsonl', {'poll_id': 1, 'file_completed': False,
            'capture_completed': {'monotonic_ns': time.monotonic_ns()}})
        frozen = self.root / 'frozen'
        report = poc.snapshot(self.output, frozen)
        self.assertEqual(report['completed_poll_id'], 1)
        self.assertEqual(report['source_collector_status'], 'running')
        self.assertEqual((frozen / 'raw_records.jsonl').read_bytes(), committed_raw)
        self.assertEqual(len(rows(frozen / 'screenshots.jsonl')), 1)
        manifest = json.loads((frozen / 'manifest.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(poc.digest(frozen / name), expected['sha256'])
        self.assertTrue((frozen / 'screenshots' / '00000001.png').is_file())
        # Freeze does not mutate the collector, its files or its active status.
        self.assertFalse(collector.closed)
        self.assertEqual(json.loads((self.output / 'manifest.json').read_text())['status'], 'running')

    def test_saved_failed_quality_frame_does_not_count_as_api_quality_success(self):
        def black(hwnd, pid, path, method='printwindow'):
            path.write_bytes(b'black-test-artifact')
            return {'status': 'failed', 'reason': 'black_frame'}
        save(self.log, [])
        collector = self.collect(black)
        collector.poll_once()
        self.assertEqual(collector.counts['screenshots_completed'], 1)
        self.assertEqual(collector.counts['api_quality_frames'], 0)
        self.assertEqual(collector.counts['capture_failures'], 1)
        row = rows(self.output / 'screenshots.jsonl')[0]
        self.assertTrue(row['file_completed'])
        self.assertFalse(row['api_quality_success'])
        self.assertFalse(row['visual_content_verified'])

    def test_failed_api_and_file_publication_error_count_one_failed_attempt(self):
        def black(hwnd, pid, path, method='printwindow'):
            path.write_bytes(b'failed-test-artifact')
            return {'status': 'failed', 'reason': 'black_frame'}
        save(self.log, [])
        collector = self.collect(black)
        # A failed-quality API result followed by a file publication error
        # remains one capture attempt, not two independent capture failures.
        with patch.object(poc.os, 'replace', side_effect=OSError('publication_error')):
            collector.capture_once()
        self.assertEqual(collector.counts['capture_failures'], 1)
        self.assertEqual(collector.counts['screenshots_completed'], 0)
        self.assertEqual(collector.counts['api_quality_frames'], 0)
        observations = rows(self.output / 'screenshots.jsonl')
        self.assertEqual(len(observations), 1)
        self.assertFalse(observations[0]['file_completed'])

    def test_hung_capture_does_not_block_log_polls_or_bounded_shutdown(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(hwnd, pid, path, method='printwindow'):
            entered.set()
            release.wait(5)
            return {'status': 'failed', 'reason': 'test_released'}
        save(self.log, source_rows()[:12])
        collector = self.collect(blocked)
        started = time.monotonic()
        try:
            collector.run(duration=.09)
            elapsed = time.monotonic() - started
            self.assertTrue(entered.is_set())
            self.assertLess(elapsed, 1.5)
            self.assertGreaterEqual(collector.counts['polls'], 3)
            self.assertGreater(collector.counts['records'], 0)
            final = json.loads((self.output / 'manifest.json').read_text())
            self.assertTrue(final['capture_shutdown']['capture_in_progress'])
            self.assertEqual(final['capture_shutdown']['capture_api_timeout'], 'unknown')
        finally:
            release.set()
            collector.capture_thread.join(1)


if __name__ == '__main__':
    unittest.main()
