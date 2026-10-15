"""Invented combat requests over scrubbed real state; not new real evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.cli import replay, watch
from mtgaplayer.combat_frontier import CombatFrontierObserver, ATTACK, BLOCK, FLAGS
from mtgaplayer.decision_input import build_decision_input
from mtgaplayer.raw_log import RawReducer
from test_raw_log import entries, state

def baseline():
    rows = entries()[:3]
    gs = state(rows[2])
    hand = next(zone['zoneId'] for zone in gs['zones']
                if zone['type'] == 'ZoneType_Hand' and zone.get('ownerSeatId') == 2)
    gs['gameObjects'] = [{'instanceId': ident, 'grpId': 987654321, 'type': 'GameObjectType_Card',
        'zoneId': zone, 'ownerSeatId': seat, 'controllerSeatId': seat,
        'visibility': 'Visibility_Public' if zone == 28 else 'Visibility_Private', 'viewers': [seat]}
        for ident, zone, seat in ((701, 28, 1), (702, 28, 2), (703, 31, 1), (704, hand, 2))]
    for zone in gs['zones']:
        if zone['zoneId'] in (28, 31, hand):
            zone['objectInstanceIds'] = [obj['instanceId'] for obj in gs['gameObjects']
                                         if obj['zoneId'] == zone['zoneId']]
    return rows

def request(typ=ATTACK, ident=990, seats=None, references=(701,)):
    key = 'attackerInstanceId' if typ == ATTACK else 'blockerInstanceId'
    rows = [{key: ref, 'PRIVATE_FIELD': 'PRIVATE_VALUE'} for ref in references]
    for row in rows:
        row.update({'legalDamageRecipients': [{'PRIVATE_RECIPIENT': 99117733}]} if typ == ATTACK
                   else {'attackerInstanceIds': [702]})
    body = {'qualifiedAttackers' if typ == ATTACK else 'blockers': rows}
    return {'greToClientEvent': {'greToClientMessages': [{'type': typ, 'msgId': ident,
        'gameStateId': 1, 'systemSeatIds': [1] if seats is None else seats,
        'declareAttackersReq' if typ == ATTACK else 'declareBlockersReq': body}]}}

def body(row):
    message = row['greToClientEvent']['greToClientMessages'][0]
    return message.get('declareAttackersReq', message.get('declareBlockersReq'))

def response(typ=ATTACK, ident=990):
    return {'payload': {'type': 'ClientMessageType_DeclareAttackersResp' if typ == ATTACK else
        'ClientMessageType_DeclareBlockersResp', 'respId': ident, 'gameStateId': 1}}

def ready():
    observer = CombatFrontierObserver()
    reducer = RawReducer(observer=lambda event, details: observer.observe(reducer, event, details))
    for row in baseline():
        reducer.apply(row)
    return reducer, observer

def project(reducer, observer, partial=False):
    document = reducer.document()
    document['source'] = {'format': 'player-log-gre-v1', 'mode': 'offline',
        'generation': reducer.generation, 'partial_record': partial,
        'input_sent': False, 'executor_connected': False}
    document['decision_input'] = build_decision_input(document)
    return observer.project(reducer, document)

def save(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

class CombatFrontierTests(unittest.TestCase):
    def test_attack_qualified_reference_and_count_only_recipient(self):
        reducer, observer = ready()
        row = request()
        body(row)['attackers'] = [{'attackerInstanceId': 703}]
        reducer.apply(row)
        result = project(reducer, observer)
        self.assertEqual((result['observed_candidate_count'], result['verified_reference_count'], result['unresolved_count']), (1, 1, 0))
        self.assertEqual(result['engine_offered_candidates'][0]['candidate_instance_id'], 701)
        self.assertEqual(result['engine_offered_candidates'][0]['observed_recipient_count'], 1)
        self.assertIsNone(result['engine_offered_candidates'][0]['attack_target_domain'])
        self.assertEqual(result['completeness'], 'partial')
        self.assertEqual(result['known_constraints'], [])
        self.assertTrue(result['unknown_request_fields_present'])
        for record in [result] + result['engine_offered_candidates']:
            self.assertTrue(all(record[name] is False for name in FLAGS))
        for private in ('PRIVATE_FIELD', 'PRIVATE_VALUE', 'PRIVATE_RECIPIENT', '99117733', '987654321', '703', '704'):
            self.assertNotIn(private, json.dumps(result))

    def test_explicit_blocker_edges_never_define_complete_attacker_domain(self):
        reducer, observer = ready()
        reducer.apply(request(BLOCK))
        result = project(reducer, observer)
        row = result['engine_offered_candidates'][0]
        self.assertEqual(row['engine_listed_attacker_references'][0]['attacker_instance_id'], 702)
        self.assertEqual(row['verified_attacker_reference_count'], 1)
        self.assertIsNone(result['complete_attacker_domain'])
        self.assertIn('blocking_combinations_unknown', result['unresolved_constraints'])

    def test_rejected_recipients_and_digest_conflicts_cannot_pollute_capture(self):
        for seats in ([True], [1.0], [2], [1, 2], [1, 1], ['1']):
            reducer, observer = ready()
            reducer.apply(request(seats=seats))
            self.assertIsNone(project(reducer, observer))
            reducer.apply(request(ident=991))
            current = project(reducer, observer)
            reducer.apply(request(ident=991, seats=seats, references=(703,)))
            self.assertEqual(project(reducer, observer), current)
        reducer, observer = ready()
        reducer.apply(request())
        reducer.apply(request(references=(703,)))
        self.assertIsNone(project(reducer, observer))
        self.assertTrue(reducer.conflict)

    def test_consumption_replacement_and_wrong_response_type_cannot_restore(self):
        for mode in ('consumed', 'wrong_type', 'replaced'):
            reducer, observer = ready()
            reducer.apply(request())
            reducer.apply(request(BLOCK, 991) if mode == 'replaced' else
                          response(BLOCK if mode == 'wrong_type' else ATTACK))
            result = project(reducer, observer)
            self.assertTrue(result is None or result['combat_request_type'] == BLOCK)
            reducer.apply(request())
            result = project(reducer, observer)
            self.assertTrue(result is None or result['request_identity']['request_id'] != 990)

    def test_multiple_gap_recoveries_do_not_revive_retransmissions(self):
        reducer, observer = ready()
        reducer.apply(request())
        # Harmless uninterrupted retransmission keeps the same observation.
        before = project(reducer, observer)
        reducer.apply(request())
        self.assertEqual(project(reducer, observer), before)
        gap = {'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_GameStateMessage',
            'systemSeatIds': [1], 'gameStateMessage': {'type': 'GameStateType_Diff',
            'gameStateId': 5, 'prevGameStateId': 999}}]}}
        for ident in (991, 992):
            reducer.apply(gap)
            reducer.apply(baseline()[2])
            reducer.apply(request(ident=ident))
            self.assertEqual(project(reducer, observer)['verified_reference_count'], 1)
        reducer.apply(gap)
        reducer.apply(baseline()[2])
        reducer.apply(request())
        self.assertIsNone(project(reducer, observer))

    def test_game_match_generation_state_and_partial_source_bindings(self):
        for mode in ('game', 'match', 'generation', 'state', 'partial'):
            reducer, observer = ready()
            reducer.apply(request())
            if mode == 'generation':
                reducer.reset(2)
            elif mode == 'match':
                room = baseline()[1]
                room['matchGameRoomStateChangedEvent']['gameRoomInfo']['gameRoomConfig']['matchId'] = 'SYNTHETIC_OTHER'
                reducer.apply(room)
            elif mode != 'partial':
                full = baseline()[2]
                state(full)['gameInfo']['gameNumber'] = 2 if mode == 'game' else 1
                state(full)['gameStateId'] = 2
                reducer.apply(full)
            self.assertIsNone(project(reducer, observer, partial=mode == 'partial'))

    def test_empty_missing_invalid_arrays_and_no_unqualified_fallback(self):
        for mode in ('empty', 'missing', 'invalid', 'body_missing'):
            reducer, observer = ready()
            row = request(references=())
            if mode == 'missing':
                body(row).clear()
                body(row)['attackers'] = [{'attackerInstanceId': 701}]
            elif mode == 'invalid':
                body(row)['qualifiedAttackers'] = None
            elif mode == 'body_missing':
                row['greToClientEvent']['greToClientMessages'][0].pop('declareAttackersReq')
            reducer.apply(row)
            result = project(reducer, observer)
            self.assertEqual(result['observed_candidate_count'], 0 if mode == 'empty' else None)
            self.assertEqual(result['completeness'], 'partial' if mode == 'empty' else 'unknown')

    def test_hidden_invalid_duplicate_and_truncated_candidate_identity(self):
        for references in ((703,), (704,), (True,), (1.0,), (0,), (-1,), (701, 701), (701,) * 257):
            reducer, observer = ready()
            reducer.apply(request(references=references))
            result = project(reducer, observer)
            self.assertEqual(result['verified_reference_count'], 0)
            self.assertEqual(result['unresolved_count'], len(references))
            self.assertTrue(all(row['candidate_instance_id'] is None for row in result['engine_offered_candidates']))
            if len(references) > 256:
                self.assertTrue(result['truncated'])
                self.assertEqual(result['unexamined_candidate_count'], 1)

    def test_blocker_missing_duplicate_invalid_truncated_and_unprojected_edges(self):
        for values in (None, [], [702, 702], [True], [702] * 257, [704]):
            reducer, observer = ready()
            row = request(BLOCK)
            if values is None:
                body(row)['blockers'][0].pop('attackerInstanceIds')
                body(row)['blockers'][0]['selectedAttackerInstanceIds'] = [702]
            else:
                body(row)['blockers'][0]['attackerInstanceIds'] = values
            reducer.apply(row)
            result = project(reducer, observer)
            projected = result['engine_offered_candidates'][0]
            self.assertEqual(result['verified_reference_count'], 1)
            edges = projected['engine_listed_attacker_references']
            if values == []:
                self.assertEqual(edges, [])
            elif values == [704]:
                self.assertIsNone(edges[0]['attacker_instance_id'])
                self.assertEqual(projected['unresolved_attacker_reference_count'], 1)
            else:
                self.assertIsNone(edges)

    def test_actual_cli_default_compatibility_and_existing_frontier_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.jsonl'
            save(path, baseline() + [request()])
            default = replay(path, format='player-log', decision_input=True, action_frontier=True, choice_graph=True)
            observed = replay(path, format='player-log', decision_input=True, action_frontier=True,
                              choice_graph=True, combat_frontier=True)
            self.assertEqual(observed.pop('combat_frontier')['verified_reference_count'], 1)
            self.assertEqual(observed, default)
            for command in ('replay', 'dry-run', 'watch'):
                result = subprocess.run([sys.executable, '-m', 'mtgaplayer', command, str(path),
                    *(['--samples', '1', '--interval', '0.01'] if command == 'watch' else ['--format', 'player-log']),
                    '--decision-input', '--combat-frontier'],
                    capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['combat_frontier']['verified_reference_count'], 1)
            with self.assertRaises(ValueError):
                replay(path, format='player-log', combat_frontier=True)
            with self.assertRaises(ValueError):
                replay(path, decision_input=True, combat_frontier=True)

    def test_actual_watch_append_consumption_and_partial_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.jsonl'
            save(path, baseline())
            pending = iter((request(BLOCK), response(BLOCK)))
            def append(_):
                with path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(next(pending)) + '\n')
            with patch('mtgaplayer.cli.time.sleep', append):
                observed = list(watch(path, samples=3, decision_input=True, combat_frontier=True))
            self.assertIsNone(observed[0]['combat_frontier'])
            self.assertEqual(observed[1]['combat_frontier']['verified_reference_count'], 1)
            self.assertFalse(observed[1]['combat_frontier']['usable_now'])
            self.assertIsNone(observed[2]['combat_frontier'])
            save(path, baseline() + [request()])
            with path.open('a') as stream:
                stream.write('{"unfinished":')
            self.assertIsNone(replay(path, format='player-log', decision_input=True,
                                     combat_frontier=True)['combat_frontier'])

    def test_caller_projection_cannot_manufacture_public_or_unique_identity(self):
        reducer, observer = ready()
        reducer.apply(request(references=(703,)))
        document = reducer.document()
        document['source'] = {'format': 'player-log-gre-v1', 'mode': 'offline',
            'generation': reducer.generation, 'partial_record': False,
            'input_sent': False, 'executor_connected': False}
        next(obj for obj in document['current']['objects'] if obj['id'] == 703)['zone'] = 'ZoneType_Battlefield'
        document['decision_input'] = build_decision_input(document)
        self.assertIsNone(observer.project(reducer, document))
        reducer, observer = ready()
        reducer.apply(request())
        document = reducer.document()
        document['source'] = {'format': 'player-log-gre-v1', 'mode': 'offline',
            'generation': reducer.generation, 'partial_record': False,
            'input_sent': False, 'executor_connected': False}
        document['current']['objects'].append(copy.deepcopy(document['current']['objects'][0]))
        document['decision_input'] = build_decision_input(document)
        self.assertIsNone(observer.project(reducer, document))

    def test_existing_scrubbed_real_headers_remain_unknown_not_empty_candidates(self):
        observer = CombatFrontierObserver()
        captured = []
        reducer = RawReducer()
        def observe(event, details):
            observer.observe(reducer, event, details)
            if event == 'request_accepted' and details['request']['type'] in (ATTACK, BLOCK):
                captured.append(project(reducer, observer))
        reducer.observer = observe
        fixture = Path(__file__).parent / 'fixtures/player_log_selectn.jsonl'
        for line in fixture.read_text(encoding='utf-8').splitlines():
            reducer.apply(json.loads(line))
        self.assertEqual(len(captured), 2)
        self.assertTrue(all(row['observed_candidate_count'] is None and row['completeness'] == 'unknown'
                            for row in captured))

if __name__ == '__main__':
    unittest.main()
