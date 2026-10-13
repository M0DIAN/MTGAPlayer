"""Offline readiness/control regressions; these are not native input evidence."""
import copy
import time
import unittest
from unittest.mock import patch
from mtgaplayer import markers
from mtgaplayer.native import NativeBlocked
from mtgaplayer.player import Executor
from mtgaplayer.policy import decide
from mtgaplayer.visual import visual_context, wait_for_frame
from test_core import full, tracker
from test_execution import FakeAdapter, FakeReader


class Clock:
    def __init__(self):
        self.value = 100.0
        self.sleeps = []

    def now(self):
        return self.value

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.value += delay


class PixelAdapter(FakeAdapter):
    def __init__(self, on_capture=lambda: None):
        super().__init__(None)
        self.captures = 0
        self.on_capture = on_capture

    def capture(self):
        self.captures += 1
        self.on_capture()
        return None


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.view = tracker().document()['current']
        self.view['valid_until'] = 200.0
        self.clock = Clock()
        self.adapter = PixelAdapter()
        self.sample = lambda: copy.deepcopy(self.view)
        self.addCleanup(patch.stopall)
        patch('mtgaplayer.visual.time.monotonic', self.clock.now).start()
        patch('mtgaplayer.visual.time.sleep', self.clock.sleep).start()

    def wait(self, **options):
        return wait_for_frame(self.adapter, 'nonce', self.sample, 100.055, required=(17,), **options)

    def test_only_missing_or_old_pixels_wait_read_only(self):
        for first in (ValueError('harness_header_not_visible'), ValueError('stale_visual_context'),
                      {markers.HEADER: (1, 1)}):
            with self.subTest(first=first):
                self.clock.value, self.clock.sleeps = 100.0, []
                self.adapter.captures = 0
                with patch('mtgaplayer.visual.markers.locate', side_effect=[first, {17: (8, 9)}]):
                    _, locations, view = self.wait()
                self.assertEqual(locations[17], (8, 9))
                self.assertEqual(self.adapter.captures, 2)
                self.assertEqual(self.clock.sleeps, [0.02])
                self.assertEqual(self.adapter.inputs, [])

    def test_focus_loss_during_wait_rejects_immediately(self):
        self.adapter.on_capture = lambda: setattr(self.adapter, 'fail', 'focus')
        with patch('mtgaplayer.visual.markers.locate', side_effect=ValueError('harness_header_not_visible')):
            with self.assertRaisesRegex(NativeBlocked, 'focus_lost'):
                self.wait()
        self.assertEqual(self.adapter.captures, 1)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.adapter.inputs, [])

    def test_fixed_deadline_and_state_expiry_sleep_without_input(self):
        for horizon in (200.0, 100.03):
            with self.subTest(horizon=horizon):
                self.clock.value, self.clock.sleeps = 100.0, []
                self.adapter.captures = 0
                self.view['valid_until'] = horizon
                with patch('mtgaplayer.visual.markers.locate', side_effect=ValueError('harness_header_not_visible')):
                    with self.assertRaisesRegex(TimeoutError, 'visual_readiness_timeout'):
                        self.wait()
                self.assertAlmostEqual(self.clock.value, min(100.055, horizon))
                self.assertTrue(self.clock.sleeps)
                self.assertTrue(all(0 < s <= 0.02 for s in self.clock.sleeps))
                self.assertLessEqual(self.adapter.captures, 3)
                self.assertEqual(self.adapter.inputs, [])

    def test_context_change_after_capture_rejects_even_missing_pixels(self):
        for field in ('layout', 'state_version', 'request', 'effects', 'outcome'):
            with self.subTest(field=field):
                original = copy.deepcopy(self.view)
                self.adapter.captures = 0
                def change():
                    if field == 'request':
                        self.view[field]['root'] = 'different-root'
                    else:
                        self.view[field] = 'changed'
                self.adapter.on_capture = change
                with patch('mtgaplayer.visual.markers.locate', side_effect=ValueError('stale_visual_context')):
                    with self.assertRaisesRegex(NativeBlocked, 'visual_context_changed'):
                        self.wait()
                self.assertEqual(self.adapter.captures, 1)
                self.assertEqual(self.clock.sleeps, [])
                self.assertEqual(self.adapter.inputs, [])
                self.view = original

    def test_ambiguous_or_unknown_decoder_errors_never_retry(self):
        for reason in ('ambiguous_visual_identity', 'unknown_decoder_error'):
            with self.subTest(reason=reason):
                self.adapter.captures = 0
                with patch('mtgaplayer.visual.markers.locate', side_effect=ValueError(reason)):
                    with self.assertRaisesRegex(ValueError, reason):
                        self.wait()
                self.assertEqual(self.adapter.captures, 1)
                self.assertEqual(self.clock.sleeps, [])
                self.assertEqual(self.adapter.inputs, [])

    def test_stop_and_deadline_after_capture_cannot_return_coordinates(self):
        stopped = [False]
        self.adapter.on_capture = lambda: stopped.__setitem__(0, True)
        with patch('mtgaplayer.visual.markers.locate', return_value={17: (8, 9)}):
            with self.assertRaises(InterruptedError):
                self.wait(stop=lambda: stopped[0])
            self.adapter.on_capture = lambda: setattr(self.clock, 'value', 100.055)
            with self.assertRaises(TimeoutError):
                self.wait()
        self.assertEqual(self.adapter.inputs, [])
        self.assertEqual(self.clock.sleeps, [])


