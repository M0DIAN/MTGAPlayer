"""Local consumer tests: scrubbed fixtures and explicitly synthetic mutations.

Subprocess tests use project Python 3.11 and real OS stdin/stdout pipes. No
private Player.log, actual MTGA, desktop input, or network is used.
"""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from mtgaplayer.cli import replay, watch, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, MAX_LINE_BYTES, consume_events
from test_action_frontier import save
from test_combat_frontier import ATTACK, BLOCK, baseline, request as combat_request
from test_decision_input import rows as selectn_rows
from test_decision_publisher import ManualClock, own_request, poll_events
from test_raw_log import entries

ROOT = Path(__file__).resolve().parents[1]


def encoded(events):
    return ''.join(json.dumps(event) + '\n' for event in events)


class DecisionConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'synthetic.jsonl'
        save(self.path, entries()[:3] + [own_request()])
        self.producer_clock = ManualClock(1_000_000)
        self.events = list(watch_decision_events(self.path, interval=0, samples=1,
            clock_ns=self.producer_clock, session_id='synthetic-session'))
        self.snapshot, self.live, self.revoke, self.stop = self.events
        self.clock = ManualClock(100)  # Deliberately unrelated to producer time.
        self.consumer = DecisionConsumer(1000, 500, self.clock)

    def assert_empty(self, status, consumer=None):
        view = (consumer or self.consumer).current_view()
        self.assertEqual(view['consumer_status'], status)
        self.assertIsNone(view['current_snapshot_ref'])
        self.assertIsNone(view['decision_state'])
        self.assertFalse(view['new_request_observed'])
        for key in ('actionable', 'execution_ready', 'input_sent'):
            self.assertIs(view[key], False)
        return view

    def test_normal_snapshot_and_detached_views(self):
        original = copy.deepcopy(self.snapshot)
        self.assertTrue(self.consumer.accept_event(self.snapshot))
        self.snapshot['decision_state']['visible_objects'].clear()
        self.snapshot['snapshot_ref']['binding']['game'] = 99
        view = self.consumer.current_view()
        self.assertEqual(view['decision_state'], original['decision_state'])
        view['decision_state']['legal_action_space'].clear()
        view['current_snapshot_ref'].clear()
        self.assertEqual(self.consumer.current_view()['decision_state'], original['decision_state'])
        self.assertFalse(view['decision_state']['source']['freshness_verified'])

    def test_first_liveness_then_snapshot(self):
        live = copy.deepcopy(self.live)
        live.update(sequence=1, current_snapshot_ref=None)
        live['binding'] = dict.fromkeys(live['binding'])
        live['timing']['observation_age_ns'] = None
        self.assertTrue(self.consumer.accept_event(live))
        self.assert_empty('WAITING')
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['sequence'] = snapshot['snapshot_ref']['sequence'] = 2
        self.assertTrue(self.consumer.accept_event(snapshot))
        self.assertEqual(self.consumer.current_view()['consumer_status'], 'OBSERVING')

    def test_exact_revoke_and_new_outer_identity(self):
        self.assertTrue(self.consumer.accept_event(self.snapshot))
        revoke = copy.deepcopy(self.revoke)
        revoke.update(sequence=2, reason='state_advanced', subscription_active=True, source_status='invalid')
        revoke['binding']['game_state_id'] += 1
        self.assertTrue(self.consumer.accept_event(revoke))
        self.assert_empty('INVALIDATED')
        live = copy.deepcopy(self.live)
        live.update(sequence=3, binding=revoke['binding'], current_snapshot_ref=None)
        self.assertTrue(self.consumer.accept_event(live))
        self.assert_empty('INVALIDATED')

    def test_every_supported_invalidation_reason(self):
        from mtgaplayer.decision_consumer import INVALIDATE_REASONS
        for reason in INVALIDATE_REASONS:
            with self.subTest(reason=reason):
                consumer = DecisionConsumer(clock_ns=self.clock)
                self.assertTrue(consumer.accept_event(self.snapshot))
                revoke = copy.deepcopy(self.revoke)
                revoke.update(sequence=2, reason=reason, subscription_active=reason != 'session_stopped')
                self.assertTrue(consumer.accept_event(revoke))
                self.assert_empty('INVALIDATED', consumer)

    def test_wrong_revoke_quarantines(self):
        self.consumer.accept_event(self.snapshot)
        revoke = copy.deepcopy(self.revoke)
        revoke['sequence'] = 2
        revoke['revoked']['binding']['request_id'] += 1
        self.assertFalse(self.consumer.accept_event(revoke))
        self.assert_empty('PROTOCOL_ERROR')
        self.assertFalse(self.consumer.accept_event(self.live))

    def test_snapshot_invalidate_liveness_same_poll_order(self):
        live = copy.deepcopy(self.live)
        revoke = copy.deepcopy(self.revoke)
        revoke.update(sequence=2, reason='observation_stale', subscription_active=True)
        live.update(sequence=3, current_snapshot_ref=None)
        for event, status in zip((self.snapshot, revoke, live), ('OBSERVING', 'INVALIDATED', 'INVALIDATED')):
            self.assertTrue(self.consumer.accept_event(event))
            self.assertEqual(self.consumer.current_view()['consumer_status'], status)
        self.assert_empty('INVALIDATED')

    def test_invalidate_snapshot_liveness_same_poll_order(self):
        self.consumer.accept_event(self.snapshot)
        revoke = copy.deepcopy(self.revoke)
        revoke.update(sequence=2, reason='request_replaced', subscription_active=True)
        # JSON transport has no object aliases between repeated child keys.
        next_snapshot = json.loads(json.dumps(self.snapshot))
        next_snapshot['sequence'] = next_snapshot['snapshot_ref']['sequence'] = 3
        # Same gameStateId, a different request identity (including child keys).
        def replace_request(node):
            if isinstance(node, dict):
                if 'request_id' in node:
                    node['request_id'] += 1
                for child in node.values():
                    replace_request(child)
            elif isinstance(node, list):
                for child in node:
                    replace_request(child)
        replace_request(next_snapshot)
        next_snapshot['phase'] = next_snapshot['decision_state']['source']['phase'] = 'append'
        next_snapshot['new_request_observed'] = True
        revoke['binding'] = next_snapshot['binding']
        live = copy.deepcopy(self.live)
        live.update(sequence=4, binding=next_snapshot['binding'], current_snapshot_ref=next_snapshot['snapshot_ref'])
        for event in (revoke, next_snapshot, live):
            self.assertTrue(self.consumer.accept_event(event))
        view = self.consumer.current_view()
        self.assertEqual(view['current_snapshot_ref']['sequence'], 3)
        self.assertTrue(view['new_request_observed'])

    def test_duplicate_backward_gap_bool_float_and_session(self):
        for sequence, session in ((1, 'synthetic-session'), (0, 'synthetic-session'),
                (3, 'synthetic-session'), (True, 'synthetic-session'),
                (2.0, 'synthetic-session'), (2, 'changed-session'), (2, 'bad session!')):
            with self.subTest(sequence=sequence, session=session):
                consumer = DecisionConsumer(clock_ns=self.clock)
                consumer.accept_event(self.snapshot)
                event = copy.deepcopy(self.live)
                event.update(sequence=sequence, session_id=session)
                self.assertFalse(consumer.accept_event(event))
                self.assert_empty('PROTOCOL_ERROR', consumer)

    def test_first_sequence_must_be_one(self):
        self.assertFalse(self.consumer.accept_event(self.live))
        self.assert_empty('PROTOCOL_ERROR')

    def test_binding_and_nested_request_identity_mismatches(self):
        for key, replacement in (('source_generation', 999), ('match', 'different'),
                ('game', 99), ('self_seat', 2), ('game_state_id', 99), ('request_id', 999),
                ('request_type', 'GREMessageType_SelectNReq')):
            for location in ('binding', 'snapshot_ref', 'decision_state'):
                with self.subTest(key=key, location=location):
                    consumer = DecisionConsumer(clock_ns=self.clock)
                    event = copy.deepcopy(self.snapshot)
                    binding = event['binding'] if location == 'binding' else event[location]['binding']
                    binding[key] = replacement
                    self.assertFalse(consumer.accept_event(event))
                    self.assert_empty('PROTOCOL_ERROR', consumer)
        event = copy.deepcopy(self.snapshot)
        event['decision_state']['legal_action_space']['immediate_frontier']['projection']['request_identity']['request_id'] += 1
        self.assertFalse(self.consumer.accept_event(event))
        self.assert_empty('PROTOCOL_ERROR')

    def test_unrevoked_snapshot_replacement_is_rejected(self):
        self.consumer.accept_event(self.snapshot)
        event = copy.deepcopy(self.snapshot)
        event['sequence'] = event['snapshot_ref']['sequence'] = 2
        self.assertFalse(self.consumer.accept_event(event))
        self.assert_empty('PROTOCOL_ERROR')

    def test_history_snapshot_is_not_new_opportunity(self):
        self.assertFalse(self.snapshot['new_request_observed'])
        self.consumer.accept_event(self.snapshot)
        view = self.consumer.current_view()
        self.assertIsNotNone(view['decision_state']['binding']['request_id'])
        self.assertFalse(view['new_request_observed'])
        event = copy.deepcopy(self.snapshot)
        event['new_request_observed'] = True
        other = DecisionConsumer(clock_ns=self.clock)
        self.assertFalse(other.accept_event(event))
        # An append envelope cannot relabel a history DecisionState either.
        event['phase'] = 'append'
        self.assertFalse(DecisionConsumer(clock_ns=self.clock).accept_event(event))

    def test_liveness_does_not_refresh_evidence_or_mix_process_clocks(self):
        self.snapshot['timing']['observation_age_ns'] = 40
        self.consumer.accept_event(self.snapshot)
        self.clock.advance(100)
        live = copy.deepcopy(self.live)
        live['timing']['observation_age_ns'] = 50
        self.assertTrue(self.consumer.accept_event(live))
        view = self.consumer.current_view()
        self.assertEqual(view['observation_age_ns'], 140)
        self.assertEqual(view['last_snapshot_received_ns'], 100)
        self.assertEqual(view['last_event_received_ns'], 200)
        self.clock.advance(361)
        self.assert_empty('STALE')

    def test_reported_age_cannot_regress_under_same_reference(self):
        self.snapshot['timing']['observation_age_ns'] = 20
        self.consumer.accept_event(self.snapshot)
        live = copy.deepcopy(self.live)
        live['timing']['observation_age_ns'] = 19
        self.assertFalse(self.consumer.accept_event(live))
        self.assert_empty('PROTOCOL_ERROR')

    def test_local_queue_delay_counts_as_age_and_silence(self):
        self.clock.advance(200)
        self.assertTrue(self.consumer.accept_event(self.snapshot, received_ns=100))
        view = self.consumer.current_view()
        self.assertEqual(view['observation_age_ns'], 200)
        self.assertEqual(view['last_snapshot_received_ns'], 100)
        self.assertEqual(view['last_event_received_ns'], 100)
        self.clock.advance(301)
        self.assert_empty('STALE')
        other = DecisionConsumer(clock_ns=self.clock)
        self.assertFalse(other.accept_event(self.snapshot, received_ns=self.clock.now + 1))
        self.assert_empty('PROTOCOL_ERROR', other)

    def test_liveness_cannot_create_or_restore_snapshot(self):
        live = copy.deepcopy(self.live)
        live['sequence'] = 1
        self.assertFalse(self.consumer.accept_event(live))
        self.assert_empty('PROTOCOL_ERROR')
        other = DecisionConsumer(clock_ns=self.clock)
        other.accept_event(self.snapshot)
        revoke = copy.deepcopy(self.revoke)
        revoke['sequence'] = 2
        other.accept_event(revoke)
        live['sequence'] = 3
        self.assertFalse(other.accept_event(live))
        self.assert_empty('PROTOCOL_ERROR', other)

    def test_liveness_missing_ref_is_not_implicit_invalidation(self):
        self.consumer.accept_event(self.snapshot)
        event = copy.deepcopy(self.live)
        event['current_snapshot_ref'] = None
        self.assertFalse(self.consumer.accept_event(event))
        self.assert_empty('PROTOCOL_ERROR')

    def test_stopped_eof_and_no_reactivation(self):
        for event in self.events:
            self.assertTrue(self.consumer.accept_event(event))
        self.assert_empty('CLOSED')
        self.consumer.close('eof')
        self.assertEqual(self.consumer.current_view()['unresolved'], ['sample_limit'])
        event = copy.deepcopy(self.snapshot)
        event['sequence'] = event['snapshot_ref']['sequence'] = 5
        self.assertFalse(self.consumer.accept_event(event))
        self.assert_empty('CLOSED')

    def test_session_stopped_invalidation_cannot_reopen_subscription(self):
        self.consumer.accept_event(self.snapshot)
        revoke = copy.deepcopy(self.revoke)
        revoke['sequence'] = 2
        self.assertTrue(self.consumer.accept_event(revoke))
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['sequence'] = snapshot['snapshot_ref']['sequence'] = 3
        self.assertFalse(self.consumer.accept_event(snapshot))
        self.assert_empty('PROTOCOL_ERROR')

    def test_first_stopped_and_stopped_without_invalidate_clear(self):
        stop = copy.deepcopy(self.stop)
        stop['sequence'] = 1
        self.assertTrue(self.consumer.accept_event(stop))
        self.assert_empty('CLOSED')
        other = DecisionConsumer(clock_ns=self.clock)
        other.accept_event(self.snapshot)
        stop['sequence'] = 2
        self.assertTrue(other.accept_event(stop))
        self.assert_empty('CLOSED', other)

    def test_eof_disconnect_input_error_and_cancellation_clear(self):
        for reason in ('eof', 'pipe_disconnected', 'input_stream_error', 'cancelled', 'producer_exited'):
            with self.subTest(reason=reason):
                consumer = DecisionConsumer(clock_ns=self.clock)
                consumer.accept_event(self.snapshot)
                consumer.close(reason)
                view = self.assert_empty('CLOSED', consumer)
                self.assertEqual(view['unresolved'], ['unexpected_eof' if reason == 'eof' else reason])

    def test_transport_silence_even_before_first_event(self):
        self.clock.advance(1001)
        view = self.consumer.tick()
        self.assertEqual(view['unresolved'], ['event_silence_expired'])
        self.assert_empty('STALE')
        self.assertFalse(self.consumer.accept_event(self.snapshot))

    def test_transport_silence_and_age_have_separate_reasons(self):
        consumer = DecisionConsumer(50, 500, self.clock)
        consumer.accept_event(self.snapshot)
        self.clock.advance(51)
        self.assertEqual(consumer.tick()['unresolved'], ['event_silence_expired'])
        self.assert_empty('STALE', consumer)
        self.consumer.accept_event(self.snapshot)
        self.clock.advance(501)
        self.assertEqual(self.consumer.tick()['unresolved'], ['observation_age_expired'])
        self.assert_empty('STALE')

    def test_structure_versions_integer_authority_and_completeness(self):
        mutations = [lambda e: e.update(schema_version='v2'),
            lambda e: e.update(event_type='unknown'), lambda e: e.pop('binding'),
            lambda e: e['binding'].update(game=True), lambda e: e['timing'].update(published_ns=1.0),
            lambda e: e['decision_state'].update(schema_version='v2'),
            lambda e: e['decision_state']['source'].update(freshness_verified=True),
            lambda e: e['decision_state']['visible_objects'].append({'instance_id': True,
                'card_id': None, 'zone': None, 'owner_seat': None, 'controller_seat': None,
                'tapped': None, 'effective_power': None, 'effective_toughness': None}),
            lambda e: e['decision_state']['legal_action_space']['immediate_frontier'].update(completeness='complete_verified'),
            lambda e: e['decision_state']['legal_action_space']['immediate_frontier']['projection']['templates'][0].update(execution_ready=True),
            lambda e: e['decision_state']['legal_action_space']['immediate_frontier']['projection']['templates'][0]['action_key'].update(list_position=0.0),
            lambda e: e['execution'].update(input_sent=0),
            lambda e: e['decision_state']['legal_action_space'].update(choice_graph=[])]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                consumer = DecisionConsumer(clock_ns=self.clock)
                event = copy.deepcopy(self.snapshot)
                mutation(event)
                self.assertFalse(consumer.accept_event(event))
                self.assert_empty('PROTOCOL_ERROR', consumer)

    def test_nested_extensible_permissions_and_completeness_are_checked(self):
        for key, value in (('read_only', False), ('usable_now', True), ('server_acceptance_verified', True),
                ('some_completeness_claim', 'complete_verified')):
            with self.subTest(key=key):
                event = copy.deepcopy(self.snapshot)
                projection = event['decision_state']['legal_action_space']['immediate_frontier']['projection']
                projection['extra'] = {'deep': [{key: value}]}
                self.assertFalse(DecisionConsumer(clock_ns=self.clock).accept_event(event))

    def test_bounds_cycles_and_nonfinite_values(self):
        for mode in ('depth', 'cycle', 'size', 'nan'):
            event = copy.deepcopy(self.snapshot)
            if mode == 'depth':
                value = {}
                for _ in range(40):
                    value = {'nested': value}
            elif mode == 'cycle':
                value = []
                value.append(value)
            elif mode == 'size':
                value = 'x' * (MAX_LINE_BYTES + 1)
            else:
                value = float('nan')
            event['extra'] = value
            self.assertFalse(DecisionConsumer(clock_ns=self.clock).accept_event(event))

    def test_four_existing_projection_shapes(self):
        for rows in (entries()[:3] + [own_request()], selectn_rows(),
                baseline() + [combat_request(ATTACK)], baseline() + [combat_request(BLOCK)]):
            save(self.path, rows)
            consumer = DecisionConsumer(clock_ns=self.clock)
            for event in watch_decision_events(self.path, interval=0, samples=1, clock_ns=self.producer_clock):
                self.assertTrue(consumer.accept_event(event), event['event_type'])
            self.assert_empty('CLOSED', consumer)

    def test_state_without_request_and_unsupported_request(self):
        save(self.path, entries()[:3])
        no_request = next(watch_decision_events(self.path, interval=0, samples=1,
                                                clock_ns=self.producer_clock))
        self.assertTrue(self.consumer.accept_event(no_request))
        self.assertIsNone(self.consumer.current_view()['decision_state']['binding']['request_id'])
        unsupported = copy.deepcopy(self.snapshot)
        for binding in (unsupported['binding'], unsupported['snapshot_ref']['binding'],
                        unsupported['decision_state']['binding']):
            binding['request_type'] = 'Synthetic_Unknown_Request'
        space = unsupported['decision_state']['legal_action_space']
        space.update(request_type='Synthetic_Unknown_Request', choice_graph=None,
            immediate_frontier={'kind': None, 'availability': 'unsupported',
                                'completeness': 'unknown', 'projection': None})
        self.assertTrue(DecisionConsumer(clock_ns=self.clock).accept_event(unsupported))

    def test_stream_normal_eof_partial_json_and_duplicate_keys(self):
        cases = [(encoded(self.events), 0, 'CLOSED', 'sample_limit'),
            (encoded([self.snapshot]), 1, 'CLOSED', 'unexpected_eof'),
            (encoded([self.snapshot]) + '{"event', 1, 'PROTOCOL_ERROR', 'invalid_json_line'),
            (json.dumps(self.snapshot), 1, 'PROTOCOL_ERROR', 'invalid_json_line'),
            ('{"sequence":1,"sequence":2}\n', 1, 'PROTOCOL_ERROR', 'invalid_json_line')]
        for payload, code, status, reason in cases:
            with self.subTest(reason=reason):
                output = []
                consumer = DecisionConsumer(clock_ns=self.clock)
                self.assertEqual(consume_events(io.StringIO(payload), output.append, consumer), code)
                self.assert_empty(status, consumer)
                self.assertEqual(output[-1]['unresolved'], [reason])
                self.assertTrue(all('decision_state' not in row and 'binding' not in row for row in output))

    def test_stream_read_error_clears_current(self):
        class BrokenStream:
            def __init__(inner):
                inner.first = True
            def readline(inner, size):
                if inner.first:
                    inner.first = False
                    return encoded([self.snapshot])
                raise OSError('synthetic input failure: private content must not be echoed')
        output = []
        self.assertEqual(consume_events(BrokenStream(), output.append, self.consumer), 1)
        self.assert_empty('CLOSED')
        self.assertEqual(output[-1]['unresolved'], ['input_stream_error'])

    def test_output_pipe_disconnect_and_callback_abandonment_clear(self):
        for error in (BrokenPipeError('synthetic disconnect'), RuntimeError('synthetic callback error')):
            consumer = DecisionConsumer(clock_ns=self.clock)
            def emit(value):
                raise error
            if isinstance(error, OSError):
                self.assertEqual(consume_events(io.StringIO(encoded(self.events)), emit, consumer), 1)
            else:
                with self.assertRaises(RuntimeError):
                    consume_events(io.StringIO(encoded(self.events)), emit, consumer)
            self.assert_empty('CLOSED', consumer)

    def test_open_blocked_stream_ticks_and_terminates(self):
        unblock = threading.Event()
        self.addCleanup(unblock.set)
        class SilentStream:
            def __init__(inner):
                inner.first = True
            def readline(inner, size):
                if inner.first:
                    inner.first = False
                    return encoded([self.snapshot])
                unblock.wait(5)
                return ''
        consumer = DecisionConsumer(80_000_000, 1_000_000_000)
        output, started = [], time.monotonic()
        self.assertEqual(consume_events(SilentStream(), output.append, consumer, tick_seconds=.01), 1)
        self.assertLess(time.monotonic() - started, 2)
        self.assert_empty('STALE', consumer)
        self.assertEqual(output[-1]['unresolved'], ['event_silence_expired'])

    def test_bounded_queue_overflow_does_not_drop_invalidation_silently(self):
        # Synchronous StringIO reader fills capacity one before the main loop;
        # either detect overflow before snapshot or on the next iteration.
        output = []
        code = consume_events(io.StringIO(encoded(self.events * 100)), output.append,
                              self.consumer, queue_capacity=1)
        self.assertEqual(code, 1)
        self.assert_empty('PROTOCOL_ERROR')
        self.assertEqual(output[-1]['unresolved'], ['input_queue_overflow'])

    def test_real_two_process_producer_consumer_pipe(self):
        producer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'watch',
            str(self.path), '--decision-events', '--samples', '5', '--interval', '.001'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
        consumer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events'],
            stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
        producer.stdout.close()
        try:
            out, err = consumer.communicate(timeout=10)
            producer.wait(timeout=10)
            producer_err = producer.stderr.read()
            self.assertEqual(producer.returncode, 0, producer_err)
            self.assertEqual(consumer.returncode, 0, err)
            rows = [json.loads(line) for line in out.splitlines()]
            self.assertTrue(all(row['consumer_status'] == 'WAITING' for row in rows if row['last_sequence'] == 0))
            rows = [row for row in rows if row['last_sequence'] > 0]
            self.assertEqual(rows[0]['consumer_status'], 'OBSERVING')
            self.assertEqual(rows[-1]['consumer_status'], 'CLOSED')
            self.assertEqual([row['last_sequence'] for row in rows], list(range(1, len(rows) + 1)))
            self.assertFalse(any(row['new_request_observed'] for row in rows))
        finally:
            for process in (producer, consumer):
                if process.poll() is None:
                    process.kill()
                process.wait()
            producer.stderr.close()

    def test_real_consumer_pipe_stays_open_and_silent(self):
        process = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events',
            '--max-event-silence-ms', '100', '--max-observation-age-ms', '10000'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
        try:
            process.stdin.write(encoded([self.snapshot]).encode())
            process.stdin.flush()
            process.wait(timeout=5)  # stdin is deliberately still open.
            out, err = process.stdout.read(), process.stderr.read()
            self.assertEqual(process.returncode, 1, err)
            rows = [json.loads(line) for line in out.splitlines()]
            self.assertTrue(any(row['consumer_status'] == 'OBSERVING' for row in rows))
            self.assertEqual(rows[-1]['unresolved'], ['event_silence_expired'])
            self.assertNotIn(b'Fatal Python error', err)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()

    def test_default_watch_and_replay_interfaces_remain_unchanged(self):
        default = replay(self.path, format='player-log')
        self.assertNotIn('decision_state', default)
        self.assertNotIn('event_type', default)
        document = next(watch(self.path, interval=0, samples=1))
        self.assertNotIn('decision_state', document)
        self.assertNotIn('event_type', document)
        for command in ('replay', 'dry-run'):
            result = subprocess.run([sys.executable, '-m', 'mtgaplayer', command,
                'examples/synthetic.jsonl'], capture_output=True, cwd=ROOT, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('event_type', json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
