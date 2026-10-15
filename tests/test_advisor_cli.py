"""Actual CLI/pipe advice delivery and owner-thread expiry counterexamples."""
import copy
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_advisor import EVIDENCE_POLICY, SIMPLE_TYPE_POLICY, assess_current_decision
from mtgaplayer.decision_consumer import DecisionConsumer, consume_events
from test_action_frontier import frames, save
from test_consumer_backpressure import QueueStream
from test_decision_advisor import PASS, PLAY
from test_decision_consumer import encoded
from test_decision_publisher import ManualClock, append, poll_events
from test_decision_state import action_message
from test_response_evidence import reply


class AdvisorCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'invented-actions.jsonl'

    def chain(self, history=False):
        data = frames()
        action_message(data[-1])['actionsAvailableReq'] = {'actions': [PASS, PLAY]}
        save(self.path, data if history else data[:-1])
        stream = watch_decision_events(self.path, interval=0, samples=4,
                                      clock_ns=ManualClock(), session_id='advisor-cli')
        self.addCleanup(stream.close)
        events = poll_events(stream)
        if not history:
            append(self.path, [data[-1]])
        events += poll_events(stream)
        events += poll_events(stream)  # unchanged liveness cannot create another opportunity
        request = action_message(data[-1])
        append(self.path, [reply(request['msgId'], request['gameStateId'])])
        events += list(stream)
        return events

    def run_cli(self, events, *options):
        result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'consume-events', *options],
            input=encoded(events), capture_output=True, text=True, encoding='utf-8', timeout=10)
        return result, [json.loads(line) for line in result.stdout.splitlines()]

    def test_opt_in_cli_default_compatibility_and_policy_rejection(self):
        events = self.chain()
        old, plain = self.run_cli(events)
        default, advised = self.run_cli(events, '--advice')
        self.assertEqual((old.returncode, default.returncode), (0, 0))
        self.assertTrue(all('decision_advice' not in row for row in plain))
        self.assertEqual([{k:v for k,v in row.items() if k != 'decision_advice'} for row in advised], plain)
        self.assertTrue(all(row['decision_advice']['policy_version'] == EVIDENCE_POLICY for row in advised))
        self.assertTrue(all(row['decision_advice']['preferred_candidate'] is None for row in advised))
        bad = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'consume-events',
            '--advice-policy', SIMPLE_TYPE_POLICY], input='', capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn('--advice-policy requires --advice', bad.stderr)

    def test_append_history_liveness_consumption_stop_via_real_cli(self):
        for history in (False, True):
            events = self.chain(history)
            result, rows = self.run_cli(events, '--advice', '--advice-policy', SIMPLE_TYPE_POLICY)
            self.assertEqual(result.returncode, 0, result.stderr)
            preferences = [r['decision_advice'] for r in rows if r['decision_advice']['preferred_candidate'] is not None]
            if history:
                self.assertEqual(preferences, [])
            else:
                self.assertGreaterEqual(len(preferences), 2)  # append snapshot and idle liveness
                self.assertTrue(all(a == preferences[0] for a in preferences))
                snap = next(e for e in events if e['event_type'] == 'snapshot' and e['new_request_observed'])
                self.assertEqual(preferences[0]['source_snapshot_ref'], snap['snapshot_ref'])
                self.assertEqual(preferences[0]['preferred_candidate']['list_position'], 1)
            for row in rows:
                advice = row['decision_advice']
                self.assertFalse(advice['new_live_opportunity'])
                self.assertTrue(all(v is False for v in advice['execution'].values()))
                if row['consumer_status'] != 'OBSERVING':
                    self.assertIsNone(advice['preferred_candidate'])
                    self.assertEqual(advice['candidate_assessments'], [])
            self.assertTrue(any(row['consumer_status'] == 'INVALIDATED' for row in rows))
            self.assertEqual(rows[-1]['consumer_status'], 'CLOSED')

    def test_actual_watch_cli_to_consumer_cli_os_pipe_history_stays_research(self):
        data = frames()
        action_message(data[-1])['actionsAvailableReq'] = {'actions': [PASS, PLAY]}
        save(self.path, data)  # A pending historical request, not an already consumed one.
        producer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'watch', str(self.path),
            '--decision-events', '--samples', '1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        consumer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events', '--advice',
            '--advice-policy', SIMPLE_TYPE_POLICY], stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        try:
            output, error = consumer.communicate(timeout=10)
            self.assertEqual(consumer.returncode, 0, error)
            self.assertEqual(producer.wait(timeout=5), 0, producer.stderr.read())
            rows = [json.loads(line) for line in output.splitlines()]
            self.assertEqual(rows[-1]['consumer_status'], 'CLOSED')
            self.assertTrue(all(r['decision_advice']['preferred_candidate'] is None for r in rows))
        finally:
            for process in (consumer, producer):
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    def interactive(self):
        process = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events', '--advice',
            '--advice-policy', SIMPLE_TYPE_POLICY, '--max-observation-age-ms', '1000'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        lines = queue.Queue()
        def read():
            for line in process.stdout:
                lines.put(json.loads(line))
            lines.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            reader.join(2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.addCleanup(cleanup)
        return process, lines

    def test_real_cli_open_pipe_age_expiry_and_abnormal_eof_clear_advice(self):
        events = self.chain()
        end = next(i for i,e in enumerate(events) if e['event_type'] == 'invalidate'
                   and e['reason'] == 'request_consumed')
        prefix = events[:end]
        for reason in ('unexpected_eof', 'observation_age_expired'):
            with self.subTest(reason=reason):
                process, lines = self.interactive()
                process.stdin.write(encoded(prefix))
                process.stdin.flush()
                while True:
                    row = lines.get(timeout=5)
                    self.assertIsNotNone(row)
                    if row['decision_advice']['preferred_candidate'] is not None:
                        break
                if reason == 'unexpected_eof':
                    process.stdin.close()
                terminal = row
                while True:
                    row = lines.get(timeout=5)
                    if row is None:
                        break
                    terminal = row
                self.assertEqual(process.wait(timeout=5), 1)
                self.assertEqual(terminal['unresolved'], [reason])
                self.assertIn(terminal['consumer_status'], ('CLOSED', 'STALE'))
                self.assertIsNone(terminal['decision_advice']['preferred_candidate'])
                self.assertEqual(terminal['decision_advice']['candidate_assessments'], [])

    def snapshot(self):
        event = copy.deepcopy(next(e for e in self.chain() if e['event_type'] == 'snapshot' and e['new_request_observed']))
        event['sequence'] = event['snapshot_ref']['sequence'] = 1
        return event

    def test_blocked_output_cannot_stop_expiry_and_assessment_uses_owner_thread(self):
        clock, entered, gate, cleared, assessed = ManualClock(100), threading.Event(), threading.Event(), threading.Event(), threading.Event()
        consumer = DecisionConsumer(10_000, 500, clock)
        stream, output, owners, result = QueueStream(), [], [], []
        clear = consumer._clear
        def clear_and_signal(status, reason):
            clear(status, reason)
            if status == 'STALE':
                cleared.set()
        consumer._clear = clear_and_signal
        def assess(c, **kwargs):
            self.assertIs(c, consumer)
            owners.append(threading.get_ident())
            advice = assess_current_decision(c, **kwargs)
            if advice['preferred_candidate'] is not None:
                assessed.set()
            return advice
        def emit(value):
            entered.set()
            gate.wait(3)
            output.append(value)
        stream.send(self.snapshot())
        def run():
            result.append(consume_events(stream, emit, consumer, tick_seconds=.002,
                                         advice_policy=SIMPLE_TYPE_POLICY))
        core = threading.Thread(target=run)
        def cleanup():
            gate.set()
            stream.lines.put('')
            core.join(3)
        self.addCleanup(cleanup)
        with patch('mtgaplayer.decision_advisor.assess_current_decision', side_effect=assess):
            core.start()
            self.assertTrue(entered.wait(2))
            self.assertTrue(assessed.wait(2))
            clock.advance(501)
            self.assertTrue(cleared.wait(2))
            self.assertFalse(gate.is_set())
            self.assertIsNone(consumer._state)
            self.assertIsNone(consumer._ref)
            gate.set()
            core.join(3)
        self.assertEqual(result, [1])
        self.assertEqual(set(owners), {core.ident})
        self.assertEqual(output[-1]['consumer_status'], 'STALE')
        self.assertIsNone(output[-1]['decision_advice']['preferred_candidate'])

    def test_lease_crossed_during_assessment_cannot_enqueue_old_preference(self):
        clock = ManualClock(100)
        consumer = DecisionConsumer(10_000, 500, clock)
        output = []
        def cross(c, **kwargs):
            advice = assess_current_decision(c, **kwargs)
            clock.advance(501)
            return advice
        with patch('mtgaplayer.decision_advisor.assess_current_decision', side_effect=cross):
            code = consume_events(io.StringIO(encoded([self.snapshot()])), output.append, consumer,
                                  advice_policy=SIMPLE_TYPE_POLICY)
        self.assertEqual(code, 1)
        self.assertEqual(output[-1]['consumer_status'], 'STALE')
        self.assertTrue(all(row['decision_advice']['preferred_candidate'] is None for row in output))

    def test_replay_advice_is_historical_and_existing_state_unchanged(self):
        data = frames()
        action_message(data[-1])['actionsAvailableReq'] = {'actions': [PASS, PLAY]}
        save(self.path, data)
        base = replay(self.path, format='player-log', decision_state=True)
        result = replay(self.path, format='player-log', advice_policy=SIMPLE_TYPE_POLICY)
        self.assertEqual({k:v for k,v in result.items() if k != 'decision_advice'}, base)
        self.assertTrue(result['decision_advice']['historical_research_only'])
        self.assertEqual(len(result['decision_advice']['candidate_assessments']), 2)
        self.assertEqual(result['decision_advice']['abstention_reason'], 'historical_research_only')
        self.assertIsNone(result['decision_advice']['preferred_candidate'])
        cli = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(self.path),
            '--format', 'player-log', '--advice'], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertTrue(json.loads(cli.stdout)['decision_advice']['historical_research_only'])
        from mtgaplayer.rules_index import build_rules_index
        from test_rules_index import card
        source, index = Path(self.temp.name) / 'cards.json', Path(self.temp.name) / 'rules.sqlite'
        source.write_text(json.dumps([card(base['decision_state']['visible_objects'][0]['card_id'])]), encoding='utf-8')
        build_rules_index(source, index, source_version='invented-cli-context')
        combined = replay(self.path, format='player-log', rules_index_path=index, advice_policy=EVIDENCE_POLICY)
        self.assertEqual(combined['static_rule_context']['binding'], combined['decision_advice']['request_identity'])
        self.assertEqual(combined['decision_state'], base['decision_state'])
        with self.assertRaisesRegex(ValueError, 'advice_requires_player_log_format'):
            replay(self.path, advice_policy=EVIDENCE_POLICY)
