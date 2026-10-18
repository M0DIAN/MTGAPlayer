"""Independent MP80 adversarial controls. All stream variants are synthetic.

Only the committed scrubbed bootstrap fixture is used. No private retained raw
bytes, implementation-author test helper, or private artifact is read.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary


def baseline():
    rows = [json.loads(line) for line in (ROOT / 'tests/fixtures/player_log_minimal.jsonl').read_text(encoding='utf8').splitlines()[:3]]
    gs = rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
    gs['gameObjects'] = [{'instanceId': 1001, 'grpId': 901, 'type': 'GameObjectType_Card', 'zoneId': 28,
        'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public', 'isTapped': False}]
    next(z for z in gs['zones'] if z['zoneId'] == 28)['objectInstanceIds'] = [1001]
    return rows


def request(ident=500, typ='ActionsAvailable'):
    m = {'type': f'GREMessageType_{typ}Req', 'systemSeatIds': [1], 'msgId': ident, 'gameStateId': 1}
    if typ == 'ActionsAvailable':
        m['actionsAvailableReq'] = {'actions': [{'actionType': 'ActionType_Pass'}]}
    return {'greToClientEvent': {'greToClientMessages': [m]}}


def response(ident=500):
    return {'payload': {'type': 'ClientMessageType_PerformActionResp', 'respId': ident, 'gameStateId': 1}}


def encoded(rows):
    return ''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in rows).encode()


class Clock:
    now = 1_000_000_000
    def __call__(self): return self.now


class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic-owner-stream.jsonl'
        self.clock = Clock()

    def stream(self, initial=None, **kwargs):
        self.path.write_bytes(encoded(baseline() if initial is None else initial))
        self.runtime = LocalShadowRuntime(self.path, interval=0, samples=None, clock_ns=self.clock,
            observation_mode='controlled_stream_replay', **kwargs)
        self.gen = self.runtime.frames()
        self.addCleanup(self.gen.close)
        self.addCleanup(self.runtime.close)
        return next(self.gen)

    def append(self, rows):
        with self.path.open('ab') as out: out.write(encoded(rows))
        return next(self.gen)

    def assert_revoked(self, f):
        self.assertNotEqual(f['time_scope'], 'current_at_completed_poll')
        self.assertIsNone(f['request_binding'])
        self.assertIsNone(f['current_options'])
        self.assertIsNone(f['shadow_preference'])
        self.assertFalse(f['input_sent'])

    def test_history_and_duplicate_are_not_opportunities(self):
        self.assert_revoked(self.stream(baseline()+[request()]))
        self.assert_revoked(self.append([request(), {}]))
        f = self.append([request(501)])
        self.assertEqual(f['request_binding']['request_id'], 501)

    def test_same_poll_only_final_unconsumed_request(self):
        self.stream()
        f = self.append([request(), response(), request(501), request(502)])
        self.assertEqual(f['request_binding']['request_id'], 502)
        self.assertEqual(f['poll_accepted_requests'], 3)
        self.assertEqual(f['poll_consumed_requests'], 1)
        self.assert_revoked(self.append([response(502)]))

    def test_same_record_final_request_and_consumed_never_reopens(self):
        self.stream()
        r = request()
        r['greToClientEvent']['greToClientMessages'].extend(request(501)['greToClientEvent']['greToClientMessages'])
        f = self.append([r])
        self.assertEqual(f['request_binding']['request_id'], 501)
        self.assert_revoked(self.append([response(501), request(501)]))
        self.assert_revoked(next(self.gen))

    def test_partial_completion_cannot_restore_old_or_retransmitted_request(self):
        self.stream()
        self.append([request()])
        with self.path.open('ab') as out: out.write(b'{"unrelated":')
        self.assert_revoked(next(self.gen))
        with self.path.open('ab') as out: out.write(b'1}\n')
        self.assert_revoked(next(self.gen))
        self.assert_revoked(self.append([request()]))
        self.assertEqual(self.append([request(501)])['time_scope'], 'current_at_completed_poll')

    def test_partial_new_request_completed_next_poll_is_fresh(self):
        self.stream()
        data = encoded([request()])
        cut = len(data)//2
        with self.path.open('ab') as out: out.write(data[:cut])
        self.assert_revoked(next(self.gen))
        with self.path.open('ab') as out: out.write(data[cut:])
        self.assertEqual(next(self.gen)['time_scope'], 'current_at_completed_poll')

    def test_reset_and_stop_revoke(self):
        self.stream()
        self.append([request()])
        replacement = self.path.with_suffix('.replacement')
        replacement.write_bytes(encoded(baseline()+[request(501)]))
        replacement.replace(self.path)
        self.assert_revoked(next(self.gen))
        self.assert_revoked(self.append([request(501)]))
        self.assertEqual(self.append([request(502)])['time_scope'], 'current_at_completed_poll')
        self.runtime.close()
        self.assert_revoked(self.runtime.current_frame())

    def test_stale_terminal_instance_fresh_request_new_subscription(self):
        self.stream(max_observation_age_ns=10_000_000, max_event_silence_ns=10_000_000)
        self.append([request()])
        old = self.runtime.consumer
        self.clock.now += 10_000_001
        self.assert_revoked(self.runtime.current_frame())
        self.assertEqual(old.current_view()['consumer_status'], 'STALE')
        self.assert_revoked(next(self.gen))
        self.assertIs(self.runtime.consumer, old)
        self.assert_revoked(self.append([request()]))
        self.assertIs(self.runtime.consumer, old)
        self.assertEqual(self.append([request(501)])['time_scope'], 'current_at_completed_poll')
        self.assertIsNot(self.runtime.consumer, old)
        self.assertEqual(old.current_view()['consumer_status'], 'STALE')

    def test_single_follower_reducer(self):
        with patch('mtgaplayer.cli.RawFollower', wraps=RawFollower) as follower, patch('mtgaplayer.cli.RawReducer', wraps=RawReducer) as reducer:
            self.stream()
            self.append([request()])
            self.assertEqual(follower.call_count, 1)
            self.assertEqual(reducer.call_count, 1)

    def test_raw_digest_change_during_frame_revokes(self):
        self.stream()
        self.append([request()])
        original = self.runtime.consumer.shadow_decision
        def altered():
            result = original()
            self.runtime._message['actionsAvailableReq']['actions'].append({'actionType':'ActionType_Pass'})
            return result
        with patch.object(self.runtime.consumer, 'shadow_decision', side_effect=altered):
            self.assert_revoked(self.runtime.current_frame())

    def test_visible_source_identity_change_during_frame_revokes(self):
        self.stream()
        self.append([request()])
        original = self.runtime.consumer.shadow_decision
        def altered():
            result = original()
            self.runtime._reducer.objects[1001]['grpId'] += 1
            return result
        with patch.object(self.runtime.consumer, 'shadow_decision', side_effect=altered):
            self.assert_revoked(self.runtime.current_frame())

    def test_visible_source_disagrees_before_frame_revokes(self):
        self.stream()
        self.append([request()])
        self.runtime._reducer.objects[1001]['grpId'] += 1
        self.assert_revoked(self.runtime.current_frame())

    def test_source_status_change_during_frame_revokes(self):
        for key, value in [('partial_record', True), ('stopped', True), ('phase', 'history')]:
            with self.subTest(key=key):
                self.stream()
                self.append([request()])
                original = self.runtime.consumer.shadow_decision
                def altered():
                    result = original()
                    self.runtime._source[key] = value
                    return result
                with patch.object(self.runtime.consumer, 'shadow_decision', side_effect=altered):
                    self.assert_revoked(self.runtime.current_frame())
                self.gen.close()

    def test_lease_expiry_during_frame_revokes(self):
        self.stream(max_observation_age_ns=10_000_000)
        self.append([request()])
        original = self.runtime.consumer.shadow_decision
        def altered():
            result = original()
            self.clock.now += 10_000_001
            return result
        with patch.object(self.runtime.consumer, 'shadow_decision', side_effect=altered):
            self.assert_revoked(self.runtime.current_frame())

    def test_stop_during_whole_frame_and_foreign_thread_revoke(self):
        self.stream();self.append([request()])
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.runtime.current_frame()))
        worker.start();worker.join()
        self.assert_revoked(results[0]);self.assertEqual(results[0]['reason'],'owner_thread_required')
        original=self.runtime.consumer.shadow_decision
        def stopped():
            result=original();self.runtime.close();return result
        with patch.object(self.runtime.consumer,'shadow_decision',side_effect=stopped):
            self.assert_revoked(self.runtime.current_frame())

    def test_stop_clock_failure_still_revokes_consumer_and_cache(self):
        self.stream();self.append([request()])
        self.clock.now-=1
        self.runtime.close()
        self.clock.now+=2
        self.assert_revoked(self.runtime.current_frame())
        view=self.runtime.consumer.current_view()
        self.assertNotEqual(view['consumer_status'],'OBSERVING')
        self.assertIsNone(view['current_snapshot_ref'])
        self.assertIsNone(self.runtime.consumer.current_decision_options()['request_binding'])
        self.assertEqual(self.runtime.performance_report()['counts']['stop_event_failures'],1)

    def test_global_ref_or_report_binding_change_discards_whole_frame(self):
        self.stream();self.append([request()])
        original=self.runtime.consumer.shadow_decision
        def foreign():
            result=original();result['request_binding']['request_id']+=1;return result
        with patch.object(self.runtime.consumer,'shadow_decision',side_effect=foreign):
            self.assert_revoked(self.runtime.current_frame())
        def consumed():
            result=original();self.runtime._reducer.apply(response());return result
        with patch.object(self.runtime.consumer,'shadow_decision',side_effect=consumed):
            self.assert_revoked(self.runtime.current_frame())

    def test_safe_summary_positive_whitelist(self):
        self.stream()
        f = self.append([request()])
        f.update(secret='ACCOUNT_SENTINEL', local_path='PATH_SENTINEL', request_type='CARD_SENTINEL',
            abstention_reason='RAW_SENTINEL', reason='ID_SENTINEL')
        text = json.dumps(safe_summary(f))
        for value in ('ACCOUNT_SENTINEL','PATH_SENTINEL','CARD_SENTINEL','RAW_SENTINEL','ID_SENTINEL','fixture-local','fixture-match'):
            self.assertNotIn(value, text)
        self.assertFalse(json.loads(text)['input_sent'])

    def test_safe_summary_retains_reviewed_abstention_reason(self):
        self.stream()
        f = self.append([request()])
        self.assertEqual(f['abstention_reason'], 'unique_play_not_observed')
        self.assertEqual(safe_summary(f)['abstention_reason'], f['abstention_reason'])

    def test_unknown_requests_are_explicit_unsupported_observations(self):
        self.stream()
        f = self.append([request(500, 'Mulligan')])
        self.assertEqual(f['time_scope'], 'current_at_completed_poll')
        self.assertEqual(f['request_support'], 'unsupported')
        self.assertEqual(f['shadow_policy_status'], 'unsupported')
        self.assertIsNone(f['complete_legal_choices'])
        self.assertFalse(f['input_sent'])

    def test_failure_poll_is_retained_in_latency_samples(self):
        self.stream()
        self.path.unlink()
        f = next(self.gen)
        self.assert_revoked(f)
        report = self.runtime.performance_report()
        self.assertEqual(report['counts']['failed_polls'], 1)
        self.assertEqual(report['phases']['failed_poll']['poll_count'], 1)
        self.assertEqual(report['phases']['failed_poll']['timings_ms']['poll_to_frame_ready']['attempted_samples'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