class ConfirmationReadinessTests(unittest.TestCase):
    def prepare(self):
        reducer = tracker()
        before = reducer.document()['current']
        plan = decide(before, time.monotonic() + 1)
        def events(flag):
            if flag == 4:
                state = full(2)
                state['objects'][0].update(zone='battlefield', visibility='public')
                state.update(land_plays=1, request=None,
                             outcome={'root': 'r1', 'action': 'land', 'source': 17, 'target': None})
                reducer.apply(state)
        adapter = PixelAdapter()
        adapter.events = events
        executor = Executor(FakeReader(reducer), adapter, 'nonce')
        executor.point = lambda *args: ((1, 1), visual_context(reducer.document()['current']))
        return reducer, before, plan, adapter, executor

    def test_terminal_pixels_lag_waits_without_repeating_input(self):
        reducer, before, plan, adapter, executor = self.prepare()
        sleeps = []
        with patch('mtgaplayer.visual.markers.locate',
                   side_effect=[ValueError('harness_header_not_visible'), {}]), \
                patch('mtgaplayer.visual.time.sleep', side_effect=sleeps.append):
            _, after = executor.execute(plan, before)
        self.assertEqual(adapter.inputs, [2, 1, 4])
        self.assertEqual(adapter.captures, 2)
        self.assertEqual(sleeps, [0.02])
        self.assertEqual(executor.phase, 'completed')
        self.assertEqual(after['state_version'], 2)

    def test_terminal_changes_during_capture_never_confirm(self):
        reducer, before, plan, adapter, executor = self.prepare()
        adapter.on_capture = lambda: reducer.apply(full(3))
        with patch('mtgaplayer.visual.markers.locate', return_value={}):
            with self.assertRaisesRegex(NativeBlocked, 'confirmation_context_changed'):
                executor.execute(plan, before)
        self.assertEqual(adapter.inputs, [2, 1, 4])
        self.assertEqual(adapter.captures, 1)
        self.assertNotEqual(executor.phase, 'completed')
        self.assertEqual(reducer.ledger[(1, 'm1', 'g1', 'r1')], 'executing')

    def test_point_uses_shared_wait_and_returns_latest_binding(self):
        reducer, before, plan, adapter, executor = self.prepare()
        # Undo only the test's screen-binding stub; exercise the real point path.
        del executor.point
        with patch('mtgaplayer.visual.markers.locate',
                   side_effect=[{markers.HEADER: (1, 1)}, {17: (8, 9)}]), \
                patch('mtgaplayer.visual.time.sleep') as sleep:
            point, binding = executor.point(plan, 'r1', 1, 'priority', 17)
        self.assertEqual(point, (8, 9))
        self.assertEqual(binding, visual_context(reducer.document()['current']))
        sleep.assert_called_once_with(0.02)
        self.assertEqual(adapter.inputs, [])


if __name__ == '__main__':
    unittest.main()
