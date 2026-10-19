"""MP82 lifecycle counterexamples over public, aliased request projections.

The retained SelectN shapes are real finite projections. Every authentication,
room, Full/Diff envelope, append schedule and mutation here is synthetic. These
tests exercise the existing production runtime, not original GRE authenticity.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mtgaplayer import current_selectn
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_runtime import LocalShadowRuntime


FIXTURE = ROOT / 'tests/fixtures/current_selectn_triggered_real_v1.json'


def wrap(message):
    return {'greToClientEvent': {'greToClientMessages': [message]}}


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode('utf8')


def bootstrap():
    """Synthetic public endpoint, independent of the request's unknown IDs."""
    rows = [json.loads(line) for line in
        (ROOT / 'tests/fixtures/player_log_minimal.jsonl').read_text(encoding='utf8').splitlines()[:3]]
    state = rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
    state['gameObjects'] = [{'instanceId': 701, 'grpId': 901, 'type': 'GameObjectType_Card',
        'zoneId': 28, 'ownerSeatId': 1, 'controllerSeatId': 1,
        'visibility': 'Visibility_Public', 'isTapped': False}]
    next(zone for zone in state['zones'] if zone['zoneId'] == 28)['objectInstanceIds'] = [701]
    return rows


def diff(state_id=2, predecessor=1):
    return wrap({'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
        'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': state_id,
            'prevGameStateId': predecessor}})


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now


class CurrentSelectNLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.sample = self.fixture['samples'][0]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic-selectn-append.jsonl'
        self.clock = Clock()
        self.runtime = self.stream = None

    def message(self, ident=990, state_id=1, sample=None):
        value = copy.deepcopy((sample or self.sample)['aliased_request'])
        value.update(msgId=ident, gameStateId=state_id)
        return value

    def request(self, ident=990, state_id=1, sample=None):
        return wrap(self.message(ident, state_id, sample))

    def response(self, ident=990, state_id=1):
        # Invented consumer lifecycle envelope, never positive choice evidence.
        return {'payload': {'type': 'ClientMessageType_SelectNResp', 'respId': ident,
            'gameStateId': state_id, 'selectNResp': {'ids': [1001]}}}

    def start(self, initial=None, **kwargs):
        if self.stream is not None:
            self.stream.close()
        if self.runtime is not None:
            self.runtime.close()
        self.clock = Clock()
        self.path.write_bytes(encoded(bootstrap() if initial is None else initial))
        self.runtime = LocalShadowRuntime(self.path, interval=0, clock_ns=self.clock,
            observation_mode='controlled_stream_replay', **kwargs)
        self.stream = self.runtime.frames()
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.stream.close)
        return next(self.stream)

    def append(self, rows):
        with self.path.open('ab') as output:
            output.write(encoded(rows))
        return next(self.stream)

    def assert_readonly(self, value):
        self.assertIs(value['read_only'], True)
        for name in EXECUTION:
            self.assertIs(value[name], False, name)

    def assert_revoked(self, frame):
        self.assertNotEqual(frame['time_scope'], 'current_at_completed_poll')
        for name in ('request_binding', 'source_snapshot_ref', 'current_options',
                     'shadow_decision', 'shadow_preference', 'engine_offered_coverage',
                     'unresolved_constraints'):
            self.assertIsNone(frame[name], name)
        self.assertEqual(frame['local_evidence'], {})
        self.assertEqual(frame['local_evidence_status'], {})
        self.assert_readonly(frame)

    def assert_observed(self, frame, count=2, ident=990):
        self.assertEqual(frame['time_scope'], 'current_at_completed_poll')
        self.assertEqual(frame['request_binding']['request_id'], ident)
        report = frame['local_evidence']['current_selectn_evidence']
        self.assertEqual(report['status'], 'observed')
        self.assertEqual(report['engine_offered_member_count'], count)
        self.assertEqual(report['unresolved_member_count'], count)
        self.assertEqual(report['request_binding'], frame['request_binding'])
        self.assertEqual(report['source_snapshot_ref'], frame['source_snapshot_ref'])
        self.assertEqual(report['reviewed_local_proposals'], [])
        self.assertIsNone(report['complete_proposal_count'])
        self.assertIsNone(frame['shadow_preference'])
        self.assert_readonly(report)
        self.assert_readonly(frame)
        return report

    def current_report(self, message):
        return self.runtime.consumer.current_decision_options(
            current_selectn_context=(self.runtime._reducer, message))['current_selectn_evidence']

    def assert_report_revoked(self, report):
        self.assertEqual(report['status'], 'insufficient_evidence')
        self.assertIsNone(report['request_binding'])
        self.assertIsNone(report['source_snapshot_ref'])
        self.assertEqual(report['engine_offered_members'], [])
        self.assertEqual(report['unresolved_member_references'], [])
        self.assertEqual(report['reviewed_local_proposals'], [])
        self.assertIsNone(report['complete_proposal_count'])
        self.assert_readonly(report)

    def test_five_real_projections_enter_existing_runtime_without_identity_or_proposals(self):
        self.assertEqual(self.fixture['origin'], 'retained_scrubbed_real')
        self.assertFalse(self.fixture['raw_equivalent'])
        self.assertFalse(self.fixture['authentication_envelope_retained'])
        self.assertFalse(self.fixture['future_response_used_for_request'])
        counts = []
        for sample in self.fixture['samples']:
            with self.subTest(case=sample['case']):
                self.assert_revoked(self.start())
                frame = self.append([self.request(sample=sample)])
                report = self.assert_observed(frame, sample['member_count'])
                counts.append(report['engine_offered_member_count'])
                self.assertEqual(report['reviewed_visible_members'], [])
                self.assertEqual(report['observed_quantity_bounds']['minimum'], 1)
                self.assertEqual(report['observed_quantity_bounds']['maximum'], sample['member_count'])
                for member in report['engine_offered_members']:
                    self.assertIsNone(member['object_ref'])
                    self.assertIsNone(member['card_id'])
                    self.assertIsNone(member['zone'])
                defaults = self.runtime.consumer.current_decision_options()
                enriched = self.runtime.consumer.current_decision_options(
                    current_selectn_context=(self.runtime._reducer, self.runtime._message))
                enriched.pop('current_selectn_evidence')
                self.assertEqual(enriched, defaults)
        self.assertEqual(counts, [2, 3, 3, 6, 10])

    def test_initial_history_and_exact_retransmission_never_create_current_opportunity(self):
        self.assert_revoked(self.start(bootstrap() + [self.request()]))
        self.assert_revoked(self.append([self.request()]))
        self.assert_observed(self.append([self.request(991)]), ident=991)
        first = self.runtime.current_frame()
        self.assertEqual(self.append([self.request(991)])['source_snapshot_ref'], first['source_snapshot_ref'])

    def test_cancel_undo_nonui_mixed_and_broadcast_interrupt_stickily(self):
        for mode in ('cancel', 'undo', 'nonui', 'mixed', 'broadcast'):
            with self.subTest(mode=mode):
                self.start()
                self.assert_observed(self.append([self.request()]))
                if mode in ('cancel', 'undo', 'nonui'):
                    typ = {'cancel': 'ClientMessageType_CancelActionReq',
                        'undo': 'ClientMessageType_UndoReq',
                        'nonui': 'ClientMessageType_UnreviewedRequest'}[mode]
                    interrupted = {'payload': {'type': typ}}
                elif mode == 'mixed':
                    interrupted = self.request()
                    interrupted['payload'] = {'type': 'ClientMessageType_UIMessage'}
                else:
                    message = self.message()
                    message['systemSeatIds'] = [1, 2]
                    interrupted = wrap(message)
                self.assert_revoked(self.append([interrupted]))
                self.assert_report_revoked(self.current_report(self.message()))
                # The private invalidation witness never becomes public State.
                self.assertNotIn('_selectn_evidence_interrupted',
                    json.dumps(self.runtime._reducer.document(include_decision_state=True)))
                self.assert_revoked(self.append([self.request()]))
                self.assert_report_revoked(self.current_report(self.message()))
                self.assert_revoked(next(self.stream))
                self.assert_observed(self.append([self.request(991)]), ident=991)

    def test_standalone_ui_telemetry_preserves_same_current_evidence(self):
        self.start()
        before = self.assert_observed(self.append([self.request()]))
        after = self.assert_observed(self.append([{'payload': {'type': 'ClientMessageType_UIMessage'}}]))
        self.assertEqual(after, before)

    def test_full_and_diff_gap_revoke_old_request_and_require_new_baseline(self):
        for mode in ('full', 'gap'):
            with self.subTest(mode=mode):
                self.start()
                self.assert_observed(self.append([self.request()]))
                full = copy.deepcopy(bootstrap()[2])
                full['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameStateId'] = 2
                self.assert_revoked(self.append([full if mode == 'full' else diff(2, 0)]))
                self.assert_revoked(self.append([self.request()]))
                if mode == 'gap':
                    self.assert_revoked(self.append([full]))
                self.assert_observed(self.append([self.request(991, 2)]), ident=991)

    def test_exact_full_reobservation_cannot_reauthenticate_previous_request(self):
        self.start()
        self.assert_observed(self.append([self.request()]))
        self.assert_revoked(self.append([bootstrap()[2]]))
        self.assert_report_revoked(self.current_report(self.message()))
        self.assert_revoked(self.append([self.request()]))
        self.assert_report_revoked(self.current_report(self.message()))
        self.assert_observed(self.append([self.request(991)]), ident=991)

    def test_same_valued_float_or_bool_predecessor_cannot_prove_typed_continuity(self):
        for predecessor in (1, 1.0, True):
            with self.subTest(predecessor=repr(predecessor)):
                self.start()
                self.assert_observed(self.append([self.request()]))
                frame = self.append([diff(2, predecessor), self.request(991, 2)])
                if type(predecessor) is int:
                    self.assert_observed(frame, ident=991)
                else:
                    self.assert_revoked(frame)
                    self.assert_report_revoked(self.current_report(self.message(991, 2)))

    def test_partial_completion_and_old_retransmission_cannot_restore_previous_evidence(self):
        self.start()
        self.assert_observed(self.append([self.request()]))
        with self.path.open('ab') as output:
            output.write(b'{"unrelated":')
        self.assert_revoked(next(self.stream))
        self.assert_report_revoked(self.current_report(self.message()))
        with self.path.open('ab') as output:
            output.write(b'1}\n')
        self.assert_revoked(next(self.stream))
        self.assert_revoked(self.append([self.request()]))
        self.assert_observed(self.append([self.request(991)]), ident=991)

    def test_split_new_request_is_current_only_after_complete_poll(self):
        self.start()
        data = encoded([self.request()])
        cut = len(data) // 2
        with self.path.open('ab') as output:
            output.write(data[:cut])
        self.assert_revoked(next(self.stream))
        with self.path.open('ab') as output:
            output.write(data[cut:])
        self.assert_observed(next(self.stream))

    def test_consumption_and_replacement_revoke_old_explicit_context(self):
        self.start()
        self.assert_observed(self.append([self.request()]))
        old_message = self.message()
        self.assert_observed(self.append([self.request(991)]), ident=991)
        self.assert_report_revoked(self.current_report(old_message))
        self.assert_revoked(self.append([self.response(991)]))
        self.assert_report_revoked(self.current_report(self.message(991)))
        self.assert_revoked(self.append([self.request(991)]))
        self.assert_revoked(self.append([self.request()]))
        self.assert_observed(self.append([self.request(992)]), ident=992)

    def test_changed_explicit_message_and_wrong_scope_cannot_borrow_current_evidence(self):
        for mode in ('members', 'request_id', 'state_float', 'seat', 'raw_match', 'raw_game', 'raw_seat'):
            with self.subTest(mode=mode):
                self.start()
                self.assert_observed(self.append([self.request()]))
                message = self.message()
                if mode == 'members':
                    message['selectNReq']['ids'].reverse()
                elif mode == 'request_id':
                    message['msgId'] += 1
                elif mode == 'state_float':
                    message['gameStateId'] = 1.0
                elif mode == 'seat':
                    message['systemSeatIds'] = [2]
                elif mode == 'raw_match':
                    self.runtime._reducer.match = 'synthetic-other-match'
                elif mode == 'raw_game':
                    self.runtime._reducer.game += 1
                else:
                    self.runtime._reducer.seat = 2
                self.assert_report_revoked(self.current_report(message))
                if mode.startswith('raw_'):
                    self.assert_revoked(self.runtime.current_frame())

    def test_same_poll_final_selectn_only_and_consumed_selectn_never_becomes_frame(self):
        self.start()
        frame = self.append([self.request(), self.response(), self.request(991), self.request(992)])
        self.assert_observed(frame, ident=992)
        self.assertEqual(frame['poll_accepted_requests'], 3)
        self.assertEqual(frame['poll_consumed_requests'], 1)
        self.assert_revoked(self.append([self.response(992), self.request(992)]))
        self.assert_revoked(next(self.stream))

    def test_same_record_final_request_owns_members_and_consumed_earlier_context_stays_revoked(self):
        self.start()
        first = self.request()
        last = self.message(991, sample=self.fixture['samples'][-1])
        first['greToClientEvent']['greToClientMessages'].append(last)
        self.assert_observed(self.append([first]), 10, ident=991)
        self.assert_report_revoked(self.current_report(self.message()))
        self.assert_revoked(self.append([self.response(991), self.request(991, sample=self.fixture['samples'][-1])]))

    def test_file_reset_and_direct_reducer_reset_revoke_every_side_result(self):
        for mode in ('file', 'reducer'):
            with self.subTest(mode=mode):
                self.start()
                self.assert_observed(self.append([self.request()]))
                if mode == 'file':
                    replacement = self.path.with_suffix('.replacement')
                    replacement.write_bytes(encoded(bootstrap() + [self.request(991)]))
                    replacement.replace(self.path)
                    self.assert_revoked(next(self.stream))
                    self.assert_revoked(self.append([self.request(991)]))
                    self.assert_observed(self.append([self.request(992)]), ident=992)
                else:
                    self.runtime._reducer.reset(2)
                    self.assert_revoked(self.runtime.current_frame())
                    self.assert_report_revoked(self.current_report(self.message()))

    def test_lease_expiry_old_retransmission_and_stop_never_revive_cached_members(self):
        self.start(max_observation_age_ns=10_000_000, max_event_silence_ns=10_000_000)
        self.assert_observed(self.append([self.request()]))
        old_consumer = self.runtime.consumer
        self.clock.now += 10_000_001
        self.assert_revoked(self.runtime.current_frame())
        self.assert_report_revoked(self.current_report(self.message()))
        self.assert_revoked(self.append([self.request()]))
        self.assertIs(self.runtime.consumer, old_consumer)
        self.assert_observed(self.append([self.request(991)]), ident=991)
        self.assertIsNot(self.runtime.consumer, old_consumer)
        self.assertEqual(old_consumer.current_view()['consumer_status'], 'STALE')
        self.runtime.close()
        self.assert_revoked(self.runtime.current_frame())
        self.assert_report_revoked(self.current_report(self.message(991)))

    def test_mutation_during_selectn_projection_discards_whole_frame(self):
        for mode in ('raw_digest', 'message', 'ref', 'visible', 'consume', 'replace', 'lease', 'stop'):
            with self.subTest(mode=mode):
                self.start(max_observation_age_ns=10_000_000)
                self.assert_observed(self.append([self.request()]))
                original = current_selectn.project_request
                called = []

                def changed(*args, **kwargs):
                    value = original(*args, **kwargs)
                    called.append(True)
                    if mode == 'raw_digest':
                        self.runtime._reducer.accepted_digest = b'changed-current-state-digest'
                    elif mode == 'message':
                        self.runtime._message['selectNReq']['ids'].reverse()
                    elif mode == 'ref':
                        self.runtime.consumer._ref['sequence'] += 1
                    elif mode == 'visible':
                        self.runtime._reducer.objects[701]['grpId'] += 1
                    elif mode == 'consume':
                        self.runtime._reducer.apply(self.response())
                    elif mode == 'replace':
                        self.runtime._reducer.apply(self.request(991))
                    elif mode == 'lease':
                        self.clock.now += 10_000_001
                    else:
                        self.runtime.close()
                    return value

                with patch.object(current_selectn, 'project_request', side_effect=changed):
                    frame = self.runtime.current_frame()
                self.assertEqual(called, [True])
                self.assert_revoked(frame)

    def test_explicit_api_also_rejects_state_digest_change_during_projection(self):
        self.start()
        self.assert_observed(self.append([self.request()]))
        original = current_selectn.project_request

        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            self.runtime._reducer.accepted_digest = b'changed-current-state-digest'
            return value

        with patch.object(current_selectn, 'project_request', side_effect=changed):
            self.assert_report_revoked(self.current_report(self.message()))

    def test_global_binding_and_source_mutations_after_local_evidence_also_clear_whole_frame(self):
        for mode in ('raw_request', 'policy_binding', 'ref', 'partial', 'visible', 'stop'):
            with self.subTest(mode=mode):
                self.start()
                self.assert_observed(self.append([self.request()]))
                original = self.runtime.consumer.shadow_decision

                def changed():
                    value = original()
                    if mode == 'raw_request':
                        self.runtime._reducer.request['id'] += 1
                    elif mode == 'policy_binding':
                        value['request_binding']['request_id'] += 1
                    elif mode == 'ref':
                        self.runtime.consumer._ref['sequence'] += 1
                    elif mode == 'partial':
                        self.runtime._source['partial_record'] = True
                    elif mode == 'visible':
                        self.runtime._reducer.objects[701]['grpId'] += 1
                    else:
                        self.runtime.close()
                    return value

                with patch.object(self.runtime.consumer, 'shadow_decision', side_effect=changed):
                    self.assert_revoked(self.runtime.current_frame())


if __name__ == '__main__':
    unittest.main(verbosity=2)
