"""MP18 event publication over committed scrubbed fixtures only.

Request bodies, malformed tails, clocks and identity changes below are explicit
synthetic variants. No private Player.log, game, desktop or network is accessed.
The stdlib checks stream invariants/schema structure, not JSON Schema validation.
"""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.cli import main, watch, watch_decision_events
from mtgaplayer.decision_publisher import DecisionPublisher, EVENT_VERSION, MAX_AGE_NS
from mtgaplayer.raw_log import RawFollower
from test_action_frontier import frames, save
from test_combat_frontier import ATTACK, BLOCK, baseline, request as combat_request
from test_decision_input import rows as selectn_rows
from test_decision_state import action_message, walk
from test_raw_log import entries, state
from test_response_evidence import action_request, reply


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'schemas/decision-event.v1.schema.json'
STATE_SCHEMA = ROOT / 'schemas/decision-state.v1.schema.json'
SAFETY_FLAGS = ('actionable', 'usable_now', 'executor_connected', 'input_sent',
                'legal_choice_verified', 'complete_legality_verified',
                'response_encoding_verified', 'server_acceptance_verified',
                'execution_ready')


def append(path, rows):
    with path.open('ab') as stream:
        stream.write(''.join(json.dumps(row) + '\n' for row in rows).encode('utf-8'))


def own_request(ident=40, state_id=1):
    """Synthetic Pass request; preserve the observed scrubbed own envelope."""
    message = copy.deepcopy(action_message(action_request([
        {'actionType': 'ActionType_Pass'}])))
    message.update(msgId=ident, gameStateId=state_id)
    return {'greToClientEvent': {'greToClientMessages': [message]}}


def poll_events(stream):
    """Consume exactly one completed poll, including its liveness marker."""
    result = []
    for event in stream:
        result.append(event)
        if event['event_type'] == 'liveness':
            return result
    raise AssertionError('stream stopped before the expected completed poll')


def of_type(events, kind):
    return [event for event in events if event['event_type'] == kind]


class ManualClock:
    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, ns):
        self.now += ns


class DecisionPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'scrubbed-synthetic.jsonl'
        self.clock = ManualClock()

    def stream(self, rows, samples=20, **options):
        save(self.path, rows)
        result = watch_decision_events(self.path, interval=0, samples=samples,
                                       clock_ns=self.clock, session_id='fixture-session',
                                       **options)
        self.addCleanup(result.close)
        return result

    def assert_stream(self, events, complete=False):
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        active = None
        snapshots = {}
        previous_publication = -1
        session = events[0]['session_id']
        for sequence, event in enumerate(events, 1):
            self.assertEqual(event['schema_version'], EVENT_VERSION)
            self.assertEqual(event['sequence'], sequence)
            self.assertEqual(event['session_id'], session)
            self.assertTrue(set(schema['required']) <= set(event))
            self.assertTrue(set(event) <= set(schema['properties']))
            self.assertEqual(set(event['binding']), set(schema['$defs']['binding']['required']))
            timing = event['timing']
            self.assertEqual(set(timing), set(schema['properties']['timing']['required']))
            for key, value in timing.items():
                if key == 'observation_stale':
                    self.assertTrue(value is None or type(value) is bool)
                elif value is not None:
                    self.assertIs(type(value), int, key)
                    self.assertGreaterEqual(value, 0, key)
            self.assertGreaterEqual(timing['published_ns'], previous_publication)
            previous_publication = timing['published_ns']
            if timing['poll_started_ns'] is not None:
                self.assertLessEqual(timing['poll_started_ns'], timing['poll_completed_ns'])
                self.assertLessEqual(timing['poll_completed_ns'], timing['published_ns'])
            self.assertIs(event['read_only'], True)
            for node in walk(event):
                for name in SAFETY_FLAGS:
                    if name in node:
                        self.assertIs(node[name], False, name)
                if 'read_only' in node:
                    self.assertIs(node['read_only'], True)
                for name, value in node.items():
                    if 'completeness' in name:
                        self.assertNotEqual(value, 'complete_verified')
            kind = event['event_type']
            self.assertIn(kind, schema['properties']['event_type']['enum'])
            if kind == 'snapshot':
                self.assertIsNone(active, 'replacement must revoke the previous reference first')
                self.assertEqual(event['binding'], event['decision_state']['binding'])
                active = event['snapshot_ref']
                self.assertEqual(active, {'session_id': session, 'sequence': sequence,
                                          'binding': event['binding']})
                snapshots[sequence] = copy.deepcopy(active)
                self.assertIs(event['subscription_active'], True)
                if event['phase'] == 'history':
                    self.assertIs(event['new_request_observed'], False)
            elif kind == 'invalidate':
                self.assertIsNotNone(active)
                self.assertEqual(event['revoked'], active)
                self.assertEqual(event['revoked'], snapshots[event['revoked']['sequence']])
                self.assertLess(event['revoked']['sequence'], sequence)
                active = None
            elif kind == 'liveness':
                self.assertEqual(event['current_snapshot_ref'], active)
                self.assertIs(event['subscription_active'], True)
            else:
                self.assertIsNone(active)
                self.assertIsNone(event['current_snapshot_ref'])
                self.assertIs(event['subscription_active'], False)
                self.assertEqual(sequence, len(events))
        if complete:
            self.assertEqual(events[-1]['event_type'], 'stopped')
            self.assertIsNone(active)

    def test_history_append_dedup_and_unrelated_bytes_do_not_create_opportunities(self):
        request = own_request()
        stream = self.stream(entries()[:3] + [request])
        events = poll_events(stream)
        first = of_type(events, 'snapshot')[0]
        self.assertEqual(first['phase'], 'history')
        self.assertFalse(first['new_request_observed'])
        self.clock.advance(10)
        append(self.path, [request, {}])
        duplicate = poll_events(stream)
        self.assertEqual([row['event_type'] for row in duplicate], ['liveness'])
        for key in ('last_new_evidence_ns', 'last_state_change_ns', 'last_request_change_ns'):
            self.assertEqual(duplicate[-1]['timing'][key], first['timing'][key])
        self.assertEqual(duplicate[-1]['timing']['observation_age_ns'], 10)
        append(self.path, [own_request(41)])
        fresh = poll_events(stream)
        self.assertEqual([row['event_type'] for row in fresh],
                         ['invalidate', 'snapshot', 'liveness'])
        self.assertEqual(fresh[0]['reason'], 'request_replaced')
        self.assertEqual(fresh[1]['binding']['request_id'], 41)
        self.assertTrue(fresh[1]['new_request_observed'])
        self.assertEqual(fresh[1]['timing']['last_state_change_ns'], first['timing']['last_state_change_ns'])
        self.assertEqual(fresh[1]['timing']['last_request_change_ns'], self.clock.now)
        self.assert_stream(events + duplicate + fresh)

    def test_snapshots_reuse_existing_actions_selectn_and_combat_projections(self):
        examples = ((frames(), 'actions_available'), (selectn_rows(), 'select_n'),
                    (baseline() + [combat_request(ATTACK)], 'declare_attackers'),
                    (baseline() + [combat_request(BLOCK)], 'declare_blockers'))
        for rows, kind in examples:
            with self.subTest(kind=kind):
                events = list(self.stream(rows, samples=1))
                snapshot = of_type(events, 'snapshot')[0]
                expected = next(watch(self.path, interval=0, samples=1, decision_state=True))['decision_state']
                self.assertEqual(snapshot['decision_state'], expected)
                self.assertEqual(snapshot['decision_state']['legal_action_space']['immediate_frontier']['kind'], kind)
                self.assert_stream(events, complete=True)

    def test_full_diff_without_request_and_one_source_read_per_poll(self):
        original = RawFollower.poll
        stream = self.stream(entries()[:3], samples=3)
        with patch.object(RawFollower, 'poll', autospec=True, side_effect=original) as read:
            first = poll_events(stream)
            self.assertEqual(read.call_count, 1)
            append(self.path, [entries()[3]])
            second = poll_events(stream)
            self.assertEqual(read.call_count, 2)
            third = poll_events(stream)
            self.assertEqual(read.call_count, 3)
            terminal = list(stream)
            self.assertEqual(read.call_count, 3)
        self.assertEqual(second[0]['reason'], 'state_advanced')
        self.assertEqual(of_type(second, 'snapshot')[0]['binding']['game_state_id'], 2)
        self.assertEqual([row['event_type'] for row in third], ['liveness'])
        for event in of_type(first + second, 'snapshot'):
            self.assertIsNone(event['binding']['request_id'])
            self.assertFalse(event['new_request_observed'])
            self.assertEqual(event['source_status'], 'state_observed_without_request')
        self.assert_stream(first + second + third + terminal, complete=True)

    def test_consumption_replacement_state_advance_and_match_completion_revoke(self):
        completed = copy.deepcopy(entries()[1])
        completed['matchGameRoomStateChangedEvent']['gameRoomInfo']['stateType'] = (
            'MatchGameRoomStateType_MatchCompleted')
        endings = ((reply(40, 1), 'request_consumed', None),
                   (own_request(41), 'request_replaced', 41),
                   (entries()[3], 'state_advanced', None),
                   (completed, 'request_ended', None))
        for ending, reason, request_id in endings:
            with self.subTest(reason=reason):
                stream = self.stream(entries()[:3] + [own_request()])
                first = poll_events(stream)
                append(self.path, [ending])
                changed = poll_events(stream)
                self.assertEqual(changed[0]['event_type'], 'invalidate')
                self.assertEqual(changed[0]['reason'], reason)
                self.assertEqual(changed[0]['revoked'], first[0]['snapshot_ref'])
                self.assertEqual(of_type(changed, 'snapshot')[0]['binding']['request_id'], request_id)
                append(self.path, [own_request()])
                retransmission = poll_events(stream)
                self.assertFalse(of_type(retransmission, 'snapshot'))
                self.assert_stream(first + changed + retransmission)
                stream.close()

    def test_same_poll_request_then_consume_never_publishes_transient_request(self):
        stream = self.stream(entries()[:3])
        first = poll_events(stream)
        append(self.path, [own_request(), reply(40, 1)])
        ended = poll_events(stream)
        self.assertEqual([row['event_type'] for row in ended], ['liveness'])
        append(self.path, [own_request()])
        retransmission = poll_events(stream)
        self.assertEqual([row['event_type'] for row in retransmission], ['liveness'])
        self.assertIsNone(ended[-1]['current_snapshot_ref']['binding']['request_id'])
        append(self.path, [own_request(41)])
        fresh = poll_events(stream)
        self.assertTrue(of_type(fresh, 'snapshot')[0]['new_request_observed'])
        self.assert_stream(first + ended + retransmission + fresh)

    def test_same_gre_record_request_replacement_exports_only_final_identity(self):
        stream = self.stream(entries()[:3])
        first = poll_events(stream)
        combined = own_request()
        combined['greToClientEvent']['greToClientMessages'].extend(
            own_request(41)['greToClientEvent']['greToClientMessages'])
        append(self.path, [combined])
        changed = poll_events(stream)
        snapshots = of_type(changed, 'snapshot')
        self.assertEqual([row['binding']['request_id'] for row in snapshots], [41])
        self.assertTrue(snapshots[0]['new_request_observed'])
        append(self.path, [own_request()])
        late = poll_events(stream)
        self.assertFalse(of_type(late, 'snapshot'))
        self.assert_stream(first + changed + late)

    def test_same_poll_loss_recovery_invalidates_even_when_final_state_is_equal(self):
        for transient in ([], [own_request()]):
            with self.subTest(transient_request=bool(transient)):
                stream = self.stream(entries()[:3])
                first = poll_events(stream)
                append(self.path, transient)
                # A raw malformed object is framed as None; a JSON null line
                # is irrelevant log text and would not exercise continuity.
                with self.path.open('ab') as output:
                    output.write(b'{"greToClientEvent":}\n')
                append(self.path, [entries()[2]] + transient)
                recovered = poll_events(stream)
                self.assertEqual(recovered[0]['event_type'], 'invalidate')
                self.assertEqual(recovered[0]['reason'], 'source_invalid')
                snapshot = of_type(recovered, 'snapshot')[0]
                self.assertIsNone(snapshot['binding']['request_id'])
                self.assertFalse(snapshot['new_request_observed'])
                before, after = copy.deepcopy(first[0]['decision_state']), copy.deepcopy(snapshot['decision_state'])
                for value in (before, after):
                    for key in ('byte_offset', 'phase', 'stopped'):
                        value['source'].pop(key, None)
                if not transient:
                    self.assertEqual(before, after)
                self.assert_stream(first + recovered)
                stream.close()

    def test_gap_full_recovery_and_retransmission_cannot_resurrect_request(self):
        stream = self.stream(entries()[:3] + [own_request()])
        first = poll_events(stream)
        gap = copy.deepcopy(entries()[3])
        state(gap)['prevGameStateId'] = 999
        append(self.path, [gap])
        invalid = poll_events(stream)
        self.assertEqual([row['event_type'] for row in invalid], ['invalidate', 'liveness'])
        self.assertEqual(invalid[0]['reason'], 'source_invalid')
        self.assertIsNone(invalid[-1]['current_snapshot_ref'])
        append(self.path, [entries()[2], own_request()])
        recovery = poll_events(stream)
        snapshot = of_type(recovery, 'snapshot')[0]
        self.assertIsNone(snapshot['binding']['request_id'])
        self.assertFalse(snapshot['new_request_observed'])
        append(self.path, [own_request(41)])
        fresh = poll_events(stream)
        self.assertEqual(of_type(fresh, 'snapshot')[0]['binding']['request_id'], 41)
        self.assertTrue(of_type(fresh, 'snapshot')[0]['new_request_observed'])
        self.assert_stream(first + invalid + recovery + fresh)

    def test_partial_tail_and_completion_quarantine_old_request(self):
        for tail, completion in ((b'{', b'}\n'),
                                 ((json.dumps(reply(40, 1)) + '\n').encode()[:19],
                                  (json.dumps(reply(40, 1)) + '\n').encode()[19:])):
            with self.subTest(unrelated_completion=completion == b'}\n'):
                stream = self.stream(entries()[:3] + [own_request()])
                first = poll_events(stream)
                with self.path.open('ab') as output:
                    output.write(tail)
                partial = poll_events(stream)
                self.assertEqual(partial[0]['reason'], 'source_partial')
                self.assertEqual(partial[-1]['source_status'], 'partial')
                self.assertIsNone(partial[-1]['current_snapshot_ref'])
                with self.path.open('ab') as output:
                    output.write(completion)
                completed = poll_events(stream)
                self.assertIsNone(of_type(completed, 'snapshot')[0]['binding']['request_id'])
                append(self.path, [own_request()])
                old = poll_events(stream)
                self.assertFalse(of_type(old, 'snapshot'))
                append(self.path, [own_request(41)])
                fresh = poll_events(stream)
                self.assertTrue(of_type(fresh, 'snapshot')[0]['new_request_observed'])
                self.assert_stream(first + partial + completed + old + fresh)
                stream.close()

    def test_request_conflict_and_new_generation_history(self):
        stream = self.stream(entries()[:3] + [own_request()])
        first = poll_events(stream)
        conflicting = own_request()
        action_message(conflicting)['actionsAvailableReq'] = {'actions': []}
        append(self.path, [conflicting])
        invalid = poll_events(stream)
        self.assertEqual(invalid[0]['reason'], 'request_conflict')
        self.assertIsNone(invalid[-1]['current_snapshot_ref'])
        # Short rewrite creates a new generation, which replays as history.
        save(self.path, entries()[:3])
        reset = poll_events(stream)
        self.assertEqual(reset[0]['event_type'], 'snapshot')
        self.assertEqual(reset[0]['phase'], 'history')
        self.assertGreater(reset[0]['binding']['source_generation'], first[0]['binding']['source_generation'])
        self.assertFalse(reset[0]['new_request_observed'])
        self.assert_stream(first + invalid + reset)

    def test_empty_start_or_reset_waits_for_history_baseline_before_live_append(self):
        for reset_after_valid in (False, True):
            with self.subTest(reset_after_valid=reset_after_valid):
                stream = self.stream(entries()[:3] + [own_request()] if reset_after_valid else [])
                events = poll_events(stream)
                if reset_after_valid:
                    self.path.write_bytes(b'')
                    lost = poll_events(stream)
                    self.assertEqual(lost[0]['reason'], 'source_reset')
                    events += lost
                append(self.path, entries()[:3] + [own_request()])
                rebuilt = poll_events(stream)
                snapshot = of_type(rebuilt, 'snapshot')[0]
                self.assertEqual(snapshot['phase'], 'history')
                self.assertFalse(snapshot['new_request_observed'])
                append(self.path, [own_request(41)])
                fresh = poll_events(stream)
                self.assertEqual(of_type(fresh, 'snapshot')[0]['phase'], 'append')
                self.assertTrue(of_type(fresh, 'snapshot')[0]['new_request_observed'])
                self.assert_stream(events + rebuilt + fresh)
                stream.close()

    def test_truncate_and_same_size_replacement_revoke_and_replay_history(self):
        for mode in ('truncate', 'same_size'):
            with self.subTest(mode=mode):
                original = entries()[:3] + [own_request()]
                stream = self.stream(original)
                first = poll_events(stream)
                if mode == 'truncate':
                    save(self.path, entries()[:3])
                else:
                    content = self.path.read_bytes()
                    changed = content.replace(b'fixture-local', b'fixture-locax')
                    self.assertEqual(len(content), len(changed))
                    self.path.write_bytes(changed)
                reset = poll_events(stream)
                self.assertEqual(reset[0]['reason'], 'source_reset')
                snapshot = of_type(reset, 'snapshot')[0]
                self.assertEqual(snapshot['phase'], 'history')
                self.assertFalse(snapshot['new_request_observed'])
                self.assertGreater(snapshot['binding']['source_generation'], first[0]['binding']['source_generation'])
                self.assert_stream(first + reset)
                stream.close()

    def test_empty_polls_age_expiry_and_duplicate_do_not_refresh_reference(self):
        stream = self.stream(entries()[:3] + [own_request()], max_observation_age_ns=10)
        first = poll_events(stream)
        self.clock.advance(10)
        boundary = poll_events(stream)
        self.assertFalse(boundary[-1]['timing']['observation_stale'])
        self.assertEqual(boundary[-1]['current_snapshot_ref'], first[0]['snapshot_ref'])
        self.clock.advance(1)
        expired = poll_events(stream)
        self.assertEqual(expired[0]['reason'], 'observation_stale')
        self.assertIsNone(expired[-1]['current_snapshot_ref'])
        stamp = first[0]['timing']['last_new_evidence_ns']
        append(self.path, [own_request(), entries()[2], {}])
        self.clock.advance(5)
        duplicate = poll_events(stream)
        self.assertEqual([row['event_type'] for row in duplicate], ['liveness'])
        self.assertIsNone(duplicate[-1]['current_snapshot_ref'])
        self.assertEqual(duplicate[-1]['timing']['last_new_evidence_ns'], stamp)
        self.assertEqual(duplicate[-1]['timing']['observation_age_ns'], 16)
        self.assert_stream(first + boundary + expired + duplicate)

    def test_no_default_expiry_and_wall_clock_cannot_determine_local_age(self):
        stream = self.stream(entries()[:3] + [own_request()])
        with patch('time.time', side_effect=AssertionError('wall clock consulted')):
            first = poll_events(stream)
            self.clock.advance(MAX_AGE_NS * 2)
            old = poll_events(stream)
        self.assertEqual(old[-1]['current_snapshot_ref'], first[0]['snapshot_ref'])
        self.assertEqual(old[-1]['timing']['observation_age_ns'], MAX_AGE_NS * 2)
        self.assertIsNone(old[-1]['timing']['observation_age_limit_ns'])
        self.assertFalse(old[-1]['timing']['observation_stale'])
        self.assert_stream(first + old)

    def test_finite_interrupt_and_source_error_stop_revoke_cached_reference(self):
        stream = self.stream(entries()[:3] + [own_request()], samples=1)
        finite = list(stream)
        self.assertEqual(finite[-2]['reason'], 'session_stopped')
        self.assertEqual(finite[-1]['reason'], 'sample_limit')
        self.assert_stream(finite, complete=True)
        for reason in ('user_interrupt', 'source_error'):
            with self.subTest(reason=reason):
                stream = self.stream(entries()[:3] + [own_request()])
                first = poll_events(stream)
                if reason == 'user_interrupt':
                    with patch('mtgaplayer.cli.time.sleep', side_effect=KeyboardInterrupt):
                        terminal = list(stream)
                else:
                    with patch.object(RawFollower, 'poll', side_effect=OSError('PRIVATE_PATH_SENTINEL')):
                        terminal = list(stream)
                self.assertEqual([row['event_type'] for row in terminal], ['invalidate', 'stopped'])
                self.assertEqual(terminal[-1]['reason'], reason)
                self.assertNotIn('PRIVATE_PATH_SENTINEL', json.dumps(terminal))
                self.assert_stream(first + terminal, complete=True)

    def test_safe_identity_binding_private_values_and_session_references(self):
        events = list(self.stream(frames(), samples=2))
        self.assert_stream(events, complete=True)
        for secret in ('PRIVATE_COST_SENTINEL', 'PRIVATE_TARGET_SENTINEL',
                       'PRIVATE_UNKNOWN', 'UNEXPECTED_PRIVATE_VALUE',
                       'HIDDEN_SENTINEL', str(self.path), '_continuity_verified',
                       '_frontier_rows'):
            self.assertNotIn(secret, json.dumps(events))
        save(self.path, entries()[:3])
        first = list(watch_decision_events(self.path, interval=0, samples=1, clock_ns=self.clock))
        second = list(watch_decision_events(self.path, interval=0, samples=1, clock_ns=self.clock))
        self.assertNotEqual(first[0]['session_id'], second[0]['session_id'])
        self.assertNotEqual(first[0]['snapshot_ref'], second[0]['snapshot_ref'])

    def test_publisher_clock_bounds_copy_isolation_and_terminal_contract(self):
        save(self.path, entries()[:3] + [own_request()])
        document = next(watch(self.path, interval=0, samples=2, decision_state=True))
        metadata = {'poll_started_ns': self.clock.now, 'poll_completed_ns': self.clock.now,
                    'poll_read_ns': 0, 'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0,
                    'reset': True, 'state_changed': True, 'request_changed': True}
        publisher = DecisionPublisher(clock_ns=self.clock, session_id='direct-session')
        untouched = copy.deepcopy(document)
        first = publisher.observe(document, metadata)
        self.assertEqual(document, untouched)
        reference = copy.deepcopy(first[0]['snapshot_ref'])
        first[0]['decision_state']['binding']['request_id'] = 999
        first[0]['snapshot_ref']['binding']['request_id'] = 999
        metadata.update(reset=False, state_changed=False, request_changed=False)
        second = publisher.observe(document, metadata)
        self.assertEqual(second[-1]['current_snapshot_ref'], reference)
        terminal = publisher.stop('other_supported_reason')
        self.assertEqual(terminal[0]['revoked'], reference)
        self.assertEqual(publisher.stop(), [])
        with self.assertRaisesRegex(ValueError, 'publication_session_stopped'):
            publisher.observe(document, metadata)
        for limit in (0, -1, True, 1.5, MAX_AGE_NS + 1):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, 'invalid_observation_age_limit'):
                DecisionPublisher(max_observation_age_ns=limit)
        for session in ('', 'private path', 'x' * 65, 2):
            with self.subTest(session=session), self.assertRaisesRegex(ValueError, 'invalid_publication_session_id'):
                DecisionPublisher(session_id=session)
        publisher = DecisionPublisher(clock_ns=self.clock)
        publisher.observe(document, metadata)
        self.clock.advance(-1)
        with self.assertRaisesRegex(ValueError, 'publication_clock_not_monotonic'):
            publisher.observe(document, metadata)
        for value in (True, -1, 1.0):
            with self.subTest(clock=value), self.assertRaisesRegex(ValueError, 'publication_clock_not_monotonic'):
                DecisionPublisher(clock_ns=lambda: value).stop()
        with self.assertRaisesRegex(ValueError, 'unsupported_publication_stop_reason'):
            DecisionPublisher().stop('PRIVATE_UNKNOWN_REASON')

    def test_publisher_rejects_elevated_state_and_invalid_poll_timing(self):
        save(self.path, entries()[:3] + [own_request()])
        document = next(watch(self.path, interval=0, samples=2, decision_state=True))
        metadata = {'poll_started_ns': self.clock.now, 'poll_completed_ns': self.clock.now,
                    'poll_read_ns': 0, 'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0}
        for key in metadata:
            bad = {**metadata, key: True}
            with self.subTest(timing=key), self.assertRaisesRegex(ValueError, 'invalid_poll_timing'):
                DecisionPublisher(clock_ns=self.clock).observe(document, bad)
        with self.assertRaisesRegex(ValueError, 'invalid_poll_timing'):
            DecisionPublisher(clock_ns=self.clock).observe(document, {**metadata,
                'poll_completed_ns': self.clock.now + 1})
        for flag in SAFETY_FLAGS:
            changed = copy.deepcopy(document)
            changed['decision_state']['execution'][flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'invalid_decision_state_observation'):
                DecisionPublisher(clock_ns=self.clock).observe(changed, metadata)

    def test_expiry_uses_publication_timestamp_including_publisher_work(self):
        save(self.path, entries()[:3])
        document = next(watch(self.path, interval=0, samples=2, decision_state=True))
        ticks = iter((100, 111))
        publisher = DecisionPublisher(max_observation_age_ns=10, clock_ns=lambda: next(ticks),
                                      session_id='publication-clock')
        events = publisher.observe(document, {'poll_started_ns': 100, 'poll_completed_ns': 100,
            'poll_read_ns': 0, 'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0,
            'reset': True, 'state_changed': True})
        self.assertEqual([row['event_type'] for row in events], ['snapshot', 'invalidate', 'liveness'])
        self.assertEqual(events[1]['reason'], 'observation_stale')
        self.assertEqual(events[-1]['timing']['observation_age_ns'], 11)
        self.assertIsNone(events[-1]['current_snapshot_ref'])
        self.assert_stream(events)

    def test_actual_cli_jsonl_optional_age_and_source_error_are_sanitized(self):
        save(self.path, entries()[:3] + [own_request()])
        executable = Path(sys.prefix) / ('Scripts/mtgaplayer.exe' if os.name == 'nt' else 'bin/mtgaplayer')
        self.assertTrue(executable.is_file(), 'installed CLI entrypoint is required')
        def run(path, extra):
            return subprocess.run([str(executable), 'watch', str(path), '--interval', '.001',
                                   '--samples', '1', *extra], cwd=ROOT, capture_output=True,
                                  text=True, encoding='utf-8', timeout=8, check=False)
        plain = run(self.path, [])
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertEqual(json.loads(plain.stdout), next(watch(self.path, interval=0, samples=1)))
        for extra, limit in ((['--decision-events'], None),
                             (['--decision-events', '--max-observation-age-ms', '1'], 1_000_000)):
            result = run(self.path, extra)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(events[-1]['reason'], 'sample_limit')
            self.assertEqual(events[0]['timing']['observation_age_limit_ns'], limit)
            self.assert_stream(events, complete=True)
        error = run(self.path.with_name('missing-private-file'), ['--decision-events'])
        self.assertEqual(error.returncode, 1)
        events = [json.loads(line) for line in error.stdout.splitlines()]
        self.assertEqual([row['event_type'] for row in events], ['stopped'])
        self.assertEqual(events[0]['reason'], 'source_error')
        self.assertNotIn('missing-private-file', error.stdout)
        self.assert_stream(events, complete=True)

    def test_main_output_interrupt_keeps_event_format_and_revokes_delivered_snapshot(self):
        save(self.path, entries()[:3] + [own_request()])
        original_print = print
        calls = 0
        def interrupted_print(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return original_print(*args, **kwargs)
        output = io.StringIO()
        with patch('builtins.print', side_effect=interrupted_print), redirect_stdout(output):
            code = main(['watch', str(self.path), '--decision-events', '--samples', '2', '--interval', '.001'])
        self.assertEqual(code, 0)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(all('event_type' in event for event in events),
                        'an interrupted event subscription must never emit legacy watch JSON')
        self.assertEqual(events[0]['event_type'], 'snapshot')
        self.assertEqual(events[-2]['event_type'], 'invalidate')
        self.assertEqual(events[-2]['revoked'], events[0]['snapshot_ref'])
        self.assertEqual(events[-1]['event_type'], 'stopped')
        self.assertEqual(events[-1]['reason'], 'user_interrupt')
        self.assertTrue(all(left['sequence'] < right['sequence']
                            for left, right in zip(events, events[1:])))

    def test_old_projection_modes_remain_unchanged_and_new_cli_guards_are_explicit(self):
        save(self.path, frames())
        names = ('decision_input', 'action_gaps', 'action_frontier', 'choice_graph', 'combat_frontier')
        for values in itertools.product((False, True), repeat=len(names)):
            options = dict(zip(names, values))
            if ((options['action_gaps'] or options['action_frontier'] or options['combat_frontier'])
                    and not options['decision_input']) or (options['choice_graph'] and not options['action_frontier']):
                continue
            for decision_state in (False, True):
                flags = ['--' + name.replace('_', '-') for name, enabled in options.items() if enabled]
                if decision_state:
                    flags.append('--decision-state')
                output, errors = io.StringIO(), io.StringIO()
                with self.subTest(flags=flags), redirect_stdout(output), redirect_stderr(errors):
                    code = main(['watch', str(self.path), '--samples', '1', '--interval', '.001', *flags])
                self.assertEqual(code, 0)
                self.assertEqual(errors.getvalue(), '')
                self.assertEqual(json.loads(output.getvalue()), next(watch(self.path, interval=0,
                    samples=1, decision_state=decision_state, **options)))
        invalid = [['--decision-events', '--' + name.replace('_', '-')] for name in names + ('decision_state',)]
        invalid += [['--max-observation-age-ms', '1']]
        invalid += [['--decision-events', '--max-observation-age-ms', value]
                    for value in ('0', '-1', 'nan', 'inf', '86400001', '.00000001')]
        for flags in invalid:
            with self.subTest(invalid=flags), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(['watch', str(self.path), *flags])
            self.assertEqual(raised.exception.code, 2)
        for kwargs in ({'samples': True}, {'samples': 0}, {'samples': 1001},
                       {'interval': float('nan')}, {'interval': -1}, {'interval': 61},
                       {'max_history_bytes': True}, {'max_history_bytes': 0}):
            with self.subTest(bounds=kwargs), self.assertRaisesRegex(ValueError, 'invalid_decision_event_watch_bounds'):
                list(watch_decision_events(self.path, **kwargs))

    def test_schema_structure_local_urn_links_and_all_event_shapes(self):
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        state_schema = json.loads(STATE_SCHEMA.read_text(encoding='utf-8'))
        self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(schema['$id'], 'urn:mtgaplayer:decision-event:v1')
        self.assertEqual(schema['properties']['schema_version']['const'], EVENT_VERSION)
        self.assertIs(schema['additionalProperties'], False)
        self.assertEqual(schema['properties']['event_type']['enum'],
                         ['snapshot', 'invalidate', 'liveness', 'stopped'])
        self.assertEqual(schema['$defs']['reference']['required'], ['session_id', 'sequence', 'binding'])
        self.assertEqual(set(schema['properties']['timing']['required']),
                         set(schema['properties']['timing']['properties']))
        for node in walk(schema):
            if '$ref' not in node:
                continue
            urn, _, fragment = node['$ref'].partition('#')
            self.assertIn(urn, ('', state_schema['$id']))
            target = schema if not urn else state_schema
            if fragment:
                self.assertTrue(fragment.startswith('/'))
                for part in fragment[1:].split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
            self.assertIsInstance(target, dict)
        stream = self.stream(entries()[:3] + [own_request()], samples=2)
        events = poll_events(stream)
        append(self.path, [reply(40, 1)])
        events += list(stream)
        self.assertEqual({row['event_type'] for row in events},
                         {'snapshot', 'invalidate', 'liveness', 'stopped'})
        self.assert_stream(events, complete=True)


if __name__ == '__main__':
    unittest.main()
