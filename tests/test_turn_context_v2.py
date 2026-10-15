"""Observed turn context through explicit State/Event v2; v1 stays default."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_advisor import assess_current_decision, assess_decision_state
from mtgaplayer.decision_consumer import DecisionConsumer, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.decision_state import build_decision_state
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.rule_context import assess_current_rule_context
from mtgaplayer.rules_index import build_rules_index, load_rules_index
from test_action_frontier import save
from test_decision_consumer import encoded
from test_decision_publisher import ManualClock, append, poll_events
from test_raw_log import entries
from test_rules_index import card

ROOT = Path(__file__).resolve().parents[1]


def minimal_prefix(version):
    """Split existing real envelopes only; message bodies are unchanged."""
    reducer, result = RawReducer(), []
    reducer.reset(1)
    for entry in entries():
        messages = entry.get('greToClientEvent', {}).get('greToClientMessages')
        frames = [entry]
        if messages is not None:
            frames = []
            for message in messages:
                frame = copy.deepcopy(entry)
                frame['greToClientEvent']['greToClientMessages'] = [message]
                frames.append(frame)
        for frame in frames:
            result.append(frame)
            reducer.apply(frame)
            if reducer.version == version:
                return result
    raise AssertionError('missing real state')


def stage(reducer):
    document = reducer.document(include_decision_state=True)
    document['source'] = {'format': 'player-log-gre-v1', 'mode': 'offline',
        'generation': reducer.generation, 'partial_record': False,
        'input_sent': False, 'executor_connected': False}
    return document


class TurnContextV2Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'real-prefix.jsonl'

    def test_real_state4_5_6_cli_context_and_legacy_output_compatibility(self):
        expected = {4: ('Phase_Beginning', 'Step_Upkeep', 2),
                    5: ('Phase_Beginning', 'Step_Upkeep', 1), 6: ('Phase_Main1', None, 2)}
        for version, context in expected.items():
            with self.subTest(state=version):
                save(self.path, minimal_prefix(version))
                old = replay(self.path, format='player-log', decision_state=True, decision_input=True)
                cli = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(self.path),
                    '--format', 'player-log', '--decision-input', '--decision-state-version', '2'],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(cli.returncode, 0, cli.stderr)
                new = json.loads(cli.stdout)
                turn = new['decision_state']['game']['turn']
                self.assertEqual(tuple(turn[k] for k in ('phase', 'step', 'priorityPlayer')), context)
                if version == 4:
                    self.assertEqual(turn['decisionPlayer'], 1)
                    self.assertNotEqual(turn['priorityPlayer'], turn['decisionPlayer'])
                self.assertEqual(new['decision_state']['schema_version'], 'mtgaplayer.decision-state.v2')
                self.assertEqual({k:v for k,v in new.items() if k != 'decision_state'},
                                 {k:v for k,v in old.items() if k != 'decision_state'})
                self.assertEqual(set(new['current']['turn']), {'turnNumber', 'activePlayer', 'decisionPlayer'})
                self.assertNotIn('_turn_context', cli.stdout)
                self.assertIn(assess_decision_state(new['decision_state'])['abstention_reason'],
                              ('current_request_not_provided', 'unsupported_request_type'))

    def reducer(self):
        reducer = RawReducer()
        reducer.reset(1)
        for frame in minimal_prefix(4):
            reducer.apply(frame)
        return reducer

    def diff(self, reducer, context='absent'):
        state = {'type': 'GameStateType_Diff', 'gameStateId': reducer.version + 1,
                 'prevGameStateId': reducer.version}
        if context != 'absent':
            state['turnInfo'] = context
        reducer.apply({'greToClientEvent': {'greToClientMessages': [{
            'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [reducer.seat],
            'gameStateMessage': state}]}})
        return build_decision_state(stage(reducer), version=2)

    def test_whole_turninfo_inheritance_replacement_nulls_and_recovery(self):
        reducer = self.reducer()
        self.assertEqual(self.diff(reducer)['game']['turn']['step'], 'Step_Upkeep')
        self.assertIsNone(self.diff(reducer, {'phase': 'Phase_Main1', 'nextStep': 'Step_BeginCombat'})['game']['turn']['step'])
        turn = self.diff(reducer, {})['game']['turn']
        self.assertTrue(all(value is None for value in turn.values()))
        self.assertIsNone(self.diff(reducer, {'phase': None, 'step': None, 'priorityPlayer': None})['game']['turn']['priorityPlayer'])
        unknown = self.diff(reducer, {'phase': 'Phase_FutureObserved', 'step': 'Step_FutureObserved'})
        self.assertEqual(unknown['game']['turn']['phase'], 'Phase_FutureObserved')
        for context in ({'phase': 3}, {'step': 'PRIVATE_SENTINEL'}, {'priorityPlayer': True}, {'priorityPlayer': 3}):
            self.assertIsNone(self.diff(reducer, context))
            # The legacy projection never interpreted these extra fields.
            self.assertIsNotNone(build_decision_state(stage(reducer)))
            self.assertEqual(self.diff(reducer, {'phase': 'Phase_Main1'})['game']['turn']['phase'], 'Phase_Main1')

    def event_chain(self, version=2):
        first, second = minimal_prefix(4), minimal_prefix(5)
        save(self.path, first)
        stream = watch_decision_events(self.path, interval=0, samples=3, clock_ns=ManualClock(),
            session_id='turn-v2', decision_state_version=version)
        self.addCleanup(stream.close)
        events = poll_events(stream)
        append(self.path, second[len(first):])
        events += poll_events(stream) + list(stream)
        return events

    def test_v2_append_chain_and_version_pairs_pin_one_subscription(self):
        events = self.event_chain()
        self.assertTrue(all(e['schema_version'] == 'mtgaplayer.decision-event.v2' for e in events))
        self.assertTrue(any(e.get('reason') == 'state_advanced' for e in events))
        snapshots = [e for e in events if e['event_type'] == 'snapshot']
        self.assertEqual([e['decision_state']['game']['turn']['priorityPlayer'] for e in snapshots], [2, 1])
        consumer = DecisionConsumer(clock_ns=ManualClock())
        self.assertTrue(all(consumer.accept_event(e) for e in events))
        snapshot = snapshots[0]
        for mutate in ('event', 'state', 'extra', 'priority', 'phase', 'unknown'):
            event = copy.deepcopy(snapshot)
            if mutate == 'event':
                event['schema_version'] = 'mtgaplayer.decision-event.v1'
            elif mutate == 'state':
                event['decision_state']['schema_version'] = 'mtgaplayer.decision-state.v1'
            elif mutate == 'extra':
                event['decision_state']['game']['turn']['nextStep'] = 'Step_BeginCombat'
            elif mutate == 'priority':
                event['decision_state']['game']['turn']['priorityPlayer'] = 3
            elif mutate == 'phase':
                event['decision_state']['game']['turn']['phase'] = 42
            else:
                event['schema_version'] = 'mtgaplayer.decision-event.v99'
            self.assertFalse(DecisionConsumer().accept_event(event), mutate)
        c = DecisionConsumer(clock_ns=ManualClock())
        self.assertTrue(c.accept_event(events[0]))
        mixed = copy.deepcopy(events[1])
        mixed['schema_version'] = 'mtgaplayer.decision-event.v1'
        self.assertFalse(c.accept_event(mixed))
        self.assertIsNone(c.current_view()['decision_state'])

    def test_actual_v2_cli_os_pipe_advice_rules_and_normal_stop(self):
        save(self.path, minimal_prefix(5))
        source, index = self.path.with_suffix('.json'), self.path.with_suffix('.sqlite')
        visible = replay(self.path, format='player-log', decision_state_version=2)['decision_state']['visible_objects']
        source.write_text(json.dumps([card(i) for i in {o['card_id'] for o in visible if o['card_id'] is not None}]), encoding='utf-8')
        build_rules_index(source, index, source_version='invented.turn.v2')
        producer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'watch', str(self.path),
            '--decision-events', '--decision-state-version', '2', '--samples', '2', '--interval', '.02'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        consumer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events', '--advice',
            '--rules-index', str(index)], stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        try:
            output, error = consumer.communicate(timeout=10)
            self.assertEqual(consumer.returncode, 0, error)
            self.assertEqual(producer.wait(timeout=5), 0, producer.stderr.read())
            diagnostics = [json.loads(line) for line in output.splitlines()]
            references = [d['current_rule_context'] for d in diagnostics if d['current_rule_context']['objects']]
            self.assertTrue(references)
            self.assertTrue(all(not d['decision_advice']['new_live_opportunity'] for d in diagnostics))
            self.assertEqual(diagnostics[-1]['consumer_status'], 'CLOSED')
            self.assertEqual(diagnostics[-1]['current_rule_context']['objects'], [])
        finally:
            for process in (consumer, producer):
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    def test_v2_local_lease_eof_and_sidecars_clear(self):
        event = self.event_chain()[0]
        clock = ManualClock(100)
        consumer = DecisionConsumer(1000, 500, clock)
        self.assertTrue(consumer.accept_event(event))
        clock.advance(501)
        self.assertEqual(assess_current_decision(consumer)['candidate_assessments'], [])
        self.assertIsNone(assess_current_rule_context(consumer)['source_snapshot_ref'])
        self.assertEqual(consumer.current_view()['consumer_status'], 'STALE')
        output = []
        self.assertEqual(consume_events(io.StringIO(encoded([event])), output.append), 1)
        self.assertEqual(output[-1]['unresolved'], ['unexpected_eof'])

    def test_formal_versions_and_unsupported_api_versions(self):
        state = json.loads((ROOT / 'schemas/decision-state.v2.schema.json').read_text())
        event = json.loads((ROOT / 'schemas/decision-event.v2.schema.json').read_text())
        self.assertEqual(state['properties']['schema_version']['const'], 'mtgaplayer.decision-state.v2')
        self.assertEqual(state['$id'], 'urn:mtgaplayer:decision-state:v2')
        self.assertEqual(event['$id'], 'urn:mtgaplayer:decision-event:v2')
        self.assertIn('priorityPlayer', state['properties']['game']['properties']['turn']['required'])
        self.assertEqual(event['properties']['decision_state']['allOf'][0]['$ref'], 'urn:mtgaplayer:decision-state:v2')
        for version in (True, 5, '2'):
            with self.assertRaises(ValueError):
                DecisionPublisher(state_version=version)
            with self.assertRaises(ValueError):
                build_decision_state({}, version=version)
