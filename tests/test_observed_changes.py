"""Visible endpoint facts over committed real data and labeled synthetic cases."""
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

from mtgaplayer.cli import watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, consume_events
from mtgaplayer.observed_changes import ObservedChanges, _compare
from mtgaplayer.raw_log import RawReducer
from test_action_frontier import save, source_rows
from test_consumer_backpressure import QueueStream
from test_decision_consumer import encoded
from test_decision_publisher import ManualClock, append, poll_events


def real_prefixes(versions):
    reducer, frames, found = RawReducer(), [], {}
    reducer.reset(1)
    for entry in source_rows():
        messages = entry.get('greToClientEvent', {}).get('greToClientMessages')
        parts = [entry]
        if messages is not None:
            parts = []
            for message in messages:
                frame = copy.deepcopy(entry)
                frame['greToClientEvent']['greToClientMessages'] = [message]
                parts.append(frame)
        for frame in parts:
            frames.append(frame)
            reducer.apply(frame)
            if reducer.version in versions and reducer.version not in found:
                found[reducer.version] = list(frames)
                if len(found) == len(versions):
                    return found
    raise AssertionError('missing real state')


class ObservedChangesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'scrubbed-endpoints.jsonl'

    def chain(self, versions=(90, 91), version=2):
        prefixes = real_prefixes(versions)
        current = prefixes[versions[0]]
        save(self.path, current)
        stream = watch_decision_events(self.path, interval=0, samples=len(versions)+1,
            clock_ns=ManualClock(), session_id='visible-endpoints', decision_state_version=version)
        self.addCleanup(stream.close)
        events = poll_events(stream)
        for state in versions[1:]:
            following = prefixes[state]
            append(self.path, following[len(current):])
            events += poll_events(stream)
            current = following
        return events + list(stream)

    def cli(self, events, *flags):
        result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'consume-events', *flags],
            input=encoded(events), text=True, capture_output=True, timeout=10)
        return result, [json.loads(line) for line in result.stdout.splitlines()]

    def test_real_life_endpoints_default_compatibility_counts_and_versions(self):
        for version in (1, 2):
            events = self.chain((90, 91, 143, 210), version)
            plain, old = self.cli(events, '--advice')
            changed, new = self.cli(events, '--advice', '--observed-changes')
            self.assertEqual((plain.returncode, changed.returncode), (0, 0), changed.stderr)
            self.assertEqual([{k:v for k,v in row.items() if k != 'observed_changes'} for row in new], old)
            pairs = {r['observed_changes']['after_snapshot_ref']['sequence']: r['observed_changes'] for r in new
                     if r['observed_changes']['status'] == 'endpoints_compared'}
            life = [c for pair in pairs.values() for c in pair['changes'] if c['kind'] == 'life_changed']
            self.assertEqual([(c['seat'], c['before'], c['after']) for c in life], [(1,20,19), (1,19,16), (1,16,15)])
            for pair in pairs.values():
                self.assertEqual(sum(pair['counts'].values()), len(pair['changes']))
                self.assertEqual(pair['source_snapshot_ref'], pair['after_snapshot_ref'])
                self.assertLess(pair['before_snapshot_ref']['sequence'], pair['after_snapshot_ref']['sequence'])
                self.assertIsNone(pair['effect_claims'])
                self.assertFalse(pair['new_live_opportunity'])
                self.assertTrue(all(v is False for v in pair['execution'].values()))
            self.assertEqual(new[-1]['observed_changes']['changes'], [])
            self.assertIsNone(new[-1]['observed_changes']['source_snapshot_ref'])

    def test_real_zone_endpoint_and_visibility_only_entry_exit(self):
        events = self.chain((43, 44))
        result, rows = self.cli(events, '--observed-changes')
        self.assertEqual(result.returncode, 0, result.stderr)
        pair = next(r['observed_changes'] for r in rows if r['observed_changes']['status'] == 'endpoints_compared')
        move = next(c for c in pair['changes'] if c['kind'] == 'zone_changed' and c['instance_id'] == 288)
        self.assertEqual((move['before'], move['after']), ('ZoneType_Stack', 'ZoneType_Battlefield'))
        self.assertEqual({c['kind'] for c in pair['changes']}, {'zone_changed'})
        before = next(e['decision_state'] for e in events if e['event_type'] == 'snapshot')
        after = copy.deepcopy(before)
        old = after['visible_objects'].pop()
        after['visible_objects'].append(dict(old, instance_id=999999, card_id=777777))
        changes, _ = _compare(before, after)
        self.assertIn({'kind': 'left_visible_projection', 'instance_id': old['instance_id']}, changes)
        self.assertIn({'kind': 'entered_visible_projection', 'instance_id': 999999}, changes)
        self.assertNotIn('777777', json.dumps(changes))  # no newly inferred hidden destination or identity

    def snapshots(self):
        events = self.chain()
        old, new = [copy.deepcopy(e) for e in events if e['event_type'] == 'snapshot']
        old['sequence'] = old['snapshot_ref']['sequence'] = 1
        new['sequence'] = new['snapshot_ref']['sequence'] = 3
        invalidate = copy.deepcopy(next(e for e in events if e.get('reason') == 'state_advanced'))
        invalidate['sequence'], invalidate['revoked'] = 2, copy.deepcopy(old['snapshot_ref'])
        return old, invalidate, new

    def test_other_invalidations_and_intervening_tick_cannot_bridge_baseline(self):
        old, invalidate, new = self.snapshots()
        for reason in ('source_reset', 'source_partial', 'source_invalid', 'identity_changed',
                       'request_replaced', 'request_consumed', 'projection_changed', 'state_advanced'):
            with self.subTest(reason=reason):
                c = DecisionConsumer(clock_ns=ManualClock())
                observer = ObservedChanges(c)
                self.assertTrue(c.accept_event(old))
                observer.observe(('snapshot', None))
                revoke = {**invalidate, 'reason': reason}
                self.assertTrue(c.accept_event(revoke))
                cleared = observer.observe(('invalidate', reason))
                self.assertEqual(cleared['changes'], [])
                self.assertIsNone(cleared['source_snapshot_ref'])
                if reason == 'state_advanced':
                    self.assertIsNotNone(observer._baseline)
                    observer.observe()  # a pause/tick must not hold an unleased old baseline
                self.assertIsNone(observer._baseline)
                self.assertTrue(c.accept_event(new))
                self.assertEqual(observer.observe(('snapshot', None))['status'], 'baseline_observed')

    def test_real_partial_and_atomic_source_replacement_establish_new_baselines(self):
        prefixes = real_prefixes((90, 91))
        save(self.path, prefixes[90])
        stream = watch_decision_events(self.path, interval=0, samples=6, clock_ns=ManualClock(), session_id='reset-changes')
        self.addCleanup(stream.close)
        events = poll_events(stream)
        append(self.path, prefixes[91][len(prefixes[90]):])
        events += poll_events(stream)
        with self.path.open('ab') as out:
            out.write(b'{"probe":')
        events += poll_events(stream)
        with self.path.open('ab') as out:
            out.write(b'true}\n')
        events += poll_events(stream)
        replacement = self.path.with_name('replacement.jsonl')
        save(replacement, prefixes[90])
        replacement.replace(self.path)
        events += poll_events(stream) + list(stream)
        result, diagnostics = self.cli(events, '--observed-changes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(e.get('reason') == 'source_partial' for e in events))
        self.assertTrue(any(e.get('reason') == 'source_reset' for e in events))
        compared = [d['observed_changes'] for d in diagnostics if d['observed_changes']['status'] == 'endpoints_compared']
        self.assertTrue(compared)
        self.assertTrue(all(c['after_snapshot_ref']['binding']['source_generation'] == 1 for c in compared))
        after_partial = next(e['sequence'] for e in events if e.get('reason') == 'source_partial')
        self.assertTrue(all(d['observed_changes']['changes'] == [] for d in diagnostics if d['last_sequence'] >= after_partial))

    def test_unknown_changed_card_or_duplicate_identity_never_proves_a_move(self):
        old, _, _ = self.snapshots()
        before = old['decision_state']
        after = copy.deepcopy(before)
        obj = after['visible_objects'][0]
        obj.update(card_id=None, zone='ZoneType_Graveyard')
        changes, unresolved = _compare(before, after)
        self.assertFalse(any(c.get('instance_id') == obj['instance_id'] for c in changes))
        self.assertIn('visible_card_identity_changed_or_unknown', unresolved)
        after['visible_objects'].append(dict(obj))
        changes, unresolved = _compare(before, after)
        self.assertFalse(any(c.get('instance_id') == obj['instance_id'] for c in changes))
        self.assertIn('ambiguous_visible_instance_identity', unresolved)
        before = copy.deepcopy(before)
        before['visible_objects'][0].update(card_id=10, tapped=False, controller_seat=1)
        after = copy.deepcopy(before)
        after['visible_objects'][0].update(tapped=True, controller_seat=2)
        changes, _ = _compare(before, after)
        self.assertEqual({c['kind'] for c in changes}, {'tapped_changed', 'controller_seat_changed'})
        before['visible_objects'][0].update(tapped=None, controller_seat=None)
        self.assertEqual(_compare(before, after)[0], [])

    def test_change_payload_budget_withholds_whole_result(self):
        old, invalidate, new = self.snapshots()
        template = old['decision_state']['visible_objects'][0]
        for event, letter in ((old, 'x'), (new, 'y')):
            event['decision_state']['visible_objects'] = [dict(template, instance_id=100000+i,
                card_id=10, zone='ZoneType_' + letter*1500) for i in range(400)]
        consumer = DecisionConsumer(clock_ns=ManualClock())
        observer = ObservedChanges(consumer)
        for event in (old, invalidate, new):
            self.assertTrue(consumer.accept_event(event))
            result = observer.observe((event['event_type'], event.get('reason')))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['changes'], [])
        self.assertIsNone(result['counts'])
        self.assertIn('observed_changes_limits_exceeded', result['unresolved'])

    def test_compare_crossing_lease_clears_changes_and_other_sidecars(self):
        old, invalidate, new = self.snapshots()
        clock, output = ManualClock(100), []
        consumer = DecisionConsumer(10000, 500, clock)
        def cross(*args):
            result = _compare(*args)
            clock.advance(501)
            return result
        with patch('mtgaplayer.observed_changes._compare', side_effect=cross):
            result = consume_events(io.StringIO(encoded([old, invalidate, new])), output.append, consumer,
                advice_policy='evidence_only.v1', observed_changes=True)
        self.assertEqual(result, 1)
        self.assertEqual(output[-1]['consumer_status'], 'STALE')
        self.assertTrue(all(r['observed_changes']['changes'] == [] for r in output))
        self.assertIsNone(output[-1]['decision_advice']['source_snapshot_ref'])

    def test_blocked_output_cannot_hold_comparison_cache_after_expiry(self):
        old, invalidate, new = self.snapshots()
        clock, gate, entered, cleared = ManualClock(100), threading.Event(), threading.Event(), threading.Event()
        consumer = DecisionConsumer(10000, 500, clock)
        stream, output, result, observers, owners = QueueStream(), [], [], [], []
        compared = threading.Event()
        original_clear = ObservedChanges.clear
        original_observe = ObservedChanges.observe
        def observe(observer, event=None):
            owners.append(threading.get_ident())
            result = original_observe(observer, event)
            if result['status'] == 'endpoints_compared':
                compared.set()
            return result
        def clear(observer, reason):
            original_clear(observer, reason)
            if reason == 'current_snapshot_unavailable' and consumer._status == 'STALE':
                observers.append(observer)
                cleared.set()
        def emit(value):
            entered.set()
            gate.wait(3)
            output.append(value)
        for event in (old, invalidate, new):
            stream.send(event)
        core = threading.Thread(target=lambda: result.append(consume_events(stream, emit, consumer,
            tick_seconds=.002, observed_changes=True)))
        def cleanup():
            gate.set()
            stream.lines.put('')
            core.join(3)
        self.addCleanup(cleanup)
        with patch.object(ObservedChanges, 'clear', clear), patch.object(ObservedChanges, 'observe', observe):
            core.start()
            self.assertTrue(entered.wait(2))
            # All three queued events are consumed on the owner even when emit blocks.
            self.assertTrue(compared.wait(2))
            self.assertEqual(consumer._sequence, 3)
            clock.advance(501)
            self.assertTrue(cleared.wait(2))
            self.assertIsNone(observers[-1]._baseline)
            self.assertFalse(gate.is_set())
            gate.set()
            core.join(3)
        self.assertEqual(result, [1])
        self.assertEqual(set(owners), {core.ident})
        self.assertEqual(output[-1]['observed_changes']['changes'], [])

    def test_actual_watch_consumer_os_pipe_append_and_stop(self):
        prefixes = real_prefixes((90, 91))
        save(self.path, prefixes[90])
        producer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'watch', str(self.path),
            '--decision-events', '--decision-state-version', '2', '--samples', '100', '--interval', '.02'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        consumer = subprocess.Popen([sys.executable, '-m', 'mtgaplayer', 'consume-events', '--observed-changes'],
            stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        lines = queue.Queue()
        def read():
            for line in consumer.stdout:
                lines.put(json.loads(line))
            lines.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while True:
                row = lines.get(timeout=5)
                self.assertIsNotNone(row)
                if row['observed_changes']['status'] == 'baseline_observed':
                    break
            append(self.path, prefixes[91][len(prefixes[90]):])
            compared, terminal = [], row
            while True:
                row = lines.get(timeout=5)
                if row is None:
                    break
                terminal = row
                if row['observed_changes']['status'] == 'endpoints_compared':
                    compared.append(row['observed_changes'])
            self.assertTrue(any(c.get('kind') == 'life_changed' and c['before'] == 20 and c['after'] == 19
                                for pair in compared for c in pair['changes']))
            self.assertEqual(consumer.wait(timeout=5), 0, consumer.stderr.read())
            self.assertEqual(producer.wait(timeout=5), 0, producer.stderr.read())
            self.assertEqual(terminal['consumer_status'], 'CLOSED')
            self.assertEqual(terminal['observed_changes']['changes'], [])
        finally:
            for process in (consumer, producer):
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            reader.join(2)
            for process in (consumer, producer):
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
