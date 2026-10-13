"""Raw GRE tests use a field-reduced, identity-scrubbed real Player.log chain."""
import copy
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from mtgaplayer.cli import replay, watch
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.raw_log import RawFramer


FIXTURE = Path(__file__).parent / 'fixtures' / 'player_log_minimal.jsonl'


def entries():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines()]


def state(entry):
    return next(m['gameStateMessage'] for m in
                entry['greToClientEvent']['greToClientMessages'] if 'gameStateMessage' in m)


class RawLogTests(unittest.TestCase):
    def test_real_chain_full_diff_visibility_and_submission(self):
        rows = entries()
        reducer = RawReducer()
        reducer.reset(1)
        for row in rows[:3]:
            reducer.apply(row)
        first = reducer.document()['current']
        self.assertTrue(first['valid'])
        self.assertEqual((first['self_seat'], first['game_state_id']), (1, 1))
        self.assertEqual([p['life'] for p in first['players']], [20, 20])
        self.assertEqual(first['objects'], [])
        reducer.apply(rows[3])
        second = reducer.document()['current']
        hand = [obj for obj in second['objects'] if obj['zone'] == 'ZoneType_Hand']
        self.assertEqual({o['id']: o['card_id'] for o in hand},
                         {161: 96839, 162: 94899, 163: 87141, 164: 96836,
                          165: 87274, 166: 96626, 167: 96836})
        self.assertEqual(len(hand), 7)
        self.assertEqual(second['hidden_counts']['2:ZoneType_Hand'], 7)
        self.assertNotIn('HIDDEN_SENTINEL', json.dumps(reducer.document()))
        reducer.apply(rows[4])
        before = reducer.document()['current']
        self.assertEqual(before['game_state_id'], 3)
        self.assertEqual(before['request']['id'], 12)
        self.assertFalse(before['request']['supported'])
        self.assertGreater(before['unsupported_broadcast_requests'], 0)
        reducer.apply(rows[5])
        after = reducer.document()['current']
        self.assertIsNone(after['request'])
        self.assertEqual(after['submission'], {'request_id': 12, 'game_state_id': 3,
                                               'confirmation': 'client_submission_only'})
        reducer.apply(rows[4])  # old diff/request retransmission never reopens
        self.assertIsNone(reducer.document()['current']['request'])
        reducer.apply(rows[6])
        self.assertEqual(reducer.document()['current']['game_state_id'], 6)
        self.assertFalse(reducer.document()['current']['actionable'])

    def test_installed_entrypoint_and_partial_append(self):
        rows = entries()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows[:3]), encoding='utf-8')
            follower, reducer = RawFollower(path), RawReducer()
            reset, batch = follower.poll()
            self.assertTrue(reset)
            reducer.reset(follower.generation)
            for row in batch:
                reducer.apply(row)
            self.assertEqual(reducer.document()['current']['game_state_id'], 1)
            encoded = json.dumps(rows[3]).encode() + b'\n'
            with path.open('ab') as stream:
                stream.write(encoded[:19])
            _, batch = follower.poll()
            self.assertEqual(batch, [])
            self.assertTrue(follower.framer.partial)
            with path.open('ab') as stream:
                stream.write(encoded[19:])
            _, batch = follower.poll()
            for row in batch:
                reducer.apply(row)
            self.assertEqual(reducer.document()['current']['game_state_id'], 2)
            self.assertEqual(replay(path, format='player-log')['current']['game_state_id'], 2)
            samples = list(watch(path, interval=0, samples=2))
            self.assertEqual(samples[0]['source']['phase'], 'history')
            self.assertEqual(samples[1]['source']['phase'], 'append')
            self.assertEqual(samples[1]['source']['new_records'], 0)
            self.assertEqual(samples[1]['current']['source_state_timestamp'],
                             samples[0]['current']['source_state_timestamp'])
            self.assertFalse(samples[1]['current']['actionable'])
            self.assertTrue(samples[1]['source']['stopped'])

    def test_missing_full_gap_corruption_and_recovery(self):
        rows = entries()
        r = RawReducer()
        r.reset(1)
        for row in (rows[0], rows[1], rows[3]):  # Diff without Full
            r.apply(row)
        self.assertFalse(r.document()['current']['valid'])
        r.apply(rows[2])
        self.assertTrue(r.document()['current']['valid'])
        gap = copy.deepcopy(rows[3])
        state(gap)['prevGameStateId'] = 999
        r.apply(gap)
        self.assertEqual(r.document()['error'], 'state_gap_or_missing_full')
        self.assertNotIn('objects', r.document()['current'])
        self.assertTrue(r.document()['last_valid']['valid'])
        r.apply(None)
        self.assertFalse(r.document()['current']['valid'])
        baseline = copy.deepcopy(rows[2])
        state(baseline)['gameStateId'] = 4
        r.apply(baseline)
        self.assertTrue(r.document()['current']['valid'])
        self.assertEqual(r.document()['current']['game_state_id'], 4)

    def test_identity_conflict_and_source_replacement(self):
        rows = entries()
        r = RawReducer()
        r.reset(1)
        for row in rows[:4]:
            r.apply(row)
        bad = copy.deepcopy(rows[4])
        for message in bad['greToClientEvent']['greToClientMessages']:
            if 'gameStateMessage' in message:
                message['systemSeatIds'] = [2]
        r.apply(bad)
        self.assertFalse(r.document()['current']['valid'])
        recovery = copy.deepcopy(rows[2])
        state(recovery)['gameStateId'] = 10
        r.apply(recovery)
        self.assertFalse(r.document()['current']['valid'])
        r.reset(2)
        for row in rows[:3]:
            r.apply(row)
        self.assertTrue(r.document()['current']['valid'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            path.write_bytes(FIXTURE.read_bytes())
            follower = RawFollower(path)
            self.assertTrue(follower.poll()[0])
            path.write_text(''.join(json.dumps(x) + '\n' for x in rows[:3]), encoding='utf-8')
            self.assertTrue(follower.poll()[0])
            self.assertEqual(follower.generation, 2)
            original = path.read_bytes()
            replaced = original.replace(b'fixture-local', b'fixture-locax')
            self.assertEqual(len(replaced), len(original))
            path.write_bytes(replaced)
            self.assertTrue(follower.poll()[0])
            self.assertEqual(follower.generation, 3)

    def test_replacement_diff_blocks_until_new_bound_full(self):
        rows = entries()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            follower, reducer = RawFollower(path), RawReducer()
            path.write_text(''.join(json.dumps(x) + '\n' for x in rows[:4]), encoding='utf-8')
            reset, batch = follower.poll()
            reducer.reset(follower.generation)
            for item in batch:
                reducer.apply(item)
            self.assertTrue(reducer.document()['current']['valid'])
            path.write_text(json.dumps(rows[3]) + '\n', encoding='utf-8')
            reset, batch = follower.poll()
            self.assertTrue(reset)
            reducer.reset(follower.generation)
            for item in batch:
                reducer.apply(item)
            self.assertFalse(reducer.document()['current']['valid'])
            self.assertNotIn('objects', reducer.document()['current'])
            replacement = copy.deepcopy(rows[2])
            state(replacement)['gameStateId'] = 4
            with path.open('a', encoding='utf-8') as stream:
                for item in (rows[0], rows[1], replacement):
                    stream.write(json.dumps(item) + '\n')
            reset, batch = follower.poll()
            self.assertFalse(reset)
            for item in batch:
                reducer.apply(item)
            self.assertEqual(reducer.document()['current']['game_state_id'], 4)
            self.assertTrue(reducer.document()['current']['valid'])

    def test_request_conflict_duplicate_diff_and_critical_framing(self):
        rows = entries()
        reducer = RawReducer()
        reducer.reset(1)
        for item in rows[:5]:
            reducer.apply(item)
        original_stamp = reducer.document()['current']['source_state_timestamp']
        replayed = copy.deepcopy(rows[4])
        replayed['timestamp'] = 'later-but-duplicate'
        reducer.apply(replayed)
        self.assertEqual(reducer.document()['current']['source_state_timestamp'], original_stamp)
        conflict = copy.deepcopy(rows[4])
        for message in conflict['greToClientEvent']['greToClientMessages']:
            if message.get('type') == 'GREMessageType_MulliganReq':
                message['type'] = 'GREMessageType_UnknownReq'
        reducer.apply(conflict)
        self.assertEqual(reducer.document()['error'], 'conflicting_request_identity')
        self.assertNotIn('request', reducer.document()['current'])
        payload_conflict = copy.deepcopy(rows[4])
        for message in payload_conflict['greToClientEvent']['greToClientMessages']:
            if message.get('type') == 'GREMessageType_MulliganReq':
                message['mulliganReq'] = {'choice': 'changed-same-id-and-type'}
        another = RawReducer()
        another.reset(1)
        for item in rows[:5]:
            another.apply(item)
        another.apply(payload_conflict)
        self.assertEqual(another.document()['error'], 'conflicting_request_identity')
        self.assertNotIn('objects', another.document()['current'])
        framer = RawFramer()
        encoded = json.dumps(rows[2], indent=2).encode('utf-8')
        self.assertEqual(framer.feed(b'log prefix without JSON\n' + encoded[:29]), [])
        self.assertTrue(framer.partial)
        self.assertEqual(framer.feed(encoded[29:]), [rows[2]])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            path.write_bytes(FIXTURE.read_bytes() + b'{"greToClientEvent":}\n')
            doc = replay(path, format='player-log')
            self.assertFalse(doc['current']['valid'])
            self.assertEqual(doc['error'], 'malformed_raw_record')
            self.assertNotIn('objects', doc['current'])

    def test_malformed_critical_envelope_blocks(self):
        for field in ('greToClientEvent', 'matchGameRoomStateChangedEvent',
                      'authenticateResponse'):
            with self.subTest(field=field):
                r = RawReducer()
                r.reset(1)
                for item in entries()[:3]:
                    r.apply(item)
                r.apply({field: None})
                self.assertEqual(r.document()['error'], 'invalid_' + field)
                self.assertNotIn('objects', r.document()['current'])

    def test_installed_cli_watch_flushes_partial_and_complete_append(self):
        executable = Path(sys.prefix) / ('Scripts/mtgaplayer.exe' if os.name == 'nt' else 'bin/mtgaplayer')
        self.assertTrue(executable.is_file(), 'installed mtgaplayer entrypoint required')
        rows = entries()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows[:3]), encoding='utf-8')
            process = subprocess.Popen([str(executable), 'watch', str(path), '--samples', '16',
                                        '--interval', '0.2'], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                       cwd=Path(__file__).resolve().parents[1])
            lines = queue.Queue()
            reader = threading.Thread(target=lambda: [lines.put(line) for line in process.stdout],
                                      daemon=True)
            reader.start()
            try:
                first = json.loads(lines.get(timeout=2))
                self.assertEqual(first['source']['phase'], 'history')
                self.assertEqual(first['current']['game_state_id'], 1)
                self.assertIsNone(process.poll(), 'first line must arrive before watch exits')
                encoded = json.dumps(rows[3]).encode('utf-8') + b'\n'
                with path.open('ab') as stream:
                    stream.write(encoded[:19])
                partial = next((doc for doc in (json.loads(lines.get(timeout=1)) for _ in range(5))
                                if doc['source']['partial_record']), None)
                self.assertIsNotNone(partial)
                self.assertEqual(partial['error'], 'partial_raw_record_waiting')
                with path.open('ab') as stream:
                    stream.write(encoded[19:])
                complete = next((doc for doc in (json.loads(lines.get(timeout=1)) for _ in range(5))
                                 if doc['current'].get('game_state_id') == 2 and
                                 doc['current']['valid']), None)
                self.assertIsNotNone(complete)
                self.assertFalse(complete['current']['actionable'])
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(process.stderr.read(), '')
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_watch_keyboard_interrupt_reports_normal_stop(self):
        from mtgaplayer import cli
        output = io.StringIO()
        with patch.object(cli, 'watch', side_effect=KeyboardInterrupt), redirect_stdout(output):
            self.assertEqual(cli.main(['watch', str(FIXTURE)]), 0)
        stopped = json.loads(output.getvalue())
        self.assertEqual(stopped['source']['stop_reason'], 'keyboard_interrupt')
        self.assertTrue(stopped['source']['stopped'])


if __name__ == '__main__':
    unittest.main()
