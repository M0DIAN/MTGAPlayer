"""Real-source SelectN prefix with explicit synthetic negative mutations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import watch
from mtgaplayer.raw_log import RawReducer


FIXTURE = Path(__file__).parent / 'fixtures' / 'player_log_selectn.jsonl'
RESPONSE = Path(__file__).parent / 'fixtures' / 'player_log_selectn_response.jsonl'


def rows():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines()]


def reducer_for(items):
    reducer = RawReducer()
    reducer.reset(1)
    for item in items:
        reducer.apply(item)
    return reducer


def request(entry):
    return next(message for message in entry['greToClientEvent']['greToClientMessages']
                if message.get('type') == 'GREMessageType_SelectNReq')


class RawRequestSemanticsTests(unittest.TestCase):
    def test_actual_installed_cli_replay_decodes_own_options_without_actions(self):
        executable = Path(sys.prefix) / ('Scripts/mtgaplayer.exe' if os.name == 'nt'
                                         else 'bin/mtgaplayer')
        self.assertTrue(executable.is_file(), 'installed mtgaplayer entrypoint required')
        result = subprocess.run([str(executable), 'replay', '--format', 'player-log', str(FIXTURE)],
                                capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        doc = json.loads(result.stdout)
        current = doc['current']
        self.assertTrue(current['valid'])
        self.assertEqual((current['self_seat'], current['game_state_id']), (1, 231))
        decoded = current['request']
        self.assertEqual((decoded['id'], decoded['game_state_id']), (311, 231))
        self.assertTrue(decoded['supported'])
        self.assertEqual(decoded['binding'], {'generation': 1, 'match': current['match'],
                                              'game': 1, 'game_state_id': 231,
                                              'self_seat': 1, 'ownership_verified': True})
        self.assertEqual(decoded['candidate_evidence'],
                         {'field': 'selectNReq.ids', 'kind': 'engine_offered_instance_ids',
                          'all_legal_actions': False})
        self.assertEqual(decoded['candidates'],
                         [{'instance_id': number} for number in (175, 176, 178, 179)])
        self.assertEqual(decoded['selection']['max_sel'], 2)
        self.assertIsNone(decoded['selection']['min_sel'])
        self.assertFalse(decoded['selection']['combinations_complete'])
        self.assertFalse(current['actionable'])
        self.assertIsNone(current['legal_actions'])
        self.assertIsNone(current['mana'])
        self.assertIsNone(current['rules'])
        self.assertIsNone(current['layout'])
        self.assertFalse(doc['source']['input_sent'])
        self.assertFalse(doc['source']['executor_connected'])
        self.assertNotIn('card_id', json.dumps(decoded))
        self.assertNotIn('unfiltered_ids', json.dumps(decoded))

        watched = subprocess.run([str(executable), 'watch', str(FIXTURE), '--samples', '1'],
                                 capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual((watched.returncode, watched.stderr), (0, ''))
        sample = json.loads(watched.stdout)
        self.assertEqual(sample['current']['request']['candidates'], decoded['candidates'])
        self.assertTrue(sample['source']['stopped'])
        self.assertFalse(sample['current']['actionable'])
        self.assertFalse(sample['source']['input_sent'])

    def test_unknown_or_malformed_semantics_keep_state_valid_without_candidates(self):
        source = rows()
        variants = []
        missing = copy.deepcopy(source[-1])
        request(missing).pop('selectNReq')
        variants.append((missing, 'missing_selectn_payload'))
        unknown = copy.deepcopy(source[-1])
        request(unknown)['selectNReq']['validationType'] = 'SelectionValidationType_Unknown'
        variants.append((unknown, 'unsupported_selectn_shape'))
        extra = copy.deepcopy(source[-1])
        request(extra)['selectNReq']['otherRestriction'] = True
        variants.append((extra, 'unsupported_selectn_shape'))
        bad_ids = copy.deepcopy(source[-1])
        request(bad_ids)['selectNReq']['ids'] = [175, 175]
        variants.append((bad_ids, 'invalid_selectn_candidates'))
        for item, reason in variants:
            with self.subTest(item=request(item).get('selectNReq')):
                doc = reducer_for(source[:-1] + [item]).document()
                self.assertIsNone(doc['error'])
                self.assertTrue(doc['current']['valid'])
                self.assertEqual(doc['current']['game_state_id'], 231)
                self.assertFalse(doc['current']['request']['supported'])
                self.assertEqual(doc['current']['request']['candidates'], [])
                self.assertEqual(doc['current']['request']['unsupported_reason'], reason)
                self.assertFalse(doc['current']['actionable'])

    def test_ownership_must_be_authenticated_room_and_single_recipient(self):
        source = rows()
        for recipients in ([2], [1, 2]):
            with self.subTest(recipients=recipients):
                item = copy.deepcopy(source[-1])
                request(item)['systemSeatIds'] = recipients
                doc = reducer_for(source[:-1] + [item]).document()
                self.assertTrue(doc['current']['valid'])
                self.assertIsNone(doc['current']['request'])
                self.assertFalse(doc['current']['actionable'])
        wrong_auth = copy.deepcopy(source)
        wrong_auth[0]['authenticateResponse']['clientId'] = 'unmatched-client'
        doc = reducer_for(wrong_auth).document()
        self.assertFalse(doc['current']['valid'])
        self.assertNotIn('request', doc['current'])

    def test_actual_response_consumes_and_duplicate_cannot_revive(self):
        source = rows()
        reducer = reducer_for(source)
        response = json.loads(RESPONSE.read_text(encoding='utf-8'))
        reducer.apply(response)
        doc = reducer.document()
        self.assertIsNone(doc['current']['request'])
        self.assertEqual(doc['current']['submission'],
                         {'request_id': 311, 'game_state_id': 231,
                          'confirmation': 'client_submission_only'})
        reducer.apply({'greToClientEvent': {'greToClientMessages':
                       [copy.deepcopy(request(source[-1]))]}})
        self.assertIsNone(reducer.document()['current']['request'])
        self.assertFalse(reducer.document()['current']['actionable'])

    def test_supersession_state_advance_and_terminal_retire_old_options(self):
        source = rows()
        reducer = reducer_for(source)
        old = copy.deepcopy(request(source[-1]))
        newer = copy.deepcopy(old)
        newer['msgId'] = 312
        reducer.apply({'greToClientEvent': {'greToClientMessages': [newer]}})
        self.assertEqual(reducer.document()['current']['request']['id'], 312)
        reducer.apply({'greToClientEvent': {'greToClientMessages': [old]}})
        self.assertEqual(reducer.document()['current']['request']['id'], 312)
        advance = {'greToClientEvent': {'greToClientMessages': [{
            'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
            'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 232,
                                 'prevGameStateId': 231}}]}}
        reducer.apply(advance)
        self.assertIsNone(reducer.document()['current']['request'])
        reducer.apply({'greToClientEvent': {'greToClientMessages': [old, newer]}})
        self.assertIsNone(reducer.document()['current']['request'])
        terminal = copy.deepcopy(advance)
        terminal['greToClientEvent']['greToClientMessages'][0]['gameStateMessage'].update({
            'gameStateId': 233, 'prevGameStateId': 232,
            'gameInfo': {'stage': 'GameStage_GameOver'}})
        reducer.apply(terminal)
        newest = copy.deepcopy(newer)
        newest['msgId'] = 313
        newest['gameStateId'] = 233
        reducer.apply({'greToClientEvent': {'greToClientMessages': [newest]}})
        self.assertIsNone(reducer.document()['current']['request'])
        completed = copy.deepcopy(source[1])
        completed['matchGameRoomStateChangedEvent']['gameRoomInfo']['stateType'] = (
            'MatchGameRoomStateType_MatchCompleted')
        reducer.apply(completed)
        self.assertIsNone(reducer.document()['current']['request'])

    def test_gap_blocks_candidates_and_new_full_can_recover(self):
        source = rows()
        bad = copy.deepcopy(source[-1])
        first_state = bad['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
        first_state['prevGameStateId'] = 999
        reducer = reducer_for(source[:-1] + [bad])
        doc = reducer.document()
        self.assertEqual(doc['error'], 'state_gap_or_missing_full')
        self.assertFalse(doc['current']['valid'])
        self.assertFalse(doc['current']['actionable'])
        self.assertNotIn('request', doc['current'])
        self.assertEqual(doc['last_valid']['game_state_id'], 228)
        full = copy.deepcopy(source[2])
        full_state = next(message['gameStateMessage'] for message in
                          full['greToClientEvent']['greToClientMessages']
                          if 'gameStateMessage' in message)
        full_state['gameStateId'] = 232
        reducer.apply(full)
        self.assertTrue(reducer.document()['current']['valid'])
        recovered = copy.deepcopy(request(source[-1]))
        recovered['msgId'] = 312
        recovered['gameStateId'] = 232
        reducer.apply({'greToClientEvent': {'greToClientMessages': [recovered]}})
        self.assertEqual(reducer.document()['current']['request']['candidates'],
                         [{'instance_id': number} for number in (175, 176, 178, 179)])
        self.assertFalse(reducer.document()['current']['actionable'])

    def test_watch_append_only_candidate_event_and_consumption(self):
        source = rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            path.write_text(''.join(json.dumps(item) + '\n' for item in source[:-1]),
                            encoding='utf-8')
            samples = watch(path, interval=0, samples=5)
            baseline = next(samples)
            self.assertEqual(baseline['source']['phase'], 'history')
            self.assertIsNone(baseline['source']['candidate_event'])
            self.assertIsNone(baseline['current']['request'])
            encoded = (json.dumps(source[-1]) + '\n').encode('utf-8')
            with path.open('ab') as stream:
                stream.write(encoded[:19])
            partial = next(samples)
            self.assertTrue(partial['source']['partial_record'])
            self.assertFalse(partial['current']['valid'])
            self.assertIsNone(partial['source']['candidate_event'])
            with path.open('ab') as stream:
                stream.write(encoded[19:])
            arrived = next(samples)
            self.assertEqual(arrived['source']['phase'], 'append')
            self.assertEqual(arrived['source']['new_records'], 1)
            request = arrived['current']['request']
            self.assertEqual(request['id'], 311)
            self.assertEqual(arrived['source']['candidate_event'],
                             {'kind': 'supported_request_observed',
                              'binding': request['binding'], 'request_id': 311,
                              'candidate_count': 4, 'read_only': True})
            self.assertFalse(arrived['current']['actionable'])
            self.assertFalse(arrived['source']['input_sent'])
            self.assertFalse(arrived['source']['executor_connected'])
            idle = next(samples)
            self.assertIsNone(idle['source']['candidate_event'])
            self.assertEqual(idle['source']['new_records'], 0)
            with path.open('a', encoding='utf-8') as stream:
                stream.write(RESPONSE.read_text(encoding='utf-8') + '\n')
            consumed = next(samples)
            self.assertIsNone(consumed['source']['candidate_event'])
            self.assertIsNone(consumed['current']['request'])
            self.assertEqual(consumed['current']['submission']['confirmation'],
                             'client_submission_only')

    def test_watch_history_and_retransmission_do_not_emit_candidate_event(self):
        source = rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            path.write_text(''.join(json.dumps(item) + '\n' for item in source),
                            encoding='utf-8')
            samples = watch(path, interval=0, samples=2)
            baseline = next(samples)
            self.assertTrue(baseline['current']['request']['supported'])
            self.assertIsNone(baseline['source']['candidate_event'])
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(source[-1]) + '\n')
            duplicate = next(samples)
            self.assertEqual(duplicate['source']['phase'], 'append')
            self.assertIsNone(duplicate['source']['candidate_event'])
            self.assertFalse(duplicate['current']['actionable'])


if __name__ == '__main__':
    unittest.main()
