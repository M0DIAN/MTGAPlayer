"""A committed real public Exile observation plus labeled synthetic negatives."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.rules_index import build_rules_index
from test_rules_index import card

FIXTURE = Path(__file__).parent / 'fixtures/player_log_selectn.jsonl'


def exile_prefix():
    """Keep the existing real state chain, ending exactly at observed state172."""
    result = []
    for original in (json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines()):
        if 'greToClientEvent' not in original:
            result.append(original)
            continue
        for message in original['greToClientEvent']['greToClientMessages']:
            row = copy.deepcopy(original)
            row['greToClientEvent']['greToClientMessages'] = [copy.deepcopy(message)]
            result.append(row)
            if message.get('gameStateMessage', {}).get('gameStateId') == 172:
                return result
    raise AssertionError('real state172 missing')


def reducer_at_exile():
    reducer = RawReducer()
    reducer.reset(1)
    for row in exile_prefix():
        reducer.apply(row)
    return reducer


def update(reducer, *, objects=(), zones=(), deleted=()):
    state = {'type': 'GameStateType_Diff', 'gameStateId': reducer.version + 1,
        'prevGameStateId': reducer.version, 'gameObjects': list(objects), 'zones': list(zones),
        'diffDeletedInstanceIds': list(deleted)}
    reducer.apply({'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': state}]}})


class PublicExileTests(unittest.TestCase):
    def test_real_public_exile_card_is_projected_once_and_not_counted_hidden(self):
        r = reducer_at_exile()
        self.assertEqual(r.version, 172)
        self.assertEqual(r.objects[325]['visibility'], 'Visibility_Public')
        self.assertEqual(r.zones[29]['visibility'], 'Visibility_Public')
        current = r.document()['current']
        self.assertTrue(current['valid'])
        projected = [o for o in current['objects'] if o['id'] == 325]
        self.assertEqual(len(projected), 1)
        self.assertEqual((projected[0]['card_id'], projected[0]['zone']), (75499, 'ZoneType_Exile'))
        self.assertNotIn('unknown:ZoneType_Exile', current['hidden_counts'])
        self.assertFalse(current['actionable'])

    def test_exile_requires_explicit_public_zone_and_object(self):
        for change in ('private_zone', 'missing_zone_visibility', 'private_object', 'unknown_object_type'):
            with self.subTest(change=change):
                r = reducer_at_exile()
                obj, zone = copy.deepcopy(r.objects[325]), copy.deepcopy(r.zones[29])
                obj['grpId'] = 777777
                if change == 'private_zone':
                    zone.update(visibility='Visibility_Private', viewers=[1])
                elif change == 'missing_zone_visibility':
                    zone.pop('visibility')
                elif change == 'private_object':
                    obj.update(visibility='Visibility_Private', viewers=[1])
                else:
                    obj['type'] = 'GameObjectType_Unknown'
                update(r, objects=[obj], zones=[zone])
                current = r.document()['current']
                self.assertTrue(current['valid'])
                self.assertNotIn(325, {o['id'] for o in current['objects']})
                self.assertEqual(current['hidden_counts']['unknown:ZoneType_Exile'], 1)
                self.assertNotIn('777777', json.dumps(r.document()))

    def test_missing_object_visibility_wrong_zone_and_revealed_view_do_not_publish_identity(self):
        for change in ('missing_visibility', 'wrong_zone', 'revealed_view'):
            with self.subTest(change=change):
                r = reducer_at_exile()
                obj = copy.deepcopy(r.objects[325])
                obj['grpId'] = 777777
                if change == 'missing_visibility':
                    obj.pop('visibility')
                elif change == 'wrong_zone':
                    obj['zoneId'] = 9999
                else:
                    obj['type'] = 'GameObjectType_RevealedCard'
                update(r, objects=[obj])
                self.assertFalse(r.document()['current']['valid'])
                self.assertNotIn('777777', json.dumps(r.document()))

    def test_delete_and_move_to_opponent_hand_remove_current_identity(self):
        for operation in ('delete', 'hide'):
            with self.subTest(operation=operation):
                r = reducer_at_exile()
                if operation == 'delete':
                    update(r, deleted=[325])
                else:
                    hand = copy.deepcopy(next(z for z in r.zones.values()
                        if z.get('type') == 'ZoneType_Hand' and z.get('ownerSeatId') == 2))
                    obj, exile = copy.deepcopy(r.objects[325]), copy.deepcopy(r.zones[29])
                    obj.update(zoneId=hand['zoneId'], visibility='Visibility_Private', grpId=777777)
                    hand['objectInstanceIds'].append(325)
                    exile['objectInstanceIds'] = []
                    update(r, objects=[obj], zones=[hand, exile])
                current = r.document()['current']
                self.assertTrue(current['valid'])
                self.assertNotIn(325, {o['id'] for o in current['objects']})
                self.assertNotIn('777777', json.dumps(r.document()))

    def test_actual_replay_cli_and_existing_static_context_use_same_visible_exile(self):
        with tempfile.TemporaryDirectory() as directory:
            path, source, index = (Path(directory) / n for n in ('prefix.jsonl', 'cards.json', 'rules.sqlite'))
            path.write_text(''.join(json.dumps(row) + '\n' for row in exile_prefix()), encoding='utf-8')
            source.write_text(json.dumps([card(75499, name='Invented exile reference'),
                                          card(777777, name='PRIVATE_SENTINEL')]), encoding='utf-8')
            build_rules_index(source, index, source_version='invented-exile')
            out = replay(path, format='player-log', rules_index_path=index)
            row = next(o for o in out['static_rule_context']['objects'] if o['instance_id'] == 325)
            self.assertEqual(row['status'], 'resolved_static_reference')
            self.assertEqual(row['reference']['name'], 'Invented exile reference')
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(out))
            cli = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', '--format', 'player-log',
                '--decision-state', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            state = json.loads(cli.stdout)['decision_state']
            self.assertEqual([o['card_id'] for o in state['visible_objects'] if o['instance_id'] == 325], [75499])
