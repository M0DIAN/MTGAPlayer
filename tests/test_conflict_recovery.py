"""Synthetic regressions for conflict recovery at the actionable boundary."""
import copy
import unittest

from mtgaplayer.stream import FramingError
from test_core import begin, full, tracker


class ConflictRecoveryTests(unittest.TestCase):
    def assert_blocked_baseline(self, reducer, state, last_valid, observed, reason):
        self.assertFalse(reducer.actionable())
        self.assertFalse(reducer.document()['current']['valid'])
        self.assertNotIn('objects', reducer.document()['current'])
        self.assertEqual(reducer.state, state)
        self.assertEqual(reducer.last_valid, last_valid)
        self.assertEqual(reducer.last_observed, observed)
        self.assertEqual(reducer.error, reason)

    def test_conflicting_duplicate_cannot_be_retried_or_downgraded(self):
        r = tracker(10)
        state, last_valid = copy.deepcopy(r.state), copy.deepcopy(r.last_valid)
        observed = r.last_observed
        conflict = full(10)
        conflict['mana'] = 99
        for event in (conflict, conflict, full(10), full(9),
                      FramingError('malformed_complete_record'), full(11)):
            r.apply(event)
            self.assert_blocked_baseline(r, state, last_valid, observed,
                                         'conflicting_duplicate_state')

    def test_binding_conflict_requires_explicit_new_game_or_generation(self):
        for conflict in (full(seat=2), full(game='unannounced')):
            with self.subTest(conflict=conflict['game'], seat=conflict['self_seat']):
                r = tracker()
                state, last_valid = copy.deepcopy(r.state), copy.deepcopy(r.last_valid)
                observed = r.last_observed
                r.apply(conflict)
                reason = r.error
                for event in (begin(), full(), full(2),
                              {**begin(), 'type': 'response', 'request_id': 'r1'},
                              FramingError('malformed_complete_record'), full(3)):
                    r.apply(event)
                    self.assert_blocked_baseline(r, state, last_valid, observed, reason)
                r.apply(begin(game='g2', seat=2))
                self.assertFalse(r.actionable())
                r.apply(full(game='g2', seat=2))
                self.assertTrue(r.actionable())
                self.assertEqual(r.state_seat, 2)
                r.apply(full(game='g2', seat=1))
                r.reset(2)
                self.assertFalse(r.actionable())
                r.apply(begin())
                r.apply(full())
                self.assertTrue(r.actionable())

    def test_nonrollback_full_recovers_gap_and_corruption(self):
        r = tracker(10)
        r.apply({**begin(), 'type': 'diff', 'state_version': 12,
                 'previous': 11, 'changes': {}})
        self.assertFalse(r.actionable())
        r.apply(full(9))
        self.assertFalse(r.actionable())
        r.apply(full(12))
        self.assertTrue(r.actionable())
        self.assertEqual(r.state['state_version'], 12)
        state = copy.deepcopy(r.state)
        r.apply(FramingError('malformed_complete_record'))
        r.apply(full(12))
        self.assertTrue(r.actionable())
        self.assertEqual(r.state, state)

    def test_corruption_does_not_allow_same_version_replacement(self):
        r = tracker()
        state, last_valid = copy.deepcopy(r.state), copy.deepcopy(r.last_valid)
        observed = r.last_observed
        r.apply(FramingError('malformed_complete_record'))
        replacement = full()
        replacement['mana'] = 99
        r.apply(replacement)
        self.assert_blocked_baseline(r, state, last_valid, observed,
                                     'conflicting_duplicate_state')

    def test_request_event_rejects_invisible_references_transactionally(self):
        for fields, reason in (({'source': 999}, 'request_source_not_visible'),
                               ({'targets': [888]}, 'request_targets_not_visible')):
            with self.subTest(fields=fields):
                r = tracker()
                state, last_valid = copy.deepcopy(r.state), copy.deepcopy(r.last_valid)
                observed, requests = r.last_observed, copy.deepcopy(r.requests)
                request = {**full()['request'], 'id': 'r2', **fields}
                r.apply({**begin(), 'type': 'request', 'state_version': 1,
                         'request': request})
                self.assert_blocked_baseline(r, state, last_valid, observed, reason)
                self.assertEqual(r.requests, requests)

    def test_request_event_accepts_visible_references_and_keeps_hidden_counts(self):
        r = tracker()
        event = full(2)
        event['objects'].append({'id': 999, 'owner': 2, 'zone': 'hand',
                                 'visibility': 'hidden', 'rule': 'SECRET'})
        r.apply(event)
        request = {**full()['request'], 'id': 'r2', 'source': 17, 'targets': [91]}
        r.apply({**begin(), 'type': 'request', 'state_version': 2, 'request': request})
        self.assertTrue(r.actionable())
        self.assertEqual(r.state['request']['source'], 17)
        self.assertEqual(r.state['request']['targets'], [91])
        self.assertEqual(r.state['hidden_counts'], {'2:hand': 1})


if __name__ == '__main__':
    unittest.main()
