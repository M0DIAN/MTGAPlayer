"""Synthetic regressions for conflict recovery at the actionable boundary."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.state import Reducer
from mtgaplayer.stream import FramingError
from test_core import begin, full, tracker


class ConflictRecoveryTests(unittest.TestCase):
    def response_tracker(self):
        reducer = Reducer()
        reducer.reset(1)
        reducer.apply(begin(), now=9)
        reducer.apply(full(), now=10)
        reducer.apply({**begin(), 'type': 'response', 'request_id': 'r1'}, now=11)
        return reducer

    def test_response_then_identical_full_preserves_consumption_and_clock(self):
        r = self.response_tracker()
        last_valid = copy.deepcopy(r.last_valid)
        r.apply(full(), now=12)
        self.assertIsNone(r.error)
        self.assertIsNone(r.state['request'])
        self.assertFalse(r.actionable(12))
        self.assertEqual(r.ledger[(1, 'm1', 'g1', 'r1')], 'confirmed')
        self.assertEqual(r.last_observed, 10)
        self.assertEqual(r.document(12)['current']['valid_until'], 13)
        self.assertEqual(r.requests[(1, 'm1', 'g1', 'r1')]['received_at'], 10)
        self.assertEqual(r.last_valid, last_valid)
        r.apply(full(), now=14)
        self.assertEqual(r.document(14)['error'], 'expired_state')
        self.assertNotIn('request', r.document(14)['current'])
        next_state = full(2)
        next_state['request'].update(id='r2', root='r2', opportunity_id='o2')
        r.apply(next_state, now=15)
        self.assertTrue(r.actionable(15))
        self.assertEqual(r.state['request']['id'], 'r2')

    def test_response_then_duplicate_at_real_replay_entrypoint(self):
        response = {**begin(), 'type': 'response', 'request_id': 'r1'}
        next_state = full(2)
        next_state['request'].update(id='r2', root='r2', opportunity_id='o2')
        events = [begin(), full(), response, full(), next_state]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'response-duplicate.jsonl'
            for count in (4, 5):
                with self.subTest(records=count):
                    path.write_text(''.join(json.dumps(e) + '\n' for e in events[:count]),
                                    encoding='utf-8')
                    result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(path)],
                                            cwd=Path(__file__).resolve().parents[1],
                                            text=True, capture_output=True, check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    document = json.loads(result.stdout)
                    self.assertIsNone(document['error'])
                    self.assertTrue(document['current']['valid'])
                    self.assertFalse(document['source']['input_sent'])
                    self.assertEqual(document['current']['state_version'], count - 3)
                    if count == 4:
                        self.assertIsNone(document['current']['request'])
                    else:
                        self.assertEqual(document['current']['request']['id'], 'r2')

    def test_consumed_request_does_not_hide_real_duplicate_conflicts(self):
        cases = [({'mana': 99}, 'conflicting_duplicate_state'),
                 ({'request': None}, 'conflicting_duplicate_state'),
                 ({'self_seat': 2}, 'same_game_seat_conflict'),
                 ({'game': 'unannounced'}, 'identity_without_begin')]
        for field, value in (('id', 'r2'), ('kind', 'target'), ('opportunity_id', 'o2'),
                             ('opportunity_at', 2), ('root', 'r2'), ('source', 17),
                             ('targets', [91])):
            request = {**full()['request'], field: value}
            cases.append(({'request': request}, 'conflicting_duplicate_state' if field == 'id'
                          else 'conflicting_request_identity'))
        for changes, reason in cases:
            with self.subTest(changes=changes):
                r = self.response_tracker()
                r.apply({**full(), **changes}, now=12)
                self.assertEqual(r.error, reason)
                r.apply(full(2), now=12)
                self.assertEqual(r.error, reason)
                self.assertFalse(r.actionable(12))

    def test_duplicate_after_response_repairs_corruption_without_renewing_state(self):
        r = self.response_tracker()
        r.apply(FramingError('malformed_complete_record'), now=11)
        r.apply(full(), now=12)
        self.assertIsNone(r.error)
        self.assertTrue(r.document(12)['current']['valid'])
        self.assertIsNone(r.state['request'])
        self.assertFalse(r.actionable(12))
        self.assertEqual(r.last_observed, 10)
        r.apply(FramingError('malformed_complete_record'), now=14)
        r.apply(full(), now=15)
        self.assertEqual(r.document(15)['error'], 'expired_state')

    def test_independent_request_and_diff_keep_latest_producer_comparison(self):
        for kind in ('request', 'diff'):
            with self.subTest(kind=kind):
                r = self.response_tracker()
                latest = full(1 if kind == 'request' else 2)
                latest['request'].update(id='r2', root='r2', opportunity_id='o2')
                event = {**begin(), 'type': kind, 'state_version': latest['state_version'],
                         'request': latest['request']} if kind == 'request' else {
                         **begin(), 'type': 'diff', 'previous': 1, 'state_version': 2,
                         'changes': {'request': latest['request'], 'layout': 2}}
                r.apply(event, now=12)
                r.apply({**begin(), 'type': 'response', 'request_id': 'r2'}, now=12)
                r.apply(latest, now=13)
                self.assertIsNone(r.error)
                self.assertIsNone(r.state['request'])
                self.assertEqual(r.last_observed, 12)
                # An advancing diff omitting request carries the consumed current state.
                r.apply({**begin(), 'type': 'diff', 'previous': latest['state_version'],
                         'state_version': 3, 'changes': {'layout': 3}}, now=13)
                complete = full(3)
                complete['request'] = None
                r.apply(complete, now=14)
                self.assertIsNone(r.error)
                self.assertIsNone(r.state['request'])
                self.assertEqual(r.last_observed, 13)

    def test_producer_comparison_is_cleared_on_new_game_and_generation(self):
        for reset in (False, True):
            with self.subTest(reset=reset):
                r = self.response_tracker()
                r.apply(full(), now=12)
                if reset:
                    r.reset(2)
                opening = begin(game='g1' if reset else 'g2', seat=2)
                r.apply(opening, now=14)
                state = full(game=opening['game'], seat=2)
                state['mana'] = 99
                r.apply(state, now=15)
                self.assertTrue(r.actionable(15))
                r.apply({**opening, 'type': 'response', 'request_id': 'r1'}, now=15)
                r.apply(state, now=16)
                self.assertIsNone(r.error)
                self.assertIsNone(r.state['request'])

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
