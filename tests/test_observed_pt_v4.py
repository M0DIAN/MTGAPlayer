"""Current P/T literals from reduced real traces; mutations are synthetic."""
import copy
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer
from mtgaplayer.decision_state import build_decision_state
from mtgaplayer.raw_log import RawReducer
from test_action_frontier import save
from test_decision_publisher import ManualClock, append, poll_events
from test_turn_context_v2 import stage

ROOT = Path(__file__).resolve().parents[1]
METADATA = {'basis': 'accepted_gre_reduced_object_literals', 'scope': 'visible_battlefield',
            'effect_sources': None, 'durations': None}


def real_rows(name='early', state=None):
    rows = [json.loads(line) for line in (ROOT/'tests/fixtures'/
        f'player_log_observed_pt_{name}.jsonl').read_text().splitlines()]
    if state is None:
        return rows
    for position, row in enumerate(rows):
        messages = row.get('greToClientEvent', {}).get('greToClientMessages', [])
        if messages and messages[0]['gameStateMessage']['gameStateId'] == state:
            return rows[:position+1]
    raise AssertionError('real state missing')


def obj(state, ident):
    return next(row for row in state['visible_objects'] if row['instance_id'] == ident)


class ObservedPTV4Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root/'pt.jsonl'

    def project(self, rows, version=4):
        save(self.path, rows)
        return replay(self.path, format='player-log', decision_state_version=version, decision_state=True)

    def reducer(self, rows=None):
        reducer = RawReducer()
        reducer.reset(1)
        for row in real_rows() if rows is None else rows:
            reducer.apply(row)
        self.assertIsNone(reducer.error)
        return reducer

    def replace(self, change):
        """One explicitly synthetic row replacement after the real state245."""
        rows = real_rows()
        reducer = self.reducer(rows)
        row = copy.deepcopy(reducer.objects[401])
        change(row)
        gs = {'type': 'GameStateType_Diff', 'gameStateId': 246, 'prevGameStateId': 245,
              'gameObjects': [row]}
        rows.append({'greToClientEvent': {'greToClientMessages': [{
            'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [reducer.seat],
            'gameStateMessage': gs}]}})
        return rows

    def test_real_current_values_diff_inheritance_and_replaced_row_clearing(self):
        for state, value in ((225,4), (226,3), (227,3), (231,4), (232,4),
                             (235,6), (236,6), (237,8), (243,7), (245,7)):
            with self.subTest(real_state=state):
                document = self.project(real_rows(state=state))
                result = document['decision_state']
                self.assertEqual((obj(result,315)['effective_power'],obj(result,315)['effective_toughness']),
                                 (value,value))
                self.assertIsNone(obj(result,315)['card_id'])  # Token identity is not a catalog ID.
                self.assertEqual(result['game']['effective_combat_stats'], METADATA)
                self.assertIsNone(result['effect_claims'])
                self.assertNotIn('effective_stats_unknown', result['unresolved'])
                self.assertIn('effective_stat_durations_unknown', result['unresolved'])
                self.assertTrue(all(value is False for value in result['execution'].values()))
                self.assertNotIn('_observed_combat_stats', json.dumps(document))
        for state, expected in ((254,(2,2)), (255,(None,None))):
            result = self.project(real_rows('clearing',state))['decision_state']
            self.assertEqual((obj(result,295)['effective_power'],obj(result,295)['effective_toughness']), expected)
        final = self.project(real_rows())['decision_state']
        self.assertEqual((obj(final,401)['effective_power'],obj(final,401)['effective_toughness']), (8,8))

    def test_synthetic_literals_independent_unknowns_and_no_static_fallback(self):
        # Explicit zero and negative literals are structure controls, not new real samples.
        rows = self.replace(lambda row: row.update(power={'value':0}, toughness={'value':-2}))
        result = self.project(rows)['decision_state']
        self.assertEqual((obj(result,401)['effective_power'],obj(result,401)['effective_toughness']), (0,-2))
        for bad in ({}, {'value':True}, {'value':1.0}, {'value':'PRIVATE_ATTRIBUTE_VALUE'},
                    {'value':2**31}, {'value':-2**31-1}, {'value':3,'PRIVATE_ATTRIBUTE_KEY':1}, 3, None):
            with self.subTest(synthetic_wrapper=bad):
                result = self.project(self.replace(lambda row: row.update(power=bad,toughness={'value':9})))['decision_state']
                self.assertEqual((obj(result,401)['effective_power'],obj(result,401)['effective_toughness']), (None,9))
                self.assertNotIn('PRIVATE_ATTRIBUTE', json.dumps(result))
        result = self.project(self.replace(lambda row: row.update(power={'value':7},toughness={})))['decision_state']
        self.assertEqual((obj(result,401)['effective_power'],obj(result,401)['effective_toughness']), (7,None))
        reducer = self.reducer(real_rows('clearing'))
        document = stage(reducer)
        target = next(row for row in document['current']['objects'] if row['id']==295)
        target['local_card'] = {'status':'resolved','name':'Invented static stats',
            'catalog_stats':{'power':99,'toughness':98}}
        result = build_decision_state(document,version=4)
        self.assertEqual((obj(result,295)['effective_power'],obj(result,295)['effective_toughness']), (None,None))
        static = next(row for row in result['card_knowledge']['objects'] if row['instance_id']==295)
        self.assertEqual(static['knowledge']['static_catalog_stats']['power'],99)

    def test_synthetic_source_scope_card_token_ability_hidden_and_hand(self):
        for kind, expected in (('GameObjectType_Card',(8,8)), ('GameObjectType_Token',(8,8)),
                               ('GameObjectType_Ability',(None,None)), ('GameObjectType_Future',(None,None))):
            result = self.project(self.replace(lambda row: row.update(type=kind)))['decision_state']
            self.assertEqual((obj(result,401)['effective_power'],obj(result,401)['effective_toughness']), expected)
        rows = self.replace(lambda row: row.update(visibility='Visibility_Private',
            power={'value':99117733},toughness={'value':99117733}))
        document = self.project(rows)
        self.assertNotIn(401,[o['instance_id'] for o in document['decision_state']['visible_objects']])
        self.assertNotIn('99117733', json.dumps(document))
        rows = real_rows()
        reducer = self.reducer(rows)
        hand = next(z for z in reducer.zones.values() if z['type']=='ZoneType_Hand' and z['ownerSeatId']==reducer.seat)
        old = reducer.zones[reducer.objects[401]['zoneId']]
        new_hand, new_old = copy.deepcopy(hand), copy.deepcopy(old)
        new_hand['objectInstanceIds'].append(401)
        new_old['objectInstanceIds'].remove(401)
        row = copy.deepcopy(reducer.objects[401])
        row.update(zoneId=hand['zoneId'], visibility='Visibility_Private', viewers=[reducer.seat],
                   ownerSeatId=reducer.seat,controllerSeatId=reducer.seat,type='GameObjectType_Card',
                   power={'value':99117733},toughness={'value':99117733})
        rows.append({'greToClientEvent': {'greToClientMessages': [{'type':'GREMessageType_GameStateMessage',
            'systemSeatIds':[reducer.seat],'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':246,
            'prevGameStateId':245,'gameObjects':[row],'zones':[new_hand,new_old]}}]}})
        document = self.project(rows)
        target = obj(document['decision_state'],401)
        self.assertEqual((target['zone'],target['effective_power'],target['effective_toughness']),
                         ('ZoneType_Hand',None,None))
        self.assertNotIn('99117733',json.dumps(document))

    def test_staging_references_and_legacy_versions_remain_separate(self):
        staged = stage(self.reducer())
        for mutate in (
            lambda rows: rows.append(dict(rows[0])),
            lambda rows: rows.append(dict(rows[0],instance_id=999999)),
        ):
            changed = copy.deepcopy(staged)
            mutate(changed['current']['_observed_combat_stats'])
            self.assertIsNone(build_decision_state(changed,version=4))
            self.assertIsNotNone(build_decision_state(changed,version=3))
        save(self.path,real_rows())
        plain = replay(self.path,format='player-log')
        current = self.project(real_rows())
        for version in (1,2,3):
            old = self.project(real_rows(),version)
            self.assertEqual(old['current'],plain['current'])
            self.assertEqual(old['current'],current['current'])
            self.assertIsNone(old['decision_state']['game']['effective_combat_stats'])
            expected = copy.deepcopy(current['decision_state']['visible_objects'])
            for row in expected:
                row['effective_power'] = row['effective_toughness'] = None
            self.assertEqual(old['decision_state']['visible_objects'],expected)
        v3 = self.project(real_rows(),3)['decision_state']
        expected = copy.deepcopy(current['decision_state']['game'])
        expected['effective_combat_stats'] = None
        self.assertEqual(v3['game'],expected)  # Includes inherited turn context and literal Stack.
        default = replay(self.path,format='player-log',decision_state=True)
        self.assertEqual(default['decision_state']['schema_version'],'mtgaplayer.decision-state.v1')

    def snapshot(self):
        save(self.path,real_rows(state=226))
        stream = watch_decision_events(self.path,interval=0,samples=2,clock_ns=ManualClock(),
            session_id='current-pt-v4',decision_state_version=4)
        self.addCleanup(stream.close)
        return next(e for e in poll_events(stream) if e['event_type']=='snapshot')

    def test_consumer_numeric_metadata_identity_and_version_contract_clears_cache(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot['schema_version'],'mtgaplayer.decision-event.v4')
        for mutate in (
            lambda s: obj(s,315).update(effective_power=True),
            lambda s: obj(s,315).update(effective_power=2**31),
            lambda s: obj(s,315).update(zone='ZoneType_Hand'),
            lambda s: s['game']['effective_combat_stats'].update(effect_sources='claimed'),
            lambda s: s['game']['effective_combat_stats'].update(PRIVATE_METADATA='unknown'),
            lambda s: s['visible_objects'].append(dict(obj(s,315),effective_power=99)),
        ):
            consumer = DecisionConsumer(clock_ns=ManualClock())
            self.assertTrue(consumer.accept_event(snapshot))
            self.assertEqual(obj(consumer.current_view()['decision_state'],315)['effective_power'],3)
            bad = copy.deepcopy(snapshot)
            bad['sequence'] = bad['snapshot_ref']['sequence'] = 2
            mutate(bad['decision_state'])
            self.assertFalse(consumer.accept_event(bad))
            self.assertIsNone(consumer.current_view()['decision_state'])
        crossed = copy.deepcopy(snapshot)
        crossed['schema_version'] = 'mtgaplayer.decision-event.v3'
        self.assertFalse(DecisionConsumer(clock_ns=ManualClock()).accept_event(crossed))
        mixed = copy.deepcopy(snapshot)
        mixed['sequence'] = mixed['snapshot_ref']['sequence'] = 2
        mixed['schema_version'] = 'mtgaplayer.decision-event.v3'
        mixed['decision_state']['schema_version'] = 'mtgaplayer.decision-state.v3'
        mixed['decision_state']['game']['effective_combat_stats'] = None
        for row in mixed['decision_state']['visible_objects']:
            row['effective_power'] = row['effective_toughness'] = None
        consumer = DecisionConsumer(clock_ns=ManualClock())
        self.assertTrue(consumer.accept_event(snapshot))
        self.assertFalse(consumer.accept_event(mixed))
        self.assertIsNone(consumer.current_view()['decision_state'])

    def test_actual_v4_cli_watch_publisher_consumer_append_and_stop(self):
        before, after = real_rows(state=226), real_rows(state=231)
        save(self.path,before)
        run = subprocess.run([sys.executable,'-m','mtgaplayer','replay',str(self.path),
            '--format','player-log','--decision-state-version','4'],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(obj(json.loads(run.stdout)['decision_state'],315)['effective_power'],3)
        producer = subprocess.Popen([sys.executable,'-m','mtgaplayer','watch',str(self.path),
            '--decision-events','--decision-state-version','4','--interval','0.1','--samples','12'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        consumer = subprocess.Popen([sys.executable,'-m','mtgaplayer','consume-events',
            '--advice','--observed-changes'],stdin=producer.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        producer.stdout.close()
        output = queue.Queue()
        def read():
            for line in consumer.stdout:
                output.put(json.loads(line))
        thread = threading.Thread(target=read,daemon=True)
        thread.start()
        try:
            while True:
                row = output.get(timeout=5)
                ref = row['observed_changes']['after_snapshot_ref']
                if ref is not None and ref['binding']['game_state_id']==226:
                    self.assertEqual(row['consumer_status'],'OBSERVING')
                    break
            append(self.path,after[len(before):])
            while True:
                row = output.get(timeout=5)
                ref = row['observed_changes']['after_snapshot_ref']
                if ref is not None and ref['binding']['game_state_id']==231:
                    self.assertEqual(row['consumer_status'],'OBSERVING')
                    self.assertEqual(row['observed_changes']['status'],'endpoints_compared')
                    break
            self.assertEqual(producer.wait(timeout=10),0,producer.stderr.read())
            self.assertEqual(consumer.wait(timeout=10),0,consumer.stderr.read())
            thread.join(2)
            tail = []
            while not output.empty():tail.append(output.get_nowait())
            self.assertEqual(tail[-1]['consumer_status'],'CLOSED')
            self.assertIsNone(tail[-1]['observed_changes']['after_snapshot_ref'])
        finally:
            for process in (producer,consumer):
                if process.poll() is None:process.kill();process.wait()
                for pipe in (process.stdout,process.stderr):
                    if pipe is not None:pipe.close()

    def test_formal_v4_metadata_scalar_bounds_and_version_refs(self):
        state = json.loads((ROOT/'schemas/decision-state.v4.schema.json').read_text())
        event = json.loads((ROOT/'schemas/decision-event.v4.schema.json').read_text())
        self.assertEqual(state['$id'],'urn:mtgaplayer:decision-state:v4')
        self.assertEqual(event['$id'],'urn:mtgaplayer:decision-event:v4')
        self.assertEqual(event['properties']['decision_state']['allOf'][0]['$ref'],state['$id'])
        self.assertNotIn(':v3',json.dumps((state,event)))
        self.assertNotIn('.v3',json.dumps((state,event)))
        stats = state['properties']['game']['properties']['effective_combat_stats']
        self.assertFalse(stats['additionalProperties'])
        self.assertEqual(set(stats['required']),set(METADATA))
        self.assertEqual(stats['properties']['basis']['const'],METADATA['basis'])
        for key in ('effective_power','effective_toughness'):
            scalar = state['$defs']['visibleObject']['properties'][key]
            self.assertEqual((scalar['type'],scalar['minimum'],scalar['maximum']),
                             (['integer','null'],-2**31,2**31-1))
        restriction = state['$defs']['visibleObject']['allOf'][0]
        self.assertEqual(restriction['if']['properties']['zone']['const'],'ZoneType_Battlefield')
        self.assertEqual(restriction['else']['properties']['effective_power'],{'type':'null'})


if __name__ == '__main__':
    unittest.main()
