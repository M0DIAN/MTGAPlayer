"""Synthetic protocol counterexamples, not the unavailable original GRE trace."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from mtgaplayer.cli import replay
from mtgaplayer.markers import HEADER, payload, locate
from mtgaplayer.player import verify_effect
from mtgaplayer.policy import Unsupported, decide
from mtgaplayer.state import Reducer
from mtgaplayer.stream import Follower, FramingError, LineFramer


def begin(match='m1', game='g1', seat=1):
    return {'schema': 1, 'type': 'begin', 'match': match, 'game': game, 'self_seat': seat}


def full(version=1, match='m1', game='g1', seat=1, kind='land'):
    return {**begin(match, game, seat), 'type': 'full', 'state_version': version,
            'objects': [{'id': 17, 'owner': seat, 'zone': 'hand', 'visibility': 'self', 'rule': kind},
                        {'id': 91, 'owner': 3 - seat, 'zone': 'battlefield', 'visibility': 'public',
                         'rule': 'inert_creature', 'hp': 5}],
            'mana': 2, 'land_plays': 0, 'phase': 'main', 'priority': seat, 'effects': [],
            'layout': version, 'outcome': None,
            'request': {'id': 'r1', 'kind': 'priority', 'opportunity_id': 'o1',
                        'opportunity_at': 1, 'root': 'r1'}}


def tracker(version=1):
    r = Reducer()
    r.reset(1)
    r.apply(begin())
    r.apply(full(version))
    return r


class StreamTests(unittest.TestCase):
    def test_half_append_utf8_and_ordered_corruption(self):
        framer = LineFramer()
        data = json.dumps({'name': '牌'}, ensure_ascii=False).encode() + b'\n'
        for chunk in data[:-1]:
            self.assertEqual(framer.feed(bytes([chunk])), [])
        self.assertTrue(framer.partial)
        self.assertEqual(framer.feed(data[-1:]), [{'name': '牌'}])
        rows = framer.feed(b'{bad}\n{"ok":1}\n')
        self.assertIsInstance(rows[0], FramingError)
        self.assertEqual(rows[1], {'ok': 1})

    def test_append_truncate_rotate_and_same_size_replace(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'state.jsonl'
            p.write_bytes(b'{"a":1}\n')
            f = Follower(p)
            self.assertEqual(f.poll(), (True, [{'a': 1}]))
            with p.open('ab') as out:
                out.write(b'{"b":')
            self.assertEqual(f.poll(), (False, []))
            with p.open('ab') as out:
                out.write(b'2}\n')
            self.assertEqual(f.poll(), (False, [{'b': 2}]))
            p.write_bytes(b'{"c":3}\n')
            self.assertEqual(f.poll(), (True, [{'c': 3}]))
            p.write_bytes(b'{"d":4}\n')
            self.assertEqual(f.poll(), (True, [{'d': 4}]))
            q = Path(d) / 'replacement'
            q.write_bytes(b'{"e":5}\n')
            q.replace(p)
            self.assertEqual(f.poll(), (True, [{'e': 5}]))
            self.assertEqual(f.generation, 4)


class StateTests(unittest.TestCase):
    def test_new_game_before_seat_and_conflicting_same_game(self):
        r = tracker()
        r.apply(begin(game='g2', seat=2))
        self.assertFalse(r.document()['current']['valid'])
        r.apply(full(game='g2', seat=2))
        self.assertEqual(r.document()['current']['self_seat'], 2)
        r.apply(full(game='g2', seat=1))
        doc = r.document()
        self.assertFalse(doc['current']['valid'])
        self.assertNotIn('objects', doc['current'])
        self.assertEqual(doc['last_valid']['self_seat'], 2)
        self.assertEqual(doc['first_error']['reason'], 'same_game_seat_conflict')
        r.apply(full())  # retired game cannot reopen
        self.assertEqual(r.document()['current']['game'], 'g2')

    def test_older_full_duplicate_and_gap_full_recovery(self):
        r = tracker(10)
        before = copy.deepcopy(r.state)
        stamp = r.last_observed
        r.apply(full(10))
        self.assertEqual(r.last_observed, stamp)
        r.apply(full(9))
        self.assertFalse(r.actionable())
        self.assertEqual(r.last_valid['state_version'], 10)
        self.assertEqual(r.state, before)
        r.apply(full(11))
        self.assertTrue(r.actionable())
        r.apply({**begin(), 'type': 'diff', 'state_version': 13, 'previous': 12, 'changes': {}})
        self.assertFalse(r.actionable())
        r.apply(full(14))
        self.assertTrue(r.actionable())
        self.assertEqual(r.first_error['reason'], 'state_rollback')

    def test_duplicate_request_after_consumption_never_reopens(self):
        r = tracker()
        stamp = r.state['request']['received_at']
        r.consume('executing')
        r.apply({**begin(), 'type': 'response', 'request_id': 'r1'})
        r.apply({**begin(), 'type': 'request', 'state_version': 1, 'request': full()['request']})
        self.assertEqual(r.state['request']['received_at'], stamp)
        self.assertFalse(r.actionable())
        r.apply(full(2))  # full baseline does not clear request ledger
        self.assertFalse(r.actionable())

    def test_complete_corruption_blocks_without_new_state_heartbeat_not_recovery(self):
        r = tracker()
        prior = copy.deepcopy(r.last_valid)
        r.apply(FramingError('malformed_complete_record'))
        r.apply({'schema': 1, 'type': 'heartbeat'})
        self.assertFalse(r.actionable())
        self.assertEqual(r.last_valid, prior)
        r.apply(full(1))  # explicit complete baseline can restore same version
        self.assertTrue(r.actionable())
        self.assertIsNotNone(r.first_error)
        r.reset(2)
        self.assertFalse(r.actionable())
        r.apply(full(1))
        self.assertFalse(r.actionable())  # needs explicit begin after source reset

    def test_hidden_fields_removed_and_missing_unknown(self):
        r = Reducer()
        r.reset(1)
        r.apply(begin())
        e = full()
        e['objects'].append({'id': 999, 'owner': 2, 'zone': 'hand', 'visibility': 'public',
                             'rule': 'PRIVATE_SENTINEL', 'name': 'SECRET'})
        del e['mana']
        r.apply(e)
        text = json.dumps(r.document())
        self.assertNotIn('PRIVATE_SENTINEL', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('999', text)
        self.assertIsNone(r.state['mana'])
        with self.assertRaises(Unsupported):
            decide(r.document()['current'], time.monotonic() + 1)

    def test_expiry_and_partial_replay_block(self):
        r = tracker()
        self.assertFalse(r.actionable(r.last_observed + 4))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'input.jsonl'
            path.write_text(json.dumps(begin()) + '\n' + json.dumps(full()) + '\n{"half":')
            doc = replay(path, True)
            self.assertFalse(doc['current']['valid'])
            self.assertNotIn('recommendation', doc)

    def test_diff_keeps_hidden_counts_and_generation_clears_binding(self):
        r = tracker()
        state = full(2)
        state['objects'].append({'id': 999, 'owner': 2, 'zone': 'hand', 'visibility': 'hidden',
                                 'rule': 'SECRET'})
        r.apply(state)
        r.apply({**begin(), 'type': 'diff', 'state_version': 3, 'previous': 2, 'changes': {'mana': 1}})
        self.assertEqual(r.state['hidden_counts'], {'2:hand': 1})
        self.assertNotIn('SECRET', json.dumps(r.document()))
        r.reset(2)
        self.assertIsNone(r.document()['current']['self_seat'])
        self.assertIsNone(r.document()['current']['last_observed'])


class PolicyTests(unittest.TestCase):
    def test_three_deterministic_actions_unknown_effect_and_deadline(self):
        r = tracker()
        view = r.document()['current']
        self.assertEqual(decide(view, time.monotonic() + 1).action, 'land')
        view['objects'][0]['rule'] = 'spark'
        self.assertEqual(decide(view, time.monotonic() + 1).action, 'cast')
        view['objects'] = view['objects'][1:]
        self.assertEqual(decide(view, time.monotonic() + 1).action, 'pass')
        view['effects'] = ['unknown_opponent_effect']
        with self.assertRaises(Unsupported):
            decide(view, time.monotonic() + 1)
        with self.assertRaises(TimeoutError):
            decide(view, time.monotonic() - 1)
        with self.assertRaises(InterruptedError):
            decide(view, time.monotonic() + 1, lambda: True)

    def test_effect_confirmation_not_just_version_growth(self):
        before = tracker().document()['current']
        plan = decide(before, time.monotonic() + 1)
        after = copy.deepcopy(before)
        after['request'] = None
        after['outcome'] = {'root': 'r1', 'action': 'land', 'source': 17, 'target': None}
        after['state_version'] += 1
        self.assertFalse(verify_effect(before, after, plan))
        after['objects'][0]['zone'] = 'battlefield'
        after['land_plays'] += 1
        self.assertTrue(verify_effect(before, after, plan))


def fake_frame(ids, layout=7, context=11):
    width, height = 500, 40
    pixels = bytearray(width * height * 4)
    for n, obj in enumerate(ids):
        x, y = 5 + n * 220, 5
        for yy in range(y, y + 12):
            for xx in range(x, x + 200):
                i = (yy * width + xx) * 4
                pixels[i:i + 3] = b'\xff\x00\xff'
        data = payload(obj, layout, context)
        for bit in range(64):
            color = b'\xff\xff\xff' if data[bit // 8] & (1 << (7 - bit % 8)) else b'\0\0\0'
            for yy in range(y + 2, y + 10):
                for xx in range(x + 4 + bit * 3, x + 7 + bit * 3):
                    i = (yy * width + xx) * 4
                    pixels[i:i + 3] = color
    return width, height, bytes(pixels)


class MarkerTests(unittest.TestCase):
    def test_identity_reorder_duplicate_context_and_occlusion(self):
        one, two = locate(fake_frame([HEADER, 17]), 7, 11), locate(fake_frame([17, HEADER]), 7, 11)
        self.assertNotEqual(one[17], two[17])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            locate(fake_frame([HEADER, HEADER]), 7, 11)
        with self.assertRaisesRegex(ValueError, 'stale'):
            locate(fake_frame([HEADER]), 8, 11)
        with self.assertRaisesRegex(ValueError, 'header'):
            locate(fake_frame([17]), 7, 11)


if __name__ == '__main__':
    unittest.main()
