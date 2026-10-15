"""Current static references over real CLI pipes and synthetic lifecycle probes."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mtgaplayer.cli import main, watch_decision_events
from mtgaplayer.decision_advisor import assess_current_decision, SIMPLE_TYPE_POLICY
from mtgaplayer.decision_consumer import DecisionConsumer, consume_events
from mtgaplayer.rule_context import assess_current_rule_context, build_static_rule_context
from mtgaplayer.rules_index import build_rules_index, load_rules_index
from test_action_frontier import frames, save
import test_advisor_cli as advice_helpers
from test_consumer_backpressure import QueueStream
from test_decision_advisor import PASS, PLAY
from test_decision_consumer import encoded
from test_decision_publisher import ManualClock, append, poll_events
from test_decision_state import action_message
from test_rules_index import card


class CurrentRuleContextTests(unittest.TestCase):
    setUp = advice_helpers.AdvisorCliTests.setUp
    chain = advice_helpers.AdvisorCliTests.chain
    snapshot = advice_helpers.AdvisorCliTests.snapshot
    run_cli = advice_helpers.AdvisorCliTests.run_cli

    def prepare(self, events, cards=None):
        self.rule_number = getattr(self, 'rule_number', 0) + 1
        self.index = Path(self.temp.name) / f'rules-{self.rule_number}.sqlite'
        source = Path(self.temp.name) / 'rules.json'
        ids = {o['card_id'] for e in events if e['event_type'] == 'snapshot'
               for o in e['decision_state']['visible_objects'] if o['card_id'] is not None}
        source.write_text(json.dumps(cards if cards is not None else
            [card(i) for i in ids] + [card(777777, name='PRIVATE_REFERENCE_SENTINEL')]), encoding='utf-8')
        build_rules_index(source, self.index, source_version='invented.current.v1')
        return load_rules_index(self.index)

    def assert_empty(self, context):
        self.assertEqual(context['status'], 'unavailable')
        self.assertEqual(context['objects'], [])
        self.assertIsNone(context['rules_source'])
        self.assertIsNone(context['counts'])

    def test_opt_in_default_compatibility_and_rules_failure_preserves_advice(self):
        events = self.chain()
        self.prepare(events)
        plain_code, plain = self.run_cli(events)
        rules_code, rules = self.run_cli(events, '--rules-index', str(self.index))
        advice_code, advice = self.run_cli(events, '--advice')
        both_code, both = self.run_cli(events, '--advice', '--rules-index', str(self.index))
        self.assertEqual([r.returncode for r in (plain_code, rules_code, advice_code, both_code)], [0]*4)
        self.assertEqual([{k:v for k,v in r.items() if k != 'current_rule_context'} for r in rules], plain)
        self.assertEqual([{k:v for k,v in r.items() if k != 'current_rule_context'} for r in both], advice)
        self.assertTrue(all('current_rule_context' not in r for r in plain))
        self.assertNotIn('PRIVATE_REFERENCE_SENTINEL', json.dumps(rules))
        self.index.unlink()
        failed, rows = self.run_cli(events, '--advice', '--rules-index', str(self.index))
        self.assertEqual(failed.returncode, 0, failed.stderr)
        self.assertEqual([{k:v for k,v in r.items() if k != 'current_rule_context'} for r in rows], advice)
        for row in rows:
            self.assert_empty(row['current_rule_context'])
            if row['consumer_status'] == 'OBSERVING':
                context = row['current_rule_context']
                self.assertEqual(context['unresolved'], ['rules_index_unavailable_or_invalid'] if
                    context['binding'] is not None else ['current_snapshot_binding_invalid'])

    def test_actual_cli_history_append_state_advance_consumption_requestless_stop(self):
        for history in (False, True):
            with self.subTest(history=history):
                events = self.chain(history)
                self.prepare(events)
                result, rows = self.run_cli(events, '--rules-index', str(self.index))
                self.assertEqual(result.returncode, 0, result.stderr)
                snapshots = {e['sequence']: e for e in events if e['event_type'] == 'snapshot'}
                observed = []
                for row in rows:
                    context = row['current_rule_context']
                    self.assertFalse(context['new_live_opportunity'])
                    self.assertTrue(all(v is False for v in context['execution'].values()))
                    if row['consumer_status'] != 'OBSERVING' or context['status'] == 'unavailable':
                        self.assert_empty(context)
                        self.assertIsNone(context['source_snapshot_ref'])
                        self.assertIsNone(context['binding'])
                        if row['consumer_status'] == 'OBSERVING':
                            # The final poll can publish a stopped source snapshot
                            # before the separate stopped event reaches Consumer.
                            self.assertEqual(context['unresolved'], ['current_snapshot_binding_invalid'])
                    else:
                        ref = context['source_snapshot_ref']
                        event = snapshots[ref['sequence']]
                        self.assertEqual(ref, event['snapshot_ref'])
                        self.assertEqual(context['binding'], event['decision_state']['binding'])
                        self.assertEqual(context['source_phase'], event['phase'])
                        self.assertEqual(sum(context['counts'].values()), len(context['objects']))
                        observed.append(context)
                self.assertTrue(any(c['source_phase'] == 'history' for c in observed))
                if not history:
                    self.assertTrue(any(c['binding']['request_id'] is None for c in observed))
                self.assertTrue(any(r['consumer_status'] == 'INVALIDATED' for r in rows))
                self.assertEqual(rows[-1]['consumer_status'], 'CLOSED')
                self.index.unlink()

    def test_actual_request_replacement_rebinds_after_empty_invalidation(self):
        data = frames()
        action_message(data[-1])['actionsAvailableReq'] = {'actions': [PASS, PLAY]}
        save(self.path, data)
        stream = watch_decision_events(self.path, interval=0, samples=3, clock_ns=ManualClock(), session_id='rules-replace')
        self.addCleanup(stream.close)
        events = poll_events(stream)
        replacement = copy.deepcopy(action_message(data[-1]))
        replacement.update(msgId=38, gameStateId=23)
        append(self.path, [{'greToClientEvent': {'greToClientMessages': [replacement]}}])
        events += poll_events(stream)
        events += list(stream)
        self.assertTrue(any(e.get('reason') == 'request_replaced' for e in events))
        self.prepare(events)
        result, rows = self.run_cli(events, '--rules-index', str(self.index))
        self.assertEqual(result.returncode, 0, result.stderr)
        refs = [r['current_rule_context']['source_snapshot_ref'] for r in rows if r['consumer_status'] == 'OBSERVING']
        self.assertGreaterEqual(len({r['binding']['request_id'] for r in refs}), 2)
        self.assertTrue(any(r['binding']['request_id'] == 38 for r in refs))
        for row in rows:
            if row['consumer_status'] == 'INVALIDATED':
                self.assert_empty(row['current_rule_context'])

    def interactive(self):
        process = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events',
            '--rules-index', str(self.index), '--advice', '--max-observation-age-ms', '1000'],
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

    def test_real_cli_prepared_source_deletion_open_pipe_age_and_eof(self):
        events = self.chain()
        end = next(i for i,e in enumerate(events) if e.get('reason') == 'request_consumed')
        for reason in ('unexpected_eof', 'observation_age_expired'):
            with self.subTest(reason=reason):
                self.prepare(events)
                process, lines = self.interactive()
                self.assertEqual(lines.get(timeout=5)['consumer_status'], 'WAITING')
                self.index.unlink()  # startup finished; queries must not reopen it
                process.stdin.write(encoded(events[:end]))
                process.stdin.flush()
                while True:
                    row = lines.get(timeout=5)
                    self.assertIsNotNone(row)
                    context = row['current_rule_context']
                    if context['binding'] is not None and context['binding']['request_id'] is not None:
                        break
                self.assertEqual(context['status'], 'reference_context_observed')
                self.assertEqual(context['rules_source']['source_version'], 'invented.current.v1')
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
                self.assert_empty(terminal['current_rule_context'])
                self.assertIsNone(terminal['current_rule_context']['source_snapshot_ref'])

    def test_preparation_finishes_before_consumer_creation(self):
        events = self.chain()
        self.prepare(events)
        order = []
        original_init = DecisionConsumer.__init__
        def prepare(path):
            value = load_rules_index(path)
            order.append('prepared')
            return value
        def init(instance, *args, **kwargs):
            self.assertEqual(order, ['prepared'])
            order.append('consumer')
            original_init(instance, *args, **kwargs)
        with patch('mtgaplayer.rules_index.load_rules_index', side_effect=prepare), \
             patch.object(DecisionConsumer, '__init__', init), \
             patch('sys.stdin', io.StringIO(encoded(events))), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['consume-events', '--rules-index', str(self.index)]), 0)
        self.assertEqual(order, ['prepared', 'consumer'])

    def test_context_owner_thread_and_blocked_output_cannot_stop_expiry(self):
        snapshot = self.snapshot()
        prepared = self.prepare([snapshot])
        clock, gate, entered, cleared = ManualClock(100), threading.Event(), threading.Event(), threading.Event()
        consumer = DecisionConsumer(10_000, 500, clock)
        stream, output, owners, result = QueueStream(), [], [], []
        original_clear = consumer._clear
        def clear(status, reason):
            original_clear(status, reason)
            if status == 'STALE':
                cleared.set()
        consumer._clear = clear
        def build(*args, **kwargs):
            owners.append(threading.get_ident())
            return build_static_rule_context(*args, **kwargs)
        def emit(value):
            entered.set()
            gate.wait(3)
            output.append(value)
        stream.send(snapshot)
        core = threading.Thread(target=lambda: result.append(consume_events(stream, emit, consumer,
            tick_seconds=.002, prepared_rules=prepared)))
        def cleanup():
            gate.set()
            stream.lines.put('')
            core.join(3)
        self.addCleanup(cleanup)
        with patch('mtgaplayer.rule_context.build_static_rule_context', side_effect=build), \
             patch('mtgaplayer.rule_context.lookup_rules', side_effect=AssertionError('file lookup')), \
             patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('SQLite')):
            core.start()
            self.assertTrue(entered.wait(2))
            clock.advance(501)
            self.assertTrue(cleared.wait(2))
            self.assertFalse(gate.is_set())
            self.assertIsNone(consumer._state)
            self.assertIsNone(consumer._ref)
            gate.set()
            core.join(3)
        self.assertEqual(result, [1])
        self.assertEqual(set(owners), {core.ident})
        self.assert_empty(output[-1]['current_rule_context'])
        self.assertEqual(output[-1]['consumer_status'], 'STALE')

    def test_context_computation_expiry_also_revokes_earlier_advice(self):
        snapshot = self.snapshot()
        prepared = self.prepare([snapshot])
        clock, output, earlier = ManualClock(100), [], []
        consumer = DecisionConsumer(10_000, 500, clock)
        def advice(*args, **kwargs):
            result = assess_current_decision(*args, **kwargs)
            earlier.append(result['preferred_candidate'])
            return result
        def cross(*args, **kwargs):
            result = build_static_rule_context(*args, **kwargs)
            clock.advance(501)
            return result
        with patch('mtgaplayer.rule_context.build_static_rule_context', side_effect=cross), \
             patch('mtgaplayer.decision_advisor.assess_current_decision', side_effect=advice):
            code = consume_events(io.StringIO(encoded([snapshot])), output.append, consumer,
                advice_policy=SIMPLE_TYPE_POLICY, prepared_rules=prepared)
        self.assertIsNotNone(earlier[0])
        self.assertEqual(code, 1)
        self.assertTrue(all(r['decision_advice']['preferred_candidate'] is None for r in output))
        self.assertTrue(all(r['current_rule_context']['objects'] == [] for r in output))
        self.assertEqual(output[-1]['consumer_status'], 'STALE')

    def test_current_adapter_rejects_detached_mismatched_and_unprepared_sources(self):
        snapshot = self.snapshot()
        prepared = self.prepare([snapshot])
        consumer = DecisionConsumer()
        self.assertTrue(consumer.accept_event(snapshot))
        view = consumer.current_view()
        self.assert_empty(assess_current_rule_context(view, prepared))
        with patch('mtgaplayer.rule_context.lookup_rules', side_effect=AssertionError('must prepare first')):
            self.assert_empty(assess_current_rule_context(consumer, self.index))
            self.assert_empty(build_static_rule_context(snapshot['decision_state'], self.index,
                                                       max_reference_bytes=0))
        context = assess_current_rule_context(consumer, prepared)
        self.assertEqual(context['source_snapshot_ref'], snapshot['snapshot_ref'])
        self.assertEqual(context['objects'], build_static_rule_context(snapshot['decision_state'], self.index)['objects'])
        for change in ({'session_id': 'other'}, {'transport_alive': False}):
            bad = {**view, **change}
            with patch.object(consumer, 'current_view', return_value=bad):
                self.assert_empty(assess_current_rule_context(consumer, prepared))

    def test_reference_budget_counts_repeated_instances_before_copy(self):
        snapshot = self.snapshot()
        template = snapshot['decision_state']['visible_objects'][0]
        snapshot['decision_state']['visible_objects'] = [dict(template, instance_id=100000+i, card_id=10) for i in range(40)]
        prepared = self.prepare([snapshot], [card(10, oracle_text='x'*16384,
            type_line='x'*16384, power='x'*16384, toughness='x'*16384)])
        consumer = DecisionConsumer()
        self.assertTrue(consumer.accept_event(snapshot))
        def no_copy(value):
            raise AssertionError('oversized references must fail before copy')
        with patch('mtgaplayer.rules_index.copy', SimpleNamespace(deepcopy=no_copy)):
            result = assess_current_rule_context(consumer, prepared)
        self.assert_empty(result)
        self.assertEqual(result['unresolved'], ['rules_context_limits_exceeded'])
        self.assertEqual(result['source_snapshot_ref'], snapshot['snapshot_ref'])
