"""Literal public Stack membership, never top or resolution inference."""
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
from mtgaplayer.rules_index import build_rules_index
from test_action_frontier import save
from test_decision_publisher import ManualClock, append, poll_events
from test_observed_changes import real_prefixes


class PublicStackV3Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root/'stack.jsonl'

    def state(self, rows, version=3):
        save(self.path, rows)
        return replay(self.path, format='player-log', decision_state=True,
                      decision_state_version=version)

    def test_real_order_inheritance_replacement_and_legacy_versions(self):
        prefixes = real_prefixes((211,212,213,215))
        for state, expected in ((211,[337,336]), (212,[337,336]), (213,[336]), (215,None)):
            doc = self.state(prefixes[state])
            stack = doc['decision_state']['game']['stack']
            self.assertEqual(stack['order_basis'], 'literal_gre_zone_objectInstanceIds')
            self.assertEqual(stack['availability'], 'unknown' if expected is None else 'observed')
            self.assertEqual(None if stack['members'] is None else [r['instance_id'] for r in stack['members']], expected)
            for position, row in enumerate(stack['members'] or []):
                self.assertEqual(row['list_position'], position)
                self.assertEqual(row['object_type'], 'GameObjectType_Ability')
                self.assertIsNone(next(o for o in doc['decision_state']['visible_objects']
                    if o['instance_id'] == row['instance_id'])['card_id'])
            self.assertNotIn('_public_stack', json.dumps(doc))
        for version in (1,2):
            old = self.state(prefixes[211], version)
            new = self.state(prefixes[211])
            self.assertNotIn('stack', old['decision_state']['game'])
            self.assertEqual(old['current'], new['current'])
            self.assertEqual(old['decision_state']['visible_objects'], new['decision_state']['visible_objects'])
        run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(self.path),
            '--format', 'player-log', '--decision-state-version', '3'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual([r['instance_id'] for r in json.loads(run.stdout)['decision_state']['game']['stack']['members']], [337,336])

    def mutation(self, change):
        rows = real_prefixes((211,))[211]
        message = rows[-1]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
        change(message)
        return rows

    def test_synthetic_empty_unknown_private_and_missing_members_are_distinct(self):
        def stack_zone(gs):
            return next(z for z in gs['zones'] if z['type'] == 'ZoneType_Stack')
        def empty(gs):
            stack_zone(gs)['objectInstanceIds'] = []
        stack = self.state(self.mutation(empty))['decision_state']['game']['stack']
        self.assertEqual((stack['availability'],stack['members']), ('confirmed_empty',[]))
        for mutation in (
            lambda gs: stack_zone(gs).pop('objectInstanceIds'),
            lambda gs: stack_zone(gs).pop('visibility'),
            lambda gs: stack_zone(gs).update(visibility='Visibility_Private'),
            lambda gs: stack_zone(gs).update(objectInstanceIds=[999999]),
            lambda gs: gs['zones'].append({'zoneId':999,'type':'ZoneType_Stack','visibility':'Visibility_Public','objectInstanceIds':[]}),
            lambda gs: stack_zone(gs).update(objectInstanceIds=list(range(900000,900513))),
        ):
            doc = self.state(self.mutation(mutation))
            self.assertIsNone(doc['error'])
            stack = doc['decision_state']['game']['stack']
            self.assertEqual((stack['availability'],stack['zone_id'],stack['members']), ('unknown',None,None))
            self.assertNotIn('999999', json.dumps(stack))
        def unknown_type(gs):
            for obj in gs['gameObjects']:
                if obj['instanceId'] in (336,337):
                    obj['type'] = 'PRIVATE_UNKNOWN_TYPE'
        stack = self.state(self.mutation(unknown_type))['decision_state']['game']['stack']
        self.assertEqual(stack['availability'], 'observed')
        self.assertTrue(all(r['object_type'] is None for r in stack['members']))
        self.assertNotIn('PRIVATE_UNKNOWN_TYPE', json.dumps(stack))

    def snapshot(self):
        save(self.path, real_prefixes((211,))[211])
        stream = watch_decision_events(self.path, interval=0, samples=2,
            clock_ns=ManualClock(), session_id='stack-v3', decision_state_version=3)
        self.addCleanup(stream.close)
        return next(e for e in poll_events(stream) if e['event_type']=='snapshot')

    def test_consumer_strict_stack_references_shapes_and_version_pairs(self):
        snapshot = self.snapshot()
        snapshot['sequence'] = snapshot['snapshot_ref']['sequence'] = 1
        for mutation in (
            lambda s: s.update(members=None),
            lambda s: s.update(availability='confirmed_empty'),
            lambda s: s['members'][0].update(instance_id=999999),
            lambda s: s['members'][0].update(list_position=True),
            lambda s: s['members'].__setitem__(0, None),
            lambda s: s['members'][0].update(object_type='PRIVATE_TYPE'),
            lambda s: s['members'][1].update(instance_id=s['members'][0]['instance_id']),
        ):
            c = DecisionConsumer(clock_ns=ManualClock())
            self.assertTrue(c.accept_event(snapshot))
            bad = copy.deepcopy(snapshot)
            bad['sequence'] = bad['snapshot_ref']['sequence'] = 2
            mutation(bad['decision_state']['game']['stack'])
            self.assertFalse(c.accept_event(bad))
            self.assertIsNone(c.current_view()['decision_state'])
        crossed = copy.deepcopy(snapshot)
        crossed['schema_version'] = 'mtgaplayer.decision-event.v2'
        self.assertFalse(DecisionConsumer(clock_ns=ManualClock()).accept_event(crossed))
        mixed = copy.deepcopy(snapshot)
        mixed['sequence'] = mixed['snapshot_ref']['sequence'] = 2
        mixed['schema_version'] = 'mtgaplayer.decision-event.v2'
        mixed['decision_state']['schema_version'] = 'mtgaplayer.decision-state.v2'
        mixed['decision_state']['game'].pop('stack')
        c = DecisionConsumer(clock_ns=ManualClock())
        self.assertTrue(c.accept_event(snapshot))
        self.assertFalse(c.accept_event(mixed))

    def test_actual_v3_watch_consumer_pipe_append_sidecars_and_stop(self):
        prefixes = real_prefixes((211,213))
        save(self.path, prefixes[211])
        source, index = self.root/'cards.json', self.root/'index.sqlite'
        source.write_text('[]', encoding='utf-8')
        build_rules_index(source,index,source_version='invented-empty')
        producer = subprocess.Popen([sys.executable,'-m','mtgaplayer','watch',str(self.path),
            '--decision-events','--decision-state-version','3','--interval','0.1','--samples','12'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        consumer = subprocess.Popen([sys.executable,'-m','mtgaplayer','consume-events','--advice',
            '--rules-index',str(index),'--observed-changes'],stdin=producer.stdout,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        producer.stdout.close()
        output = queue.Queue()
        def read():
            for line in consumer.stdout:
                output.put(json.loads(line))
        thread = threading.Thread(target=read,daemon=True)
        thread.start()
        try:
            rows=[]
            while True:
                row=output.get(timeout=5); rows.append(row)
                ref=row['current_rule_context']['source_snapshot_ref']
                if ref is not None and ref['binding']['game_state_id']==211:
                    break
            append(self.path,prefixes[213][len(prefixes[211]):])
            while True:
                row=output.get(timeout=5); rows.append(row)
                ref=row['current_rule_context']['source_snapshot_ref']
                if ref is not None and ref['binding']['game_state_id']==213:
                    self.assertEqual(row['observed_changes']['status'],'endpoints_compared')
                    break
            self.assertEqual(producer.wait(timeout=10),0,producer.stderr.read())
            self.assertEqual(consumer.wait(timeout=10),0,consumer.stderr.read())
            thread.join(2)
            while not output.empty(): rows.append(output.get_nowait())
            self.assertEqual(rows[-1]['consumer_status'],'CLOSED')
            self.assertIsNone(rows[-1]['current_rule_context']['source_snapshot_ref'])
            self.assertEqual(rows[-1]['observed_changes']['changes'],[])
        finally:
            for process in (producer,consumer):
                if process.poll() is None: process.kill(); process.wait()
                for pipe in (process.stdout,process.stderr):
                    if pipe is not None: pipe.close()

    def test_v3_formal_ids_refs_and_local_lease(self):
        snapshot=self.snapshot()
        clock=ManualClock()
        c=DecisionConsumer(100,100,clock)
        self.assertTrue(c.accept_event(snapshot))
        self.assertEqual(c.current_view()['decision_state']['game']['stack']['members'][0]['instance_id'],337)
        clock.advance(101_000_000)
        self.assertIsNone(c.current_view()['decision_state'])
        root=Path(__file__).resolve().parents[1]/'schemas'
        state=json.loads((root/'decision-state.v3.schema.json').read_text())
        event=json.loads((root/'decision-event.v3.schema.json').read_text())
        self.assertEqual(state['$id'],'urn:mtgaplayer:decision-state:v3')
        self.assertEqual(event['$id'],'urn:mtgaplayer:decision-event:v3')
        self.assertIn('stack',state['properties']['game']['required'])
        self.assertNotIn(':v2',json.dumps((state,event)))
        self.assertNotIn('.v2',json.dumps((state,event)))
