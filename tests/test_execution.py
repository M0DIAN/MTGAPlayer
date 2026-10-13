"""Offline executor safety checks with explicit fakes; NEVER native evidence."""
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from mtgaplayer.benchmark import summarize
from mtgaplayer.native import NativeBlocked
from mtgaplayer.player import Executor, Reader, run_loop
from mtgaplayer.policy import decide
from mtgaplayer.visual import visual_context
from test_core import begin, full, tracker


class FakeAdapter:
    def __init__(self, events, fail=None):
        self.events = events
        self.fail = fail
        self.first_input = self.last_input = None
        self.pressed = False
        self.releases = 0
        self.inputs = []

    def check(self):
        if self.fail == 'focus':
            raise NativeBlocked('focus_lost')

    def capture(self):
        return None

    def dispatch(self, point, flag):
        self.first_input = self.first_input or time.monotonic()
        self.last_input = time.monotonic()
        self.inputs.append(flag)
        self.pressed = flag == 2 or (self.pressed and flag != 4)
        if self.fail == 'exception':
            raise RuntimeError('injected_after_button_down')
        if self.events:
            self.events(flag)

    def release(self):
        if self.pressed:
            self.releases += 1
            self.pressed = False


class FakeReader:
    def __init__(self, r):
        self.reducer = r

    def sample(self):
        return self.reducer.document()['current']


class ExecutionTests(unittest.TestCase):
    def test_land_actual_postcondition_required_and_dedup(self):
        r = tracker()
        before = r.document()['current']
        plan = decide(before, time.monotonic() + 1)
        def events(flag):
            if flag == 4:
                state = full(2)
                state['objects'][0]['zone'], state['objects'][0]['visibility'] = 'battlefield', 'public'
                state['land_plays'], state['request'] = 1, None
                state['outcome'] = {'root': 'r1', 'action': 'land', 'source': 17, 'target': None}
                r.apply(state)
        adapter = FakeAdapter(events)
        executor = Executor(FakeReader(r), adapter, 'fake-nonce')
        # Stub ONLY screen binding; state/transition/postcondition code runs.
        executor.point = lambda *args: ((1, 1), visual_context(r.document()['current']))
        with patch('mtgaplayer.player.markers.locate', return_value={}):
            confirmed, after = executor.execute(plan, before)
        self.assertEqual(adapter.inputs, [2, 1, 4])
        self.assertEqual(executor.phase, 'completed')
        self.assertEqual(r.ledger[(1, 'm1', 'g1', 'r1')], 'confirmed')
        self.assertFalse(r.actionable())

    def test_compound_keeps_root_time_and_validates_each_child(self):
        r = tracker()
        # Establish a new valid version, without first poisoning the fixture
        # with a conflicting duplicate (covered by test_conflict_recovery).
        r.apply(full(2, kind='spark'))
        before = r.document()['current']
        plan = decide(before, time.monotonic() + 2)
        releases = 0
        def events(flag):
            nonlocal releases
            if flag != 4:
                return
            releases += 1
            e = full(2 + releases, kind='spark')
            if releases < 3:
                e['request'].update(id='r1:' + ('target' if releases == 1 else 'submit'),
                                    kind='target' if releases == 1 else 'submit', source=17, targets=[91])
            else:
                e['request'] = None
                e['mana'] = 1
                e['objects'][0].update(zone='graveyard', visibility='public')
                e['objects'][1]['hp'] = 4
                e['outcome'] = {'root': 'r1', 'action': 'cast', 'source': 17, 'target': 91}
            r.apply(e)
        adapter = FakeAdapter(events)
        executor = Executor(FakeReader(r), adapter, 'fake-nonce')
        executor.point = lambda *args: ((1, 1), visual_context(r.document()['current']))
        with patch('mtgaplayer.player.markers.locate', return_value={}):
            confirmed, after = executor.execute(plan, before)
        self.assertEqual(adapter.inputs, [2, 4, 2, 4, 2, 4])
        self.assertEqual(plan.request, 'r1')
        self.assertEqual(plan.opportunity_id, 'o1')
        self.assertGreaterEqual(confirmed, adapter.last_input)

    def test_focus_stop_expiry_target_disappearance_and_unexpected_substage(self):
        r = tracker()
        r.apply(full(2, kind='spark'))
        before = r.document()['current']
        plan = decide(before, time.monotonic() + 1)
        adapter = FakeAdapter(None, 'focus')
        executor = Executor(FakeReader(r), adapter, 'fake-nonce')
        with self.assertRaisesRegex(NativeBlocked, 'focus_lost'):
            executor.execute(plan, before)
        self.assertEqual(adapter.inputs, [])
        adapter.fail = None
        executor.stop = lambda: True
        with self.assertRaises(InterruptedError):
            executor.execute(plan, before)
        executor.stop = lambda: False
        child = full(3, kind='spark')
        child['request'].update(id='r1:target', kind='target', source=17, targets=[91])
        child['effects'] = ['unknown_opponent_effect']
        r.apply(child)
        executor.before = before
        with self.assertRaisesRegex(NativeBlocked, 'unexpected_substage'):
            executor.context(plan, 'r1:target', 3, 'target')
        child['effects'] = []
        child['objects'] = child['objects'][:1]
        child['request']['targets'] = []
        child['state_version'] = 4
        r.apply(child)
        with self.assertRaises(NativeBlocked):
            executor.context(plan, 'r1:target', 4, 'target')
        self.assertEqual(adapter.inputs, [])

    def test_exception_releases_owned_button_and_never_retries(self):
        r = tracker()
        before = r.document()['current']
        plan = decide(before, time.monotonic() + 1)
        adapter = FakeAdapter(None, 'exception')
        executor = Executor(FakeReader(r), adapter, 'fake-nonce')
        executor.point = lambda *args: ((1, 1), visual_context(r.document()['current']))
        with self.assertRaises(RuntimeError):
            executor.execute(plan, before)
        self.assertEqual(adapter.inputs, [2])
        self.assertFalse(adapter.pressed)
        self.assertEqual(adapter.releases, 1)
        self.assertEqual(r.ledger[(1, 'm1', 'g1', 'r1')], 'executing')
        self.assertFalse(r.actionable())

    def test_all_terminal_opportunities_counted_in_report(self):
        rows = []
        for i, status in enumerate(['confirmed', 'unsupported', 'timeout', 'paused', 'cancelled', 'uncertain', 'fail']):
            rows.append({'status': status, 'action': 'cast', 'opportunity_at': 0,
                         'observed': 0.1, 'state_ready': 0.2, 'decision_end': 0.3,
                         'first_input': 0.4 if i == 0 else None,
                         'last_input': 0.5 if i == 0 else None,
                         'confirm': 0.6 if i == 0 else None, 'ended_at': i + 1})
        report = summarize(rows, 123)
        self.assertEqual(report['opportunities'], 7)
        self.assertEqual(report['all_ended_opportunities_ms']['max'], 7000)
        self.assertEqual(report['all_ended_opportunities_ms']['n'], 7)
        self.assertEqual(report['NATIVE_HARNESS'], 'FAIL')
        self.assertEqual(report['status_counts']['unsupported'], 1)


if __name__ == '__main__':
    unittest.main()
